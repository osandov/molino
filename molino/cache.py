import ast
import datetime
import email.header
import email.utils
import locale
import sqlite3

from imap4.parser import TextBody, MessageBody, BasicBody, MultipartBody


class Cache:
    def __init__(self, db):
        locale.setlocale(locale.LC_ALL, '')
        self.db = db
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys = ON')

        # Mailboxes

        self.db.create_collation('mailbox', collate_mailboxes)
        self.db.execute('''
        CREATE TABLE IF NOT EXISTS mailboxes (
            name TEXT PRIMARY KEY ASC NOT NULL COLLATE mailbox,
            raw_name BLOB NOT NULL,
            /*
             * name is the decoded string representation of the mailbox name.
             * raw_name is the name exactly as it was sent by the server. In
             * theory, name.encode('imap-utf-7') == raw_name, but we store
             * raw_name to be defensive against a buggy server.
             */
            delimiter INTEGER NOT NULL,
            attributes TEXT NOT NULL,
            "exists" INTEGER,
            unseen INTEGER,
            recent INTEGER,
            uidvalidity INTEGER
        )''')
        self.db.execute('INSERT OR IGNORE INTO mailboxes VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        ('INBOX', b'INBOX', ord('/'), adapt_flags(set()), None,
                         None, None, None))

        # Messages

        self.db.execute('''
        CREATE TABLE IF NOT EXISTS gmail_messages (
            gm_msgid INTEGER PRIMARY KEY,
            date INTEGER NOT NULL, /* Unix time */
            timezone INTEGER, /* Offset from UTC in seconds */
            subject TEXT,
            "from" TEXT,
            sender TEXT,
            reply_to TEXT,
            "to" TEXT,
            cc TEXT,
            bcc TEXT,
            in_reply_to TEXT,
            message_id TEXT,
            bodystructure TEXT,
            flags TEXT NOT NULL,
            labels TEXT NOT NULL,
            modseq INTEGER NOT NULL
        )''')

        # Message bodies

        self.db.execute('''
        CREATE TABLE IF NOT EXISTS gmail_message_bodies (
            gm_msgid INTEGER NOT NULL,
            section TEXT NOT NULL,
            body BLOB NOT NULL,
            PRIMARY KEY(gm_msgid, section),
            FOREIGN KEY(gm_msgid) REFERENCES gmail_messages(gm_msgid)
        )''')

        # Mailbox UIDs

        self.db.execute('''
        CREATE TABLE IF NOT EXISTS gmail_mailbox_uids (
            mailbox TEXT NOT NULL COLLATE mailbox,
            uid INTEGER NOT NULL,
            gm_msgid INTEGER NOT NULL,
            date INTEGER NOT NULL,
            PRIMARY KEY(mailbox, uid ASC),
            FOREIGN KEY(mailbox) REFERENCES mailboxes(name),
            FOREIGN KEY(gm_msgid) REFERENCES gmail_messages(gm_msgid)
        )''')
        self.db.execute('''
        CREATE INDEX IF NOT EXISTS gmail_mailbox_index_gm_msgid
        ON gmail_mailbox_uids (gm_msgid)
        ''')
        self.db.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS gmail_mailbox_index_date
        ON gmail_mailbox_uids (mailbox, date ASC, gm_msgid ASC)
        ''')

        self.db.execute('''
        CREATE TRIGGER IF NOT EXISTS gmail_mailbox_uids_date
        AFTER UPDATE OF date ON gmail_messages
        BEGIN
            UPDATE gmail_mailbox_uids SET date=NEW.date WHERE gm_msgid=OLD.gm_msgid;
        END''')

        self.db.commit()

    def close(self):
        self.db.close()

    def commit(self):
        self.db.commit()

    # Mailboxes

    def add_mailbox(self, name, raw_name, *, delimiter, attributes,
                    exists=None, unseen=None, recent=None, uidvalidity=None):
        self.db.execute('INSERT INTO mailboxes VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (name, raw_name, delimiter, adapt_flags(attributes),
                         exists, unseen, recent, uidvalidity))

    def delete_mailbox(self, name):
        self.db.execute('DELETE FROM mailboxes WHERE name=?', (name,))

    def update_mailbox(self, name, *, delimiter=None, attributes=None,
                       exists=None, unseen=None, recent=None, uidvalidity=None):
        cols = []
        params = []
        if delimiter is not None:
            cols.append('delimiter=?')
            params.append(delimiter)
        if attributes is not None:
            cols.append('attributes=?')
            params.append(adapt_flags(attributes))
        if exists is not None:
            cols.append('"exists"=?')
            params.append(exists)
        if unseen is not None:
            cols.append('unseen=?')
            params.append(unseen)
        if recent is not None:
            cols.append('recent=?')
            params.append(recent)
        if uidvalidity is not None:
            cols.append('uidvalidity=?')
            params.append(uidvalidity)
        assert len(params) > 0
        params.append(name)
        self.db.execute('UPDATE mailboxes SET ' + ', '.join(cols) + ' WHERE name=?',
                        params)

    def has_mailbox(self, name):
        cur = self.db.execute('SELECT COUNT(*) FROM mailboxes WHERE name=?',
                              (name,))
        return bool(cur.fetchone()[0])

    def mailbox_encoded_name(self, name):
        cur = self.db.execute('SELECT raw_name FROM mailboxes WHERE name=?',
                              (name,))
        return cur.fetchone()[0]

    def get_mailbox_attributes(self, name):
        cur = self.db.execute('SELECT attributes FROM mailboxes WHERE name=?',
                              (name,))
        return convert_flags(cur.fetchone()[0])

    def get_mailbox_exists(self, name):
        cur = self.db.execute('SELECT "exists" FROM mailboxes WHERE name=?',
                              (name,))
        return cur.fetchone()[0]

    def get_mailbox_uidvalidity(self, name):
        cur = self.db.execute('SELECT uidvalidity FROM mailboxes WHERE name=?',
                              (name,))
        return cur.fetchone()[0]

    def create_temp_mailbox_list(self):
        self.db.execute('''
        CREATE TEMP TABLE temp.listing (
            name TEXT PRIMARY KEY ASC NOT NULL COLLATE mailbox
        )''')

    def drop_temp_mailbox_list(self):
        self.db.execute('DROP TABLE temp.listing')

    def add_listing_mailbox(self, name):
        self.db.execute('INSERT INTO temp.listing VALUES (?)', (name,))

    def delete_unlisted_mailboxes(self):
        # This is necessarily a full table scan. Ideally, this table won't be
        # too massive.
        self.db.execute('DELETE FROM mailboxes WHERE name NOT IN temp.listing')

    # Messages

    def add_message(self, gm_msgid, *, date, subject=None, from_=None,
                    sender=None, reply_to=None, to=None, cc=None, bcc=None,
                    in_reply_to=None, message_id=None, bodystructure=None,
                    flags, labels, modseq):
        timestamp, timezone = adapt_date(date)
        self.db.execute('''
        INSERT INTO gmail_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (gm_msgid, timestamp, timezone, subject, adapt_addrs(from_),
              adapt_addrs(sender), adapt_addrs(reply_to), adapt_addrs(to),
              adapt_addrs(cc), adapt_addrs(bcc), in_reply_to, message_id,
              adapt_bodystructure(bodystructure), adapt_flags(flags),
              adapt_labels(labels), modseq))

    def add_message_with_envelope(self, gm_msgid, envelope, *,
                                  bodystructure=None, flags, labels, modseq):
        def decode_header(b):
            if b is None:
                return None
            try:
                s = b.decode('ascii')
            except UnicodeDecodeError:
                # If it wasn't ASCII, try UTF-8, replacing any errors.
                return b.decode('utf-8', errors='replace')
            try:
                return str(email.header.make_header(email.header.decode_header(s)))
            except UnicodeDecodeError:
                # If the header is malformed, just return the raw ASCII.
                return s
        def envelope_addrs(addrs):
            if not addrs:
                return None
            l = []
            for name, adl, mailbox, host in addrs:
                assert not adl
                try:
                    email_address = '%s@%s' % (mailbox.decode('ascii'), host.decode('ascii'))
                except (UnicodeDecodeError, AttributeError):
                    # XXX: the mailbox and host are either None or not ASCII.
                    # Log a warning or something?
                    continue
                if name:
                    try:
                        realname = email.utils.quote(decode_header(name))
                        l.append('"%s" <%s>' % (realname, email_address))
                    except UnicodeDecodeError:
                        l.append(email_address)
                else:
                    l.append(email_address)
            return l if l else None
        if envelope.date is None:
            date = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
        else:
            date = envelope.date
        self.add_message(gm_msgid, date=date,
                         subject=decode_header(envelope.subject),
                         from_=envelope_addrs(envelope.from_),
                         sender=envelope_addrs(envelope.sender),
                         reply_to=envelope_addrs(envelope.reply_to),
                         to=envelope_addrs(envelope.to),
                         cc=envelope_addrs(envelope.cc),
                         bcc=envelope_addrs(envelope.bcc),
                         in_reply_to=decode_header(envelope.in_reply_to),
                         message_id=decode_header(envelope.message_id),
                         bodystructure=bodystructure, flags=flags,
                         labels=labels, modseq=modseq)

    def delete_message(self, gm_msgid):
        self.db.execute('DELETE FROM gmail_messages WHERE gm_msgid=?',
                        (gm_msgid,))

    def update_message(self, gm_msgid, *, bodystructure=None, flags=None,
                       labels=None, modseq=None):
        cols = []
        params = []
        if bodystructure is not None:
            cols.append('bodystructure=?')
            params.append(adapt_bodystructure(bodystructure))
        if flags is not None:
            cols.append('flags=?')
            params.append(adapt_flags(flags))
        if labels is not None:
            cols.append('labels=?')
            params.append(adapt_labels(labels))
        if modseq is not None:
            cols.append('modseq=?')
            params.append(modseq)
        assert len(params) > 0
        params.append(gm_msgid)
        self.db.execute('UPDATE gmail_messages SET ' + ', '.join(cols) + ' WHERE gm_msgid=?',
                        params)

    def update_message_by_uid(self, mailbox, uid, *, bodystructure=None,
                              flags=None, labels=None, modseq):
        cols = []
        params = []
        if bodystructure is not None:
            cols.append('bodystructure=?')
            params.append(adapt_bodystructure(bodystructure))
        if flags is not None:
            cols.append('flags=?')
            params.append(adapt_flags(flags))
        if labels is not None:
            cols.append('labels=?')
            params.append(adapt_labels(labels))
        if modseq is not None:
            cols.append('modseq=?')
            params.append(modseq)
        assert len(params) > 0
        params.append(mailbox)
        params.append(uid)
        self.db.execute('UPDATE gmail_messages SET ' + ', '.join(cols) +
                        ' WHERE gm_msgid=(SELECT gm_msgid FROM gmail_mailbox_uids WHERE mailbox=? AND uid=?)',
                        params)

    # Message bodies

    def add_body_sections_by_uid(self, mailbox, uid, sections):
        gm_msgid = self.db.execute('''
        SELECT gm_msgid FROM gmail_mailbox_uids
        WHERE mailbox=? and uid=?
        ''', (mailbox, uid)).fetchone()[0]
        def section_iter():
            for section, (content, origin) in sections.items():
                assert origin is None
                yield gm_msgid, section, content
        self.db.executemany('INSERT INTO gmail_message_bodies VALUES (?, ?, ?)',
                            section_iter())

    # Mailbox UIDs

    def add_mailbox_uid(self, mailbox, uid, gm_msgid):
        self.db.execute('''
        INSERT INTO gmail_mailbox_uids
        VALUES (?, ?, ?, (SELECT date FROM gmail_messages WHERE gm_msgid=?))
        ''', (mailbox, uid, gm_msgid, gm_msgid))

    def delete_mailbox_uid(self, mailbox, uid):
        self.db.execute('''
        DELETE FROM gmail_mailbox_uids
        WHERE mailbox=? AND uid=?
        ''', (mailbox, uid))

    # Fetching

    def create_temp_fetching_table(self, mailbox, uids=None):
        self.db.execute('''
        CREATE TEMP TABLE temp.fetching (
            uid INTEGER PRIMARY KEY,
            gm_msgid INTEGER
        )''')
        self._fetching_mailbox = mailbox
        if uids is not None:
            self.db.executemany('''
            INSERT INTO temp.fetching (uid) VALUES (?)
            ''', ((uid,) for uid in uids))

    def drop_temp_fetching_table(self):
        self.db.execute('DROP TABLE temp.fetching')
        del self._fetching_mailbox

    def add_fetching_uid(self, uid, gm_msgid):
        self.db.execute('''
        INSERT INTO temp.fetching VALUES (?, ?)
        ''', (uid, gm_msgid))

    def delete_fetching_uid(self, uid):
        self.db.execute('''
        DELETE FROM temp.fetching
        WHERE uid=?
        ''', (uid,))

    def update_fetching_gm_msgid(self, uid, gm_msgid):
        self.db.execute('''
        UPDATE temp.fetching SET gm_msgid=? WHERE uid=?
        ''', (gm_msgid, uid))

    def get_fetching_old_new_uids(self):
        cur = self.db.execute('''
        SELECT uid, uid IN (SELECT uid FROM gmail_mailbox_uids WHERE mailbox=?)
        FROM temp.fetching
        ''', (self._fetching_mailbox,))
        old = set()
        new = set()
        for row in cur:
            if row[1]:
                old.add(row[0])
            else:
                new.add(row[0])
        return old, new

    def get_fetching_old_new_gm_msgids(self):
        cur = self.db.execute('''
        SELECT uid, gm_msgid, gm_msgid IN (SELECT gm_msgid FROM gmail_messages)
        FROM temp.fetching
        ''')
        old = {}
        new = {}
        for row in cur:
            if row[2]:
                old[row[0]] = row[1]
            else:
                new[row[0]] = row[1]
        return old, new

    def add_fetching_uids(self):
        cur = self.db.execute('''
        INSERT INTO gmail_mailbox_uids
        SELECT ?, uid, gm_msgid, (
            SELECT date FROM gmail_messages WHERE gm_msgid=temp.fetching.gm_msgid
        )
        FROM temp.fetching
        WHERE gm_msgid NOT NULL
        ORDER BY uid DESC
        ''', (self._fetching_mailbox,))
        return cur.rowcount

    def delete_fetching_missing(self, start_uid, end_uid):
        self.db.execute('''
        DELETE FROM gmail_mailbox_uids
        WHERE mailbox=?
        AND uid>=? AND uid<?
        AND uid NOT IN (SELECT uid FROM temp.fetching)
        ''', (self._fetching_mailbox, start_uid, end_uid))


