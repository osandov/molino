import codecs
from collections import namedtuple
import datetime
import email.utils
import re


_token_re = re.compile(b'[a-zA-Z0-9.-]+')
_atom_re = re.compile(b'[^](){ %*"\\\\\x00-\x1f\x7f-\xff]+')
_astring_re = re.compile(b'[^(){ %*"\\\\\x00-\x1f\x7f-\xff]+')
_list_re = re.compile(b'[^(){ "\\\\\x00-\x1f\x7f-\xff]+')
_tag_re = re.compile(b'[^+(){ %*"\\\\\x00-\x1f\x7f-\xff]+')
_text_re = re.compile(b'[^\x00\r\n\x7f-\xff]+')
_resp_text_code_re = re.compile(b'[^]\x00\r\n\x7f-\xff]+')
_number_re = re.compile(b'[0-9]+')
_quoted_re = re.compile(b'([^\x00\r\n"\\\\\x7f-\xff]|\\\\["\\\\])*')
_section_spec_re = re.compile(b'[^]]*')


class IMAPError(Exception):
    pass


class IMAPParseError(IMAPError):
    def __init__(self, message, buf, cursor):
        super().__init__(message)
        self.message = message
        self.buf = buf
        self.cursor = cursor


class IMAPShortParse(IMAPError):
    def __init__(self, hint):
        super().__init__()
        self.hint = hint


"""
Address in ENVELOPE.

name - bytes or None
adl - bytes or None
mailbox - bytes or None
host - bytes or None
"""
Address = namedtuple('Address', ['name', 'adl', 'mailbox', 'host'])

"""
Continuation request.

text - human-readable or base64 text as bytestring
"""
ContinueReq = namedtuple('ContinueReq', ['text'])

"""
BODYSTRUCTURE with "text/*" media type.

type - always "text"
subtype - lowercase str
params - dict[lowercase str]->str
id - str or None
description - str or None
encoding - lowercase str
size - int
lines - int
md5 - str or None
disposition - (lowercase str, dict[lowercase str]->str) or None
lang - list of str or None
location - str or None
extension - list
"""
TextBody = namedtuple('TextBody', ['type', 'subtype', 'params', 'id',
                                   'description', 'encoding', 'size', 'lines',
                                   'md5', 'disposition', 'lang', 'location',
                                   'extension'])

"""
BODYSTRUCTURE with "message/rfc822" media type.

type - always "message"
subtype - always "rfc822"
params - dict[lowercase str]->str
id - str or None
description - str or None
encoding - lowercase str
size - int
envelope - Envelope
body - BODYSTRUCTURE type
lines - int
md5 - str or None
disposition - (lowercase str, dict[lowercase str]->str) or None
lang - list of str or None
location - str or None
extension - list
"""
MessageBody = namedtuple('MessageBody', ['type', 'subtype', 'params', 'id',
                                         'description', 'encoding', 'size',
                                         'envelope', 'body', 'lines', 'md5',
                                         'disposition', 'lang', 'location',
                                         'extension'])

"""
Any other single-part BODYSTRUCTURE.

type - lowercase str
subtype - lowercase str
params - dict[lowercase str]->str
id - str or None
description - str or None
encoding - lowercase str
size - int
md5 - str or None
disposition - (lowercase str, dict[lowercase str]->str) or None
lang - list of str or None
location - str or None
extension - list
"""
BasicBody = namedtuple('BasicBody', ['type', 'subtype', 'params', 'id',
                                     'description', 'encoding', 'size', 'md5',
                                     'disposition', 'lang', 'location',
                                     'extension'])

"""
BODYSTRUCTURE with "multipart/*" media type.

type - always "multipart"
subtype - lowercase str
parts - list of BODYSTRUCTURE types
params - dict[lowercase str]->str
disposition - (lowercase str, dict[lowercase str]->str) or None
lang - list of str or None
location - str or None
extension - list
"""
MultipartBody = namedtuple('MultipartBody', ['type', 'subtype', 'parts',
                                             'params', 'disposition', 'lang',
                                             'location', 'extension'])

