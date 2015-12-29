import ast
import datetime
import email.header
import email.utils

from molino.callbackstack import callback_stack
import molino.imap.codecs
from molino.imap.parser import Address, Envelope, TextBody, MessageBody, BasicBody, MultipartBody


class Model:
    """
    The email client is essentially a sync engine between the actual state on
    the IMAP server and the view presented to the user. Data from the IMAP
    server is cached in two levels: on disk as a SQLite database and in memory.

    The database uses several tables to cache data and metadata. The
    'mailboxes' table stores the mailbox list metadata. The mailbox name is the
    primary key. The 'gmail_mailbox_uids' table maps the UIDs in a mailbox to
    the Gmail message ID. The 'gmail_messages' table maps Gmail message IDs to
    message metadata. The 'gmail_message_bodies' table maps section names of a
    message body to the contents.
    """

    def __init__(self, db):
        self._db = db
        self.__mailboxes = {}
        self.__gmail_msgs = {}

        self._db.execute('''
        CREATE TABLE IF NOT EXISTS mailboxes (
            name BLOB PRIMARY KEY,
            delimiter INTEGER,
            attributes BLOB,
            exists_ INTEGER,
            unseen INTEGER
        )''')
        self._db.execute('INSERT OR IGNORE INTO mailboxes VALUES (?, ?, ?, ?, ?)',
                         (b'INBOX', ord('/'), adapt_flags(set()), None, None))

        self._db.execute('''
        CREATE TABLE IF NOT EXISTS gmail_mailbox_uids (
            mailbox BLOB,
            uid INTEGER,
            gm_msgid INTEGER,
            PRIMARY KEY (mailbox, uid ASC)
        )''')

        self._db.execute('''
        CREATE TABLE IF NOT EXISTS gmail_messages (
            gm_msgid INTEGER PRIMARY KEY,
            date BLOB,
            subject BLOB,
            from_ BLOB,
            sender BLOB,
            reply_to BLOB,
            to_ BLOB,
            cc BLOB,
            bcc BLOB,
            in_reply_to BLOB,
            message_id BLOB,
            bodystructure STRING,
            flags BLOB
        )''')

        self._db.execute('''
        CREATE TABLE IF NOT EXISTS gmail_message_bodies (
            gm_msgid INTEGER,
            section STRING,
            body BLOB,
            PRIMARY KEY (gm_msgid, section)
        )''')

        self._db.commit()

    # Mailboxes

    def get_mailbox(self, name):
        """
        Get the mailbox with the given name or raise KeyError if there is no
        such mailbox.
        """
        try:
            return self.__mailboxes[name]
        except KeyError:
            pass
        cur = self._db.execute('SELECT * FROM mailboxes WHERE name=?', (name,))
        row = cur.fetchone()
        if row is None:
            raise KeyError
        mailbox = row_to_mailbox(self, row)
        self.__mailboxes[name] = mailbox
        return mailbox

    def add_mailbox(self, mailbox):
        """Add the given mailbox to the cache."""
        self.__mailboxes[mailbox.name] = mailbox
        attributes = adapt_flags(mailbox.attributes)
        self._db.execute('INSERT INTO mailboxes VALUES (?, ?, ?, ?, ?)',
                         (mailbox.name, mailbox.delimiter, attributes,
                          mailbox.exists, mailbox.num_unseen()))
        self._db.commit()
        self.on_mailboxes_add(mailbox)

    def delete_mailbox(self, name):
        """Delete the mailbox with the given name from the cache."""
        mailbox = self.__mailboxes.pop(name)
        self._db.execute('DELETE FROM mailboxes WHERE name=?', (name,))
        self._db.commit()
        self.on_mailboxes_delete(mailbox)

    def mailboxes(self):
        """Return an iterator over all of the mailboxes in the cache."""
        for row in self._db.execute('SELECT * FROM mailboxes'):
            try:
                yield self.__mailboxes[row['name']]
            except KeyError:
                mailbox = row_to_mailbox(self, row)
                self.__mailboxes[row['name']] = mailbox
                yield mailbox

    @callback_stack
    def on_mailboxes_add(self, mailbox):
        """Mailbox was added."""
        return True

    @callback_stack
    def on_mailboxes_delete(self, mailbox):
        """Mailbox was deleted."""
        return True

    @callback_stack
    def on_mailbox_update(self, mailbox, what):
        """Mailbox was updated."""
        return True

    # Messages

    def get_gmail_message(self, gm_msgid):
        try:
            return self.__gmail_msgs[gm_msgid]
        except KeyError:
            pass
        cur = self._db.execute('SELECT * FROM gmail_messages WHERE gm_msgid=?', (gm_msgid,))
        row = cur.fetchone()
        if row is None:
            raise KeyError
        message = row_to_message(self, row)
        self.__gmail_msgs[gm_msgid] = message
        return message

    def add_gmail_message(self, message):
        self.__gmail_msgs[message.gm_msgid] = message
        envelope = adapt_envelope(message.envelope)
        body = adapt_bodystructure(message.bodystructure)
        self._db.execute('''INSERT INTO gmail_messages
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                         (message.gm_msgid, *envelope, body, message.flags))
        self._db.commit()

    def delete_gmail_message(self, gm_msgid):
        del self.__gmail_msgs[gm_msgid]
        self._db.execute('DELETE FROM gmail_messages WHERE gm_msgid=?', (gm_msgid,))
        self._db.commit()

    def gmail_messages(self):
        cur = self._db.execute('SELECT * FROM gmail_messages')
        for row in cur:
            gm_msgid = row['gm_msgid']
            try:
                yield self.__gmail_msgs[gm_msgid]
            except KeyError:
                message = row_to_message(self, row)
                self.__gmail_msgs[gm_msgid] = message
                yield message

    @callback_stack
    def on_message_add(self, mailbox, uid, message):
        """Message was added to a Mailbox."""
        return True

    @callback_stack
    def on_message_delete(self, mailbox, uid, message):
        """Message was deleted from a Mailbox."""
        return True

    @callback_stack
    def on_message_update(self, message, what):
        """Message was updated."""
        return True


class Mailbox:
    """Cache of an IMAP mailbox."""

    def __init__(self, model, name, delimiter, attributes, exists=None,
                 unseen=None):
        self._model = model
        self._db = self._model._db
        self.__name = name
        try:
            self.__name_decoded = self.__name.decode('imap-utf-7')
        except UnicodeDecodeError:
            # If the mailbox isn't valid modified UTF-7, assume it's UTF-8 and
            # be robust to errors.
            self.__name_decoded = self.__name.decode('utf-8', errors='backslashreplace')
        if self.__name_decoded == 'INBOX':
            self.__name_decoded = 'Inbox'
        self.__delimiter = delimiter
        self.__attributes = attributes
        self.__exists = exists
        self.__unseen = set()
        self.__num_unseen = unseen
        self.__recent = None
        self.__flags = None
        self.__uids = []
        self.__messages = {}

    @property
    def name(self):
        """Raw mailbox name as bytes."""
        return self.__name

    @property
    def name_decoded(self):
        """Decoded mailbox name as string."""
        return self.__name_decoded

    @property
    def delimiter(self):
        """
        Character (as integer) used as delimiter in mailbox name hierarchy.
        """
        return self.__delimiter

    @delimiter.setter
    def delimiter(self, value):
        if value != self.__delimiter:
            self.__delimiter = value
            self._db.execute('UPDATE mailboxes SET delimiter=? WHERE name=?',
                             (value, self.name))
            self._db.commit()
            self._model.on_mailbox_update(self, 'delimiter')

    @property
    def attributes(self):
        """Set of mailbox name attributes as strings."""
        # XXX: should these be case-insensitive?
        return self.__attributes

    @attributes.setter
    def attributes(self, value):
        if value != self.__attributes:
            self.__attributes = value
            self._db.execute('UPDATE mailboxes SET attributes=? WHERE name=?',
                             (adapt_flags(value), self.name))
            self._db.commit()
            self._model.on_mailbox_update(self, 'attributes')

    def can_select(self):
        """
        Returns whether the mailbox can be selected. Mailboxes with the
        \\Noselect and \\NonExistent attributes cannot be selected.
        """
        return ('\\Noselect' not in self.__attributes and
                '\\NonExistent' not in self.__attributes)

    @property
    def exists(self):
        """Total number of messages in the mailbox."""
        return self.__exists

    @exists.setter
    def exists(self, value):
        self.__exists = value
        self._db.execute('UPDATE mailboxes SET exists_=? WHERE name=?',
                         (value, self.name))
        self._db.commit()
        self._model.on_mailbox_update(self, 'exists')

    def set_unseen(self, uids):
        """Update the set of UIDs of unseen messages in the mailbox."""
        self.__unseen = uids
        self.set_num_unseen(len(self.__unseen))

    def add_unseen(self, uid):
        """Add a UID to the set of unseen messages."""
        self.__unseen.add(uid)
        self.set_num_unseen(len(self.__unseen))

    def remove_unseen(self, uid):
        """Remove a UID from the set of unseen messages."""
        self.__unseen.discard(uid)
        self.set_num_unseen(len(self.__unseen))

    def set_num_unseen(self, num):
        """Set the number of unseen messages."""
        if num != self.__num_unseen:
            self.__num_unseen = num
            self._db.execute('UPDATE mailboxes SET unseen=? WHERE name=?',
                             (num, self.name))
            self._db.commit()
            self._model.on_mailbox_update(self, 'unseen')

    def num_unseen(self):
        """Total number of unseen messages in the mailbox."""
        return self.__num_unseen

    @property
    def unseen(self):
        """Return the set of UIDs of unseen messages."""
        return self.__unseen

    @property
    def recent(self):
        """Total number of recent messages in the mailbox."""
        return self.__recent

    @recent.setter
    def recent(self, value):
        self.__recent = value
        self._model.on_mailbox_update(self, 'recent')

    @property
    def flags(self):
        """Defined flags in the mailbox."""
        return self.__flags

    @flags.setter
    def flags(self, value):
        self.__flags = value
        self._model.on_mailbox_update(self, 'flags')

    @property
    def uids(self):
        """Mapping from mailbox sequence number to UID."""
        return self.__uids

    @uids.setter
    def uids(self, value):
        self.__uids = value

    def get_message(self, uid):
        """
        Get the message with the given UID or raise KeyError if there is no
        such message.
        """
        try:
            return self.__messages[uid]
        except KeyError:
            pass
        cur = self._db.execute('''SELECT gm_msgid FROM gmail_mailbox_uids
                                  WHERE mailbox=? AND uid=?''',
                               (self.name, uid))
        row = cur.fetchone()
        if row is None:
            raise KeyError
        message = self._model.get_gmail_message(row['gm_msgid'])
        self.__messages[uid] = message
        return message

    def contains_message(self, uid):
        """Return whether the mailbox contains a message with the given UID."""
        try:
            self.get_message(uid)
            return True
        except KeyError:
            return False

    def add_message(self, uid, message):
        """Add a message with the given UID to the mailbox."""
        self.__messages[uid] = message
        self._db.execute('INSERT INTO gmail_mailbox_uids VALUES (?, ?, ?)',
                         (self.name, uid, message.gm_msgid))
        self._db.commit()
        self._model.on_message_add(self, uid, message)

    def delete_message(self, uid):
        """Delete the message with the given UID from the mailbox."""
        message = self.__messages.pop(uid)
        self._db.execute('DELETE FROM gmail_mailbox_uids WHERE mailbox=? AND uid=?',
                         (self.name, uid))
        self._db.commit()
        self._model.on_message_delete(self, uid, message)

    def messages(self):
        """
        Return an iterator over all of the (UID, message) pairs in the mailbox.
        """
        cur = self._db.execute('SELECT uid, gm_msgid FROM gmail_mailbox_uids WHERE mailbox=?',
                               (self.name,))
        for row in cur:
            uid = row['uid']
            gm_msgid = row['gm_msgid']
            try:
                yield uid, self.__messages[uid]
            except KeyError:
                message = self._model.get_gmail_message(gm_msgid)
                self.__messages[uid] = message
                yield uid, message


def _decode_header(b):
    strings = []
    errors = 'backslashreplace'
    for decoded, charset in email.header.decode_header(b.decode('ascii', errors=errors)):
        if charset:
            strings.append(decoded.decode(charset, errors=errors))
        else:
            strings.append(decoded)
    return ''.join(strings)


def _addr_list(l, name_only):
    addrs = []
    for addr in l:
        addr_spec = '%s@%s' % (addr.mailbox.decode('ascii'), addr.host.decode('ascii'))
        if addr.name:
            name = _decode_header(addr.name)
            if name_only:
                addrs.append(name)
            else:
                addrs.append('"%s" <%s>' % (email.utils.quote(name), addr_spec))
        else:
            addrs.append(addr_spec)
    return addrs


class Message:
    def __init__(self, model, id, envelope=None, bodystructure=None, flags=None):
        self._model = model
        self._db = self._model._db
        self.__id = id
        self.__envelope = envelope
        self.__bodystructure = bodystructure
        self.__flags = flags

    @property
    def id(self):
        """
        Hashable object that uniquely identifies this message across all
        mailboxes forever. For Gmail, this is the X-GM-MSGID, an unsigned
        64-bit integer.
        """
        return self.__id

    @property
    def gm_msgid(self):
        return self.__id

    @property
    def envelope(self):
        """Internet Message Format envelope."""
        return self.__envelope

    @envelope.setter
    def envelope(self, value):
        if self.__envelope is None:
            self.__envelope = value
            envelope = adapt_envelope(value)
            self._db.execute('''UPDATE gmail_messages SET
                                date=?, subject=?, from_=?, sender=?,
                                reply_to=?, to_=?, cc=?, bcc=?, in_reply_to=?,
                                message_id=? WHERE gm_msgid=?''',
                             (*envelope, self.gm_msgid))
            self._db.commit()
            self._model.on_message_update(self, 'envelope')

    def subject(self):
        """
        Return the message subject as a string. If the subject contained any
        MIME encoded-words, these will be decoded.
        """
        if self.__envelope and self.__envelope.subject:
            return _decode_header(self.__envelope.subject)

    def from_(self, name_only=False):
        """
        Return the From: addresses as a list of strings. If the address
        contained any MIME encoded-words, these will be decoded. If name_only
        is False, the addresses will be formatted as '"Display Name"
        <example@example.org>' if the address has a display name or
        'example@example.org' if not. If name_only is True, the addresses will
        be formatted as 'Display Name' or 'example@example.org'.
        """
        if self.__envelope and self.__envelope.from_:
            return _addr_list(self.__envelope.from_, name_only)

    def to(self, name_only=False):
        """
        Return the To: addresses as a list of strings. See from_() for the
        format.
        """
        if self.__envelope and self.__envelope.to:
            return _addr_list(self.__envelope.to, name_only)

    def cc(self, name_only=False):
        """
        Return the Cc: addresses as a list of strings. See from_() for the
        format.
        """
        if self.__envelope and self.__envelope.cc:
            return _addr_list(self.__envelope.cc, name_only)

    def bcc(self, name_only=False):
        """
        Return the Bcc: addresses as a list of strings. See from_() for the
        format.
        """
        if self.__envelope and self.__envelope.bcc:
            return _addr_list(self.__envelope.bcc, name_only)

    @property
    def bodystructure(self):
        """MIME body structure."""
        return self.__bodystructure

    @bodystructure.setter
    def bodystructure(self, value):
        self.__bodystructure = value
        self._db.execute('UPDATE gmail_messages SET bodystructure=? WHERE gm_msgid=?',
                         (adapt_bodystructure(self.bodystructure), self.gm_msgid))
        self._db.commit()
        self._model.on_message_update(self, 'bodystructure')

    def get_body_section(self, section):
        """Get the given body section or raise KeyError if it is not cached."""
        cur = self._db.execute('''SELECT body FROM gmail_message_bodies
                                  WHERE gm_msgid=? AND section=?''',
                               (self.gm_msgid, section))
        row = cur.fetchone()
        if row is None:
            raise KeyError
        return row['body']

    def have_body_section(self, section):
        """Return whether the given section is cached."""
        try:
            # XXX: is there a better way to do this?
            self.get_body_section(section)
            return True
        except KeyError:
            return False

    def add_body_sections(self, sections):
        for section, (content, origin) in sections.items():
            assert origin is None
            self._db.execute('INSERT INTO gmail_message_bodies VALUES (?, ?, ?)',
                             (self.gm_msgid, section, content))
            self._db.commit()
        self._model.on_message_update(self, 'body')

    @property
    def flags(self):
        """Message flags."""
        return self.__flags

    @flags.setter
    def flags(self, value):
        self.__flags = value
        self._db.execute('UPDATE gmail_messages SET flags=? WHERE gm_msgid=?',
                         (adapt_flags(self.flags), self.gm_msgid))
        self._db.commit()
        self._model.on_message_update(self, 'flags')


def row_to_mailbox(model, row):
    return Mailbox(model, name=row['name'],
                   delimiter=row['delimiter'],
                   attributes=convert_flags(row['attributes']),
                   exists=row['exists_'],
                   unseen=row['unseen'])


def row_to_message(model, row):
    envelope = Envelope(date=convert_datetime(row['date']),
                        subject=row['subject'],
                        from_=convert_addrs(row['from_']),
                        sender=convert_addrs(row['sender']),
                        reply_to=convert_addrs(row['reply_to']),
                        to=convert_addrs(row['to_']),
                        cc=convert_addrs(row['cc']),
                        bcc=convert_addrs(row['bcc']),
                        in_reply_to=row['in_reply_to'],
                        message_id=row['message_id'])
    if all(x is None for x in envelope):
        envelope = None
    return Message(model, row['gm_msgid'], envelope=envelope,
                   bodystructure=convert_bodystructure(row['bodystructure']),
                   flags=convert_flags(row['flags']))


def adapt_addrs(addrs):
    if addrs is None:
        return None
    strs = []
    for addr in addrs:
        if not addr.mailbox or not addr.host:
            continue
        addr_spec = b'%s@%s' % (addr.mailbox, addr.host)
        if addr.name:
            # email.utils.quote() takes str, not bytes.
            name = addr.name.replace(b'\\', b'\\\\').replace(b'"', b'\\"')
            strs.append(b'"%s" <%s>' % (name, addr_spec))
        else:
            strs.append(addr_spec)
    return b'\n'.join(strs)


def convert_addrs(s):
    if s is None:
        return None
    strs = [addr.decode('ascii') for addr in s.split(b'\n')]
    l = []
    for name, addr_spec in email.utils.getaddresses(strs):
        mailbox, host = addr_spec.split('@')
        l.append(Address(name.encode('ascii'), None, mailbox.encode('ascii'), host.encode('ascii')))
    return l


def adapt_datetime(dt):
    if dt is None:
        return None
    else:
        return email.utils.format_datetime(dt).encode('ascii')


def convert_datetime(s):
    if s is None:
        return None
    else:
        return email.utils.parsedate_to_datetime(s.decode('ascii'))


def adapt_flags(flags):
    if flags is None:
        return None
    else:
        return ','.join(flags).encode('ascii')


def convert_flags(s):
    if s is None:
        return None
    elif s == b'':
        return set()
    else:
        return set(s.decode('ascii').split(','))


def adapt_bodystructure(body):
    def simplify_addresses(addrs):
        if addrs:
            return [addr[:] for addr in addrs]
        else:
            return None
    def simplify_datetime(dt):
        if dt:
            return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond,
                    dt.tzinfo.utcoffset(dt).total_seconds() if dt.tzinfo else None)
        else:
            return None
    def simplify_envelope(envelope):
        return (simplify_datetime(envelope.date), envelope.subject,
                simplify_addresses(envelope.from_), simplify_addresses(envelope.sender),
                simplify_addresses(envelope.reply_to), simplify_addresses(envelope.to),
                simplify_addresses(envelope.cc), simplify_addresses(envelope.bcc),
                envelope.in_reply_to, envelope.message_id)
    def simplify_body(body):
        if isinstance(body, TextBody):
            return body[:]
        elif isinstance(body, MessageBody):
            return (body[:7] + (simplify_envelope(body.envelope), simplify_body(body.body)) +
                    body[9:])
        elif isinstance(body, BasicBody):
            return body[:]
        elif isinstance(body, MultipartBody):
            return (body[:2] + ([simplify_body(part) for part in body.parts],) +
                    body[3:])
    if body is None:
        return None
    else:
        return repr(simplify_body(body))


def convert_bodystructure(s):
    def recover_addresses(l):
        if l:
            return [Address(*t) for t in l]
        else:
            return None
    def recover_datetime(t):
        if t:
            tzinfo = datetime.timezone(datetime.timedelta(seconds=t[-1]))
            return datetime.datetime(*t[:-1], tzinfo)
        else:
            return None
    def recover_envelope(t):
        return Envelope(recover_datetime(t[0]), t[1],
                        recover_addresses(t[2]), recover_addresses(t[3]),
                        recover_addresses(t[4]), recover_addresses(t[5]),
                        recover_addresses(t[6]), recover_addresses(t[7]),
                        t[8], t[9])
    def recover_body(t):
        if t[0] == 'text':
            return TextBody(*t)
        elif t[0] == 'message' and t[1] == 'rfc822':
            return MessageBody(*t[:7], recover_envelope(t[7]), recover_body(t[8]), *t[9:])
        elif t[0] != 'multipart':
            return BasicBody(*t)
        else:
            return MultipartBody(*t[:2], [recover_body(part) for part in t[2]], *t[3:])
    if s is None:
        return None
    else:
        return recover_body(ast.literal_eval(s))

def adapt_envelope(envelope):
    if envelope is None:
        return (None,) * 10
    else:
        return (
                adapt_datetime(envelope.date),
                envelope.subject,
                adapt_addrs(envelope.from_),
                adapt_addrs(envelope.sender),
                adapt_addrs(envelope.reply_to),
                adapt_addrs(envelope.to),
                adapt_addrs(envelope.cc),
                adapt_addrs(envelope.bcc),
                envelope.in_reply_to,
                envelope.message_id
        )
