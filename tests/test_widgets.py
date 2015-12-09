import curses
import functools
import unittest

from molino.widgets import *


def scroll_test_hidden(f):
    @functools.wraps(f)
    def wrapper(self):
        with self.subTest('Shown'):
            f(self)
        with self.subTest('Hidden'):
            self.window.resize(5, 10)
            self.widget = ScrollWidget(None, self.color_scheme)
            self.widget.resize(5, 10)
            self.hidden = True
            f(self)
    return wrapper


class TestScrollWidget(unittest.TestCase):
    def setUp(self):
        self.stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(False)
        self.color_scheme = {'normal': 0, 'reverse': curses.A_REVERSE}
        self.window = curses.newwin(5, 10, 0, 0)
        self.widget = ScrollWidget(self.window, self.color_scheme)
        self.hidden = True

    def tearDown(self):
        curses.curs_set(True)
        curses.nocbreak()
        curses.echo()
        curses.endwin()

    def check_screen(self, lines):
        if self.hidden:
            return
        lines += [b''] * (self.widget._nlines - len(lines))
        for y, line in enumerate(lines):
            line += b' ' * (self.widget._ncols - len(line))
            for x, c in enumerate(line):
                curses_c = self.window.inch(y, x) & 0xff
                curses_attr = self.window.inch(y, x) & ~0xff
                self.assertEqual(chr(curses_c), chr(c))
                self.assertEqual(curses_attr, 0)  # XXX

    @scroll_test_hidden
    def test_empty(self):
        self.widget.reset()
        self.widget.flush()
        self.check_screen([])
        self.widget.scroll(-1)
        self.check_screen([])
        self.widget.scroll(1)
        self.check_screen([])

    @scroll_test_hidden
    def test_basic(self):
        self.widget.reset()
        self.widget.add('1\n', 'normal')
        self.widget.add('2\n', 'normal')
        self.widget.add('3\n', 'normal')
        self.widget.flush()
        self.check_screen([b'1', b'2', b'3'])

    @scroll_test_hidden
    def test_scroll_shorter(self):
        self.widget.reset()
        self.widget.add('1\n', 'normal')
        self.widget.add('2\n', 'normal')
        self.widget.add('3\n', 'normal')
        self.widget.flush()

        self.widget.scroll(-1)
        self.check_screen([b'1', b'2', b'3'])

        self.widget.scroll(-3)
        self.check_screen([b'1', b'2', b'3'])

        self.widget.scroll(1)
        self.check_screen([b'1', b'2', b'3'])

        self.widget.scroll(3)
        self.check_screen([b'1', b'2', b'3'])

    @scroll_test_hidden
    def test_scroll_longer(self):
        self.widget.reset()
        self.widget.add('1\n', 'normal')
        self.widget.add('2\n', 'normal')
        self.widget.add('3\n', 'normal')
        self.widget.add('4\n', 'normal')
        self.widget.add('5\n', 'normal')
        self.widget.add('6\n', 'normal')
        self.widget.add('7\n', 'normal')
        self.widget.add('8', 'normal')
        self.widget.flush()
        self.check_screen([b'1', b'2', b'3', b'4', b'5'])

        self.widget.scroll(-1)
        self.check_screen([b'1', b'2', b'3', b'4', b'5'])

        self.widget.scroll(-2)
        self.check_screen([b'1', b'2', b'3', b'4', b'5'])

        self.widget.scroll(1)
        self.check_screen([b'2', b'3', b'4', b'5', b'6'])

        self.widget.scroll(2)
        self.check_screen([b'4', b'5', b'6', b'7', b'8'])

        self.widget.scroll(1)
        self.check_screen([b'4', b'5', b'6', b'7', b'8'])

        self.widget.scroll(3)
        self.check_screen([b'4', b'5', b'6', b'7', b'8'])

        self.widget.scroll(-2)
        self.check_screen([b'2', b'3', b'4', b'5', b'6'])

        self.widget.scroll(10)
        self.check_screen([b'4', b'5', b'6', b'7', b'8'])

    @scroll_test_hidden
    def test_resize(self):
        self.widget.reset()
        self.widget.add('1\n', 'normal')
        self.widget.add('2\n', 'normal')
        self.widget.add('3\n', 'normal')
        self.widget.add('4\n', 'normal')
        self.widget.add('5\n', 'normal')
        self.widget.add('6\n', 'normal')
        self.widget.scroll(1)
        self.check_screen([b'2', b'3', b'4', b'5', b'6'])

        self.widget.resize(3, 10)

        self.widget.reset()
        self.widget.add('1\n', 'normal')
        self.widget.add('2\n', 'normal')
        self.widget.add('3\n', 'normal')
        self.widget.add('4\n', 'normal')
        self.widget.add('5\n', 'normal')
        self.widget.add('6\n', 'normal')
        self.widget.flush()
        self.check_screen([b'2', b'3', b'4'])

    @scroll_test_hidden
    def test_carriage_return(self):
        self.widget.add('1\r\n', 'normal')
        self.widget.add('2\r\n', 'normal')
        self.widget.flush()
        self.check_screen([b'1', b'2'])

    def test_hide(self):
        self.widget.add('1\r\n', 'normal')
        self.widget.add('2\r\n', 'normal')
        self.widget.flush()
        self.check_screen([b'1', b'2'])
        self.widget.setwin(None)
        self.widget.setwin(self.window)
        self.widget.add('1\r\n', 'normal')
        self.widget.add('2\r\n', 'normal')
        self.widget.flush()
        self.check_screen([b'1', b'2'])

    def test_refresh(self):
        self.widget.refresh()
        self.widget.setwin(None)
        self.widget.refresh()


