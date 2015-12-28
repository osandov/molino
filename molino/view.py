import base64
import collections
import curses
import email.header
import enum
import locale
import logging
import math
import quopri
import re

from molino.callbackstack import callback_stack
from molino.sorteddict import SortedDict
from molino.widgets import MenuWidget, ScrollWidget


# TODO: these should be config options
SIDEBAR_WIDTH = 20
SIDEBAR_INDENT = 2
COLOR_SCHEME = [
    ('status-info', (29, -1), curses.A_BOLD),
    ('status-error', (curses.COLOR_RED, -1), curses.A_BOLD),
    ('sidebar', (-1, -1), 0),
    ('sidebar-indicator', (-1, 254), 0),
    ('sidebar-new', (29, -1), curses.A_BOLD),
    ('sidebar-new-indicator', (29, 254), curses.A_BOLD),
    ('index', (-1, -1), 0),
    ('index-indicator', (-1, 254), 0),
    ('index-new', (29, -1), curses.A_BOLD),
    ('index-new-indicator', (29, 254), curses.A_BOLD),
    ('body', (-1, -1), 0),
    ('header', (-1, -1), curses.A_BOLD),
]
ADDR_WIDTH = 15


class StatusLevel(enum.Enum):
    info = 0
    error = 1


class View:
    def __init__(self, config, stdscr, model):
        self._config = config
        self._stdscr = stdscr
        self._model = model

        assert curses.COLORS >= 256
        self._color_scheme = {}
        for i, color in enumerate(COLOR_SCHEME, 1):
            name, (fg, bg), attr = color
            curses.init_pair(i, fg, bg)
            self._color_scheme[name] = curses.color_pair(i) | attr

        self._reset_stdscr()

        sidebar_window = self._new_sidebar_window()
        self._sidebar_view = _MailboxSidebar(self._config, self._model,
                                             sidebar_window, self._color_scheme)
        self._index_view = None
        self._message_view = None
        self.open_index_view(self._model.get_mailbox(b'INBOX'), False)

    def _reset_stdscr(self):
        self._stdscr.erase()
        if curses.LINES >= 1:
            for x in range(0, curses.COLS):
                self._stdscr.insch(0, x, ord(' '), curses.A_REVERSE)
        if curses.LINES >= 2:
            for x in range(0, curses.COLS):
                self._stdscr.insch(curses.LINES - 2, x, ord(' '), curses.A_REVERSE)
        if curses.COLS > SIDEBAR_WIDTH:
            for y in range(1, curses.LINES - 2):
                self._stdscr.addch(y, SIDEBAR_WIDTH, ord('|'), curses.A_REVERSE)
        self._stdscr.refresh()

    def update_status(self, msg, level):
        self._stdscr.move(curses.LINES - 1, 0)
        self._stdscr.clrtoeol()
        self._stdscr.insstr(msg, {
            StatusLevel.info: self._color_scheme['status-info'],
            StatusLevel.error: self._color_scheme['status-error'],
        }[level])
        self._stdscr.refresh()

    def _sidebar_window_yx(self):
        return curses.LINES - 3, min(SIDEBAR_WIDTH, curses.COLS)

    def _new_sidebar_window(self):
        nlines, ncols = self._sidebar_window_yx()
        if nlines > 0 and ncols > 0:
            return curses.newwin(nlines, ncols, 1, 0)
        else:
            return None

    def _main_window_yx(self):
        return curses.LINES - 3, curses.COLS - SIDEBAR_WIDTH - 1

    def _new_main_window(self):
        nlines, ncols = self._main_window_yx()
        if nlines > 0 and ncols > 0:
            return curses.newwin(nlines, ncols, 1, SIDEBAR_WIDTH + 1)
        else:
            return None

    def resize(self):
        old_sidebar_nlines, old_sidebar_ncols = self._sidebar_window_yx()
        old_main_nlines, old_main_ncols = self._main_window_yx()

        curses.endwin()
        self._stdscr.refresh()
        curses.update_lines_cols()
        self._reset_stdscr()

        sidebar_nlines, sidebar_ncols = self._sidebar_window_yx()
        if sidebar_nlines <= 0 or sidebar_ncols <= 0:
            self._sidebar_view.hide()
        else:
            self._sidebar_view.resize(curses.LINES - 3, SIDEBAR_WIDTH)
            if old_sidebar_nlines <= 0 or old_sidebar_ncols <= 0:
                window = self._new_sidebar_window()
                assert window is not None
                self._sidebar_view.show(window)

        main_nlines, main_ncols = self._main_window_yx()
        if main_nlines <= 0 or main_ncols <= 0:
            if self._message_view:
                self._message_view.hide()
            if self._index_view:
                self._index_view.hide()
        else:
            if self._message_view:
                self._message_view.resize(main_nlines, main_ncols)
            if self._index_view:
                self._index_view.resize(main_nlines, main_ncols)
            if old_main_nlines <= 0 or old_main_ncols <= 0:
                window = self._new_main_window()
                assert window is not None
                if self._message_view:
                    self._message_view.show(window)
                elif self._index_view:
                    self._index_view.show(window)
        self.update_status('lines = %d, cols = %d' % (curses.LINES, curses.COLS), StatusLevel.error)

    def handle_input(self):
        # TODO: configurable key-bindings, multiple character commands (use a
        # trie).
        c = self._stdscr.getch()
        if c == ord('q'):
            self.on_quit()
        elif c == 0x12:  # Ctrl-R
            self.on_refresh()
        elif self._sidebar_view.handle_input(self, c):
            return
        elif self._message_view:
            self._message_view.handle_input(self, c)
        elif self._index_view:
            self._index_view.handle_input(self, c)

    def open_index_view(self, mailbox, event=True):
        if self._index_view:
            if self._message_view:
                window = self._message_view.hide()
                self._message_view.close()
                self._message_view = None
                self._index_view.hide()
            else:
                window = self._index_view.hide()
            self._index_view.close()
            self._index_view = None
        else:
            assert self._message_view is None
            window = self._new_main_window()
        self._index_view = _IndexView(self._config, self._model, mailbox, window,
                                      self._color_scheme)
        if event:
            self.on_select_mailbox(mailbox)

    def open_message_view(self, mailbox, uid, message):
        assert self._index_view is not None
        assert self._message_view is None
        window = self._index_view.hide()
        self._message_view = _MessageView(self, mailbox, uid, message, window,
                                          self._color_scheme)
        self.on_open_message(mailbox, uid)

    def close_message_view(self):
        assert self._index_view is not None
        assert self._message_view is not None
        window = self._message_view.hide()
        self._message_view.close()
        self._message_view = None
        self._index_view.show(window)

    @callback_stack
    def on_quit(self):
        return False

    @callback_stack
    def on_refresh(self):
        return False

    @callback_stack
    def on_select_mailbox(self, mailbox):
        return False

    @callback_stack
    def on_open_message(self, mailbox, uid):
        return False

    @callback_stack
    def on_read_body_sections(self, mailbox, uid, sections):
        return False


