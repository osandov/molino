import unittest

from molino.imap.formatter import *


class TestFormat(unittest.TestCase):
    def setUp(self):
        self.buffer = bytearray()

    def test_astring(self):
        conts = []
        format_astring(self.buffer, conts, b'atom]')
        self.assertEqual(self.buffer, b'atom]')
        self.assertEqual(conts, [])

        conts = []
        self.buffer.clear()
        format_astring(self.buffer, conts, b'quoted string')
        self.assertEqual(self.buffer, b'"quoted string"')
        self.assertEqual(conts, [])

        conts = []
        self.buffer.clear()
        format_astring(self.buffer, conts, b'')
        self.assertEqual(self.buffer, b'""')
        self.assertEqual(conts, [])

        conts = []
        self.buffer.clear()
        format_astring(self.buffer, conts, b'quoted "escaped" string\\')
        self.assertEqual(self.buffer, b'"quoted \\"escaped\\" string\\\\"')
        self.assertEqual(conts, [])

        conts = []
        self.buffer.clear()
        format_astring(self.buffer, conts, b'literal\r\nstring')
        self.assertEqual(self.buffer, b'{15}\r\nliteral\r\nstring')
        self.assertEqual(conts, [6])

    def test_parent_list(self):
        def format(buffer, conts, value):
            if isinstance(value, list):
                format_paren_list(buffer, conts, value, format)
            else:
                buffer.extend(str(value).encode('utf-8'))

        conts = []
        format_paren_list(self.buffer, conts, [], format)
        self.assertEqual(self.buffer, b'()')
        self.assertEqual(conts, [])

        conts = []
        self.buffer.clear()
        format_paren_list(self.buffer, conts, [1, 2, 3], format)
        self.assertEqual(self.buffer, b'(1 2 3)')
        self.assertEqual(conts, [])

        conts = []
        self.buffer.clear()
        l = [[], 100, [200, [210, 211], 220], [300, 350]]
        format_paren_list(self.buffer, conts, l, format)
        self.assertEqual(self.buffer, b'(() 100 (200 (210 211) 220) (300 350))')
        self.assertEqual(conts, [])

    def test_capability(self):
        conts = format_capability(self.buffer, 'A001')
        self.assertEqual(self.buffer, b'A001 CAPABILITY\r\n')
        self.assertEqual(conts, [])

    def test_check(self):
        conts = format_check(self.buffer, 'A001')
        self.assertEqual(self.buffer, b'A001 CHECK\r\n')
        self.assertEqual(conts, [])

    def test_close(self):
        conts = format_close(self.buffer, 'A001')
        self.assertEqual(self.buffer, b'A001 CLOSE\r\n')
        self.assertEqual(conts, [])

    def test_enable(self):
        conts = format_enable(self.buffer, 'A001', 'CONDSTORE', 'X-GOOD-IDEA')
        self.assertEqual(self.buffer, b'A001 ENABLE CONDSTORE X-GOOD-IDEA\r\n')
        self.assertEqual(conts, [])

    def test_examine(self):
        conts = format_examine(self.buffer, 'A001', b'Trash')
        self.assertEqual(self.buffer, b'A001 EXAMINE Trash\r\n')
        self.assertEqual(conts, [])

    def test_fetch(self):
        conts = format_fetch(self.buffer, 'A001', [1], 'UID')
        self.assertEqual(self.buffer, b'A001 FETCH 1 UID\r\n')
        self.assertEqual(conts, [])

        self.buffer.clear()
        conts = format_fetch(self.buffer, 'A001', [(1, 100)], 'ENVELOPE', uid=True)
        self.assertEqual(self.buffer, b'A001 UID FETCH 1:100 ENVELOPE\r\n')
        self.assertEqual(conts, [])

        self.buffer.clear()
        conts = format_fetch(self.buffer, 'A001', [(1, 49), (51, 100)], 'UID', 'ENVELOPE')
        self.assertEqual(self.buffer, b'A001 FETCH 1:49,51:100 (UID ENVELOPE)\r\n')
        self.assertEqual(conts, [])

    def test_idle(self):
        conts = format_idle(self.buffer, 'A001')
        self.assertEqual(self.buffer, b'A001 IDLE\r\nDONE\r\n')
        self.assertEqual(conts, [11])

    def test_list(self):
        conts = format_list(self.buffer, 'A001', b'', b'*', status_items=['MESSAGES', 'UNSEEN'])
        self.assertEqual(self.buffer, b'A001 LIST "" * RETURN (STATUS (MESSAGES UNSEEN))\r\n')
        self.assertEqual(conts, [])

        self.buffer.clear()
        conts = format_list(self.buffer, 'A001', b'~osandov', b'%/linux.git')
        self.assertEqual(self.buffer, b'A001 LIST ~osandov %/linux.git\r\n')
        self.assertEqual(conts, [])

    def test_login(self):
        conts = format_login(self.buffer, 'A001', 'example@example.com', 'gr8 password')
        self.assertEqual(self.buffer, b'A001 LOGIN example@example.com "gr8 password"\r\n')
        self.assertEqual(conts, [])

    def test_logout(self):
        conts = format_logout(self.buffer, 'A001')
        self.assertEqual(self.buffer, b'A001 LOGOUT\r\n')
        self.assertEqual(conts, [])

    def test_noop(self):
        conts = format_noop(self.buffer, 'A001')
        self.assertEqual(self.buffer, b'A001 NOOP\r\n')
        self.assertEqual(conts, [])

    def test_search(self):
        conts = format_search(self.buffer, 'A001', ('ALL',))
        self.assertEqual(self.buffer, b'A001 SEARCH ALL\r\n')
        self.assertEqual(conts, [])

        self.buffer.clear()
        conts = format_search(self.buffer, 'A001', ('ALL',), uid=True)
        self.assertEqual(self.buffer, b'A001 UID SEARCH ALL\r\n')
        self.assertEqual(conts, [])

        self.buffer.clear()
        conts = format_search(self.buffer, 'A001', ('UNSEEN',))
        self.assertEqual(self.buffer, b'A001 SEARCH UNSEEN\r\n')
        self.assertEqual(conts, [])

        self.buffer.clear()
        with self.assertRaises(ValueError):
            conts = format_search(self.buffer, 'A001', ('FOO',), uid=True)

        self.buffer.clear()
        conts = format_search(self.buffer, 'A001', ('ALL',), esearch=())
        self.assertEqual(self.buffer, b'A001 SEARCH RETURN () ALL\r\n')
        self.assertEqual(conts, [])

        self.buffer.clear()
        conts = format_search(self.buffer, 'A001', ('UNSEEN',), esearch=('MIN', 'COUNT'))
        self.assertEqual(self.buffer, b'A001 SEARCH RETURN (MIN COUNT) UNSEEN\r\n')
        self.assertEqual(conts, [])

    def test_select(self):
        conts = format_select(self.buffer, 'A001', b'INBOX')
        self.assertEqual(self.buffer, b'A001 SELECT INBOX\r\n')
        self.assertEqual(conts, [])

    def test_status(self):
        conts = format_status(self.buffer, 'A001', b'INBOX', 'MESSAGES', 'UNSEEN')
        self.assertEqual(self.buffer, b'A001 STATUS INBOX (MESSAGES UNSEEN)\r\n')
        self.assertEqual(conts, [])

        self.buffer.clear()
        conts = format_status(self.buffer, 'A001', b'Spam', 'RECENT')
        self.assertEqual(self.buffer, b'A001 STATUS Spam (RECENT)\r\n')
        self.assertEqual(conts, [])
