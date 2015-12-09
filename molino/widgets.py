import curses
import logging

from molino.sorteddict import SortedDict


class ScrollWidget:
    """
    A widget containing a scrollable region of text.
    """

    def __init__(self, window, color_scheme):
        self._window = window
        if self._window:
            self._nlines, self._ncols = self._window.getmaxyx()
            self._window.erase()
        else:
            self._nlines = 20
            self._ncols = 80
        self._color_scheme = color_scheme

        self._pad = curses.newpad(self._nlines, self._ncols)
        self._scroll_pos = 0

    def refresh(self):
        if self._window:
            self._window.refresh()

    def resize(self, nlines, ncols):
        if self._window:
            self._window.resize(nlines, ncols)
            self._window.erase()
        self._resize(nlines, ncols)

    def _resize(self, nlines, ncols):
        self._nlines, self._ncols = nlines, ncols
        self._pad.resize(self._nlines, self._ncols)

    def setwin(self, window):
        old_window = self._window
        self._window = window
        if self._window:
            self._resize(*self._window.getmaxyx())
        return old_window

    def reset(self):
        """Reset the buffer. The scroll position will be conserved."""
        self._pad.move(0, 0)
        self._pad.erase()

    def add(self, string, color):
        """Add the given string to the scrollable buffer."""
        attr = self._color_scheme[color]
        for c in string:
            if c == '\r':
                # XXX
                continue
            h, w = self._pad.getmaxyx()
            if self._pad.getyx()[0] == h - 1:
                self._pad.resize(h + self._nlines, w)
            self._pad.addstr(c, attr)

    def flush(self):
        """Flush the scrollable buffer to the window."""
        self._scroll_pos = self._clip_scroll_pos(self._scroll_pos)
        self._flush()

    def scroll(self, lines):
        """
        Scroll the widget by the given number of lines, which may be positive
        (down) or negative (up). The buffer is implicitly flushed.
        """
        self.scroll_to(self._scroll_pos + lines)

    def scroll_to(self, line):
        """
        Scroll the widget to the given line number, counting from 0. The buffer
        is implicitly flushed.
        """
        newpos = self._clip_scroll_pos(line)
        if newpos != self._scroll_pos:
            self._scroll_pos = newpos
            self._flush()

    def _clip_scroll_pos(self, pos):
        y, x = self._pad.getyx()
        lines = y + (1 if x else 0)
        return max(min(pos, lines - self._nlines), 0)

    def _flush(self):
        assert self._scroll_pos >= 0
        assert self._scroll_pos <= self._pad.getmaxyx()[0]
        if not self._window:
            return
        nlines = min(self._pad.getmaxyx()[0] - self._scroll_pos, self._nlines)
        ncols = min(self._pad.getmaxyx()[1], self._ncols)
        self._pad.overwrite(self._window, self._scroll_pos, 0,
                            0, 0, nlines - 1, ncols - 1)


