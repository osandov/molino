import email.header
import email.utils

from molino.callbackstack import callback_stack
import molino.imap.codecs


class Model:
    """
    The email client is essentially a sync engine between the actual state on
    the IMAP server and the view presented to the user. We cache just about
    everything the server tells us in memory.
    """

    def __init__(self):
        self.__mailboxes = {b'INBOX': Mailbox(self, b'INBOX', ord('/'), set())}
        self.__gmail_msgs = {}

    # Mailboxes

    def get_mailbox(self, name):
        """
        Get the mailbox with the given name or raise KeyError if there is no
        such mailbox.
        """
        return self.__mailboxes[name]

    def add_mailbox(self, mailbox):
        """Add the given mailbox to the database."""
        self.__mailboxes[mailbox.name] = mailbox
        self.on_mailboxes_add(mailbox)

    def delete_mailbox(self, name):
        """Delete the mailbox with the given name from the database."""
        mailbox = self.__mailboxes.pop(name)
        self.on_mailboxes_delete(mailbox)

    def mailboxes(self):
        """Return an iterator over all of the mailboxes in the database."""
        return self.__mailboxes.values()

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

    @property
    def gmail_msgs(self):
        """Mapping from Gmail message ID to Message object."""
        return self.__gmail_msgs


class Mailbox:
    """Cache of an IMAP mailbox."""

    def __init__(self, model, name, delimiter, attributes):
        self._model = model
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
        self.__exists = None
        self.__unseen = set()
        self.__num_unseen = None
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
        self.__delimiter = value
        self._model.on_mailbox_update(self, 'delimiter')

    @property
    def attributes(self):
        """Set of mailbox name attributes as strings."""
        # XXX: should these be case-insensitive?
        return self.__attributes

    @attributes.setter
    def attributes(self, value):
        self.__attributes = value
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
        return self.__messages[uid]

    def contains_message(self, uid):
        """Return whether the mailbox contains a message with the given UID."""
        return uid in self.__messages

    def add_message(self, uid, message):
        """Add a message with the given UID to the mailbox."""
        self.__messages[uid] = message
        self._model.on_message_add(self, uid, message)

    def delete_message(self, uid):
        """Delete the message with the given UID from the mailbox."""
        message = self.__messages.pop(uid)
        self._model.on_message_delete(self, uid, message)

    def messages(self):
        """
        Return an iterator over all of the (UID, message) pairs in the mailbox.
        """
        return self.__messages.items()


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
    def __init__(self, model, id):
        self._model = model
        self.__id = id
        self.__envelope = None
        self.__bodystructure = None
        self.__body = {}
        self.__flags = None

    @property
    def id(self):
        """
        Hashable object that uniquely identifies this message across all
        mailboxes forever. For Gmail, this is the X-GM-MSGID, an unsigned
        64-bit integer.
        """
        return self.__id

    @property
    def envelope(self):
        """Internet Message Format envelope."""
        return self.__envelope

    @envelope.setter
    def envelope(self, value):
        self.__envelope = value
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
        self._model.on_message_update(self, 'bodystructure')

    def get_body_section(self, section):
        """Get the given body section or raise KeyError if it is not cached."""
        return self.__body[section]

    def have_body_section(self, section):
        """Return whether the given section is cached."""
        return section in self.__body

    def add_body_sections(self, sections):
        for section, (content, origin) in sections.items():
            assert origin is None
            self.__body[section] = content
        self._model.on_message_update(self, 'body')

    @property
    def flags(self):
        """Message flags."""
        return self.__flags

    @flags.setter
    def flags(self, value):
        self.__flags = value
        self._model.on_message_update(self, 'flags')