def menu_test_hidden(f):
    @functools.wraps(f)
    def wrapper(self):
        with self.subTest('Shown'):
            f(self)
        with self.subTest('Hidden'):
            self.window.resize(5, 10)
            self.widget = MenuWidget(self.formatter, None, self.color_scheme)
            self.widget.resize(5, 10)
            self.hidden = True
            f(self)
    return wrapper


class TestMenuWidget(unittest.TestCase):
    def setUp(self):
        self.stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(False)
        self.color_scheme = {'normal': 0, 'reverse': curses.A_REVERSE}
        self.window = curses.newwin(5, 10, 0, 0)
        self.window.scrollok(True)

        self.widget = MenuWidget(self.formatter, self.window, self.color_scheme)
        self.hidden = False

    @staticmethod
    def formatter(window, color_scheme, key, value, is_indicator):
        attr = color_scheme['reverse' if is_indicator else 'normal']
        entry = '%s: %s' % (key, value)
        entry += ' ' * max(0, window.getmaxyx()[1] - len(entry))
        window.insstr(entry, attr)

    def tearDown(self):
        curses.curs_set(True)
        curses.nocbreak()
        curses.echo()
        curses.endwin()

    def check_screen(self, lines):
        if self.hidden:
            self.widget.setwin(self.window)
        height, width = self.window.getmaxyx()
        lines = lines + [(b'', 0)] * (height - len(lines))
        for y, (line, attr) in enumerate(lines):
            line = line + b' ' * (width - len(line))
            for x, c in enumerate(line):
                curses_c = self.window.inch(y, x) & 0xff
                curses_attr = self.window.inch(y, x) & ~0xff
                self.assertEqual(chr(curses_c), chr(c))
                self.assertEqual(curses_attr, attr)
        if self.hidden:
            self.widget.setwin(None)

    @menu_test_hidden
    def test_empty(self):
        self.check_screen([])
        self.widget.move_indicator(1)
        self.check_screen([])
        self.widget.move_indicator(-1)
        self.check_screen([])
        self.widget.redraw()
        self.check_screen([])
        self.assertEqual(self.widget.get_indicator(), None)

    @menu_test_hidden
    def test_basic(self):
        self.widget.add_entry('abc', 123)
        self.check_screen([
            (b'abc: 123', curses.A_REVERSE),
        ])

        self.widget.add_entry('def', 456)
        self.check_screen([
            (b'abc: 123', curses.A_REVERSE),
            (b'def: 456', 0),
        ])

    @menu_test_hidden
    def test_move_indicator(self):
        self.widget.add_entry('a', 1)
        self.widget.add_entry('b', 2)
        self.assertEqual(self.widget.get_indicator(), ('a', 1))
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
        ])
        self.widget.move_indicator(1)
        self.assertEqual(self.widget.get_indicator(), ('b', 2))
        self.check_screen([
            (b'a: 1', 0),
            (b'b: 2', curses.A_REVERSE),
        ])
        self.widget.move_indicator(-1)
        self.assertEqual(self.widget.get_indicator(), ('a', 1))
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
        ])
        self.widget.move_indicator(2)
        self.assertEqual(self.widget.get_indicator(), ('b', 2))
        self.check_screen([
            (b'a: 1', 0),
            (b'b: 2', curses.A_REVERSE),
        ])
        self.widget.move_indicator(-2)
        self.assertEqual(self.widget.get_indicator(), ('a', 1))
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
        ])
        self.widget.move_indicator(3)
        self.assertEqual(self.widget.get_indicator(), ('b', 2))
        self.check_screen([
            (b'a: 1', 0),
            (b'b: 2', curses.A_REVERSE),
        ])
        self.widget.move_indicator(1)
        self.assertEqual(self.widget.get_indicator(), ('b', 2))
        self.check_screen([
            (b'a: 1', 0),
            (b'b: 2', curses.A_REVERSE),
        ])
        self.widget.move_indicator(-3)
        self.assertEqual(self.widget.get_indicator(), ('a', 1))
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
        ])
        self.widget.move_indicator(-1)
        self.assertEqual(self.widget.get_indicator(), ('a', 1))
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
        ])

    @menu_test_hidden
    def test_add_in_order(self):
        self.widget.add_entry('a', 1)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
        ])
        self.widget.add_entry('b', 2)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
        ])
        self.widget.add_entry('c', 3)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
            (b'c: 3', 0),
        ])
        self.widget.add_entry('d', 4)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
        ])
        self.widget.add_entry('e', 5)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 5', 0),
        ])

    @menu_test_hidden
    def test_add_in_order_moving(self):
        self.widget.add_entry('a', 1)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
        ])
        self.widget.add_entry('b', 2)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
        ])
        self.widget.move_indicator(1)
        self.widget.add_entry('c', 3)
        self.check_screen([
            (b'a: 1', 0),
            (b'b: 2', curses.A_REVERSE),
            (b'c: 3', 0),
        ])
        self.widget.move_indicator(1)
        self.widget.add_entry('d', 4)
        self.check_screen([
            (b'a: 1', 0),
            (b'b: 2', 0),
            (b'c: 3', curses.A_REVERSE),
            (b'd: 4', 0),
        ])
        self.widget.move_indicator(1)
        self.widget.add_entry('e', 5)
        self.check_screen([
            (b'a: 1', 0),
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', curses.A_REVERSE),
            (b'e: 5', 0),
        ])

    @menu_test_hidden
    def test_add_offscreen_below(self):
        self.widget.add_entry('a', 1)
        self.widget.add_entry('b', 2)
        self.widget.add_entry('c', 3)
        self.widget.add_entry('d', 4)
        self.widget.add_entry('e', 5)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 5', 0),
        ])
        self.widget.add_entry('f', 6)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 5', 0),
        ])
        self.widget.move_indicator(4)
        self.widget.add_entry('g', 7)
        self.check_screen([
            (b'a: 1', 0),
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 5', curses.A_REVERSE),
        ])

    @menu_test_hidden
    def test_insert_below(self):
        self.widget.add_entry('a', 1)
        self.widget.add_entry('e', 2)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'e: 2', 0),
        ])
        self.widget.add_entry('c', 3)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'c: 3', 0),
            (b'e: 2', 0),
        ])
        self.widget.add_entry('d', 4)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 2', 0),
        ])
        self.widget.add_entry('b', 5)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 5', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 2', 0),
        ])

    @menu_test_hidden
    def test_insert_below_full(self):
        self.widget.add_entry('a', 1)
        self.widget.add_entry('b', 2)
        self.widget.add_entry('c', 3)
        self.widget.add_entry('d', 4)
        self.widget.add_entry('e', 5)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 5', 0),
        ])
        self.widget.add_entry('aa', 11)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'aa: 11', 0),
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
        ])
        self.widget.add_entry('cc', 204)
        self.check_screen([
            (b'a: 1', curses.A_REVERSE),
            (b'aa: 11', 0),
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'cc: 204', 0),
        ])

    @menu_test_hidden
    def test_add_in_reverse(self):
        self.widget.add_entry('e', 1)
        self.check_screen([
            (b'e: 1', curses.A_REVERSE),
        ])
        self.widget.add_entry('d', 2)
        self.check_screen([
            (b'd: 2', 0),
            (b'e: 1', curses.A_REVERSE),
        ])
        self.widget.add_entry('c', 3)
        self.check_screen([
            (b'c: 3', 0),
            (b'd: 2', 0),
            (b'e: 1', curses.A_REVERSE),
        ])
        self.widget.add_entry('b', 4)
        self.check_screen([
            (b'b: 4', 0),
            (b'c: 3', 0),
            (b'd: 2', 0),
            (b'e: 1', curses.A_REVERSE),
        ])
        self.widget.add_entry('a', 5)
        self.check_screen([
            (b'a: 5', 0),
            (b'b: 4', 0),
            (b'c: 3', 0),
            (b'd: 2', 0),
            (b'e: 1', curses.A_REVERSE),
        ])

    @menu_test_hidden
    def test_add_in_reverse_moving(self):
        self.widget.add_entry('e', 1)
        self.check_screen([
            (b'e: 1', curses.A_REVERSE),
        ])
        self.widget.add_entry('d', 2)
        self.widget.move_indicator(-1)
        self.check_screen([
            (b'd: 2', curses.A_REVERSE),
            (b'e: 1', 0),
        ])
        self.widget.add_entry('c', 3)
        self.widget.move_indicator(-1)
        self.check_screen([
            (b'c: 3', curses.A_REVERSE),
            (b'd: 2', 0),
            (b'e: 1', 0),
        ])
        self.widget.add_entry('b', 4)
        self.widget.move_indicator(-1)
        self.check_screen([
            (b'b: 4', curses.A_REVERSE),
            (b'c: 3', 0),
            (b'd: 2', 0),
            (b'e: 1', 0),
        ])
        self.widget.add_entry('a', 5)
        self.widget.move_indicator(-1)
        self.check_screen([
            (b'a: 5', curses.A_REVERSE),
            (b'b: 4', 0),
            (b'c: 3', 0),
            (b'd: 2', 0),
            (b'e: 1', 0),
        ])

    @menu_test_hidden
    def test_add_offscreen_above_line0(self):
        # Add an entry offscreen such that it becomes the new first entry.
        self.widget.add_entry('f', -1)
        self.widget.add_entry('g', -2)
        self.widget.add_entry('h', -3)
        self.widget.add_entry('i', -4)
        self.widget.add_entry('j', -5)
        self.check_screen([
            (b'f: -1', curses.A_REVERSE),
            (b'g: -2', 0),
            (b'h: -3', 0),
            (b'i: -4', 0),
            (b'j: -5', 0),
        ])
        self.widget.add_entry('e', 1)
        self.check_screen([
            (b'e: 1', 0),
            (b'f: -1', curses.A_REVERSE),
            (b'g: -2', 0),
            (b'h: -3', 0),
            (b'i: -4', 0),
        ])
        self.widget.add_entry('d', 2)
        self.check_screen([
            (b'd: 2', 0),
            (b'e: 1', 0),
            (b'f: -1', curses.A_REVERSE),
            (b'g: -2', 0),
            (b'h: -3', 0),
        ])
        self.widget.add_entry('c', 1)
        self.check_screen([
            (b'c: 1', 0),
            (b'd: 2', 0),
            (b'e: 1', 0),
            (b'f: -1', curses.A_REVERSE),
            (b'g: -2', 0),
        ])
        self.widget.add_entry('b', 0)
        self.check_screen([
            (b'b: 0', 0),
            (b'c: 1', 0),
            (b'd: 2', 0),
            (b'e: 1', 0),
            (b'f: -1', curses.A_REVERSE),
        ])

    @menu_test_hidden
    def test_insert_above(self):
        self.widget.add_entry('e', 2)
        self.widget.add_entry('a', 1)
        self.check_screen([
            (b'a: 1', 0),
            (b'e: 2', curses.A_REVERSE),
        ])
        self.widget.add_entry('c', 3)
        self.check_screen([
            (b'a: 1', 0),
            (b'c: 3', 0),
            (b'e: 2', curses.A_REVERSE),
        ])
        self.widget.add_entry('d', 4)
        self.check_screen([
            (b'a: 1', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 2', curses.A_REVERSE),
        ])
        self.widget.add_entry('b', 5)
        self.check_screen([
            (b'a: 1', 0),
            (b'b: 5', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 2', curses.A_REVERSE),
        ])

    @menu_test_hidden
    def test_insert_above_full(self):
        self.widget.add_entry('c', 0)
        self.widget.add_entry('b', 0)
        self.widget.add_entry('d', 0)
        self.widget.add_entry('e', 0)
        self.widget.add_entry('f', 0)
        self.check_screen([
            (b'b: 0', 0),
            (b'c: 0', curses.A_REVERSE),
            (b'd: 0', 0),
            (b'e: 0', 0),
            (b'f: 0', 0),
        ])
        self.widget.add_entry('a', 0)
        self.check_screen([
            (b'a: 0', 0),
            (b'b: 0', 0),
            (b'c: 0', curses.A_REVERSE),
            (b'd: 0', 0),
            (b'e: 0', 0),
        ])
        self.widget.add_entry('aa', 0)
        self.check_screen([
            (b'a: 0', 0),
            (b'aa: 0', 0),
            (b'b: 0', 0),
            (b'c: 0', curses.A_REVERSE),
            (b'd: 0', 0),
        ])
        self.widget.add_entry('bb', 0)
        self.check_screen([
            (b'a: 0', 0),
            (b'aa: 0', 0),
            (b'b: 0', 0),
            (b'bb: 0', 0),
            (b'c: 0', curses.A_REVERSE),
        ])

    @menu_test_hidden
    def test_add_offscreen_above_extra(self):
        # Add an entry offscreen that scrolls everything down by one line.
        self.widget.add_entry('b', 1)
        self.widget.add_entry('c', 2)
        self.widget.add_entry('d', 3)
        self.widget.add_entry('e', 4)
        self.widget.add_entry('f', 5)
        self.widget.add_entry('g', 6)
        self.widget.add_entry('h', 7)
        self.widget.move_indicator(6)
        self.widget.move_indicator(-2)
        self.check_screen([
            (b'd: 3', 0),
            (b'e: 4', 0),
            (b'f: 5', curses.A_REVERSE),
            (b'g: 6', 0),
            (b'h: 7', 0),
        ])
        self.widget.add_entry('aa', 8)
        self.check_screen([
            (b'c: 2', 0),
            (b'd: 3', 0),
            (b'e: 4', 0),
            (b'f: 5', curses.A_REVERSE),
            (b'g: 6', 0),
        ])
        self.widget.add_entry('a', 88)
        self.check_screen([
            (b'b: 1', 0),
            (b'c: 2', 0),
            (b'd: 3', 0),
            (b'e: 4', 0),
            (b'f: 5', curses.A_REVERSE),
        ])

    @menu_test_hidden
    def test_add_offscreen_above_at_end(self):
        self.widget.add_entry('b', 2)
        self.widget.add_entry('c', 3)
        self.widget.add_entry('d', 4)
        self.widget.add_entry('e', 5)
        self.widget.add_entry('f', 6)
        self.widget.move_indicator(4)
        self.check_screen([
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 5', 0),
            (b'f: 6', curses.A_REVERSE),
        ])
        self.widget.add_entry('a', 7)
        self.check_screen([
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 5', 0),
            (b'f: 6', curses.A_REVERSE),
        ])
        self.widget.add_entry('aa', 77)
        self.check_screen([
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 5', 0),
            (b'f: 6', curses.A_REVERSE),
        ])

    @menu_test_hidden
    def test_add_above_at_end(self):
        self.widget.add_entry('b', 2)
        self.widget.add_entry('c', 3)
        self.widget.add_entry('d', 4)
        self.widget.add_entry('e', 5)
        self.widget.add_entry('f', 6)
        self.widget.move_indicator(4)
        self.check_screen([
            (b'b: 2', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 5', 0),
            (b'f: 6', curses.A_REVERSE),
        ])
        self.widget.add_entry('bb', 7)
        self.check_screen([
            (b'bb: 7', 0),
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'e: 5', 0),
            (b'f: 6', curses.A_REVERSE),
        ])
        self.widget.add_entry('dd', 8)
        self.check_screen([
            (b'c: 3', 0),
            (b'd: 4', 0),
            (b'dd: 8', 0),
            (b'e: 5', 0),
            (b'f: 6', curses.A_REVERSE),
        ])

    @menu_test_hidden
    def test_move_indicator_offscreen(self):
        self.widget.add_entry('a', 0)
        self.widget.add_entry('b', 1)
        self.widget.add_entry('c', 2)
        self.widget.add_entry('d', 3)
        self.widget.add_entry('e', 4)
        self.widget.add_entry('f', 5)
        self.widget.add_entry('g', 6)
        self.widget.add_entry('h', 7)
        self.widget.add_entry('i', 8)
        self.widget.add_entry('j', 9)
        self.widget.add_entry('k', 10)

        self.widget.move_indicator(5)
        self.check_screen([
            (b'b: 1', 0),
            (b'c: 2', 0),
            (b'd: 3', 0),
            (b'e: 4', 0),
            (b'f: 5', curses.A_REVERSE),
        ])

        self.widget.move_indicator(5)
        self.check_screen([
            (b'g: 6', 0),
            (b'h: 7', 0),
            (b'i: 8', 0),
            (b'j: 9', 0),
            (b'k: 10', curses.A_REVERSE),
        ])

        self.widget.move_indicator(-6)
        self.check_screen([
            (b'e: 4', curses.A_REVERSE),
            (b'f: 5', 0),
            (b'g: 6', 0),
            (b'h: 7', 0),
            (b'i: 8', 0),
        ])

        self.widget.move_indicator(-6)
        self.check_screen([
            (b'a: 0', curses.A_REVERSE),
            (b'b: 1', 0),
            (b'c: 2', 0),
            (b'd: 3', 0),
            (b'e: 4', 0),
        ])

    @menu_test_hidden
    def test_del_indicator(self):
        self.widget.add_entry('a', 97)
        self.widget.add_entry('b', 98)
        self.widget.add_entry('c', 99)
        self.widget.move_indicator(1)
        self.check_screen([
            (b'a: 97', 0),
            (b'b: 98', curses.A_REVERSE),
            (b'c: 99', 0),
        ])
        self.widget.del_entry('b')
        self.check_screen([
            (b'a: 97', 0),
            (b'c: 99', curses.A_REVERSE),
        ])
        self.widget.del_entry('c')
        self.check_screen([
            (b'a: 97', curses.A_REVERSE),
        ])
        self.widget.del_entry('a')
        self.check_screen([])

        self.widget.add_entry('a', 97)
        self.widget.add_entry('b', 98)
        self.widget.add_entry('c', 99)
        self.widget.add_entry('d', 100)
        self.widget.add_entry('e', 101)
        self.widget.add_entry('f', 102)
        self.widget.del_entry('a')
        self.check_screen([
            (b'b: 98', curses.A_REVERSE),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
            (b'f: 102', 0),
        ])

        self.widget.add_entry('a', 97)
        self.widget.move_indicator(4)
        self.widget.del_entry('f')
        self.check_screen([
            (b'a: 97', 0),
            (b'b: 98', 0),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', curses.A_REVERSE),
        ])

    @menu_test_hidden
    def test_del_below(self):
        self.widget.add_entry('a', 97)
        self.widget.add_entry('b', 98)
        self.widget.del_entry('b')
        self.check_screen([
            (b'a: 97', curses.A_REVERSE),
        ])

        self.widget.add_entry('b', 98)
        self.widget.add_entry('c', 99)
        self.widget.add_entry('d', 100)
        self.widget.add_entry('e', 101)
        self.widget.add_entry('f', 102)
        self.widget.del_entry('b')
        self.check_screen([
            (b'a: 97', curses.A_REVERSE),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
            (b'f: 102', 0),
        ])

        self.widget.add_entry('b', 98)

        self.widget.move_indicator(5)
        self.widget.move_indicator(-4)
        self.check_screen([
            (b'b: 98', curses.A_REVERSE),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
            (b'f: 102', 0),
        ])

        self.widget.del_entry('f')
        self.check_screen([
            (b'a: 97', 0),
            (b'b: 98', curses.A_REVERSE),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
        ])

        self.widget.add_entry('f', 102)
        self.widget.del_entry('f')
        self.check_screen([
            (b'a: 97', 0),
            (b'b: 98', curses.A_REVERSE),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
        ])

    @menu_test_hidden
    def test_del_above(self):
        self.widget.add_entry('a', 97)
        self.widget.add_entry('b', 98)
        self.widget.move_indicator(1)
        self.widget.del_entry('a')
        self.check_screen([
            (b'b: 98', curses.A_REVERSE),
        ])

        self.widget.add_entry('c', 99)
        self.widget.add_entry('d', 100)
        self.widget.add_entry('e', 101)
        self.widget.add_entry('f', 102)
        self.widget.add_entry('a', 97)
        self.check_screen([
            (b'a: 97', 0),
            (b'b: 98', curses.A_REVERSE),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
        ])

        self.widget.del_entry('a')
        self.check_screen([
            (b'b: 98', curses.A_REVERSE),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
            (b'f: 102', 0),
        ])

        self.widget.move_indicator(1)
        self.widget.del_entry('b')
        self.check_screen([
            (b'c: 99', curses.A_REVERSE),
            (b'd: 100', 0),
            (b'e: 101', 0),
            (b'f: 102', 0),
        ])

        self.widget.add_entry('a', 97)
        self.widget.add_entry('b', 98)
        self.widget.move_indicator(3)
        self.widget.del_entry('e')
        self.check_screen([
            (b'a: 97', 0),
            (b'b: 98', 0),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'f: 102', curses.A_REVERSE),
        ])

        self.widget.add_entry('e', 101)
        self.widget.del_entry('a')
        self.check_screen([
            (b'b: 98', 0),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
            (b'f: 102', curses.A_REVERSE),
        ])

        self.widget.add_entry('a', 97)
        self.widget.move_indicator(-4)
        self.check_screen([
            (b'b: 98', curses.A_REVERSE),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
            (b'f: 102', 0),
        ])

        self.widget.del_entry('a')
        self.check_screen([
            (b'b: 98', curses.A_REVERSE),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
            (b'f: 102', 0),
        ])

    @menu_test_hidden
    def test_resize(self):
        self.widget.add_entry('a', 97)
        self.widget.add_entry('b', 98)
        self.widget.add_entry('c', 99)
        self.widget.add_entry('d', 100)
        self.widget.add_entry('e', 101)
        if self.hidden:
            self.window.resize(3, 10)
        else:
            self.widget.resize(3, 10)
        self.check_screen([
            (b'a: 97', curses.A_REVERSE),
            (b'b: 98', 0),
            (b'c: 99', 0),
        ])

        if self.hidden:
            self.window.resize(5, 10)
        else:
            self.widget.resize(5, 10)
        self.check_screen([
            (b'a: 97', curses.A_REVERSE),
            (b'b: 98', 0),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
        ])

        self.widget.move_indicator(4)
        if self.hidden:
            self.window.resize(3, 10)
        else:
            self.widget.resize(3, 10)
        self.check_screen([
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', curses.A_REVERSE),
        ])

        if self.hidden:
            self.window.resize(5, 10)
        else:
            self.widget.resize(5, 10)
        self.check_screen([
            (b'a: 97', 0),
            (b'b: 98', 0),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', curses.A_REVERSE),
        ])

    @menu_test_hidden
    def test_redraw_entry(self):
        self.widget.add_entry('a', 97)
        self.widget.add_entry('b', 98)
        self.widget.add_entry('c', 99)
        self.widget.add_entry('d', 100)
        self.widget.add_entry('e', 101)
        self.widget.add_entry('f', 102)
        self.check_screen([
            (b'a: 97', curses.A_REVERSE),
            (b'b: 98', 0),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
        ])

        self.window.insstr(0, 0, 'XXXXX')
        self.widget.redraw_entry('a')
        self.check_screen([
            (b'a: 97', curses.A_REVERSE),
            (b'b: 98', 0),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
        ])

        self.widget.redraw_entry('f')
        self.check_screen([
            (b'a: 97', curses.A_REVERSE),
            (b'b: 98', 0),
            (b'c: 99', 0),
            (b'd: 100', 0),
            (b'e: 101', 0),
        ])

    @menu_test_hidden
    def test_one_line(self):
        if self.hidden:
            self.window.resize(1, 10)
        else:
            self.widget.resize(1, 10)
        self.widget.add_entry('b', 2)
        self.check_screen([
            (b'b: 2', curses.A_REVERSE),
        ])
        self.widget.add_entry('a', 1)
        self.check_screen([
            (b'b: 2', curses.A_REVERSE),
        ])
        self.widget.add_entry('c', 3)
        self.check_screen([
            (b'b: 2', curses.A_REVERSE),
        ])

        if self.hidden:
            self.window.resize(3, 10)
        else:
            self.widget.resize(3, 10)
        self.check_screen([
            (b'a: 1', 0),
            (b'b: 2', curses.A_REVERSE),
            (b'c: 3', 0),
        ])
        if self.hidden:
            self.window.resize(1, 10)
        else:
            self.widget.resize(1, 10)
        self.check_screen([
            (b'b: 2', curses.A_REVERSE),
        ])

        self.widget.del_entry('b')
        self.check_screen([
            (b'c: 3', curses.A_REVERSE),
        ])
        self.widget.del_entry('a')
        self.check_screen([
            (b'c: 3', curses.A_REVERSE),
        ])
        self.widget.del_entry('c')
        self.check_screen([])

    def test_refresh(self):
        self.widget.refresh()
        self.widget.setwin(None)
        self.widget.refresh()
