#!/usr/bin/env python3

import curses
import locale
import logging
import sqlite3
import sys
import traceback

import molino.cache
import molino.config
import molino.operations
import molino.view

if __name__ == '__main__':
    locale.setlocale(locale.LC_ALL, '')
    with open('molinorc', 'r') as f:
        config = molino.config.parse_config(f)

    logging.basicConfig(filename='/tmp/molino.log', level=logging.DEBUG)
    cache = None
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

        db = sqlite3.connect('/tmp/molino.db')
        cache = molino.cache.Cache(db)
        view = molino.view.View(config, stdscr, cache)
        main = molino.operations.MainOperation(config, cache, view)
        main.start()
    finally:
        if cache:
            cache.close()
        stdscr.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()
