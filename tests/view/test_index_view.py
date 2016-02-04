import curses
import datetime
import sqlite3
import unittest

from molino.cache import Cache
from molino.view import IndexView


class TestIndexView(unittest.TestCase):
    def setUp(self):
        sqlite3.enable_callback_tracebacks(True)
        self.cache = Cache(sqlite3.connect(':memory:'))
        date1 = datetime.datetime.fromtimestamp(1, datetime.timezone.utc)
        date2 = datetime.datetime.fromtimestamp(2, datetime.timezone.utc)
        self.cache.add_message(1337, date=date2,
                               from_=['"Jane Doe" <jane@example.org>'],
                               subject='Janie', flags={'\\Seen'}, labels=set(),
                               modseq=1)
        self.cache.add_message(1338, date=date1,
                               from_=['"John Doe" <john@example.org>'],
                               subject='Johnnie', flags={'\\Answered'},
                               labels=set(), modseq=2)
        self.cache.add_message(1336, date=date2,
                               from_=['"Joe Bloggs" <joe@example.org>'],
                               subject='Joey', flags={'\\Flagged'},
                               labels=set(), modseq=3)
        self.cache.add_mailbox_uid('INBOX', 1, 1337)
        self.cache.add_mailbox_uid('INBOX', 2, 1338)
        self.cache.add_mailbox_uid('INBOX', 5, 1336)
        self.stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(False)
        self.color_scheme = {
            'index': 0,
            'index-new': curses.A_UNDERLINE,
            'index-indicator': curses.A_REVERSE,
            'index-new-indicator': curses.A_UNDERLINE | curses.A_REVERSE,
        }

        # The index is displayed in order of descending dates, with ties broken
        # by the Gmail message ID, also in descending order. So, we should
        # have, in order:
        self.keys = [
            (-2, -1337),
            (-2, -1336),
            (-1, -1338),
        ]
        self.rows = [
            (1337, 2, 0, '"Jane Doe" <jane@example.org>', 'Janie', '\\Seen'),
            (1336, 2, 0, '"Joe Bloggs" <joe@example.org>', 'Joey', '\\Flagged'),
            (1338, 1, 0, '"John Doe" <john@example.org>', 'Johnnie', '\\Answered'),
        ]

    def tearDown(self):
        curses.curs_set(True)
        curses.nocbreak()
        curses.echo()
        curses.endwin()
        self.cache.close()

    def check_screen(self, lines):
        height, width = self.window.getmaxyx()
        lines = lines + [(b'', 0)] * (height - len(lines))
        for y, (line, attr) in enumerate(lines):
            line = line + b' ' * (width - len(line))
            for x, c in enumerate(line):
                curses_c = self.window.inch(y, x) & 0xff
                curses_attr = self.window.inch(y, x) & ~0xff
                self.assertEqual(chr(curses_c), chr(c))
                self.assertEqual(curses_attr, attr)

    def create_index(self, nlines=5, ncols=80, mailbox='INBOX'):
        self.window = curses.newwin(nlines, ncols, 0, 0)
        self.index = IndexView(self.cache, mailbox, self.window, self.color_scheme)

    def test_max_key(self):
        self.create_index()
        self.assertEqual(self.index.max_key(), self.keys[-1])

    def test_prev_key(self):
        self.create_index()
        self.assertIsNone(self.index.prev_key(self.keys[0]))
        for i in range(1, len(self.keys)):
            with self.subTest(i=i):
                self.assertEqual(self.index.prev_key(self.keys[i]), self.keys[i - 1])

    def test_next_key(self):
        self.create_index()
        for i in range(len(self.keys) - 1):
            with self.subTest(i=i):
                self.assertEqual(self.index.next_key(self.keys[i]), self.keys[i + 1])
        self.assertIsNone(self.index.next_key(self.keys[-1]))

    def test_skip_forward(self):
        self.create_index()
        for i in range(len(self.keys)):
            for j in range(1, len(self.keys) - i):
                with self.subTest(i=i, j=j):
                    self.assertEqual(self.index.skip_forward(self.keys[i], j),
                                     (self.keys[i + j], j))
            j = len(self.keys) - i
            with self.subTest(i=i, j=j):
                self.assertEqual(self.index.skip_forward(self.keys[i], j),
                                 (self.keys[-1], j - 1))

    def test_skip_backward(self):
        self.create_index()
        for i in range(len(self.keys)):
            for j in range(1, i + 1):
                with self.subTest(i=i, j=j):
                    self.assertEqual(self.index.skip_backward(self.keys[i], j),
                                     (self.keys[i - j], j))
            j = i + 1
            with self.subTest(i=i, j=j):
                self.assertEqual(self.index.skip_backward(self.keys[i], j),
                                 (self.keys[0], j - 1))

    def test_first_n(self):
        self.create_index()
        for i in range(len(self.rows) + 1):
            with self.subTest(i=i):
                rows = [tuple(row) for row in self.index.first_n(i)]
                self.assertEqual(rows, self.rows[:i])

    def test_prev_n(self):
        self.create_index()
        for i in range(len(self.rows)):
            for j in range(1, i + 1):
                with self.subTest(i=i, j=j):
                    rows = [tuple(row) for row in self.index.prev_n(self.keys[i], j)]
                    self.assertEqual(rows, self.rows[i:i - j:-1])
            j = i + 1
            with self.subTest(i=i, j=j):
                rows = [tuple(row) for row in self.index.prev_n(self.keys[i], j)]
                self.assertEqual(rows, self.rows[i::-1])

    def test_next_n(self):
        self.create_index()
        for i in range(len(self.rows)):
            for j in range(1, len(self.rows) - i + 2):
                with self.subTest(i=i, j=j):
                    rows = [tuple(row) for row in self.index.next_n(self.keys[i], j)]
                    self.assertEqual(rows, self.rows[i:i + j])

    def test_init(self):
        self.create_index()
        self.check_screen([
            (b'Jan 01 Jane Doe        Janie', curses.A_REVERSE),
            (b'Jan 01 Joe Bloggs      Joey', curses.A_UNDERLINE),
            (b'Jan 01 John Doe        Johnnie', curses.A_UNDERLINE),
        ])

    def test_update(self):
        self.create_index()
        self.cache.update_message(self.rows[0][0], flags={})
        self.check_screen([
            (b'Jan 01 Jane Doe        Janie', curses.A_REVERSE | curses.A_UNDERLINE),
            (b'Jan 01 Joe Bloggs      Joey', curses.A_UNDERLINE),
            (b'Jan 01 John Doe        Johnnie', curses.A_UNDERLINE),
        ])

    def test_add(self):
        self.create_index()
        date = datetime.datetime(1970, 1, 2, tzinfo=datetime.timezone.utc)
        self.index.move_indicator(0)
        self.cache.add_message(1339, date=date,
                               from_=['smith@example.org'],
                               subject='Smithy', flags={'\\Seen'},
                               labels=set(), modseq=1)
        self.cache.add_mailbox_uid('INBOX', 3, 1339)
        self.check_screen([
            (b'Jan 02 smith@example.o Smithy', 0),
            (b'Jan 01 Jane Doe        Janie', curses.A_REVERSE),
            (b'Jan 01 Joe Bloggs      Joey', curses.A_UNDERLINE),
            (b'Jan 01 John Doe        Johnnie', curses.A_UNDERLINE),
        ])

    def test_delete(self):
        self.create_index()
        self.cache.delete_mailbox_uid('INBOX', 1)
        self.check_screen([
            (b'Jan 01 Joe Bloggs      Joey', curses.A_UNDERLINE | curses.A_REVERSE),
            (b'Jan 01 John Doe        Johnnie', curses.A_UNDERLINE),
        ])

    def test_other_mailbox(self):
        self.create_index()
        self.cache.add_mailbox('Sent', b'Sent', delimiter=ord('/'),
                               attributes=set())
        date = datetime.datetime(1970, 1, 2, tzinfo=datetime.timezone.utc)
        self.cache.add_message(1339, date=date,
                               from_=['smith@example.org'],
                               subject='Smithy', flags={'\\Seen'},
                               labels=set(), modseq=1)
        self.cache.add_mailbox_uid('Sent', 1, 1339)
        self.check_screen([
            (b'Jan 01 Jane Doe        Janie', curses.A_REVERSE),
            (b'Jan 01 Joe Bloggs      Joey', curses.A_UNDERLINE),
            (b'Jan 01 John Doe        Johnnie', curses.A_UNDERLINE),
        ])

    def test_stay_top(self):
        self.create_index()
        date = datetime.datetime(1970, 1, 2, tzinfo=datetime.timezone.utc)
        self.cache.add_message(1339, date=date,
                               from_=['smith@example.org'],
                               subject='Smithy', flags={'\\Seen'},
                               labels=set(), modseq=1)
        self.cache.add_mailbox_uid('INBOX', 3, 1339)
        self.check_screen([
            (b'Jan 02 smith@example.o Smithy', curses.A_REVERSE),
            (b'Jan 01 Jane Doe        Janie', 0),
            (b'Jan 01 Joe Bloggs      Joey', curses.A_UNDERLINE),
            (b'Jan 01 John Doe        Johnnie', curses.A_UNDERLINE),
        ])
