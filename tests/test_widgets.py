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
