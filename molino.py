#!/usr/bin/env python3

import curses
import locale
import logging
import sys
import traceback

import molino.config
import molino.imap.parser
import molino.model
import molino.operations
import molino.view

if __name__ == '__main__':
    locale.setlocale(locale.LC_ALL, '')
    with open('molinorc', 'r') as f:
        config = molino.config.parse_config(f)

    logging.basicConfig(filename='/tmp/molino.log', level=logging.DEBUG)
    try:
        # Curses
        stdscr = curses.initscr()
        # Disable echo
        curses.noecho()
        # Disable buffering
        curses.cbreak()  # Disable buffering
        # Have curses handle special keys (TODO: deal with escape sequences
        # blocking)
        stdscr.keypad(True)
        # Non-blocking
        stdscr.nodelay(True)
        # Don't show the cursor
        curses.curs_set(False)

        # Enable colors
        curses.start_color()
        curses.use_default_colors()

        model = molino.model.Model()
        view = molino.view.View(config, stdscr, model)
        main = molino.operations.MainOperation(config, model, view)
        main.start()
    except molino.imap.parser.IMAPParseError as e:
        traceback.print_exc()
        print(repr(e.buf), file=sys.stderr)
        print(' ' * (len(repr(e.buf[:e.cursor])) - 2) + '^', file=sys.stderr)
    finally:
        stdscr.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()
