import bisect
import curses


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


class DBViewWidget:
    def __init__(self, window, color_scheme):
        self._window = window
        if self._window:
            self._window.scrollok(True)
            self._nlines, self._ncols = self._window.getmaxyx()
            self._window.erase()
        else:
            self._nlines = 20
            self._ncols = 80
        self._color_scheme = color_scheme

        self._displayed = []
        self._indicator = None
        self._indicator_pos = None
        for i, row in enumerate(self.first_n(self._nlines)):
            key = self.row_to_key(row)
            if i == 0:
                self._indicator = key
                self._indicator_pos = 0
            self._displayed.append(key)
            self.draw_record(i, row)
        self._stay_top = False
        self.refresh()

    def row_to_key(self, row):
        raise NotImplementedError

    def max_key(self):
        raise NotImplementedError

    def prev_key(self, key):
        raise NotImplementedError

    def next_key(self, key):
        raise NotImplementedError

    def skip_forward(self, key, n):
        raise NotImplementedError

    def skip_backward(self, key, n):
        raise NotImplementedError

    def first_n(self, n):
        raise NotImplementedError

    def prev_n(self, key, n):
        raise NotImplementedError

    def next_n(self, key, n):
        raise NotImplementedError

    def draw_key(self, line, key):
        raise NotImplementedError

    def draw_record(self, line, row):
        raise NotImplementedError

    def add_record(self, key):
        if not self._displayed:
            self._indicator = key
            self._indicator_pos = 0
            line = 0
        else:
            line = bisect.bisect_left(self._displayed, key)
            if line == 0:
                if self._stay_top:
                    assert self._indicator_pos == 0
                    assert self._indicator == self._displayed[0]
                    self._indicator = key
                    self.draw_key(0, self._displayed[0])
                else:
                    if self._indicator_pos == self._nlines - 1:
                        # Offscreen, don't need to do anything.
                        return
                    key = self.prev_key(self._displayed[0])
                    self._indicator_pos += 1
            elif line <= self._indicator_pos:
                assert not self._stay_top
                if self._indicator_pos == self._nlines - 1:
                    del self._displayed[0]
                    line -= 1
                    self._indicator_pos -= 1
                    self._win_scroll()
                self._indicator_pos += 1
            elif line >= self._nlines:
                # Offscreen, don't need to do anything.
                return
        self._displayed.insert(line, key)
        if len(self._displayed) > self._nlines:
            del self._displayed[-1]
        self._win_move(line, 0)
        self._win_insertln()
        self.draw_key(line, key)

    def delete_record(self, key):
        line = bisect.bisect_left(self._displayed, key)
        if line == 0 and self._displayed[0] != key:
            line = -1
        if line < self._indicator_pos:
            if self._indicator_pos == 0:
                # Can't scroll up, don't need to do anything else.
                return
            self._indicator_pos -= 1
            if line >= 0:
                del self._displayed[line]
                self._win_move(line, 0)
                self._win_deleteln()
            else:
                del self._displayed[0]
                self._win_scroll()
        elif line > self._indicator_pos:
            if line == len(self._displayed):
                # Offscreen, don't need to do anything else.
                return
            del self._displayed[line]
            self._win_move(line, 0)
            self._win_deleteln()
        else:
            del self._displayed[line]
            self._win_move(line, 0)
            self._win_deleteln()
            self._indicator = self.next_key(self._indicator)
            if self._indicator is None:
                self._indicator = self.max_key()
                if self._indicator is None:
                    self._indicator_pos = None
                    return
                else:
                    self._indicator_pos -= 1
            self.draw_key(self._indicator_pos, self._indicator)

        if self._nlines == 1:
            assert len(self._displayed) == 0
            self._displayed.append(self._indicator)
            return
        if len(self._displayed) < self._nlines - 1:
            return
        # Deleting the entry left a gap at the bottom. Fill it in if we can.
        key2 = self.next_key(self._displayed[-1])
        if key2:
            self._displayed.append(key2)
            self.draw_key(self._nlines - 1, key2)
        else:
            key2 = self.prev_key(self._displayed[0])
            if key2:
                self._indicator_pos += 1
                self._win_scroll(-1)
                self._displayed.insert(0, key2)
                self.draw_key(0, key2)

    def update_record(self, key):
        line = bisect.bisect_left(self._displayed, key)
        if line < len(self._displayed) and self._displayed[line] == key:
            self.draw_key(line, key)

    def move_indicator(self, delta):
        self._stay_top = False
        if not self._displayed or delta == 0:
            return

        old_indicator = self._indicator
        old_indicator_pos = self._indicator_pos
        if delta > 0:
            self._indicator, delta = self.skip_forward(self._indicator, delta)
        else:
            self._indicator, delta = self.skip_backward(self._indicator, -delta)
            delta = -delta
        if delta == 0:
            return
        self._indicator_pos += delta
        self.draw_key(old_indicator_pos, old_indicator)

        if self._indicator_pos < 0:
            lines = -self._indicator_pos
            self._indicator_pos = 0
            self._win_scroll(-lines)
            new_displayed = []
            for i, row in enumerate(self.next_n(self._indicator, lines)):
                new_displayed.append(self.row_to_key(row))
                self.draw_record(i, row)
            new_displayed.extend(self._displayed[:self._nlines - lines])
            self._displayed = new_displayed
        elif self._indicator_pos >= self._nlines:
            lines = self._indicator_pos - self._nlines + 1
            self._indicator_pos = self._nlines - 1
            self._win_scroll(lines)
            self._displayed = self._displayed[lines:]
            self._displayed.extend([None] * lines)
            for i, row in enumerate(self.prev_n(self._indicator, lines)):
                self._displayed[self._nlines - 1 - i] = self.row_to_key(row)
                self.draw_record(self._nlines - 1 - i, row)
        else:
            self.draw_key(self._indicator_pos, self._indicator)

    def resize(self, nlines, ncols):
        if self._window:
            self._window.resize(nlines, ncols)
        self._resize(nlines, ncols)
        self.refresh()

    def _resize(self, nlines, ncols):
        old_nlines = self._nlines
        self._nlines, self._ncols = nlines, ncols
        self._win_erase()
        if self._displayed:
            if self._nlines < old_nlines and self._indicator_pos >= self._nlines:
                lines = self._indicator_pos - self._nlines + 1
                key = self._displayed[lines]
                self._indicator_pos = self._nlines - 1
            elif self._nlines > old_nlines:
                key, lines = self.skip_backward(self._displayed[0],
                                                self._nlines - old_nlines)
                self._indicator_pos += lines
            else:
                key = self._displayed[0]
            self._displayed.clear()
            for i, row in enumerate(self.next_n(key, self._nlines)):
                self._displayed.append(self.row_to_key(row))
                self.draw_record(i, row)

    def setwin(self, window):
        old_window = self._window
        self._window = window
        if self._window:
            self._window.scrollok(True)
            self._resize(*self._window.getmaxyx())
        return old_window

    def hide(self):
        return self.setwin(None)

    def show(self, window):
        self.setwin(window)
        self._window.refresh()

    def refresh(self):
        if self._window:
            self._window.refresh()

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