class _MailboxSidebar:
    def __init__(self, config, model, window, color_scheme):
        self._config = config
        self._model = model
        self._model.on_mailboxes_add.register(self._mailboxes_add)
        self._model.on_mailboxes_delete.register(self._mailboxes_delete)
        self._model.on_mailbox_update.register(self._mailbox_update)
        self._widget = MenuWidget(self._formatter, window,
                                  color_scheme, self._mailbox_sort_key)
        self._mailboxes_add(self._model.get_mailbox(b'INBOX'), False)
        for mailbox in self._model.mailboxes():
            if mailbox.name != b'INBOX':
                self._mailboxes_add(mailbox, False)
        self._widget.refresh()

    @staticmethod
    def _mailbox_sort_key(key):
        if key == 'Inbox':
            # The inbox should come first
            return 0, None, None
        elif key.startswith('[Gmail]'):
            # Gmail mailboxes should come last.
            return 2, locale.strxfrm(key.casefold()), key
        else:
            # Otherwise, sort alphabetically and break ties lexicographically
            # (this can happen if there are two mailboxes which differ only in
            # case; Gmail doesn't allow this but other mail servers might).
            return 1, locale.strxfrm(key.casefold()), key

    def hide(self):
        return self._widget.setwin(None)

    def show(self, window):
        self._widget.setwin(window)
        self._widget.noutrefresh()

    def resize(self, nlines, ncols):
        self._widget.resize(nlines, ncols)
        self._widget.refresh()

    def handle_input(self, view, c):
        if c == 0x0e:  # Ctrl-N
            self._widget.move_indicator(1)
            self._widget.refresh()
            return True
        elif c == 0x0f:  # Ctrl-O
            mailbox = self._widget.get_indicator()[1]
            view.open_index_view(mailbox)
            return True
        elif c == 0x10:  # Ctrl-P
            self._widget.move_indicator(-1)
            self._widget.refresh()
            return True
        else:
            return False

    @staticmethod
    def _formatter(window, color_scheme, key, mailbox, is_indicator):
        if mailbox.delimiter:
            levels = mailbox.name_decoded.split(chr(mailbox.delimiter))
        else:
            levels = [mailbox.name_decoded]
        entry = ' ' * (2 * (len(levels) - 1))
        unseen = mailbox.num_unseen()
        if unseen:
            entry += '%s (%d)' % (levels[-1], unseen)
            color = 'sidebar-new'
        else:
            entry += levels[-1]
            color = 'sidebar'
        if is_indicator:
            color += '-indicator'
        ncols = window.getmaxyx()[1]
        if len(entry) > ncols:
            entry = levels[-1][:ncols - 2] + '..'
        entry += ' ' * max(0, ncols - len(entry))
        window.insstr(entry, color_scheme[color])

    def _mailboxes_add(self, mailbox, render=True):
        self._widget.add_entry(mailbox.name_decoded, mailbox)
        if render:
            self._widget.refresh()
        return False

    def _mailboxes_delete(self, mailbox):
        self._widget.del_entry(mailbox.name_decoded)
        self._widget.refresh()
        return False

    def _mailbox_update(self, mailbox, what):
        if what == 'unseen':
            self._widget.redraw_entry(mailbox.name_decoded)
            self._widget.refresh()
        return False