"""
ENVELOPE fetch item.

date - datetime.datetime or None
subject - bytes or None
from_ - list of Address or None
sender - list of Address or None
reply_to - list of Address or None
to - list of Address or None
cc - list of Address or None
bcc - list of Address or None
in_reply_to - bytes or None
message_id - bytes or None
"""
Envelope = namedtuple('Envelope', ['date', 'subject', 'from_', 'sender',
                                   'reply_to', 'to', 'cc', 'bcc',
                                   'in_reply_to', 'message_id'])


"""
ESEARCH response.

tag - string or None
uid - bool
returned - dict[str]->data type:
    'MIN', 'MAX', 'COUNT': int
    'ALL': sequence set
"""
Esearch = namedtuple('Esearch', ['tag', 'uid', 'returned'])

"""
FETCH response.

msg - message sequence number as int
items - mapping from item to value as dict[str]->data type:
    'ENVELOPE': Envelope
    'FLAGS': set(str)
    'INTERNALDATE': datetime.datetime
    'RFC822', 'RFC822.HEADER', 'RFC822.TEXT': str or None
    'RFC822.SIZE': int
    'BODY[]': dict[str]->(bytes, int)
    and origin is an int or None
    'UID': int
    'X-GM-MSGID': unsigned 64-bit int ('X-GM-EXT1' capability)
"""
Fetch = namedtuple('Fetch', ['msg', 'items'])

"""
LIST response.

attributes - set of name attributes as strings
delimiter - mailbox delimiter as integer (ord(char)) or None
mailbox - mailbox as bytes
"""
List = namedtuple('List', ['attributes', 'delimiter', 'mailbox'])

"""
STATUS response.

mailbox - mailbox as bytes
status - mapping from item to value as dict[str]->int
"""
Status = namedtuple('Status', ['mailbox', 'status'])

"""
Tagged response.

tag - response tag as str
type - response type as str ('OK', 'NO', or 'BAD')
text - human-readable response text as ResponseText
"""
TaggedResponse = namedtuple('TaggedResponse', ['tag', 'type', 'text'])

"""
Untagged response.

type - response type as str
data - type-specific response data
    'OK', 'NO', 'BAD', 'BYE', 'PREAUTH': ResponseText
    'CAPABILITY', 'FLAGS': set of strings
    'ESEARCH': Esearch
    'EXISTS', 'EXPUNGE', 'RECENT': int
    'FETCH': Fetch
    'LIST', 'LSUB': List
    'SEARCH': set of integers
    'STATUS': Status
"""
UntaggedResponse = namedtuple('UntaggedResponse', ['type', 'data'])

"""
Response text.

text - human-readable text as str or None
code - bracket-enclosed code type as str or None
code_data - type-specific code data
    'ALERT', 'PARSE', 'READ-ONLY', 'READ-WRITE', 'TRYCREATE': None
    'HIGHESTMODSEQ', 'UIDNEXT', 'UIDVALIDITY', 'UNSEEN': int
    Anything else: str or None
"""
ResponseText = namedtuple('ResponseText', ['text', 'code', 'code_data'])


