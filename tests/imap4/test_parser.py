import datetime
import unittest

from imap4 import *
from imap4.parser import *


class TestIMAPScanner(unittest.TestCase):
    def setUp(self):
        self.scanner = IMAPScanner()

    def test_basic(self):
        self.scanner.feed(b'A001 OK Success\r\nA002 BAD Failure\r\n')

        line = self.scanner.get()
        self.assertEqual(line, b'A001 OK Success\r\n')
        self.scanner.consume(len(line))

        line = self.scanner.get()
        self.assertEqual(line, b'A002 BAD Failure\r\n')

    def test_short(self):
        self.scanner.feed(b'A001 OK')
        self.assertRaises(ScanError, self.scanner.get)
        self.scanner.feed(b' Success\r\n')

        line = self.scanner.get()
        self.assertEqual(line, b'A001 OK Success\r\n')
        self.scanner.consume(len(line))

        self.scanner.feed(b'A002 BAD Failure\r')
        self.assertRaises(ScanError, self.scanner.get)
        self.scanner.feed(b'\n')

        line = self.scanner.get()
        self.assertEqual(line, b'A002 BAD Failure\r\n')

    def test_slice(self):
        self.scanner.feed(b'A001 OK Success\r\n', 15)
        self.assertRaises(ScanError, self.scanner.get)

        self.scanner.feed(b'\r\n', 10)
        line = self.scanner.get()
        self.assertEqual(line, b'A001 OK Success\r\n')
        self.scanner.consume(len(line))

        self.scanner.feed(b'A001 OK Success\r\n', -2)
        self.assertRaises(ScanError, self.scanner.get)

        self.scanner.feed(b'\r\n', -2)
        self.assertRaises(ScanError, self.scanner.get)

        self.scanner.feed(b'\r\n', -10)
        self.assertRaises(ScanError, self.scanner.get)

        self.scanner.feed(b'\r\n', 2)
        line = self.scanner.get()
        self.assertEqual(line, b'A001 OK Success\r\n')

    def test_twice(self):
        self.scanner.feed(b'A001 OK Success\r\n')
        for i in range(2):
            with self.subTest(i=i):
                line = self.scanner.get()
                self.assertEqual(line, b'A001 OK Success\r\n')

    def test_literal(self):
        self.scanner.feed(b'A {7}\r\nliteral\r\n')

        line = self.scanner.get()
        self.assertEqual(line, b'A {7}\r\nliteral\r\n')

    def test_not_really_literal(self):
        self.scanner.feed(b'A {}\r\n7}\r\n[11}\r\n}\r\n')

        line = self.scanner.get()
        self.assertEqual(line, b'A {}\r\n')
        self.scanner.consume(len(line))

        line = self.scanner.get()
        self.assertEqual(line, b'7}\r\n')
        self.scanner.consume(len(line))

        line = self.scanner.get()
        self.assertEqual(line, b'[11}\r\n')
        self.scanner.consume(len(line))

        line = self.scanner.get()
        self.assertEqual(line, b'}\r\n')

    def test_multiple_literals(self):
        self.scanner.feed(b'a{3}\r\nABC{2}\r\nDE\r\nXYZ\r\n')

        line = self.scanner.get()
        self.assertEqual(line, b'a{3}\r\nABC{2}\r\nDE\r\n')

    def test_incomplete_literal(self):
        self.scanner.feed(b'A {7}\r\nliter')
        self.assertRaises(ScanError, self.scanner.get)

        self.scanner.feed(b'al')
        self.assertRaises(ScanError, self.scanner.get)

        self.scanner.feed(b'\r\n')
        line = self.scanner.get()
        self.assertEqual(line, b'A {7}\r\nliteral\r\n')


