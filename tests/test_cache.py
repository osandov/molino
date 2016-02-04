import datetime
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import call, MagicMock

from molino.cache import Cache, collate_mailboxes


def make_test_cache():
    fd, path = tempfile.mkstemp(prefix='test_cache_', suffix='.db')
    os.close(fd)
    return path, Cache(sqlite3.connect(path))


class TestMailboxes(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cache = make_test_cache()

    def tearDown(self):
        self.cache.close()
        os.unlink(self.db_path)

    def check_db(self, rows):
        db = sqlite3.connect(self.db_path)
        db.create_collation('mailbox', collate_mailboxes)
        cur = db.execute('''
        SELECT name, raw_name, delimiter, attributes
        FROM mailboxes
        ORDER BY name
        ''')
        self.assertEqual(list(cur), rows)
        db.close()

    def check_db_full(self, rows):
        db = sqlite3.connect(self.db_path)
        db.create_collation('mailbox', collate_mailboxes)
        cur = db.execute('SELECT * FROM mailboxes ORDER BY name')
        self.assertEqual(list(cur), rows)
        db.close()

    def test_init(self):
        self.check_db_full([('INBOX', b'INBOX', ord('/'), '', None, None, None, None)])

    def test_add(self):
        self.cache.add_mailbox('[Gmail]', b'[Gmail]', delimiter=ord('/'),
                               attributes={'\\NonExistent', '\\HasChildren'},
                               exists=0, unseen=0, recent=0, uidvalidity=0)
        self.cache.commit()
        self.check_db_full([
            ('INBOX', b'INBOX', ord('/'), '', None, None, None, None),
            ('[Gmail]', b'[Gmail]', ord('/'), '\\HasChildren,\\NonExistent', 0, 0, 0, 0),
        ])

    def test_delete(self):
        self.cache.add_mailbox('[Gmail]', b'[Gmail]', delimiter=ord('/'),
                               attributes=set())
        self.cache.delete_mailbox('[Gmail]')
        self.cache.commit()
        self.check_db([('INBOX', b'INBOX', ord('/'), '')])

    def test_update(self):
        self.cache.update_mailbox('INBOX', exists=1, unseen=0)
        self.cache.commit()
        self.check_db_full([('INBOX', b'INBOX', ord('/'), '', 1, 0, None, None)])

        self.cache.update_mailbox('INBOX', delimiter=ord('/'),
                                  attributes={'\\HasNoChildren'}, recent=1,
                                  uidvalidity=2)
        self.cache.commit()
        self.check_db_full([('INBOX', b'INBOX', ord('/'), '\\HasNoChildren', 1, 0, 1, 2)])

    def test_collate(self):
        # INBOX comes first
        self.cache.add_mailbox('Apple', b'Apple', delimiter=ord('/'),
                               attributes=set())
        self.cache.commit()
        self.check_db([
            ('INBOX', b'INBOX', ord('/'), ''),
            ('Apple', b'Apple', ord('/'), ''),
        ])

        # Case is ignored
        self.cache.add_mailbox('aardvark', b'aardvark', delimiter=ord('/'),
                               attributes=set())
        self.cache.commit()
        self.check_db([
            ('INBOX', b'INBOX', ord('/'), ''),
            ('aardvark', b'aardvark', ord('/'), ''),
            ('Apple', b'Apple', ord('/'), ''),
        ])

        # Locale is respected
        self.cache.add_mailbox('ábacus', b'&AOE-bacus', delimiter=ord('/'),
                               attributes=set())
        self.cache.commit()
        self.check_db([
            ('INBOX', b'INBOX', ord('/'), ''),
            ('aardvark', b'aardvark', ord('/'), ''),
            ('ábacus', b'&AOE-bacus', ord('/'), ''),
            ('Apple', b'Apple', ord('/'), ''),
        ])

        # Ties are broken lexicographically
        self.cache.add_mailbox('apple', b'apple', delimiter=ord('/'), attributes=set())
        self.cache.commit()
        self.check_db([
            ('INBOX', b'INBOX', ord('/'), ''),
            ('aardvark', b'aardvark', ord('/'), ''),
            ('ábacus', b'&AOE-bacus', ord('/'), ''),
            ('Apple', b'Apple', ord('/'), ''),
            ('apple', b'apple', ord('/'), ''),
        ])

        # [Gmail] stuff goes last
        self.cache.add_mailbox('[Gmail]', b'[Gmail]', delimiter=ord('/'), attributes=set())
        self.cache.add_mailbox('[Gmail]/Apple', b'[Gmail]/Apple',
                               delimiter=ord('/'), attributes=set())
        self.cache.add_mailbox('[Gmail]/aardvark', b'[Gmail]/aardvark',
                               delimiter=ord('/'), attributes=set())
        self.cache.add_mailbox('[Gmail]/ábacus', b'[Gmail]/&AOE-bacus',
                               delimiter=ord('/'), attributes=set())
        self.cache.add_mailbox('[Gmail]/apple', b'[Gmail]/apple',
                               delimiter=ord('/'), attributes=set())
        self.cache.commit()
        self.check_db([
            ('INBOX', b'INBOX', ord('/'), ''),
            ('aardvark', b'aardvark', ord('/'), ''),
            ('ábacus', b'&AOE-bacus', ord('/'), ''),
            ('Apple', b'Apple', ord('/'), ''),
            ('apple', b'apple', ord('/'), ''),
            ('[Gmail]', b'[Gmail]', ord('/'), ''),
            ('[Gmail]/aardvark', b'[Gmail]/aardvark', ord('/'), ''),
            ('[Gmail]/ábacus', b'[Gmail]/&AOE-bacus', ord('/'), ''),
            ('[Gmail]/Apple', b'[Gmail]/Apple', ord('/'), ''),
            ('[Gmail]/apple', b'[Gmail]/apple', ord('/'), ''),
        ])

    def test_position(self):
        self.cache.add_mailbox('Apple', b'Apple', delimiter=ord('/'), attributes=set())
        self.cache.add_mailbox('Zebra', b'Zebra', delimiter=ord('/'), attributes=set())
        self.cache.commit()

        db = sqlite3.connect(self.db_path)
        db.create_collation('mailbox', collate_mailboxes)
        for i, name in enumerate(['INBOX', 'Apple', 'Zebra']):
            cur = db.execute('SELECT COUNT(*) FROM mailboxes WHERE name<?', (name,))
            self.assertEqual(cur.fetchone()[0], i)

    def test_listing(self):
        self.cache.add_mailbox('Apple', b'Apple', delimiter=ord('/'),
                               attributes=set())
        self.cache.add_mailbox('Penguin', b'Penguin', delimiter=ord('/'),
                               attributes=set())
        self.cache.add_mailbox('Zebra', b'Zebra', delimiter=ord('/'),
                               attributes=set())

        self.cache.create_temp_mailbox_list()
        self.cache.add_listing_mailbox('INBOX')
        self.cache.add_listing_mailbox('Penguin')
        self.cache.delete_unlisted_mailboxes()
        self.cache.drop_temp_mailbox_list()

        self.cache.commit()
        self.check_db([
            ('INBOX', b'INBOX', ord('/'), ''),
            ('Penguin', b'Penguin', ord('/'), ''),
        ])

    def test_has_mailbox(self):
        self.assertTrue(self.cache.has_mailbox('INBOX'))
        self.assertFalse(self.cache.has_mailbox('[Gmail]'))


class TestGmailMessages(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cache = make_test_cache()

    def tearDown(self):
        self.cache.close()
        os.unlink(self.db_path)

    def check_db(self, rows):
        db = sqlite3.connect(self.db_path)
        db.create_collation('mailbox', collate_mailboxes)
        cur = db.execute('SELECT * FROM gmail_messages ORDER BY gm_msgid')
        self.assertEqual(list(cur), rows)
        db.close()

    def test_init(self):
        self.check_db([])

    def test_add(self):
        timestamp = int(time.time())
        date = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)

        self.cache.add_message(1337,
            date=date, subject='Re: X',
            from_=['"Jane Doe" <jane@example.com>'],
            sender=['"Jane Doe" <jane@example.org>'],
            reply_to=['"Jane Doe" <jane@example.com>'],
            to=['"John Doe" <john@example.com>', 'example@example.com'],
            cc=['cc@example.com'], bcc=['bcc@example.com'],
            in_reply_to='<1234@example.com>', message_id='<1235@example.com>',
            bodystructure=None, flags={'\\Seen', '\\Answered'},
            labels={b'\\Inbox'}, modseq=1
        )
        self.cache.commit()
        self.check_db([
            (1337, timestamp, 0, 'Re: X', '"Jane Doe" <jane@example.com>',
             '"Jane Doe" <jane@example.org>', '"Jane Doe" <jane@example.com>',
             '"John Doe" <john@example.com>\nexample@example.com',
             'cc@example.com', 'bcc@example.com', '<1234@example.com>',
             '<1235@example.com>', None, '\\Answered,\\Seen', '\\Inbox', 1)
        ])

    def test_delete(self):
        timestamp = int(time.time())
        date = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        self.cache.add_message(1337, date=date, flags={}, labels=set(), modseq=1)
        self.cache.add_message(404, date=date, flags={}, labels=set(), modseq=2)
        self.cache.delete_message(1337)
        self.cache.commit()
        self.check_db([
            (404, timestamp, 0, None, None, None, None, None, None, None, None,
             None, None, '', '', 2),
        ])

    def test_update(self):
        timestamp = int(time.time())
        date = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)

        self.cache.add_message(1337,
            date=date, subject='Re: X',
            from_=['"Jane Doe" <jane@example.com>'],
            sender=['"Jane Doe" <jane@example.org>'],
            reply_to=['"Jane Doe" <jane@example.com>'],
            to=['"John Doe" <john@example.com>', 'example@example.com'],
            cc=['cc@example.com'], bcc=['bcc@example.com'],
            in_reply_to='<1234@example.com>', message_id='<1235@example.com>',
            bodystructure=None, flags={'\\Answered'}, labels=set(), modseq=1
        )
        self.cache.update_message(1337, flags={'\\Seen', '\\Answered'},
                                  labels={b'foo', b'bar'}, modseq=2)
        self.cache.commit()
        self.check_db([
            (1337, timestamp, 0, 'Re: X', '"Jane Doe" <jane@example.com>',
             '"Jane Doe" <jane@example.org>', '"Jane Doe" <jane@example.com>',
             '"John Doe" <john@example.com>\nexample@example.com',
             'cc@example.com', 'bcc@example.com', '<1234@example.com>',
             '<1235@example.com>', None, '\\Answered,\\Seen', 'bar,foo', 2),
        ])


