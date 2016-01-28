import datetime
import unittest

from molino.imap.parser import *


class TestParser(unittest.TestCase):
    def setUp(self):
        self.imap = IMAP4Parser()

    def assertStops(self, value, callable, *args, **kwds):
        with self.assertRaises(StopIteration) as cm:
            callable(*args, **kwds)
        self.assertEqual(cm.exception.value, value)

    def test_getc(self):
        self.assertRaises(IMAPShortParse, self.imap.getc)
        self.imap.feed(b'ab')
        self.assertEqual(self.imap.getc(), ord('a'))
        self.imap.advance()
        self.assertEqual(self.imap.getc(), ord('b'))
        self.imap.advance()
        self.assertRaises(IMAPShortParse, self.imap.getc)

        self.imap.feed(b'cd')
        self.assertEqual(self.imap.getc(), ord('c'))
        self.assertEqual(self.imap.getc(), ord('d'))
        self.assertRaises(IMAPShortParse, self.imap.getc)
        self.imap.advance()

    def test_ungetc(self):
        self.imap.feed(b'ab')
        self.assertEqual(self.imap.getc(), ord('a'))
        self.assertEqual(self.imap.getc(), ord('b'))
        self.imap.ungetc(ord('b'))
        self.imap.ungetc(ord('a'))
        self.assertEqual(self.imap.getc(), ord('a'))
        self.assertEqual(self.imap.getc(), ord('b'))
        self.assertRaises(IMAPShortParse, self.imap.getc)

    def test_peekc(self):
        self.imap.feed(b'ab')
        self.assertEqual(self.imap.peekc(), ord('a'))
        self.assertEqual(self.imap.peekc(), ord('a'))
        self.assertEqual(self.imap.getc(), ord('a'))
        self.assertEqual(self.imap.peekc(), ord('b'))
        self.assertEqual(self.imap.peekc(), ord('b'))
        self.assertEqual(self.imap.getc(), ord('b'))
        self.imap.advance()
        self.assertRaises(IMAPShortParse, self.imap.peekc)
        self.imap.feed(b'c')
        self.assertEqual(self.imap.peekc(), ord('c'))
        self.assertEqual(self.imap.peekc(), ord('c'))
        self.assertEqual(self.imap.getc(), ord('c'))

    def test_expectc(self):
        self.assertRaises(IMAPShortParse, self.imap.expectc, ord('a'))
        self.imap.feed(b'ab')
        self.imap.expectc(ord('a'))
        self.assertRaisesRegex(IMAPParseError, "Expected 'a'; got 'b'", self.imap.expectc, ord('a'))

    def test_expects(self):
        self.assertRaises(IMAPShortParse, self.imap.expects, b'abc')
        self.imap.feed(b'ab')
        self.assertRaises(IMAPShortParse, self.imap.expects, b'abc')
        self.imap.feed(b'c')
        self.imap.expects(b'abc')
        self.imap.advance()
        self.imap.feed(b'abd')
        self.assertRaisesRegex(IMAPParseError, "Expected b'abc'; got b'abd'",
                               self.imap.expects, b'abc')

    def test_parse_error(self):
        self.imap.feed(b'foo\r\nbar daz\r\n')
        self.imap.expects(b'foo\r\n')
        self.imap.expects(b'bar ')
        with self.assertRaises(IMAPParseError) as cm:
            self.imap.expects(b'baz')
        exc = cm.exception
        self.assertEqual(exc.buf, b'bar daz')
        self.assertEqual(exc.cursor, 4)

    def test_parse_re(self):
        self.assertRaises(IMAPShortParse, self.imap.parse_atom)
        self.imap.feed(b']]]')
        self.assertRaises(IMAPParseError, self.imap.parse_atom)

    def _test_astring(self, buf, obj):
        imap = IMAP4Parser()
        imap.feed(buf)
        self.assertEqual(imap.parse_astring(), obj)

    def test_astring(self):
        self._test_astring(b'atom] ', b'atom]')
        self._test_astring(b'"quoted string"', b'quoted string')
        self._test_astring(b'"quoted \\"escaped\\" string\\\\"', b'quoted "escaped" string\\')
        self._test_astring(b'{3}\r\nabcdef ', b'abc')

    def _test_string(self, buf, obj):
        imap = IMAP4Parser()
        imap.feed(buf)
        self.assertEqual(imap.parse_string(), obj)

    def test_string(self):
        self.imap.feed(b'"abc')
        self.assertRaises(IMAPShortParse, self.imap.parse_string)
        self.imap.feed(b'"')
        self.assertEqual(self.imap.parse_string(), b'abc')
        self.imap.advance()
        self.imap.feed(b'"\\"abc\\')
        self.assertRaises(IMAPShortParse, self.imap.parse_string)
        self.imap.feed(b'\""')
        self.assertEqual(self.imap.parse_string(), b'\"abc\"')

        with self.assertRaisesRegex(IMAPParseError, 'Invalid string'):
            self._test_string(b'%sql%', None)

        with self.assertRaisesRegex(IMAPParseError, "Expected '\"'; got '\\\\r'"):
            self._test_string(b'"abc\r\n', None)

    def test_literal(self):
        self.imap.feed(b'{')
        self.assertRaises(IMAPShortParse, self.imap.parse_string)
        self.imap.feed(b'3')
        self.assertRaises(IMAPShortParse, self.imap.parse_string)
        self.imap.feed(b'}\r')
        self.assertRaises(IMAPShortParse, self.imap.parse_string)
        self.imap.feed(b'\n')
        with self.assertRaises(IMAPShortParse) as cm:
            self.imap.parse_string()
        self.assertEqual(cm.exception.hint, 3)
        self.imap.feed(b'ab')
        with self.assertRaises(IMAPShortParse) as cm:
            self.imap.parse_string()
        self.assertEqual(cm.exception.hint, 1)
        self.imap.feed(b'c')
        self.assertEqual(self.imap.parse_string(), b'abc')

    def _test(self, buf, obj):
        imap = IMAP4Parser()
        imap.feed(buf)
        self.assertEqual(imap.parse_response_line(), obj)

    def test_continue_req(self):
        self._test(b'+ idling\r\n', ContinueReq(ResponseText('idling', None, None)))

    def test_cond(self):
        self._test(b'* OK woohoo\r\n',
                   UntaggedResponse('OK', ResponseText('woohoo', None, None)))
        self._test(b'* NO no\r\n',
                   UntaggedResponse('NO', ResponseText('no', None, None)))
        self._test(b'* BAD bad\r\n',
                   UntaggedResponse('BAD', ResponseText('bad', None, None)))
        self._test(b'* BYE adios\r\n',
                   UntaggedResponse('BYE', ResponseText('adios', None, None)))

    def test_capability(self):
        self._test(b'* CAPABILITY IMAP4rev1 IDLE LIST-STATUS\r\n',
                   UntaggedResponse('CAPABILITY', {'IMAP4rev1', 'IDLE', 'LIST-STATUS'}))

    def test_flags(self):
        self._test(b'* FLAGS ()\r\n', UntaggedResponse('FLAGS', set()))
        self._test(b'* FLAGS (\\Seen \\Deleted Foo)\r\n',
                   UntaggedResponse('FLAGS', {'Foo', '\\Seen', '\\Deleted'}))

    def test_numeric(self):
        self._test(b'* 23 EXISTS\r\n', UntaggedResponse('EXISTS', 23))
        self._test(b'* 5 RECENT\r\n', UntaggedResponse('RECENT', 5))
        self._test(b'* 44 EXPUNGE\r\n', UntaggedResponse('EXPUNGE', 44))

    def test_fetch(self):
        self._test(b'* 23 FETCH (FLAGS (\Seen) RFC822.SIZE 44827)\r\n',
                   UntaggedResponse('FETCH',
                                    Fetch(23, {'FLAGS': {'\\Seen'}, 'RFC822.SIZE': 44827})))
        date = datetime.datetime(1996, 7, 17, 2, 44, 25,
                                 tzinfo=datetime.timezone(datetime.timedelta(-1, 61200)))
        self._test(b'* 12 FETCH (INTERNALDATE "17-Jul-1996 02:44:25 -0700")\r\n',
                   UntaggedResponse('FETCH', Fetch(12, {'INTERNALDATE': date})))
        with self.assertRaisesRegex(IMAPParseError, 'Invalid date'):
            self._test(b'* 12 FETCH (INTERNALDATE "bogus")\r\n', None)
        self._test(b'* 1 FETCH (UID 1 X-GM-MSGID 9842179)\r\n',
                   UntaggedResponse('FETCH', Fetch(1, {'UID': 1, 'X-GM-MSGID': 9842179})))
        with self.assertRaisesRegex(IMAPParseError, 'Unknown FETCH item'):
            self._test(b'* 1 FETCH (BLURDYBLOOP 1)\r\n', None)

        header = b"""\
From: John Doe <jdoe@machine.example>
To: Mary Smith <mary@example.net>
Subject: Saying Hello
Date: Fri, 21 Nov 1997 09:55:06 -0600
Message-ID: <1234@local.machine.example>

""".replace(b'\n', b'\r\n')
        self._test(b'* 16 FETCH (RFC822.HEADER {180}\r\n' + header + b')\r\n',
                   UntaggedResponse('FETCH', Fetch(16, {'RFC822.HEADER': header})))

    def test_envelope(self):
        env = Envelope(None, None, None, None, None, None, None, None, None, None)
        self._test(b'* 2 FETCH (ENVELOPE (NIL NIL NIL NIL NIL NIL NIL NIL NIL NIL))\r\n',
                   UntaggedResponse('FETCH', Fetch(2, {'ENVELOPE': env})))
        self._test(b'* 2 FETCH (ENVELOPE ("bogus" NIL NIL NIL NIL NIL NIL NIL NIL NIL))\r\n',
                   UntaggedResponse('FETCH', Fetch(2, {'ENVELOPE': env})))
        env = Envelope(
            datetime.datetime(2002, 10, 31, 8, 0,
                              tzinfo=datetime.timezone(datetime.timedelta(-1, 68400))),
            b"Re: Halloween",
            [Address(b'Example User', b'@example.org,@example.com:', b'example', b'example.com')],
            None, None, None, None, None,
            b'<1234@local.machine.example>', b'<3456@example.net>',
        )
        self._test(b'* 2 FETCH (ENVELOPE ("Wed, 31 Oct 2002 08:00:00 EST" '
                   b'"Re: Halloween" '
                   b'(("Example User" "@example.org,@example.com:" "example" "example.com")) '
                   b'NIL NIL NIL NIL NIL '
                   b'"<1234@local.machine.example>" "<3456@example.net>"))\r\n',
                   UntaggedResponse('FETCH', Fetch(2, {'ENVELOPE': env})))

    def test_bodystructure(self):
        resp = b"""\
* 18 FETCH (BODY ("TEXT" "PLAIN" ("CHARSET" "us-ascii") NIL NIL "7BIT" 252 11))\r\n"""
        body = TextBody('text', 'plain', {'charset': 'us-ascii'}, None, None,
                        '7bit', 252, 11, None, None, None, None, [])
        fetch = UntaggedResponse('FETCH', Fetch(18, {'BODY': body}))
        self._test(resp, fetch)

        resp = b"""\
* 1 FETCH (BODY ("MESSAGE" "RFC822" NIL NIL NIL "7BIT" 1 \
(NIL NIL NIL NIL NIL NIL NIL NIL NIL NIL) \
("TEXT" "PLAIN" NIL NIL NIL "7BIT" 1 1) 1))\r\n"""
        body = MessageBody('message', 'rfc822', {}, None, None, '7bit', 1,
                           Envelope(None, None, None, None, None, None, None,
                                    None, None, None),
                           TextBody('text', 'plain', {}, None, None,
                                    '7bit', 1, 1, None, None, None, None, []),
                           1, None, None, None, None, [])
        fetch = UntaggedResponse('FETCH', Fetch(1, {'BODY': body}))
        self._test(resp, fetch)

        resp = b"""\
* 22 FETCH (BODYSTRUCTURE \
((("TEXT" "PLAIN" ("CHARSET" "iso-8859-1") NIL NIL "QUOTED-PRINTABLE" 387 28 NIL NIL ("en" "es"))\
("TEXT" "HTML" ("CHARSET" "iso-8859-1") NIL NIL "QUOTED-PRINTABLE" 3353 76 NIL) \
"ALTERNATIVE" ("BOUNDARY" "----=_NextPart_000_0105_01D1167D.AA68E820") NIL NIL)\
("TEXT" "PLAIN" ("CHARSET" "us-ascii") NIL NIL "7BIT" 183 4 NIL ("INLINE" NIL)) \
"MIXED"))\r\n"""
        body = MultipartBody('multipart', 'mixed', [
            MultipartBody('multipart', 'alternative', [
                TextBody('text', 'plain', {'charset': 'iso-8859-1'}, None, None,
                         'quoted-printable', 387, 28, None, None, ['en', 'es'], None, []),
                TextBody('text', 'html', {'charset': 'iso-8859-1'}, None, None,
                         'quoted-printable', 3353, 76, None, None, None, None, []),
                ], {'boundary':  '----=_NextPart_000_0105_01D1167D.AA68E820'},
                None, None, None, []
            ),
            TextBody('text', 'plain', {'charset': 'us-ascii'}, None, None,
                     '7bit', 183, 4, None, ('inline', {}), None, None, []),
            ], {}, None, None, None, []
        )
        fetch = UntaggedResponse('FETCH', Fetch(22, {'BODYSTRUCTURE': body}))
        self._test(resp, fetch)

        resp = b"""\
* 1 FETCH (BODYSTRUCTURE \
("IMAGE" "GIF" ("NAME" "cat.gif" "FOO" "BAR") \
"<960723163407.20117h@cac.washington.edu>" "Cat" "BASE64" 4554 \
"d41d8cd98f00b204e9800998ecf8427e" NIL "en-cockney" "fiction/fiction1" (10 NIL)))\r\n"""
        body = BasicBody('image', 'gif', {'name': 'cat.gif', 'foo': 'BAR'},
                         '<960723163407.20117h@cac.washington.edu>',
                         'Cat', 'base64', 4554,
                         'd41d8cd98f00b204e9800998ecf8427e', None, ['en-cockney'],
                         'fiction/fiction1', [[10, None]])
        fetch = UntaggedResponse('FETCH', Fetch(1, {'BODYSTRUCTURE': body}))
        self._test(resp, fetch)

        # Test optional extensions
        resp = b"""\
* 1 FETCH (BODYSTRUCTURE (("TEXT" "PLAIN" NIL NIL NIL "7BIT" 1 1) \
"MIXED" NIL))\r\n"""
        body = MultipartBody('multipart', 'mixed', [
            TextBody('text', 'plain', {}, None, None,
                     '7bit', 1, 1, None, None, None, None, []),
            ], {}, None, None, None, []
        )
        fetch = UntaggedResponse('FETCH', Fetch(1, {'BODYSTRUCTURE': body}))
        self._test(resp, fetch)
        resp = b"""\
* 1 FETCH (BODYSTRUCTURE (("TEXT" "PLAIN" NIL NIL NIL "7BIT" 1 1) \
"MIXED" NIL NIL))\r\n"""
        self._test(resp, fetch)
        resp = b"""\
* 1 FETCH (BODYSTRUCTURE (("TEXT" "PLAIN" NIL NIL NIL "7BIT" 1 1) \
"MIXED" NIL NIL NIL NIL NIL))\r\n"""
        body = MultipartBody('multipart', 'mixed', [
            TextBody('text', 'plain', {}, None, None,
                     '7bit', 1, 1, None, None, None, None, []),
            ], {}, None, None, None, [None]
        )
        fetch = UntaggedResponse('FETCH', Fetch(1, {'BODYSTRUCTURE': body}))
        self._test(resp, fetch)

        # Content-Location
        resp = b"""\
* 1 FETCH (BODYSTRUCTURE (("TEXT" "PLAIN" NIL NIL NIL "7BIT" 1 1) \
"MIXED" NIL NIL NIL "fiction1/fiction2"))\r\n"""
        body = MultipartBody('multipart', 'mixed', [
            TextBody('text', 'plain', {}, None, None,
                     '7bit', 1, 1, None, None, None, None, []),
            ], {}, None, None, 'fiction1/fiction2', []
        )
        fetch = UntaggedResponse('FETCH', Fetch(1, {'BODYSTRUCTURE': body}))
        self._test(resp, fetch)

    def test_body(self):
        resp = b"""* 1 FETCH (BODY[] {4}\r\nasdf)\r\n"""
        fetch = UntaggedResponse('FETCH', Fetch(1, {'BODY[]': {'': (b'asdf', None)}}))
        self._test(resp, fetch)

        resp = b"""* 1 FETCH (BODY[1] {4}\r\nasdf BODY[TEXT]<10> "jkl;")\r\n"""
        body = {'1': (b'asdf', None), 'TEXT': (b'jkl;', 10)}
        fetch = UntaggedResponse('FETCH', Fetch(1, {'BODY[]': body}))
        self._test(resp, fetch)

    def test_enabled(self):
        self._test(b'* ENABLED\r\n', UntaggedResponse('ENABLED', set()))
        self._test(b'* ENABLED CONDSTORE\r\n', UntaggedResponse('ENABLED', {'CONDSTORE'}))
        self._test(b'* ENABLED CONDSTORE X-GOOD-IDEA\r\n',
                   UntaggedResponse('ENABLED', {'CONDSTORE', 'X-GOOD-IDEA'}))

    def test_esearch(self):
        self._test(b'* ESEARCH\r\n', UntaggedResponse('ESEARCH', Esearch(None, False, {})))
        self._test(b'* ESEARCH (TAG "A282") MIN 2 COUNT 3\r\n',
                   UntaggedResponse('ESEARCH', Esearch('A282', False, {'MIN': 2, 'COUNT': 3})))
        self._test(b'* ESEARCH (TAG "A283") ALL 2,10:11\r\n',
                   UntaggedResponse('ESEARCH', Esearch('A283', False, {'ALL': [2, (10, 11)]})))
        self._test(b'* ESEARCH (TAG "A285") UID MIN 7 MAX 3800\r\n',
                   UntaggedResponse('ESEARCH', Esearch('A285', True, {'MIN': 7, 'MAX': 3800})))

    def test_list(self):
        self._test(b'* LIST (\\HasNoChildren) "/" INBOX\r\n',
                   UntaggedResponse('LIST', List({'\\HasNoChildren'}, ord('/'), b'INBOX')))
        self._test(b'* LIST () NIL inbox\r\n',
                   UntaggedResponse('LIST', List(set(), None, b'INBOX')))
        self._test(b'* LIST (\\HasNoChildren \\Junk) "/" Spam\r\n',
                   UntaggedResponse('LIST', List({'\\HasNoChildren', '\\Junk'}, ord('/'), b'Spam')))

    def test_search(self):
        self._test(b'* SEARCH\r\n', UntaggedResponse('SEARCH', set()))
        self._test(b'* SEARCH 1 2 3 5 10\r\n',
                   UntaggedResponse('SEARCH', {1, 2, 3, 5, 10}))

    def test_status(self):
        self._test(b'* STATUS blurdybloop (MESSAGES 231 UIDNEXT 44292)\r\n',
                   UntaggedResponse('STATUS',
                                    Status(b'blurdybloop', {'MESSAGES': 231, 'UIDNEXT': 44292})))

    def test_tagged(self):
        self._test(b'A001 OK [READ-WRITE] woohoo\r\n',
                   TaggedResponse('A001', 'OK', ResponseText('woohoo', 'READ-WRITE', None)))
        self._test(b'A001 OK [READ-ONLY]\r\n',
                   TaggedResponse('A001', 'OK', ResponseText(None, 'READ-ONLY', None)))
        with self.assertRaisesRegex(IMAPParseError, "Unknown tagged response 'BLURDYBLOOP'"):
            self._test(b'A001 BLURDYBLOOP boop\r\n', None)

    def test_response_text(self):
        self._test(b'A002 OK [BLURDYBLOOP]\r\n',
                   TaggedResponse('A002', 'OK', ResponseText(None, 'BLURDYBLOOP', None)))
        self._test(b'A002 OK [BLURDYBLOOP boop]\r\n',
                   TaggedResponse('A002', 'OK', ResponseText(None, 'BLURDYBLOOP', 'boop')))
        self._test(b'* OK [UIDNEXT 2]\r\n',
                   UntaggedResponse('OK', ResponseText(None, 'UIDNEXT', 2)))
        self._test(b'* OK [UIDVALIDITY 1]\r\n',
                   UntaggedResponse('OK', ResponseText(None, 'UIDVALIDITY', 1)))
        self._test(b'* OK [UNSEEN 17]\r\n',
                   UntaggedResponse('OK', ResponseText(None, 'UNSEEN', 17)))

    def test_errors(self):
        with self.assertRaisesRegex(IMAPParseError, "Unknown response 'BLURDYBLOOP'"):
            self._test(b'* BLURDYBLOOP 1 2 3\r\n', None)
        with self.assertRaisesRegex(IMAPParseError, "Unknown response 'BLURDYBLOOP'"):
            self._test(b'* 1 BLURDYBLOOP\r\n', None)
        with self.assertRaisesRegex(IMAPParseError, "Expected b'\\\\r\\\\n'; got b'\\\\nA'"):
            self._test(b'A001 OK ok\nA002 OK ok\n', None)