def mailbox_sort_key(mailbox):
    if mailbox is None:
        return None
    elif mailbox == 'INBOX':
        # INBOX always comes first.
        return 0, None, mailbox
    elif mailbox.startswith('[Gmail]'):
        # [Gmail] stuff goes last.
        return 2, locale.strxfrm(mailbox.casefold()), mailbox
    else:
        # Everything else is sorted alphabetically ignoring case and respecting
        # locale. Ties are broken lexicographically (this can happen if there
        # are two mailboxes which differ only in case; Gmail doesn't allow this
        # but other mail servers might).
        return 1, locale.strxfrm(mailbox.casefold()), mailbox


def collate_mailboxes(mailbox1, mailbox2):
    key1 = mailbox_sort_key(mailbox1)
    key2 = mailbox_sort_key(mailbox2)
    if key1 < key2:
        return -1
    elif key1 > key2:
        return 1
    else:
        return 0


def adapt_date(date):
    timestamp = int(date.timestamp())
    if date.tzinfo is None:
        timezone = None
    else:
        timezone = int(date.tzinfo.utcoffset(date).total_seconds())
    return timestamp, timezone


def convert_date(timestamp, timezone):
    if timezone is None:
        tzinfo = None
    else:
        tzinfo = datetime.timezone(datetime.timedelta(seconds=timezone))
    return datetime.datetime.fromtimestamp(timestamp, tzinfo)


def adapt_flags(flags):
    return ','.join(sorted(flags))


def convert_flags(s):
    if s == '':
        return set()
    else:
        return set(s.split(','))


def adapt_addrs(addrs):
    if addrs is None:
        return None
    else:
        return '\n'.join(addrs)


def convert_addrs(s):
    if s is None:
        return None
    else:
        return s.split('\n')


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
            return TextBody(t)
        elif t[0] == 'message' and t[1] == 'rfc822':
            return MessageBody(t[:7] + (recover_envelope(t[7]), recover_body(t[8])) + t[9:])
        elif t[0] != 'multipart':
            return BasicBody(t)
        else:
            return MultipartBody(t[:2] + ([recover_body(part) for part in t[2]],) + t[3:])
    if s is None:
        return None
    else:
        return recover_body(ast.literal_eval(s))


def adapt_labels(labels):
    return b','.join(sorted(labels)).decode('ascii')


def convert_labels(s):
    if s == '':
        return set()
    else:
        return set(s.encode('ascii').split(b','))
