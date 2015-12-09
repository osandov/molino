import unittest

import molino.imap.codecs


class TestIMAPUtf7(unittest.TestCase):
    def _test(self, decoded, encoded):
        self.assertEqual(decoded.encode('imap-utf-7'), encoded)
        self.assertEqual(encoded.decode('imap-utf-7'), decoded)

    def test_direct(self):
        self._test('Hello, world!', b'Hello, world!')

    def test_ascii(self):
        self._test('DOS\r\n', b'DOS&AA0ACg-')

    def test_ampersand(self):
        self._test('&', b'&-')
        self._test('Slanted & Enchanted', b'Slanted &- Enchanted')
        self._test('make && make install', b'make &-&- make install')
        self._test('\r&\n', b'&AA0AJgAK-')
        self._test('foo &', b'foo &-')

    def test_hyphen(self):
        self._test('vice-versa', b'vice-versa')

    def test_bmp(self):
        self._test('P\u00e9rez', b'P&AOk-rez')
        self._test('Z\u00fa\u00f1iga', b'Z&APoA8Q-iga')

    def test_surrogates(self):
        self._test('\U0001030f', b'&2ADfDw-')

    def test_end_shifted(self):
        self._test('Potos\u00ed', b'Potos&AO0-')

    def test_base64_altchars(self):
        self._test('\uffff', b'&,,8-')
        self._test('\ufa00', b'&+gA-')

    def test_decode_error_ends_in_base64(self):
        with self.assertRaises(UnicodeDecodeError) as cm:
            b'Potos&AO0'.decode('imap-utf-7')
        self.assertEqual(cm.exception.start, 9)
        self.assertEqual(cm.exception.end, 9)
        self.assertEqual(b'Potos&AO0'.decode('imap-utf-7', errors='ignore'), 'Potos')
        self.assertEqual(b'Potos&AO0'.decode('imap-utf-7', errors='replace'), 'Potos\ufffd')

    def test_decode_error_unencoded_char(self):
        with self.assertRaises(UnicodeDecodeError) as cm:
            b'DOS\r\nUnix\n'.decode('imap-utf-7')
        self.assertEqual(cm.exception.start, 3)
        self.assertEqual(cm.exception.end, 4)
        self.assertEqual(b'DOS\r\nUnix\n'.decode('imap-utf-7', errors='ignore'), 'DOSUnix')
        self.assertEqual(b'DOS\r\nUnix\n'.decode('imap-utf-7', errors='replace'),
                         'DOS\ufffd\ufffdUnix\ufffd')

    def test_decode_error_non_ascii(self):
        with self.assertRaises(UnicodeDecodeError) as cm:
            b'\xff'.decode('imap-utf-7')
        self.assertEqual(cm.exception.start, 0)
        self.assertEqual(cm.exception.end, 1)
        self.assertEqual(b'\xff'.decode('imap-utf-7', errors='ignore'), '')
        self.assertEqual(b'\xff'.decode('imap-utf-7', errors='replace'), '\ufffd')

    def test_decode_error_bad_base64(self):
        with self.assertRaises(UnicodeDecodeError) as cm:
            b'a&~$!-b'.decode('imap-utf-7')
        self.assertEqual(cm.exception.start, 1)
        self.assertEqual(cm.exception.end, 6)
        self.assertEqual(cm.exception.reason, 'invalid Base64')
        self.assertEqual(b'a&~$!-b'.decode('imap-utf-7', errors='ignore'), 'ab')
        self.assertEqual(b'a&~$!-b'.decode('imap-utf-7', errors='replace'), 'a\ufffdb')

    def test_decode_error_bad_utf16(self):
        with self.assertRaises(UnicodeDecodeError) as cm:
            b'&2AA-'.decode('imap-utf-7')
        self.assertEqual(cm.exception.start, 0)
        self.assertEqual(cm.exception.end, 5)
        self.assertEqual(cm.exception.reason, 'invalid UTF-16BE')
        self.assertEqual(b'&2AA-'.decode('imap-utf-7', errors='ignore'), '')
        self.assertEqual(b'&2AA-'.decode('imap-utf-7', errors='replace'), '\ufffd')