class _IndexView:
    def __init__(self, config, model, mailbox, window, color_scheme):
        self._config = config
        self._model = model
        self._mailbox = mailbox

        self._model.on_message_add.register(self._message_add)
        self._model.on_message_delete.register(self._message_delete)
        self._model.on_message_update.register(self._message_update)
        self._model.on_mailbox_update.register(self._mailbox_update)

        self._widget = MenuWidget(self._formatter, window,
                                  color_scheme, self._message_sort_key)
        self._widget.add_entry(None, self._mailbox)
        self._incomplete_messages = {}
        for uid, message in self._mailbox.messages():
            self._message_add(self._mailbox, uid, message, False)
        self._widget.refresh()

    @staticmethod
    def _message_sort_key(key):
        if key is None:
            return -math.inf, None
        id, envelope = key
        if envelope.date is None:
            return math.inf, id
        else:
            return -envelope.date.timestamp(), id

    def hide(self):
        return self._widget.setwin(None)

    def show(self, window):
        self._widget.setwin(window)
        self._widget.refresh()

    def close(self):
        self._model.on_message_add.unregister(self._message_add)
        self._model.on_message_delete.unregister(self._message_delete)
        self._model.on_message_update.unregister(self._message_update)

    def resize(self, nlines, ncols):
        self._widget.resize(nlines, ncols)
        self._widget.refresh()

    def handle_input(self, view, c):
        if c == ord('j'):
            self._widget.move_indicator(1)
            self._widget.refresh()
        elif c == ord('k'):
            self._widget.move_indicator(-1)
            self._widget.refresh()
        elif c == ord('\n'):
            key, value = self._widget.get_indicator()
            if key is not None:
                message, uid = value
                view.open_message_view(self._mailbox, uid, message)

    @staticmethod
    def _formatter(window, color_scheme, key, value, is_indicator):
        if key is None:
            entry = value.name_decoded
            exists = value.exists
            unseen = value.num_unseen()
            if exists is not None and unseen is not None:
                entry += ' (%d unread / %d messages)' % (unseen, exists)
            entry += ' ' * max(0, window.getmaxyx()[1] - len(entry))
            color = 'index-indicator' if is_indicator else 'index'
            window.insstr(entry, color_scheme[color])
            return

        message = value[0]
        entry = []
        if message.envelope.date is None:
            entry.append('      ')
        else:
            entry.append(message.envelope.date.strftime('%b %d'))
        addrs = message.from_(name_only=True)
        if addrs:
            from_ = addrs[0]
        else:
            from_ = ''
        entry.append('%-*.*s' % (ADDR_WIDTH, ADDR_WIDTH, from_))
        subject = message.subject()
        if subject:
            entry.append(subject)
        else:
            entry.append('')
        if '\\Seen' in message.flags:
            color = 'index'
        else:
            color = 'index-new'
        if is_indicator:
            color += '-indicator'
        entry = ' '.join(entry)
        entry += ' ' * max(0, window.getmaxyx()[1] - len(entry))
        window.insstr(entry, color_scheme[color])

    def _message_add(self, mailbox, uid, message, render=True):
        if mailbox != self._mailbox:
            return False
        if message.envelope is None or message.flags is None:
            self._incomplete_messages[message] = uid
        else:
            key = (message.id, message.envelope)
            self._widget.add_entry(key, (message, uid))
            if render:
                self._widget.refresh()
        return False

    def _message_delete(self, mailbox, uid, message):
        if mailbox != self._mailbox:
            return False
        if message.envelope:
            key = (message.id, message.envelope)
            self._widget.del_entry(key)
            self._widget.refresh()
        return False

    def _message_update(self, message, what):
        key = (message.id, message.envelope)
        try:
            uid = self._incomplete_messages[message]
            if message.envelope is not None and message.flags is not None:
                del self._incomplete_messages[message]
                self._widget.add_entry(key, (message, uid))
                self._widget.refresh()
        except KeyError:
            if key in self._widget.dict:
                if what == 'flags':
                    self._widget.redraw_entry(key)
                    self._widget.refresh()
        return False

    def _mailbox_update(self, mailbox, what):
        if mailbox == self._mailbox and (what == 'exists' or what == 'unseen'):
            self._widget.redraw_entry(None)
            self._widget.refresh()
        return False