class TestIMAPParser(unittest.TestCase):
    def setUp(self):
        self.maxDiff = None

    def _test_astring(self, buf, obj):
        self.assertEqual(parse_imap_astring(buf), obj)

    def test_astring(self):
        self._test_astring(b'atom]', b'atom]')
        self._test_astring(b'"quoted string"', b'quoted string')
        self._test_astring(b'"quoted \\"escaped\\" string\\\\"', b'quoted "escaped" string\\')
        self._test_astring(b'{3}\r\nxyz', b'xyz')

    def _test_string(self, buf, obj):
        self.assertEqual(parse_imap_string(buf), obj)

    def test_string(self):
        self._test_string(b'"abc"', b'abc')
        self._test_string(rb'"\"abc\\"', b'\"abc\\')

        with self.assertRaisesRegex(ParseError, "invalid string"):
            self._test_string(b"'sql'", None)

    def test_literal(self):
        self._test_string(b'{3}\r\nabc', b'abc')

        with self.assertRaisesRegex(ParseError, "expected"):
            parse_imap_string(b'{3}abc')

        with self.assertRaisesRegex(ParseError, "truncated"):
            parse_imap_string(b'{3}\r\nab')

        self.assertRaises(ParseError, parse_imap_string, b'{}\r\nabc')

    def _test(self, buf, obj):
        self.assertEqual(parse_response_line(buf), obj)

    def test_continue_req(self):
        self._test(b'+ idling\r\n', ContinueReq([ResponseText(['idling', None, None])]))

    def test_cond(self):
        self._test(b'* OK woohoo\r\n',
                   UntaggedResponse([OK, ResponseText(['woohoo', None, None])]))
        self._test(b'* NO no\r\n',
                   UntaggedResponse([NO, ResponseText(['no', None, None])]))
        self._test(b'* BAD bad\r\n',
                   UntaggedResponse([BAD, ResponseText(['bad', None, None])]))
        self._test(b'* BYE adios\r\n',
                   UntaggedResponse([BYE, ResponseText(['adios', None, None])]))

    def test_capability(self):
        self._test(b'* CAPABILITY IMAP4rev1 IDLE LIST-STATUS\r\n',
                   UntaggedResponse([CAPABILITY, {'IMAP4rev1', 'IDLE', 'LIST-STATUS'}]))

    def test_flags(self):
        self._test(b'* FLAGS ()\r\n', UntaggedResponse([FLAGS, set()]))
        self._test(b'* FLAGS (\\Seen \\Deleted Foo)\r\n',
                   UntaggedResponse([FLAGS, {'Foo', '\\Seen', '\\Deleted'}]))

    def test_numeric(self):
        self._test(b'* 23 EXISTS\r\n', UntaggedResponse([EXISTS, 23]))
        self._test(b'* 5 RECENT\r\n', UntaggedResponse([RECENT, 5]))
        self._test(b'* 44 EXPUNGE\r\n', UntaggedResponse([EXPUNGE, 44]))

    def test_fetch(self):
        self._test(b'* 23 FETCH (FLAGS (\Seen) RFC822.SIZE 44827)\r\n',
                   UntaggedResponse([FETCH,
                                     Fetch([23, {FLAGS: {'\\Seen'}, RFC822_SIZE: 44827}])]))
        date = datetime.datetime(1996, 7, 17, 2, 44, 25,
                                 tzinfo=datetime.timezone(datetime.timedelta(-1, 61200)))
        # TODO XXX
        self._test(b'* 12 FETCH (INTERNALDATE "17-Jul-1996 02:44:25 -0700")\r\n',
                   UntaggedResponse([FETCH, Fetch([12, {INTERNALDATE: date}])]))
        with self.assertRaisesRegex(ParseError, "invalid date"):
            self._test(b'* 12 FETCH (INTERNALDATE "bogus")\r\n', None)
        self._test(b'* 1 FETCH (UID 1 X-GM-MSGID 9842179)\r\n',
                   UntaggedResponse([FETCH, Fetch([1, {UID: 1, X_GM_MSGID: 9842179}])]))
        with self.assertRaisesRegex(ParseError, 'unknown FETCH item'):
            self._test(b'* 1 FETCH (BLURDYBLOOP 1)\r\n', None)

        header = b"""\
From: John Doe <jdoe@machine.example>
To: Mary Smith <mary@example.net>
Subject: Saying Hello
Date: Fri, 21 Nov 1997 09:55:06 -0600
Message-ID: <1234@local.machine.example>

""".replace(b'\n', b'\r\n')
        self._test(b'* 16 FETCH (RFC822.HEADER {180}\r\n' + header + b')\r\n',
                   UntaggedResponse([FETCH, Fetch([16, {RFC822_HEADER: header}])]))

        self._test(b'* 1 FETCH (MODSEQ (624140003))\r\n',
                   UntaggedResponse([FETCH, Fetch([1, {MODSEQ: 624140003}])]))

        self._test(b'* 1 FETCH (X-GM-THRID 1509653592627481811 X-GM-LABELS ("\\\\Important" Linux))\r\n',
                   UntaggedResponse([FETCH, Fetch([1, {X_GM_THRID: 1509653592627481811,
                                                       X_GM_LABELS: {b"\\Important", b"Linux"}}])]))

        self._test(b'* 1 FETCH (X-GM-LABELS ())\r\n',
                   UntaggedResponse([FETCH, Fetch([1, {X_GM_LABELS: set()}])]))

    def test_envelope(self):
        env = Envelope([None, None, None, None, None, None, None, None, None, None])
        self._test(b'* 2 FETCH (ENVELOPE (NIL NIL NIL NIL NIL NIL NIL NIL NIL NIL))\r\n',
                   UntaggedResponse([FETCH, Fetch([2, {ENVELOPE: env}])]))
        self._test(b'* 2 FETCH (ENVELOPE ("bogus" NIL NIL NIL NIL NIL NIL NIL NIL NIL))\r\n',
                   UntaggedResponse([FETCH, Fetch([2, {ENVELOPE: env}])]))
        env = Envelope([
            datetime.datetime(2002, 10, 31, 8, 0,
                              tzinfo=datetime.timezone(datetime.timedelta(-1, 68400))),
            b"Re: Halloween",
            [Address([b'Example User', b'@example.org,@example.com:', b'example', b'example.com'])],
            None, None, None, None, None,
            b'<1234@local.machine.example>', b'<3456@example.net>',
        ])
        self._test(b'* 2 FETCH (ENVELOPE ("Wed, 31 Oct 2002 08:00:00 EST" '
                   b'"Re: Halloween" '
                   b'(("Example User" "@example.org,@example.com:" "example" "example.com")) '
                   b'NIL NIL NIL NIL NIL '
                   b'"<1234@local.machine.example>" "<3456@example.net>"))\r\n',
                   UntaggedResponse([FETCH, Fetch([2, {ENVELOPE: env}])]))

    def test_bodystructure(self):
        resp = b"""\
* 18 FETCH (BODY ("TEXT" "PLAIN" ("CHARSET" "us-ascii") NIL NIL "7BIT" 252 11))\r\n"""
        body = TextBody(['text', 'plain', {'charset': 'us-ascii'}, None, None,
                        '7bit', 252, 11, None, None, None, None, []])
        fetch = UntaggedResponse([FETCH, Fetch([18, {BODY: body}])])
        self._test(resp, fetch)

        resp = b"""\
* 1 FETCH (BODY ("MESSAGE" "RFC822" NIL NIL NIL "7BIT" 1 \
(NIL NIL NIL NIL NIL NIL NIL NIL NIL NIL) \
("TEXT" "PLAIN" NIL NIL NIL "7BIT" 1 1) 1))\r\n"""
        body = MessageBody(['message', 'rfc822', {}, None, None, '7bit', 1,
                            Envelope([None, None, None, None, None, None, None,
                                      None, None, None]),
                            TextBody(['text', 'plain', {}, None, None,
                                      '7bit', 1, 1, None, None, None, None, []]),
                            1, None, None, None, None, []])
        fetch = UntaggedResponse([FETCH, Fetch([1, {BODY: body}])])
        self._test(resp, fetch)

        resp = b"""\
* 22 FETCH (BODYSTRUCTURE \
((("TEXT" "PLAIN" ("CHARSET" "iso-8859-1") NIL NIL "QUOTED-PRINTABLE" 387 28 NIL NIL ("en" "es"))\
("TEXT" "HTML" ("CHARSET" "iso-8859-1") NIL NIL "QUOTED-PRINTABLE" 3353 76 NIL) \
"ALTERNATIVE" ("BOUNDARY" "----=_NextPart_000_0105_01D1167D.AA68E820") NIL NIL)\
("TEXT" "PLAIN" ("CHARSET" "us-ascii") NIL NIL "7BIT" 183 4 NIL ("INLINE" NIL)) \
"MIXED"))\r\n"""
        body = MultipartBody(['multipart', 'mixed', [
            MultipartBody(['multipart', 'alternative', [
                TextBody(['text', 'plain', {'charset': 'iso-8859-1'}, None, None,
                          'quoted-printable', 387, 28, None, None, ['en', 'es'], None, []]),
                TextBody(['text', 'html', {'charset': 'iso-8859-1'}, None, None,
                          'quoted-printable', 3353, 76, None, None, None, None, []]),
                ], {'boundary':  '----=_NextPart_000_0105_01D1167D.AA68E820'},
                None, None, None, []
            ]),
            TextBody(['text', 'plain', {'charset': 'us-ascii'}, None, None,
                      '7bit', 183, 4, None, ('inline', {}), None, None, []]),
            ], {}, None, None, None, []
        ])
        fetch = UntaggedResponse([FETCH, Fetch([22, {BODYSTRUCTURE: body}])])
        self._test(resp, fetch)

        resp = b"""\
* 1 FETCH (BODYSTRUCTURE \
("IMAGE" "GIF" ("NAME" "cat.gif" "FOO" "BAR") \
"<960723163407.20117h@cac.washington.edu>" "Cat" "BASE64" 4554 \
"d41d8cd98f00b204e9800998ecf8427e" NIL "en-cockney" "fiction/fiction1" (10 NIL)))\r\n"""
        body = BasicBody(['image', 'gif', {'name': 'cat.gif', 'foo': 'BAR'},
                          '<960723163407.20117h@cac.washington.edu>',
                          'Cat', 'base64', 4554,
                          'd41d8cd98f00b204e9800998ecf8427e', None, ['en-cockney'],
                          'fiction/fiction1', [[10, None]]])
        fetch = UntaggedResponse([FETCH, Fetch([1, {BODYSTRUCTURE: body}])])
        self._test(resp, fetch)

        # Test optional extensions
        resp = b"""\
* 1 FETCH (BODYSTRUCTURE (("TEXT" "PLAIN" NIL NIL NIL "7BIT" 1 1) \
"MIXED" NIL))\r\n"""
        body = MultipartBody(['multipart', 'mixed', [
            TextBody(['text', 'plain', {}, None, None,
                      '7bit', 1, 1, None, None, None, None, []]),
            ], {}, None, None, None, []
        ])
        fetch = UntaggedResponse([FETCH, Fetch([1, {BODYSTRUCTURE: body}])])
        self._test(resp, fetch)
        resp = b"""\
* 1 FETCH (BODYSTRUCTURE (("TEXT" "PLAIN" NIL NIL NIL "7BIT" 1 1) \
"MIXED" NIL NIL))\r\n"""
        self._test(resp, fetch)
        resp = b"""\
* 1 FETCH (BODYSTRUCTURE (("TEXT" "PLAIN" NIL NIL NIL "7BIT" 1 1) \
"MIXED" NIL NIL NIL NIL NIL))\r\n"""
        body = MultipartBody(['multipart', 'mixed', [
            TextBody(['text', 'plain', {}, None, None,
                      '7bit', 1, 1, None, None, None, None, []]),
            ], {}, None, None, None, [None]
        ])
        fetch = UntaggedResponse([FETCH, Fetch([1, {BODYSTRUCTURE: body}])])
        self._test(resp, fetch)

        # Content-Location
        resp = b"""\
* 1 FETCH (BODYSTRUCTURE (("TEXT" "PLAIN" NIL NIL NIL "7BIT" 1 1) \
"MIXED" NIL NIL NIL "fiction1/fiction2"))\r\n"""
        body = MultipartBody(['multipart', 'mixed', [
            TextBody(['text', 'plain', {}, None, None,
                      '7bit', 1, 1, None, None, None, None, []]),
            ], {}, None, None, 'fiction1/fiction2', []
        ])
        fetch = UntaggedResponse([FETCH, Fetch([1, {BODYSTRUCTURE: body}])])
        self._test(resp, fetch)

    def test_body(self):
        resp = b"""* 1 FETCH (BODY[] {4}\r\nasdf)\r\n"""
        fetch = UntaggedResponse([FETCH, Fetch([1, {BODYSECTIONS: {'': (b'asdf', None)}}])])
        self._test(resp, fetch)

        resp = b"""* 1 FETCH (BODY[1] {4}\r\nasdf BODY[TEXT]<10> "jkl;")\r\n"""
        body = {'1': (b'asdf', None), 'TEXT': (b'jkl;', 10)}
        fetch = UntaggedResponse([FETCH, Fetch([1, {BODYSECTIONS: body}])])
        self._test(resp, fetch)

    def test_enabled(self):
        self._test(b'* ENABLED\r\n', UntaggedResponse([ENABLED, set()]))
        self._test(b'* ENABLED CONDSTORE\r\n', UntaggedResponse([ENABLED, {'CONDSTORE'}]))
        self._test(b'* ENABLED CONDSTORE X-GOOD-IDEA\r\n',
                   UntaggedResponse([ENABLED, {'CONDSTORE', 'X-GOOD-IDEA'}]))

    def test_esearch(self):
        self._test(b'* ESEARCH\r\n', UntaggedResponse([ESEARCH, Esearch([None, False, {}])]))
        self._test(b'* ESEARCH (TAG "A282") MIN 2 COUNT 3\r\n',
                   UntaggedResponse([ESEARCH, Esearch(['A282', False, {MIN: 2, COUNT: 3}])]))
        self._test(b'* ESEARCH (TAG "A283") ALL 2,10:11\r\n',
                   UntaggedResponse([ESEARCH, Esearch(['A283', False, {ALL: [2, (10, 11)]}])]))
        self._test(b'* ESEARCH (TAG "A285") UID MIN 7 MAX 3800\r\n',
                   UntaggedResponse([ESEARCH, Esearch(['A285', True, {MIN: 7, MAX: 3800}])]))

    def test_list(self):
        self._test(b'* LIST (\\HasNoChildren) "/" INBOX\r\n',
                   UntaggedResponse([LIST, List([{'\\HasNoChildren'}, ord('/'), b'INBOX'])]))
        self._test(b'* LIST () NIL inbox\r\n',
                   UntaggedResponse([LIST, List([set(), None, b'INBOX'])]))
        self._test(b'* LIST (\\HasNoChildren \\Junk) "/" Spam\r\n',
                   UntaggedResponse([LIST, List([{'\\HasNoChildren', '\\Junk'}, ord('/'), b'Spam'])]))
        self._test(b'* LIST (\\HasNoChildren \\Junk) "/" "Spam"\r\n',
                   UntaggedResponse([LIST, List([{'\\HasNoChildren', '\\Junk'}, ord('/'), b'Spam'])]))

    def test_search(self):
        self._test(b'* SEARCH\r\n', UntaggedResponse([SEARCH, set()]))
        self._test(b'* SEARCH 1 2 3 5 10\r\n',
                   UntaggedResponse([SEARCH, {1, 2, 3, 5, 10}]))

    def test_status(self):
        self._test(b'* STATUS blurdybloop (MESSAGES 231 UIDNEXT 44292)\r\n',
                   UntaggedResponse([STATUS,
                                    Status([b'blurdybloop', {MESSAGES: 231, UIDNEXT: 44292}])]))

    def test_tagged(self):
        self._test(b'A001 OK [READ-WRITE] woohoo\r\n',
                   TaggedResponse(['A001', OK, ResponseText(['woohoo', READ_WRITE, None])]))
        self._test(b'A001 OK [READ-ONLY]\r\n',
                   TaggedResponse(['A001', OK, ResponseText([None, READ_ONLY, None])]))
        with self.assertRaisesRegex(ParseError, "unknown tagged response"):
            self._test(b'A001 BLURDYBLOOP boop\r\n', None)

    def test_response_text(self):
        self._test(b'A002 OK [BLURDYBLOOP]\r\n',
                   TaggedResponse(['A002', OK, ResponseText([None, 'BLURDYBLOOP', None])]))
        self._test(b'A002 OK [BLURDYBLOOP boop]\r\n',
                   TaggedResponse(['A002', OK, ResponseText([None, 'BLURDYBLOOP', 'boop'])]))
        self._test(b'* OK [UIDNEXT 2]\r\n',
                   UntaggedResponse([OK, ResponseText([None, UIDNEXT, 2])]))
        self._test(b'* OK [UIDVALIDITY 1]\r\n',
                   UntaggedResponse([OK, ResponseText([None, UIDVALIDITY, 1])]))
        self._test(b'* OK [UNSEEN 17]\r\n',
                   UntaggedResponse([OK, ResponseText([None, UNSEEN, 17])]))

    def test_errors(self):
        with self.assertRaisesRegex(ParseError, "unknown untagged response"):
            self._test(b'* BLURDYBLOOP 1 2 3\r\n', None)
        with self.assertRaisesRegex(ParseError, "unknown message data"):
            self._test(b'* 1 BLURDYBLOOP\r\n', None)
        with self.assertRaisesRegex(ParseError, "expected"):
            self._test(b'A001 OK ok\nA002', None)
