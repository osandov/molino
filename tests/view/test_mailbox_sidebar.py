import curses
import sqlite3
import unittest

from molino.cache import Cache
from molino.view import MailboxSidebar


class TestMailboxSidebar(unittest.TestCase):
    def setUp(self):
        sqlite3.enable_callback_tracebacks(True)
        self.cache = Cache(sqlite3.connect(':memory:'))
        self.stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(False)
        self.color_scheme = {
            'sidebar': 0,
            'sidebar-new': curses.A_UNDERLINE,
            'sidebar-indicator': curses.A_REVERSE,
            'sidebar-new-indicator': curses.A_UNDERLINE | curses.A_REVERSE,
        }

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

    def create_sidebar(self, nlines=5, ncols=10):
        self.window = curses.newwin(nlines, ncols, 0, 0)
        self.sidebar = MailboxSidebar(self.cache, self.window, self.color_scheme)

    def add_mailbox(self, name):
        self.cache.add_mailbox(name, name.encode('ascii'), delimiter=ord('/'),
                               attributes=set())

    def test_init(self):
        self.create_sidebar()
        self.check_screen([
            (b'Inbox', curses.A_REVERSE),
        ])

    def test_init_multiple_mailboxes(self):
        self.add_mailbox('Apple')
        self.add_mailbox('Zebra')
        self.create_sidebar()
        self.check_screen([
            (b'Inbox', curses.A_REVERSE),
            (b'Apple', 0),
            (b'Zebra', 0),
        ])

    def test_unseen(self):
        self.cache.update_mailbox('INBOX', unseen=2)
        self.create_sidebar()
        self.check_screen([
            (b'Inbox (2)', curses.A_UNDERLINE | curses.A_REVERSE),
        ])

    def test_update_mailbox(self):
        self.add_mailbox('Apple')
        self.add_mailbox('Zebra')
        self.create_sidebar(nlines=2)
        self.cache.update_mailbox('INBOX', unseen=2)
        self.check_screen([
            (b'Inbox (2)', curses.A_UNDERLINE | curses.A_REVERSE),
            (b'Apple', 0),
        ])
        self.cache.update_mailbox('INBOX', unseen=0)
        self.check_screen([
            (b'Inbox', curses.A_REVERSE),
            (b'Apple', 0),
        ])
        self.cache.update_mailbox('Zebra', unseen=1)
        self.check_screen([
            (b'Inbox', curses.A_REVERSE),
            (b'Apple', 0),
        ])
        # TODO: above line 0

    def test_move_indicator(self):
        self.cache.delete_mailbox('INBOX')
        self.add_mailbox('a')
        self.add_mailbox('b')
        self.create_sidebar()
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
        ])
        self.sidebar.move_indicator(1)
        self.check_screen([
            (b'a', 0),
            (b'b', curses.A_REVERSE),
        ])
        self.sidebar.move_indicator(-1)
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
        ])
        self.sidebar.move_indicator(2)
        self.check_screen([
            (b'a', 0),
            (b'b', curses.A_REVERSE),
        ])
        self.sidebar.move_indicator(-2)
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
        ])
        self.sidebar.move_indicator(3)
        self.check_screen([
            (b'a', 0),
            (b'b', curses.A_REVERSE),
        ])
        self.sidebar.move_indicator(1)
        self.check_screen([
            (b'a', 0),
            (b'b', curses.A_REVERSE),
        ])
        self.sidebar.move_indicator(-3)
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
        ])
        self.sidebar.move_indicator(-1)
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
        ])

    def test_add_in_order(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('a')
        self.check_screen([
            (b'a', curses.A_REVERSE),
        ])
        self.add_mailbox('b')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
        ])
        self.add_mailbox('c')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
        ])
        self.add_mailbox('d')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
        ])
        self.add_mailbox('e')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])
        self.add_mailbox('f')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])

    def test_add_in_order_moving(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('a')
        self.check_screen([
            (b'a', curses.A_REVERSE),
        ])
        self.add_mailbox('b')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
        ])
        self.sidebar.move_indicator(1)
        self.add_mailbox('c')
        self.check_screen([
            (b'a', 0),
            (b'b', curses.A_REVERSE),
            (b'c', 0),
        ])
        self.sidebar.move_indicator(1)
        self.add_mailbox('d')
        self.check_screen([
            (b'a', 0),
            (b'b', 0),
            (b'c', curses.A_REVERSE),
            (b'd', 0),
        ])
        self.sidebar.move_indicator(1)
        self.add_mailbox('e')
        self.check_screen([
            (b'a', 0),
            (b'b', 0),
            (b'c', 0),
            (b'd', curses.A_REVERSE),
            (b'e', 0),
        ])

    def test_add_offscreen_below(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('a')
        self.add_mailbox('b')
        self.add_mailbox('c')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])
        self.add_mailbox('f')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])
        self.sidebar.move_indicator(4)
        self.add_mailbox('g')
        self.check_screen([
            (b'a', 0),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])

    def test_insert_below(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('a')
        self.add_mailbox('e')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'e', 0),
        ])
        self.add_mailbox('c')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'c', 0),
            (b'e', 0),
        ])
        self.add_mailbox('d')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])
        self.add_mailbox('b')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])

    def test_insert_below_full(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('a')
        self.add_mailbox('b')
        self.add_mailbox('c')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])
        self.add_mailbox('aa')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'aa', 0),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
        ])
        self.add_mailbox('cc')
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'aa', 0),
            (b'b', 0),
            (b'c', 0),
            (b'cc', 0),
        ])

    def test_add_in_reverse(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('e')
        self.check_screen([
            (b'e', curses.A_REVERSE),
        ])
        self.add_mailbox('d')
        self.check_screen([
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])
        self.add_mailbox('c')
        self.check_screen([
            (b'c', 0),
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])
        self.add_mailbox('b')
        self.check_screen([
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])
        self.add_mailbox('a')
        self.check_screen([
            (b'a', 0),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])
        self.add_mailbox('INBOX')
        self.check_screen([
            (b'a', 0),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])

    def test_add_in_reverse_moving(self):
        self.cache.delete_mailbox('INBOX')
        self.add_mailbox('e')
        self.create_sidebar()
        self.check_screen([
            (b'e', curses.A_REVERSE),
        ])
        self.add_mailbox('d')
        self.sidebar.move_indicator(-1)
        self.check_screen([
            (b'd', curses.A_REVERSE),
            (b'e', 0),
        ])
        self.add_mailbox('c')
        self.sidebar.move_indicator(-1)
        self.check_screen([
            (b'c', curses.A_REVERSE),
            (b'd', 0),
            (b'e', 0),
        ])
        self.add_mailbox('b')
        self.sidebar.move_indicator(-1)
        self.check_screen([
            (b'b', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])
        self.add_mailbox('a')
        self.sidebar.move_indicator(-1)
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])

    def test_add_offscreen_above_line0(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        # Add an entry offscreen such that it becomes the new first entry.
        self.add_mailbox('f')
        self.add_mailbox('g')
        self.add_mailbox('h')
        self.add_mailbox('i')
        self.add_mailbox('j')
        self.check_screen([
            (b'f', curses.A_REVERSE),
            (b'g', 0),
            (b'h', 0),
            (b'i', 0),
            (b'j', 0),
        ])
        self.add_mailbox('e')
        self.check_screen([
            (b'e', 0),
            (b'f', curses.A_REVERSE),
            (b'g', 0),
            (b'h', 0),
            (b'i', 0),
        ])
        self.add_mailbox('d')
        self.check_screen([
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
            (b'g', 0),
            (b'h', 0),
        ])
        self.add_mailbox('c')
        self.check_screen([
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
            (b'g', 0),
        ])
        self.add_mailbox('b')
        self.check_screen([
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
        ])

    def test_insert_above(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('e')
        self.add_mailbox('a')
        self.check_screen([
            (b'a', 0),
            (b'e', curses.A_REVERSE),
        ])
        self.add_mailbox('c')
        self.check_screen([
            (b'a', 0),
            (b'c', 0),
            (b'e', curses.A_REVERSE),
        ])
        self.add_mailbox('d')
        self.check_screen([
            (b'a', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])
        self.add_mailbox('b')
        self.check_screen([
            (b'a', 0),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])

    def test_insert_above_full(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('c')
        self.add_mailbox('b')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.add_mailbox('f')
        self.check_screen([
            (b'b', 0),
            (b'c', curses.A_REVERSE),
            (b'd', 0),
            (b'e', 0),
            (b'f', 0),
        ])
        self.add_mailbox('a')
        self.check_screen([
            (b'a', 0),
            (b'b', 0),
            (b'c', curses.A_REVERSE),
            (b'd', 0),
            (b'e', 0),
        ])
        self.add_mailbox('aa')
        self.check_screen([
            (b'a', 0),
            (b'aa', 0),
            (b'b', 0),
            (b'c', curses.A_REVERSE),
            (b'd', 0),
        ])
        self.add_mailbox('bb')
        self.check_screen([
            (b'a', 0),
            (b'aa', 0),
            (b'b', 0),
            (b'bb', 0),
            (b'c', curses.A_REVERSE),
        ])

    def test_add_offscreen_above_extra(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        # Add an entry offscreen that scrolls everything down by one line.
        self.add_mailbox('b')
        self.add_mailbox('c')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.add_mailbox('f')
        self.add_mailbox('g')
        self.add_mailbox('h')
        self.sidebar.move_indicator(6)
        self.sidebar.move_indicator(-2)
        self.check_screen([
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
            (b'g', 0),
            (b'h', 0),
        ])
        self.add_mailbox('aa')
        self.check_screen([
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
            (b'g', 0),
        ])
        self.add_mailbox('a')
        self.check_screen([
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
        ])

    def test_add_offscreen_above_at_end(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('b')
        self.add_mailbox('c')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.add_mailbox('f')
        self.sidebar.move_indicator(4)
        self.check_screen([
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
        ])
        self.add_mailbox('a')
        self.check_screen([
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
        ])
        self.add_mailbox('aa')
        self.check_screen([
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
        ])

    def test_add_above_at_end(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('b')
        self.add_mailbox('c')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.add_mailbox('f')
        self.sidebar.move_indicator(4)
        self.check_screen([
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
        ])
        self.add_mailbox('bb')
        self.check_screen([
            (b'bb', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
        ])
        self.add_mailbox('dd')
        self.check_screen([
            (b'c', 0),
            (b'd', 0),
            (b'dd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
        ])

    def test_move_indicator_offscreen(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('a')
        self.add_mailbox('b')
        self.add_mailbox('c')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.add_mailbox('f')
        self.add_mailbox('g')
        self.add_mailbox('h')
        self.add_mailbox('i')
        self.add_mailbox('j')
        self.add_mailbox('k')

        self.sidebar.move_indicator(5)
        self.check_screen([
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
        ])

        self.sidebar.move_indicator(5)
        self.check_screen([
            (b'g', 0),
            (b'h', 0),
            (b'i', 0),
            (b'j', 0),
            (b'k', curses.A_REVERSE),
        ])

        self.sidebar.move_indicator(-6)
        self.check_screen([
            (b'e', curses.A_REVERSE),
            (b'f', 0),
            (b'g', 0),
            (b'h', 0),
            (b'i', 0),
        ])

        self.sidebar.move_indicator(-6)
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])

    def test_del_indicator(self):
        self.cache.delete_mailbox('INBOX')
        self.add_mailbox('a')
        self.add_mailbox('b')
        self.add_mailbox('c')
        self.create_sidebar()
        self.sidebar.move_indicator(1)
        self.check_screen([
            (b'a', 0),
            (b'b', curses.A_REVERSE),
            (b'c', 0),
        ])
        self.cache.delete_mailbox('b')
        self.check_screen([
            (b'a', 0),
            (b'c', curses.A_REVERSE),
        ])
        self.cache.delete_mailbox('c')
        self.check_screen([
            (b'a', curses.A_REVERSE),
        ])
        self.cache.delete_mailbox('a')
        self.check_screen([])

        self.add_mailbox('a')
        self.add_mailbox('b')
        self.add_mailbox('c')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.add_mailbox('f')
        self.cache.delete_mailbox('a')
        self.check_screen([
            (b'b', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', 0),
        ])

        self.add_mailbox('a')
        self.sidebar.move_indicator(4)
        self.cache.delete_mailbox('f')
        self.check_screen([
            (b'a', 0),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])

    def test_del_below(self):
        self.create_sidebar()
        self.add_mailbox('Sent')
        self.cache.delete_mailbox('Sent')
        self.check_screen([
            (b'Inbox', curses.A_REVERSE),
        ])

        self.add_mailbox('b')
        self.add_mailbox('c')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.add_mailbox('f')
        self.cache.delete_mailbox('b')
        self.check_screen([
            (b'Inbox', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', 0),
        ])

        self.add_mailbox('b')

        self.sidebar.move_indicator(5)
        self.sidebar.move_indicator(-4)
        self.check_screen([
            (b'b', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', 0),
        ])

        self.cache.delete_mailbox('f')
        self.check_screen([
            (b'Inbox', 0),
            (b'b', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])

        self.add_mailbox('f')
        self.cache.delete_mailbox('f')
        self.check_screen([
            (b'Inbox', 0),
            (b'b', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])

    def test_del_above(self):
        self.cache.delete_mailbox('INBOX')
        self.add_mailbox('a')
        self.add_mailbox('b')
        self.create_sidebar()
        self.sidebar.move_indicator(1)
        self.cache.delete_mailbox('a')
        self.check_screen([
            (b'b', curses.A_REVERSE),
        ])

        self.add_mailbox('c')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.add_mailbox('f')
        self.add_mailbox('a')
        self.check_screen([
            (b'a', 0),
            (b'b', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])

        self.cache.delete_mailbox('a')
        self.check_screen([
            (b'b', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', 0),
        ])

        self.sidebar.move_indicator(1)
        self.cache.delete_mailbox('b')
        self.check_screen([
            (b'c', curses.A_REVERSE),
            (b'd', 0),
            (b'e', 0),
            (b'f', 0),
        ])

        self.add_mailbox('a')
        self.add_mailbox('b')
        self.sidebar.move_indicator(3)
        self.cache.delete_mailbox('e')
        self.check_screen([
            (b'a', 0),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'f', curses.A_REVERSE),
        ])

        self.add_mailbox('e')
        self.cache.delete_mailbox('a')
        self.check_screen([
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', curses.A_REVERSE),
        ])

        self.add_mailbox('a')
        self.sidebar.move_indicator(-4)
        self.check_screen([
            (b'b', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', 0),
        ])

        self.cache.delete_mailbox('a')
        self.check_screen([
            (b'b', curses.A_REVERSE),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
            (b'f', 0),
        ])

    def test_resize(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.add_mailbox('a')
        self.add_mailbox('b')
        self.add_mailbox('c')
        self.add_mailbox('d')
        self.add_mailbox('e')
        self.sidebar.resize(3, 10)
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
        ])

        self.sidebar.resize(5, 10)
        self.check_screen([
            (b'a', curses.A_REVERSE),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', 0),
        ])

        self.sidebar.move_indicator(4)
        self.sidebar.resize(3, 10)
        self.check_screen([
            (b'c', 0),
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])

        self.sidebar.resize(5, 10)
        self.check_screen([
            (b'a', 0),
            (b'b', 0),
            (b'c', 0),
            (b'd', 0),
            (b'e', curses.A_REVERSE),
        ])

    def test_one_line(self):
        self.cache.delete_mailbox('INBOX')
        self.create_sidebar()
        self.sidebar.resize(1, 10)
        self.add_mailbox('b')
        self.check_screen([
            (b'b', curses.A_REVERSE),
        ])
        self.add_mailbox('a')
        self.check_screen([
            (b'b', curses.A_REVERSE),
        ])
        self.add_mailbox('c')
        self.check_screen([
            (b'b', curses.A_REVERSE),
        ])

        self.sidebar.resize(3, 10)
        self.check_screen([
            (b'a', 0),
            (b'b', curses.A_REVERSE),
            (b'c', 0),
        ])
        self.sidebar.resize(1, 10)
        self.check_screen([
            (b'b', curses.A_REVERSE),
        ])

        self.cache.delete_mailbox('b')
        self.check_screen([
            (b'c', curses.A_REVERSE),
        ])
        self.cache.delete_mailbox('a')
        self.check_screen([
            (b'c', curses.A_REVERSE),
        ])
        self.cache.delete_mailbox('c')
        self.check_screen([])