class MenuWidget:
    def __init__(self, formatter, window, color_scheme, sort_key=None):
        self._formatter = formatter
        self._window = window
        if self._window:
            self._window.scrollok(True)
            self._nlines, self._ncols = self._window.getmaxyx()
            self._window.erase()
        else:
            self._nlines = 20
            self._ncols = 80
        self._color_scheme = color_scheme

        self.dict = SortedDict(sort_key=sort_key)
        self._indicator = None
        self._indicator_pos = None

    def refresh(self):
        if self._window:
            self._window.refresh()

    def resize(self, nlines, ncols):
        if self._window:
            self._window.resize(nlines, ncols)
        self._resize(nlines, ncols)

    def _resize(self, nlines, ncols):
        old_nlines = self._nlines
        self._nlines, self._ncols = nlines, ncols
        if len(self.dict) > 0:
            if self._nlines < old_nlines:
                if self._indicator_pos >= self._nlines:
                    self._indicator_pos = self._nlines - 1
            elif self._nlines > old_nlines:
                index = self.dict.index(self._indicator)
                first_index = index - self._indicator_pos
                new_lines = self._nlines - old_nlines
                self._indicator_pos += min(new_lines, first_index)
        self.redraw()

    def setwin(self, window):
        old_window = self._window
        self._window = window
        if self._window:
            self._window.scrollok(True)
            self._resize(*self._window.getmaxyx())
        return old_window

    def get_indicator(self):
        if len(self.dict) > 0:
            return self._indicator, self.dict[self._indicator]

    def add_entry(self, key, value):
        first = len(self.dict) == 0
        self.dict[key] = value
        if first:
            self._indicator = key
            self._indicator_pos = 0
            line = self._indicator_pos
        else:
            indicator_index = self.dict.index(self._indicator)
            index = self.dict.index(key)

            if index < indicator_index:
                if self._indicator_pos == self._nlines - 1:
                    self._win_scroll()
                    self._indicator_pos -= 1
                self._indicator_pos += 1
                line = self._indicator_pos + index - indicator_index
                if line < 0:
                    key = self.dict.ith_key(indicator_index - self._indicator_pos)
                    line = 0
                self._win_move(line, 0)
                self._win_insertln()
            else:
                line = self._indicator_pos + index - indicator_index
                if line >= self._nlines:
                    # Offscreen, don't need to draw anything.
                    return
                else:
                    self._win_move(line, 0)
                    self._win_insertln()
        self._draw_entry(key, self.dict[key], line)

    def del_entry(self, key):
        if len(self.dict) == 1:
            del self.dict[key]
            self._win_move(0, 0)
            self._win_clrtoeol()
            self._indicator = None
            self._indicator_pos = None
            return

        indicator_index = self.dict.index(self._indicator)
        index = self.dict.index(key)
        del self.dict[key]
        line = self._indicator_pos + index - indicator_index

        if index < indicator_index:
            if self._indicator_pos == 0:
                # Can't scroll up, don't need to do anything else.
                return
            indicator_index -= 1
            self._indicator_pos -= 1
            if line >= 0:
                self._win_move(line, 0)
                self._win_deleteln()
            else:
                self._win_scroll()
        elif index > indicator_index:
            if line >= self._nlines:
                # Offscreen, don't need to do anything else.
                return
            self._win_move(line, 0)
            self._win_deleteln()
        else:
            self._win_move(line, 0)
            self._win_deleteln()
            try:
                self._indicator = self.dict.next_key(self._indicator)
            except IndexError:
                self._indicator = self.dict.max_key()
                indicator_index -= 1
                self._indicator_pos -= 1
            self._draw_entry(self._indicator, self.dict[self._indicator],
                             self._indicator_pos)

        # Deleting the entry left a gap at the bottom. Fill it in if we can.
        index2 = indicator_index + self._nlines - self._indicator_pos - 1
        if index2 < len(self.dict):
            key, value = self.dict.ith_item(index2)
            self._draw_entry(key, value, self._nlines - 1)
        else:
            index2 = indicator_index - self._indicator_pos - 1
            if index2 >= 0:
                self._indicator_pos += 1
                self._win_scroll(-1)
                key, value = self.dict.ith_item(index2)
                self._draw_entry(key, value, 0)

    def redraw_entry(self, key):
        indicator_index = self.dict.index(self._indicator)
        index = self.dict.index(key)
        line = self._indicator_pos + index - indicator_index
        if not 0 <= line < self._nlines:
            return
        self._draw_entry(key, self.dict[key], line)

    def move_indicator(self, delta):
        if len(self.dict) == 0:
            return
        index = self.dict.index(self._indicator)
        if delta > 0:
            delta = min(len(self.dict) - 1 - index, delta)
        else:
            delta = -min(index, -delta)
        if delta == 0:
            return

        old_indicator = self._indicator
        old_indicator_pos = self._indicator_pos
        index += delta
        self._indicator = self.dict.ith_key(index)
        self._indicator_pos += delta
        self._draw_entry(old_indicator, self.dict[old_indicator],
                         old_indicator_pos)
        if self._indicator_pos < 0:
            lines = -self._indicator_pos
            self._indicator_pos = 0
            self._win_scroll(-lines)
            for i in range(lines):
                key, value = self.dict.ith_item(index + i)
                self._draw_entry(key, value, i)
        elif self._indicator_pos >= self._nlines:
            lines = self._indicator_pos - self._nlines + 1
            self._indicator_pos = self._nlines - 1
            self._win_scroll(lines)
            for i in range(lines):
                key, value = self.dict.ith_item(index - i)
                self._draw_entry(key, value, self._nlines - 1 - i)
        else:
            self._draw_entry(self._indicator, self.dict[self._indicator],
                             self._indicator_pos)

    def redraw(self):
        if len(self.dict) == 0:
            self._win_erase()
            return

        indicator_index = self.dict.index(self._indicator)
        first_index = indicator_index - self._indicator_pos
        lines_after = self._nlines - 1 - self._indicator_pos
        last_index = min(indicator_index + lines_after, len(self.dict) - 1)

        self._win_erase()
        for line, i in enumerate(range(first_index, last_index + 1)):
            # TODO: SortedDict iterators starting at a given position?
            key, value = self.dict.ith_item(i)
            self._draw_entry(key, value, line)

    def _win_clrtoeol(self):
        if self._window:
            self._window.clrtoeol()

    def _win_deleteln(self):
        if self._window:
            self._window.deleteln()

    def _win_erase(self):
        if self._window:
            self._window.erase()

    def _win_insertln(self):
        if self._window:
            self._window.insertln()

    def _win_move(self, line, col):
        if self._window:
            self._window.move(line, col)

    def _win_scroll(self, lines=1):
        if self._window:
            self._window.scroll(lines)

    def _draw_entry(self, key, value, line):
        if self._window:
            self._window.move(line, 0)
            self._window.clrtoeol()
            self._formatter(self._window, self._color_scheme, key, value,
                            key == self._indicator)
            assert self._window.getyx()[0] == line