class TestGmailMailboxUIDs(unittest.TestCase):
    def setUp(self):
        self.db_path, self.cache = make_test_cache()

    def tearDown(self):
        self.cache.close()
        os.unlink(self.db_path)

    def check_db(self, rows):
        db = sqlite3.connect(self.db_path)
        db.create_collation('mailbox', collate_mailboxes)
        cur = db.execute('SELECT * FROM gmail_mailbox_uids ORDER BY mailbox, uid')
        self.assertEqual(list(cur), rows)
        db.close()

    def test_init(self):
        self.check_db([])

    def test_add(self):
        date = datetime.datetime.now(datetime.timezone.utc)
        self.cache.add_message(1337, date=date, flags={}, labels=set(), modseq=1)
        self.cache.add_mailbox_uid('INBOX', 1, 1337)
        self.cache.commit()
        self.check_db([
            ('INBOX', 1, 1337, int(date.timestamp())),
        ])

    def test_delete(self):
        date = datetime.datetime.now(datetime.timezone.utc)
        self.cache.add_message(1337, date=date, flags={}, labels=set(), modseq=1)
        self.cache.add_mailbox_uid('INBOX', 1, 1337)
        self.cache.delete_mailbox_uid('INBOX', 1)
        self.cache.commit()
        self.check_db([])

    def test_date(self):
        timestamp = int(time.time())
        date = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        self.cache.add_message(1337, date=date, flags={}, labels=set(), modseq=1)
        self.cache.add_mailbox_uid('INBOX', 1, 1337)
        self.cache.commit()
        self.check_db([
            ('INBOX', 1, 1337, timestamp),
        ])
