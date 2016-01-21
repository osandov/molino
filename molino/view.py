import base64
import collections
import curses
import email.header
import email.utils
import enum
import locale
import math
import quopri
import re

from molino.cache import mailbox_sort_key, convert_addrs, convert_bodystructure, convert_date, convert_flags
from molino.callbackstack import callback_stack
from molino.widgets import DBViewWidget, ScrollWidget


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
    def __init__(self, config, stdscr, cache):
        self._config = config
        self._stdscr = stdscr
        self._cache = cache

        assert curses.COLORS >= 256
        self._color_scheme = {}
        for i, color in enumerate(COLOR_SCHEME, 1):
            name, (fg, bg), attr = color
            curses.init_pair(i, fg, bg)
            self._color_scheme[name] = curses.color_pair(i) | attr

        self._reset_stdscr()

        sidebar_window = self._new_sidebar_window()
        self._sidebar_view = MailboxSidebar(self._cache, sidebar_window,
                                            self._color_scheme)
        self._index_view = None
        self._message_view = None
        self.open_index_view('INBOX', False)

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
        self._index_view = IndexView(self._cache, mailbox, window,
                                     self._color_scheme)
        if event:
            self.on_select_mailbox(mailbox)

    def open_message_view(self, mailbox, uid, gm_msgid):
        assert self._index_view is not None
        assert self._message_view is None
        window = self._index_view.hide()
        self._message_view = _MessageView(self, mailbox, uid, gm_msgid, window,
                                          self._color_scheme)

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


class MailboxSidebar(DBViewWidget):
    def __init__(self, cache, window, color_scheme):
        self._cache = cache

        self._cache.db.create_function('mailbox_sidebar_add_mailbox', 1, self.on_add_mailbox)
        self._cache.db.execute('''
        CREATE TEMP TRIGGER mailbox_sidebar_add_mailbox
        AFTER INSERT ON mailboxes
        BEGIN
            SELECT mailbox_sidebar_add_mailbox(NEW.name);
        END''')

        self._cache.db.create_function('mailbox_sidebar_delete_mailbox', 1, self.on_delete_mailbox)
        self._cache.db.execute('''
        CREATE TEMP TRIGGER mailbox_sidebar_delete_mailbox
        AFTER DELETE ON mailboxes
        BEGIN
            SELECT mailbox_sidebar_delete_mailbox(OLD.name);
        END''')

        self._cache.db.create_function('mailbox_sidebar_update_mailbox', 1, self.on_update_mailbox)
        self._cache.db.execute('''
        CREATE TEMP TRIGGER mailbox_sidebar_update_mailbox
        AFTER UPDATE OF delimiter, unseen ON mailboxes
        BEGIN
            SELECT mailbox_sidebar_update_mailbox(NEW.name);
        END''')

        super().__init__(window, color_scheme)

    def row_to_key(self, row):
        return mailbox_sort_key(row['name'])

    def max_key(self):
        cur = self._cache.db.execute('SELECT MAX(name) FROM mailboxes')
        return mailbox_sort_key(cur.fetchone()[0])

    def prev_key(self, key):
        cur = self._cache.db.execute('SELECT MAX(name) FROM mailboxes WHERE name<?',
                                     (key[2],))
        return mailbox_sort_key(cur.fetchone()[0])

    def next_key(self, key):
        cur = self._cache.db.execute('SELECT MIN(name) FROM mailboxes WHERE name>?',
                                     (key[2],))
        return mailbox_sort_key(cur.fetchone()[0])

    def skip_forward(self, key, n):
        row = self._cache.db.execute('''
        SELECT MAX(name), COUNT(*) - 1 FROM (
            SELECT name FROM mailboxes WHERE name>=? ORDER BY name ASC LIMIT ?
        )''', (key[2], n + 1)).fetchone()
        return mailbox_sort_key(row[0]), row[1]

    def skip_backward(self, key, n):
        row = self._cache.db.execute('''
        SELECT MIN(name), COUNT(*) - 1 FROM (
            SELECT name FROM mailboxes WHERE name<=? ORDER BY name DESC LIMIT ?
        )''', (key[2], n + 1)).fetchone()
        return mailbox_sort_key(row[0]), row[1]

    def first_n(self, n):
        return self._cache.db.execute('''
        SELECT name, delimiter, unseen FROM mailboxes
        ORDER BY name ASC LIMIT ?
        ''', (n,))

    def prev_n(self, key, n):
        return self._cache.db.execute('''
        SELECT name, delimiter, unseen FROM mailboxes
        WHERE name<=?
        ORDER BY name DESC LIMIT ?
        ''', (key[2], n))

    def next_n(self, key, n):
        return self._cache.db.execute('''
        SELECT name, delimiter, unseen FROM mailboxes
        WHERE name>=?
        ORDER BY name ASC LIMIT ?
        ''', (key[2], n))

    def draw_key(self, line, key):
        row = self._cache.db.execute('''
        SELECT delimiter, unseen FROM mailboxes WHERE name=?
        ''', (key[2],)).fetchone()
        self._draw_record(line, key[2] == self._indicator[2], key[2],
                row['delimiter'], row['unseen'])

    def draw_record(self, line, row):
        self._draw_record(line, row['name'] == self._indicator[2], row['name'],
                          row['delimiter'], row['unseen'])

    def _draw_record(self, line, is_indicator, name, delimiter, unseen):
        if not self._window:
            return
        self._window.move(line, 0)
        self._window.clrtoeol()

        orig_name = name
        if name == 'INBOX':
            name = 'Inbox'
        if delimiter:
            levels = name.split(chr(delimiter))
        else:
            levels = [name]
        entry = ' ' * (2 * (len(levels) - 1))
        if unseen:
            entry += '%s (%d)' % (levels[-1], unseen)
            color = 'sidebar-new'
        else:
            entry += levels[-1]
            color = 'sidebar'
        if is_indicator:
            color += '-indicator'
        if len(entry) > self._ncols:
            entry = levels[-1][:self._ncols - 2] + '..'
        entry += ' ' * max(0, self._ncols - len(entry))
        self._window.insstr(entry, self._color_scheme[color])

    def on_add_mailbox(self, name):
        self.add_record(mailbox_sort_key(name))
        self.refresh()

    def on_delete_mailbox(self, name):
        self.delete_record(mailbox_sort_key(name))
        self.refresh()

    def on_update_mailbox(self, name):
        self.update_record(mailbox_sort_key(name))
        self.refresh()

    def handle_input(self, view, c):
        if c == 0x0e:  # Ctrl-N
            self.move_indicator(1)
            self.refresh()
            return True
        elif c == 0x0f:  # Ctrl-O
            view.open_index_view(self._indicator[2])
            return True
        elif c == 0x10:  # Ctrl-P
            self.move_indicator(-1)
            self.refresh()
            return True
        else:
            return False