class IMAP4Parser:
    def __init__(self):
        self._buf = bytearray()
        self._cursor = 0

    def feed(self, buf):
        self._buf.extend(buf)

    def advance(self):
        assert self._cursor <= len(self._buf)
        del self._buf[:self._cursor]
        self._cursor = 0

    def _error(self, msg='Parse error'):
        line_start = self._buf.rfind(b'\r\n', 0, self._cursor)
        if line_start == -1:
            line_start = 0
        else:
            line_start += 2
        line_end = self._buf.find(b'\r\n', self._cursor)
        if line_end == -1:
            line_end = len(self._buf)
        cursor = self._cursor - line_start
        raise IMAPParseError(msg, bytes(self._buf[line_start:line_end]), cursor)

    def _short_parse(self, hint=None):
        self._cursor = 0
        raise IMAPShortParse(hint)

    def getc(self):
        """Parse a single character."""
        try:
            c = self._buf[self._cursor]
            self._cursor += 1
            return c
        except IndexError:
            self._short_parse()

    def ungetc(self, c):
        """Push the given character back into the stream."""
        assert self._cursor > 0
        self._cursor -= 1

    def ungets(self, s):
        """Push the given bytes back into the stream."""
        for c in reversed(s):
            self.ungetc(c)

    def peekc(self):
        """Parse a single character without advancing the stream."""
        try:
            return self._buf[self._cursor]
        except IndexError:
            self._short_parse()

    def expectc(self, expected):
        try:
            c = self._buf[self._cursor]
            if c != expected:
                self._error('Expected %r; got %r' % (chr(expected), chr(c)))
            self._cursor += 1
            return c
        except IndexError:
            self._short_parse()

    def expects(self, expected):
        """Parse a bytes with expected contents."""
        start = self._cursor
        self._cursor += len(expected)
        s = self._buf[start:self._cursor]
        if s != expected:
            if len(s) < len(expected):
                self._short_parse()
            else:
                self._cursor -= len(expected)
                self._error('Expected %r; got %r' % (expected, bytes(s)))

    def _parse_re(self, re):
        if self._cursor >= len(self._buf):
            self._short_parse()
        try:
            match = re.match(self._buf, self._cursor)
            if match.end() >= len(self._buf):
                self._short_parse()
            self._cursor = match.end()
            return match
        except AttributeError:
            # If match was None
            self._error()

    def _parse_token(self):
        # This isn't a production in the ABNF, but we use it in various places.
        return self._parse_re(_token_re).group().upper().decode('ascii')

    def parse_address(self):
        """Returns Address."""
        self.expectc(ord(b'('))
        name = self.parse_nstring()  # addr-name
        self.expectc(ord(b' '))

        adl = self.parse_nstring()  # addr-adl
        self.expectc(ord(b' '))

        mailbox = self.parse_nstring()  # addr-mailbox
        self.expectc(ord(b' '))

        host = self.parse_nstring()  # addr-host
        self.expectc(ord(b')'))

        return Address(name, adl, mailbox, host)

    def parse_astring(self):
        """Returns bytes."""
        c = self.peekc()
        if c == ord('"') or c == ord('{'):
            return self.parse_string()
        else:
            return self._parse_re(_astring_re).group()

    def parse_atom(self):
        """Returns bytes."""
        return self._parse_re(_atom_re).group()

    def parse_body(self):
        self.expectc(ord('('))
        if self.peekc() == ord('('):
            body = self.parse_body_type_mpart()
        else:
            body = self.parse_body_type_1part()
        self.expectc(ord(')'))
        return body

    def parse_body_extension(self):
        """Returns str, int, or list."""
        c = self.peekc()
        if c == ord('('):
            self.getc()
            extension = []
            while True:
                extension.append(self.parse_body_extension())
                if self.peekc() == ord(')'):
                    self.getc()
                    return extension
                self.expectc(ord(' '))
        elif ord('0') <= c <= ord('9'):
            return self.parse_number()
        else:
            return self.parse_nstring()

    def parse_body_ext_1part(self):
        data = []
        data.append(self.parse_nstring())  # body-fld-md5
        if data[-1] is not None:
            data[-1] = data[-1].decode('ascii')

        if self.peekc() != ord(' '):
            return data
        self.getc()
        data.append(self.parse_body_fld_dsp())

        if self.peekc() != ord(' '):
            return data
        self.getc()
        data.append(self.parse_body_fld_lang())

        if self.peekc() != ord(' '):
            return data
        self.getc()
        data.append(self.parse_nstring())  # body-fld-loc
        if data[-1] is not None:
            data[-1] = data[-1].decode('ascii')

        while self.peekc() == ord(' '):
            self.getc()
            data.append(self.parse_body_extension())
        return data

    def parse_body_ext_mpart(self):
        """Returns list."""
        data = []
        data.append(self.parse_body_fld_param())

        if self.peekc() != ord(' '):
            return data
        self.getc()
        data.append(self.parse_body_fld_dsp())

        if self.peekc() != ord(' '):
            return data
        self.getc()
        data.append(self.parse_body_fld_lang())

        if self.peekc() != ord(' '):
            return data
        self.getc()
        data.append(self.parse_nstring())  # body-fld-loc
        if data[-1] is not None:
            data[-1] = data[-1].decode('ascii')

        while self.peekc() == ord(' '):
            self.getc()
            data.append(self.parse_body_extension())
        return data

    def parse_body_fields(self):
        """Returns list."""
        fields = []
        fields.append(self.parse_body_fld_param())
        self.expectc(ord(' '))
        fields.append(self.parse_nstring())  # body-fld-id
        if fields[-1] is not None:
            fields[-1] = fields[-1].decode('ascii')
        self.expectc(ord(' '))
        fields.append(self.parse_nstring())  # body-fld-desc
        if fields[-1] is not None:
            fields[-1] = fields[-1].decode('ascii')
        self.expectc(ord(' '))
        fields.append(self.parse_string().lower().decode('ascii'))  # body-fld-enc
        self.expectc(ord(' '))
        fields.append(self.parse_number())  # body-fld-octets
        return fields

    def parse_body_fld_dsp(self):
        """
        Returns lowercase str, dict with lowercase str keys and str values or
        None.
        """
        if self.peekc() == ord('('):
            self.getc()
            disp_type = self.parse_string().lower().decode('ascii')
            self.expectc(ord(' '))
            disp_params = self.parse_body_fld_param()
            self.expectc(ord(')'))
            return disp_type, disp_params
        else:
            self.expects(b'NIL')
            return None

    def parse_body_fld_lang(self):
        """Returns list of str or None."""
        if self.peekc() == ord('('):
            self.getc()
            langs = []
            while True:
                langs.append(self.parse_string().decode('ascii'))
                if self.peekc() == ord(')'):
                    self.getc()
                    return langs
                self.expectc(ord(' '))
        else:
            lang = self.parse_nstring()
            if lang is None:
                return None
            else:
                return [lang.decode('ascii')]

    def parse_body_fld_param(self):
        """Returns dict with lowercase str keys and str values."""
        if self.peekc() == ord('('):
            self.getc()
            params = {}
            while True:
                key = self.parse_string().lower().decode('ascii')
                self.expectc(ord(' '))
                value = self.parse_string().decode('ascii')
                params[key] = value
                if self.peekc() == ord(')'):
                    self.getc()
                    return params
                self.expectc(ord(' '))
        else:
            self.expects(b'NIL')
            return {}

    def parse_body_type_1part(self):
        """Returns TextBody, MessageBody, or BasicBody."""
        media_type = self.parse_string().lower().decode('ascii')
        self.expectc(ord(' '))
        media_subtype = self.parse_string().lower().decode('ascii')
        self.expectc(ord(' '))
        args = [media_type, media_subtype]
        if media_type == 'text':
            # body-type-text
            args.extend(self.parse_body_fields())
            self.expectc(ord(' '))
            args.append(self.parse_number())  # body-fld-lines
            type_ = TextBody
        elif media_type == 'message' and media_subtype == 'rfc822':
            # body-type-msg
            args.extend(self.parse_body_fields())
            self.expectc(ord(' '))
            args.append(self.parse_envelope())
            self.expectc(ord(' '))
            args.append(self.parse_body())
            self.expectc(ord(' '))
            args.append(self.parse_number())  # body-fld-lines
            type_ = MessageBody
        else:
            # body-type-basic
            args.extend(self.parse_body_fields())
            type_ = BasicBody
        if self.peekc() == ord(' '):
            self.getc()
            extension = self.parse_body_ext_1part()
            if len(extension) < 4:
                extension.extend([None] * (4 - len(extension)))
            return type_(*args, *extension[:4], extension[4:])
        else:
            return type_(*args, None, None, None, None, [])

    def parse_body_type_mpart(self):
        """Returns MultipartBody."""
        bodies = []
        while self.peekc() == ord('('):
            bodies.append(self.parse_body())
        self.expectc(ord(' '))
        media_subtype = self.parse_string().lower().decode('ascii')
        if self.peekc() == ord(' '):
            self.getc()
            extension = self.parse_body_ext_mpart()
            if len(extension) < 4:
                extension.extend([None] * (4 - len(extension)))
            return MultipartBody('multipart', media_subtype, bodies,
                                 *extension[:4], extension[4:])
        else:
            return MultipartBody('multipart', media_subtype, bodies,
                                 {}, None, None, None, [])

    def parse_continue_req(self):
        """Returns ContinueReq."""
        self.expects(b'+ ')
        text = self.parse_resp_text()
        self.expects(b'\r\n')
        return ContinueReq(text)

    def parse_envelope(self):
        """Returns Envelope."""
        self.expectc(ord(b'('))
        args = []
        date = self.parse_nstring()  # env-date
        if date is not None:
            try:
                date = email.utils.parsedate_to_datetime(date.decode('ascii'))
            except Exception:
                # As of Python 3.5.0, email.utils.parsedate_to_datetime() for a
                # bogus date will try to unpack None and end up with a
                # TypeError as a result, but let's be safe in case this is
                # changed in the future.
                date = None
        args.append(date)
        self.expectc(ord(b' '))
        args.append(self.parse_nstring())  # env-subject
        self.expectc(ord(b' '))
        args.append(self.parse_env_addrs())  # env-from
        self.expectc(ord(b' '))
        args.append(self.parse_env_addrs())  # env-sender
        self.expectc(ord(b' '))
        args.append(self.parse_env_addrs())  # env-reply-to
        self.expectc(ord(b' '))
        args.append(self.parse_env_addrs())  # env-to
        self.expectc(ord(b' '))
        args.append(self.parse_env_addrs())  # env-cc
        self.expectc(ord(b' '))
        args.append(self.parse_env_addrs())  # env-bcc
        self.expectc(ord(b' '))
        args.append(self.parse_nstring())  # env-in-reply-to
        self.expectc(ord(b' '))
        args.append(self.parse_nstring())  # env-message-id
        self.expectc(ord(b')'))
        return Envelope(*args)

    def parse_env_addrs(self):
        """Returns list of Address or None."""
        if self.peekc() == ord('N'):
            self.expects(b'NIL')
            return None
        else:
            self.expectc(ord(b'('))
            addrs = []
            while True:
                addrs.append(self.parse_address())
                if self.peekc() != ord('('):
                    break
            self.expectc(ord(b')'))
            return addrs

    def parse_flag_list(self):
        """Returns set of strings."""
        flags = set()
        self.expectc(ord(b'('))
        c = self.peekc()
        if c == ord(')'):
            self.getc()
            return flags
        while True:
            c = self.peekc()
            if c == ord('\\'):
                self.getc()
                flags.add('\\' + self.parse_atom().decode('ascii'))
            else:
                flags.add(self.parse_atom().decode('ascii'))
            c = self.getc()
            if c != ord(' '):
                self.ungetc(c)
                break
        self.expectc(ord(b')'))
        return flags

    def parse_mailbox(self):
        """Returns bytes."""
        mailbox = self.parse_astring()
        if mailbox.upper() == b'INBOX':
            return b'INBOX'
        else:
            return mailbox

    def parse_mailbox_data(self):
        """Returns data as per UntaggedResponse.data"""
        type_ = self._parse_token()
        if type_ == 'ESEARCH':
            # esearch-response
            if self.peekc() != ord(b' '):
                return Esearch(None, False, {})
            self.getc()
            tag = None
            if self.peekc() == ord(b'('):
                # search-correlator
                self.expects(b'(TAG ')
                tag = self.parse_string().decode('ascii')
                self.expectc(ord(b')'))
            uid = False
            returned = {}
            while True:
                c = self.peekc()
                if c != ord(' '):
                    return Esearch(tag, uid, returned)
                self.getc()
                modifier = self._parse_token()
                if modifier == 'UID':
                    uid = True
                elif modifier in ['COUNT', 'MAX', 'MIN']:
                    self.expectc(ord(' '))
                    returned[modifier] = self.parse_number()
                elif modifier == 'ALL':
                    self.expectc(ord(' '))
                    returned[modifier] = self.parse_sequence_set()
        elif type_ == 'FLAGS':
            self.expectc(ord(b' '))
            return self.parse_flag_list()
        elif type_ == 'LIST' or type_ == 'LSUB':
            self.expectc(ord(b' '))
            return self.parse_mailbox_list()
        elif type_ == 'SEARCH':
            search = set()
            while True:
                c = self.peekc()
                if c != ord(' '):
                    return search
                self.getc()
                search.add(self.parse_number())
        elif type_ == 'STATUS':
            self.expectc(ord(b' '))
            mailbox = self.parse_mailbox()
            self.expects(b' (')
            status = self.parse_status_att_list()
            self.expectc(ord(b')'))
            return Status(mailbox, dict(status))
        else:
            self._error('Unknown response %r' % type_)

    def parse_mailbox_list(self):
        """Returns List."""
        self.expectc(ord(b'('))
        flags = self.parse_mbx_list_flags()
        self.expects(b') ')

        if self.peekc() == ord('"'):
            self.getc()
            delimiter = self.getc()
            self.expects(b'" ')
        else:
            self.expects(b'NIL ')
            delimiter = None

        mailbox = self.parse_mailbox()
        return List(flags, delimiter, mailbox)

    def parse_mbx_list_flags(self):
        """Returns a set of strings."""
        flags = set()
        c = self.peekc()
        if c == ord(')'):
            return flags
        while True:
            self.expectc(ord(b'\\'))
            flag = '\\' + self.parse_atom().decode('ascii')
            flags.add(flag)
            c = self.getc()
            if c != ord(' '):
                self.ungetc(c)
                break
        return flags

    def parse_message_data(self):
        """Returns (type, data)."""
        number = self.parse_number()
        self.expectc(ord(b' '))

        # In the ABNF, this is only for EXPUNGE and FETCH. However, some
        # mailbox-data also starts with a number.
        type_ = self._parse_token()
        if type_ == 'FETCH':
            self.expectc(ord(b' '))
            data = Fetch(number, dict(self.parse_msg_att()))
        elif type_ in ['EXISTS', 'EXPUNGE', 'RECENT']:
            data = number
        else:
            self._error('Unknown response %r' % type_)
        return type_, data

    def parse_msg_att(self):
        """Returns list of data."""
        data = []
        body = {}
        self.expectc(ord(b'('))
        while True:
            att_item, att_data = self.parse_msg_att_item()
            if att_item == 'BODY[]':
                # All of the BODY[section-spec]<origin> items get folded into
                # one in the list.
                section_spec, origin, content = att_data
                body[section_spec] = (content, origin)
            else:
                data.append((att_item, att_data))
            c = self.getc()
            if c != ord(' '):
                self.ungetc(c)
                break
        self.expectc(ord(b')'))
        if body:
            data.append(('BODY[]', body))
        return data

    def parse_msg_att_item(self):
        """Returns (str, data)."""
        item = self._parse_token()
        # msg-att-dynamic
        if item == 'FLAGS':
            self.expectc(ord(b' '))
            data = self.parse_flag_list()
        # msg-att-static
        elif item == 'ENVELOPE':
            self.expectc(ord(b' '))
            data = self.parse_envelope()
        elif item == 'INTERNALDATE':
            self.expects(b' "')
            match = self._parse_re(_quoted_re)
            self.expectc(ord(b'"'))
            try:
                data = datetime.datetime.strptime(match.group().decode('ascii'),
                                                  '%d-%b-%Y %H:%M:%S %z')
            except ValueError:
                self._error('Invalid date-time')
        elif item in ['RFC822', 'RFC822.HEADER', 'RFC822.TEXT']:
            self.expectc(ord(b' '))
            data = self.parse_nstring()
        elif item == 'RFC822.SIZE':
            self.expectc(ord(b' '))
            data = self.parse_number()
        elif item == 'BODY':
            if self.peekc() == ord('['):
                self.getc()
                # We could parse this exactly according to the grammar, but
                # it's simpler to just assume it's whatever is in the []
                # brackets.
                section_spec = self._parse_re(_section_spec_re).group().decode('ascii')
                self.expectc(ord(']'))
                if self.peekc() == ord('<'):
                    self.getc()
                    origin = self.parse_number()
                    self.expectc(ord('>'))
                else:
                    origin = None
                self.expectc(ord(b' '))
                content = self.parse_nstring()
                item = 'BODY[]'
                data = section_spec, origin, content
            else:
                self.expectc(ord(b' '))
                data = self.parse_body()
        elif item == 'BODYSTRUCTURE':
            self.expectc(ord(b' '))
            data = self.parse_body()
        elif item == 'UID':
            self.expectc(ord(b' '))
            data = self.parse_number()
        elif item == 'X-GM-MSGID':
            self.expectc(ord(b' '))
            data = self.parse_number()
        else:
            self._error('Unknown FETCH item %s' % item)
        return item, data

    def parse_nstring(self):
        """Returns bytes or None."""
        if self.peekc() == ord('N'):
            self.expects(b'NIL')
            return None
        else:
            return self.parse_string()

    def parse_number(self):
        """Returns int."""
        return int(self._parse_re(_number_re).group())

    def parse_response_line(self):
        """Returns ContinueReq, TaggedResponse, or UntaggedResponse."""
        c = self.peekc()
        if c == ord('+'):
            return self.parse_continue_req()
        elif c == ord('*'):
            return self.parse_response_data()
        else:
            # In ABNF, we have response-done = response-tagged / response-fatal,
            # but response-fatal will get caught by response-data above, so
            # we just need to parse response-tagged.
            return self.parse_response_tagged()

    def parse_response_data(self):
        """Returns UntaggedResponse."""
        self.expects(b'* ')
        c = self.peekc()
        if ord('0') <= c <= ord('9'):
            type_, data = self.parse_message_data()
        else:
            type_ = self._parse_token()
            if type_ in ['OK', 'NO', 'BAD', 'PREAUTH', 'BYE']:
                # resp-cond-state, resp-cond-auth, and resp-cond-bye
                self.expectc(ord(b' '))
                data = self.parse_resp_text()
            elif type_ == 'CAPABILITY':
                # capability-data
                caps = set()
                while True:
                    c = self.peekc()
                    if c == ord(' '):
                        self.getc()
                        caps.add(self.parse_atom().decode('ascii'))
                    else:
                        break
                data = caps
            else:
                self.ungets(type_)
                data = self.parse_mailbox_data()
        self.expects(b'\r\n')
        return UntaggedResponse(type_, data)

    def parse_response_tagged(self):
        """Returns TaggedResponse."""
        tag = self.parse_tag()
        self.expectc(ord(b' '))
        # resp-cond-state
        type_ = self._parse_token()
        if type_ not in ['OK', 'NO', 'BAD']:
            self._error('Unknown tagged response %r' % type_)
        self.expectc(ord(b' '))
        text = self.parse_resp_text()
        self.expects(b'\r\n')
        return TaggedResponse(tag, type_, text)

    def parse_resp_text(self):
        """Returns ResponseText."""
        c = self.peekc()
        if c == ord('['):
            self.getc()
            code, code_data = self.parse_resp_text_code()
            self.expectc(ord(b']'))
            c = self.peekc()
            if c == ord(' '):
                self.getc()
                text = self.parse_text()
            else:
                # It's not clear whether this case is allowed by the ABNF, but
                # Gmail does it.
                text = None
        else:
            code = None
            code_data = None
            text = self.parse_text()
        return ResponseText(text, code, code_data)

    def parse_resp_text_code(self):
        """Returns (string, data)."""
        code = self.parse_atom().upper().decode('ascii')
        if code in ['ALERT', 'PARSE', 'READ-ONLY', 'READ-WRITE',
                    'TRYCREATE']:
            data = None
        if code in ['HIGHESTMODSEQ', 'UIDNEXT', 'UIDVALIDITY', 'UNSEEN']:
            self.expectc(ord(b' '))
            data = self.parse_number()
        else:
            c = self.peekc()
            if c == ord(' '):
                self.getc()
                data = self._parse_re(_resp_text_code_re).group().decode('ascii')
            else:
                data = None
        return code, data

    def parse_sequence_set(self):
        """Returns list of ints and (int, int) tuples."""
        seq_set = []
        while True:
            number1 = self.parse_number()
            if self.peekc() == ord(':'):
                self.getc()
                number2 = self.parse_number()
                seq_set.append((number1, number2))
            else:
                seq_set.append(number1)
            if self.peekc() == ord(','):
                self.getc()
            else:
                return seq_set

    def parse_status_att_list(self):
        """Returns list of (str, int)."""
        status = []
        while True:
            item = self.parse_atom().decode('ascii')
            self.expectc(ord(b' '))
            value = self.parse_number()
            status.append((item, value))
            c = self.peekc()
            if c != ord(' '):
                break
            self.getc()
        return status

    def parse_string(self):
        """Returns bytes."""
        c = self.getc()
        if c == ord('"'):
            match = self._parse_re(_quoted_re)
            if self.peekc() == ord('\\'):
                self._short_parse()
            self.expectc(ord('"'))
            return codecs.escape_decode(match.group())[0]
        elif c == ord('{'):
            size = self.parse_number()
            self.expects(b'}\r\n')
            start = self._cursor
            self._cursor += size
            s = self._buf[start:self._cursor]
            if len(s) < size:
                self._short_parse(size - len(s))
            return bytes(s)
        else:
            self._error('Invalid string')

    def parse_tag(self):
        """Returns string."""
        return self._parse_re(_tag_re).group().decode('ascii')

    def parse_text(self):
        """Returns string."""
        return self._parse_re(_text_re).group().decode('ascii')