def sizeof_fmt(num):
    if abs(num) < 1024:
        return '%d' % (num)
    for unit in ['K', 'M', 'G', 'T', 'P', 'E', 'Z']:
        num /= 1024
        if abs(num) < 1024:
            return '%.1f%s' % (num, unit)
    return '%.1f%s' % (num, 'Y')


class _MessageView:
    def __init__(self, root_view, mailbox, uid, message, window, color_scheme):
        self._root_view = root_view
        self._model = root_view._model
        self._mailbox = mailbox
        self._uid = uid
        self._message = message
        self._model.on_message_update.register(self._message_update)
        self._widget = ScrollWidget(window, color_scheme)
        if self._message.bodystructure:
            self._open_body_sections()
        self._redraw()

    def hide(self):
        return self._widget.setwin(None)

    def show(self, window):
        self._widget.setwin(window)
        self._redraw()

    def close(self):
        self._model.on_message_update.unregister(self._message_update)

    def handle_input(self, view, c):
        if c == ord('i'):
            view.close_message_view()
            return True
        elif c == ord('j'):
            self._widget.scroll(1)
            self._widget.refresh()
            return True
        elif c == ord('k'):
            self._widget.scroll(-1)
            self._widget.refresh()
            return True
        else:
            return False

    def resize(self, nlines, ncols):
        self._widget.resize(nlines, ncols)
        self._redraw()

    def _message_update(self, message, what):
        if message == self._message:
            if what == 'bodystructure':
                self._open_body_sections()
                self._redraw()
            elif what == 'body':
                self._redraw()
        return False

    def _open_body_sections(self):
        sections = []
        for body, section in self._walk_body():
            if body.type == 'text' or body.type == 'message':
                sections.append(section)
        self._root_view.on_read_body_sections(self._mailbox, self._uid,
                                              sections)

    def _redraw(self):
        self._widget.reset()
        if self._message.envelope:
            self._add_addrs('From', self._message.from_())
            self._add_addrs('To', self._message.to())
            self._add_addrs('Cc', self._message.cc())
            self._add_addrs('Bcc', self._message.bcc())
            if self._message.envelope.date:
                date = self._message.envelope.date.strftime('%a, %b, %Y at %I:%M %p')
                self._widget.add('Date: %s\n' % date, 'header')
        subject = self._message.subject()
        if subject:
            self._widget.add('Subject: %s\n' % subject, 'header')
        self._widget.add('\n', 'body')
        if self._message.bodystructure:
            for body, section in self._walk_body():
                if body.type == 'multipart':
                    if body.subtype == 'alternative':
                        alternatives = ', '.join('%s/%s' % (part.type, part.subtype)
                                                 for part in body.parts)
                        body_div = '[-- Type: %s/%s, Alternatives: [%s] --]\n' % \
                                   (body.type, body.subtype, alternatives)
                    else:
                        body_div = '[-- Type: %s/%s --]\n' % (body.type, body.subtype)
                else:
                    size = sizeof_fmt(body.size)
                    body_div = '[-- Type: %s/%s, Encoding: %s, Size: %s --]\n' % \
                               (body.type, body.subtype, body.encoding, size)
                self._widget.add(body_div, 'header')
                if body.type == 'text' or body.type == 'message':
                    try:
                        content = self._message.get_body_section(section)
                    except KeyError:
                        continue
                    decoded = self._decode_text_body(body, content)
                    self._widget.add(decoded, 'body')
        self._widget.flush()
        self._widget.refresh()

    def _add_addrs(self, label, addrs):
        if addrs:
            self._widget.add('%s: %s\n' % (label, ', '.join(addrs)), 'header')

    @staticmethod
    def _decode_text_body(body, content):
        # TODO: be robust here
        if body.encoding == 'quoted-printable':
            content = quopri.decodestring(content)
        elif body.encoding == 'base64':
            content = base64.b64decode(content)
        elif body.encoding != '7bit' and body.encoding != '8bit':
            assert False, body.encoding
        charset = body.params.get('charset', 'us-ascii')
        return content.decode(charset)

    def _walk_body(self):
        def _walk_body_helper(body, section):
            if body.type == 'multipart':
                if body.subtype == 'mixed':
                    for i, part in enumerate(body.parts, 1):
                        section.append(str(i))
                        yield from _walk_body_helper(part, section)
                        section.pop()
                elif body.subtype == 'alternative':
                    # TODO: handle this properly
                    yield body, '.'.join(section)
                    section.append('1')
                    yield from _walk_body_helper(body.parts[0], section)
                    section.pop()
                else:
                    yield body, '.'.join(section)
            else:
                yield body, '.'.join(section)
        section = []
        if self._message.bodystructure.type != 'multipart':
            section.append('1')
        yield from _walk_body_helper(self._message.bodystructure, section)