class IndexView(DBViewWidget):
    def __init__(self, cache, mailbox, window, color_scheme):
        self._cache = cache
        self._mailbox = mailbox

        # SQLite doesn't allow parameters in triggers, so we have to do this
        # manually.
        escaped = self._mailbox.replace("'", "''")

        self._cache.db.create_function('index_view_add_mailbox_uid', 2, self.on_add_mailbox_uid)
        self._cache.db.execute('''
        CREATE TEMP TRIGGER index_view_add_mailbox_uid
        AFTER INSERT ON gmail_mailbox_uids WHEN NEW.mailbox='%s'
        BEGIN
            SELECT index_view_add_mailbox_uid(NEW.gm_msgid, NEW.date);
        END''' % escaped)

        self._cache.db.create_function('index_view_delete_mailbox_uid', 2, self.on_delete_mailbox_uid)
        self._cache.db.execute('''
        CREATE TEMP TRIGGER index_view_delete_mailbox_uid
        AFTER DELETE ON gmail_mailbox_uids WHEN OLD.mailbox='%s'
        BEGIN
            SELECT index_view_delete_mailbox_uid(OLD.gm_msgid, OLD.date);
        END''' % escaped)

        self._cache.db.create_function('index_view_update_message', 2, self.on_update_message)
        self._cache.db.execute('''
        CREATE TEMP TRIGGER index_view_update_message
        AFTER UPDATE OF date, timezone, "from", subject, flags
        ON gmail_messages
        WHEN EXISTS (SELECT gm_msgid FROM gmail_mailbox_uids WHERE mailbox='%s' AND date=NEW.date AND gm_msgid=NEW.gm_msgid)
        BEGIN
            SELECT index_view_update_message(NEW.gm_msgid, NEW.date);
        END''' % escaped)

        super().__init__(window, color_scheme)
        self._stay_top = True

    def close(self):
        self._cache.db.execute('DROP TRIGGER index_view_add_mailbox_uid')
        self._cache.db.execute('DROP TRIGGER index_view_delete_mailbox_uid')
        self._cache.db.execute('DROP TRIGGER index_view_update_message')
        self._cache.db.create_function('index_view_add_mailbox_uid', 0, None)
        self._cache.db.create_function('index_view_delete_mailbox_uid', 0, None)
        self._cache.db.create_function('index_view_update_message', 0, None)

    def row_to_key(self, row):
        return (-row['date'], -row['gm_msgid'])

    def max_key(self):
        row = self._cache.db.execute('''
        SELECT date, gm_msgid FROM gmail_mailbox_uids
        WHERE mailbox=?
        ORDER by date ASC, gm_msgid ASC
        LIMIT 1
        ''', (self._mailbox,)).fetchone()
        if row is None:
            return None
        else:
            return self.row_to_key(row)

    def prev_key(self, key):
        date, gm_msgid = -key[0], -key[1]
        row = self._cache.db.execute('''
        SELECT date, gm_msgid FROM gmail_mailbox_uids
        WHERE mailbox=? AND date=? AND gm_msgid>?
        UNION
        SELECT date, gm_msgid FROM gmail_mailbox_uids
        WHERE mailbox=?1 AND date>?2
        ORDER by date ASC, gm_msgid ASC
        LIMIT 1''', (self._mailbox, date, gm_msgid)).fetchone()
        if row is None:
            return None
        else:
            return self.row_to_key(row)

    def next_key(self, key):
        date, gm_msgid = -key[0], -key[1]
        row = self._cache.db.execute('''
        SELECT date, gm_msgid FROM gmail_mailbox_uids
        WHERE mailbox=? AND date=? AND gm_msgid<?
        UNION
        SELECT date, gm_msgid FROM gmail_mailbox_uids
        WHERE mailbox=?1 AND date<?2
        ORDER by date DESC, gm_msgid DESC
        LIMIT 1''', (self._mailbox, date, gm_msgid)).fetchone()
        if row is None:
            return None
        else:
            return self.row_to_key(row)

    def skip_forward(self, key, n):
        date, gm_msgid = -key[0], -key[1]
        row = self._cache.db.execute('''
        SELECT date, gm_msgid, COUNT(*) - 1 FROM (
            SELECT date, gm_msgid FROM gmail_mailbox_uids
            WHERE mailbox=? AND date=? AND gm_msgid<=?
            UNION
            SELECT date, gm_msgid FROM gmail_mailbox_uids
            WHERE mailbox=?1 AND date<?2
            ORDER by date DESC, gm_msgid DESC
            LIMIT ?
        ) ORDER BY date ASC, gm_msgid ASC
        LIMIT 1''', (self._mailbox, date, gm_msgid, n + 1)).fetchone()
        return self.row_to_key(row), row[2]

    def skip_backward(self, key, n):
        date, gm_msgid = -key[0], -key[1]
        row = self._cache.db.execute('''
        SELECT date, gm_msgid, COUNT(*) - 1 FROM (
            SELECT date, gm_msgid FROM gmail_mailbox_uids
            WHERE mailbox=? AND date=? AND gm_msgid>=?
            UNION
            SELECT date, gm_msgid FROM gmail_mailbox_uids
            WHERE mailbox=?1 AND date>?2
            ORDER by date ASC, gm_msgid ASC
            LIMIT ?
        ) ORDER BY date DESC, gm_msgid DESC
        LIMIT 1''', (self._mailbox, date, gm_msgid, n + 1)).fetchone()
        return self.row_to_key(row), row[2]

    def first_n(self, n):
        return self._cache.db.execute('''
        SELECT messages.gm_msgid, messages.date, messages.timezone,
        messages."from", messages.subject, messages.flags
        FROM gmail_messages AS messages JOIN gmail_mailbox_uids AS uids
        WHERE uids.mailbox=? AND messages.gm_msgid=uids.gm_msgid
        ORDER BY uids.date DESC, uids.gm_msgid DESC
        LIMIT ?
        ''', (self._mailbox, n))

    def prev_n(self, key, n):
        date, gm_msgid = -key[0], -key[1]
        return self._cache.db.execute('''
        SELECT messages.gm_msgid, messages.date, messages.timezone,
        messages."from", messages.subject, messages.flags
        FROM gmail_messages AS messages JOIN gmail_mailbox_uids AS uids
        WHERE uids.mailbox=?
        AND ((uids.date=? AND uids.gm_msgid>=?) OR (uids.date>?))
        AND messages.gm_msgid=uids.gm_msgid
        ORDER BY uids.date ASC, uids.gm_msgid ASC
        LIMIT ?
        ''', (self._mailbox, date, gm_msgid, date, n))

    def next_n(self, key, n):
        date, gm_msgid = -key[0], -key[1]
        return self._cache.db.execute('''
        SELECT messages.gm_msgid, messages.date, messages.timezone,
        messages."from", messages.subject, messages.flags
        FROM gmail_messages AS messages JOIN gmail_mailbox_uids AS uids
        WHERE uids.mailbox=?
        AND ((uids.date=? AND uids.gm_msgid<=?) OR (uids.date<?))
        AND messages.gm_msgid=uids.gm_msgid
        ORDER BY uids.date DESC, uids.gm_msgid DESC
        LIMIT ?
        ''', (self._mailbox, date, gm_msgid, date, n))

    def draw_key(self, line, key):
        gm_msgid = -key[1]
        row = self._cache.db.execute('''
        SELECT date, timezone, "from", subject, flags FROM gmail_messages
        WHERE gm_msgid=?
        ''', (gm_msgid,)).fetchone()
        date = convert_date(row['date'], row['timezone'])
        self._draw_record(line, gm_msgid == -self._indicator[1], date,
                          convert_addrs(row['from']), row['subject'],
                          convert_flags(row['flags']))

    def draw_record(self, line, row):
        date = convert_date(row['date'], row['timezone'])
        self._draw_record(line, row['gm_msgid'] == -self._indicator[1], date,
                          convert_addrs(row['from']), row['subject'],
                          convert_flags(row['flags']))

    def _draw_record(self, line, is_indicator, date, from_, subject, flags):
        if not self._window:
            return
        self._window.move(line, 0)
        self._window.clrtoeol()

        entry = []
        entry.append(date.strftime('%b %d'))
        if from_:
            realname, email_address = email.utils.parseaddr(from_[0])
            if realname:
                from_str = realname
            else:
                from_str = email_address
        else:
            from_str = ''
        entry.append('%-*.*s' % (ADDR_WIDTH, ADDR_WIDTH, from_str))
        if subject:
            entry.append(subject)
        if '\\Seen' in flags:
            color = 'index'
        else:
            color = 'index-new'
        if is_indicator:
            color += '-indicator'
        entry = ' '.join(entry)
        entry += ' ' * max(0, self._ncols - len(entry))
        self._window.insstr(entry, self._color_scheme[color])

    def on_add_mailbox_uid(self, gm_msgid, date):
        self.add_record((-date, -gm_msgid))
        self.refresh()

    def on_delete_mailbox_uid(self, gm_msgid, date):
        self.delete_record((-date, -gm_msgid))
        self.refresh()

    def on_update_message(self, gm_msgid, date):
        self.update_record((-date, -gm_msgid))
        self.refresh()

    def _indicator_uid(self):
        date, gm_msgid = -self._indicator[0], -self._indicator[1]
        row = self._cache.db.execute('''
        SELECT uid FROM gmail_mailbox_uids
        WHERE mailbox=? AND date=? AND gm_msgid=?
        ''', (self._mailbox, date, gm_msgid)).fetchone()
        return row['uid']

    def handle_input(self, view, c):
        if c == ord('j'):
            self.move_indicator(1)
            self.refresh()
            return True
        elif c == ord('k'):
            self.move_indicator(-1)
            self.refresh()
            return True
        elif c == ord('\n'):
            if self._indicator is not None:
                uid = self._indicator_uid()
                gm_msgid = -self._indicator[1]
                view.open_message_view(self._mailbox, uid, gm_msgid)


def sizeof_fmt(num):
    if abs(num) < 1024:
        return '%d' % (num)
    for unit in ['K', 'M', 'G', 'T', 'P', 'E', 'Z']:
        num /= 1024
        if abs(num) < 1024:
            return '%.1f%s' % (num, unit)
    return '%.1f%s' % (num, 'Y')


class _MessageView:
    def __init__(self, root_view, mailbox, uid, gm_msgid, window,
                 color_scheme):
        self._root_view = root_view
        self._cache = root_view._cache
        self._mailbox = mailbox
        self._uid = uid
        self._gm_msgid = gm_msgid

        self._cache.db.create_function('message_view_update_bodystructure', 1,
                                       self.on_update_bodystructure)
        self._cache.db.execute('''
        CREATE TEMP TRIGGER message_view_update_bodystructure
        AFTER UPDATE OF bodystructure ON gmail_messages
        WHEN NEW.gm_msgid=%d
        BEGIN
            SELECT message_view_update_bodystructure(NEW.bodystructure);
        END''' % self._gm_msgid)

        self._cache.db.create_function('message_view_add_body_section', 2,
                                       self.on_add_body_section)
        self._cache.db.execute('''
        CREATE TEMP TRIGGER message_view_add_body_section
        AFTER INSERT ON gmail_message_bodies
        WHEN NEW.gm_msgid=%d
        BEGIN
            SELECT message_view_add_body_section(NEW.section, NEW.body);
        END''' % self._gm_msgid)

        self._widget = ScrollWidget(window, color_scheme)

        row = self._cache.db.execute('''
        SELECT date, timezone, subject, "from", "to", cc, bcc, bodystructure
        FROM gmail_messages
        WHERE gm_msgid=?
        ''', (self._gm_msgid,)).fetchone()
        self._date = convert_date(row['date'], row['timezone'])
        self._from = convert_addrs(row['from'])
        self._to = convert_addrs(row['to'])
        self._cc = convert_addrs(row['cc'])
        self._bcc = convert_addrs(row['bcc'])
        self._subject = row['subject']
        self._bodystructure = convert_bodystructure(row['bodystructure'])

        cur = self._cache.db.execute('''
        SELECT section, body FROM gmail_message_bodies
        WHERE gm_msgid=?
        ''', (self._gm_msgid,))
        self._body_sections = {row['section']: row['body'] for row in cur}

        self._root_view.on_open_message(self._mailbox, self._uid,
                                        self._bodystructure is None)
        if self._bodystructure:
            self._open_body_sections()
        self._redraw()

    def close(self):
        self._cache.db.execute('DROP TRIGGER message_view_update_bodystructure')
        self._cache.db.execute('DROP TRIGGER message_view_add_body_section')
        self._cache.db.create_function('message_view_update_bodystructure', 0, None)
        self._cache.db.create_function('message_view_add_body_section', 0, None)

    def on_update_bodystructure(self, bodystructure):
        self._bodystructure = convert_bodystructure(bodystructure)
        self._open_body_sections()
        self._redraw()

    def on_add_body_section(self, section, body):
        self._body_sections[section] = body
        self._redraw()

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
        if self._bodystructure.type != 'multipart':
            section.append('1')
        yield from _walk_body_helper(self._bodystructure, section)

    def _open_body_sections(self):
        sections = []
        for body, section in self._walk_body():
            if ((body.type == 'text' or body.type == 'message') and
                section not in self._body_sections):
                sections.append(section)
        self._root_view.on_read_body_sections(self._mailbox, self._uid,
                                              sections)

    def _redraw(self):
        self._widget.reset()
        self._add_addrs('From', self._from)
        self._add_addrs('To', self._to)
        self._add_addrs('Cc', self._cc)
        self._add_addrs('Bcc', self._bcc)
        date = self._date.strftime('%a, %b, %Y at %I:%M %p')
        self._widget.add('Date: %s\n' % date, 'header')
        if self._subject:
            self._widget.add('Subject: %s\n' % self._subject, 'header')
        self._widget.add('\n', 'body')
        if self._bodystructure:
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
                        content = self._body_sections[section]
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

    def hide(self):
        return self._widget.setwin(None)

    def show(self, window):
        self._widget.setwin(window)
        self._redraw()
