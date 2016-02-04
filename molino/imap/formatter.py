import codecs
import re

import molino.imap.codecs


_astring_re = re.compile(b'[^(){ %*"\\\\\x00-\x1f\x7f-\xff]+')
_list_re = re.compile(b'[^(){ "\\\\\x00-\x1f\x7f-\xff]+')
_text_re = re.compile(b'[^\x00\r\n\x7f-\xff]+')


"""
The following functions are used to format an IMAP4 command as per the
protocol. They all take some arguments in common in addition to the
command-specific arguments.

buffer - buffer to output to
tag - command tag

In addition, they all return a list of positions in the buffer where
continuations are needed.
"""


def _format_common(buffer, tag, cmd):
    buffer.extend(tag.encode('ascii'))
    buffer.extend(b' ')
    buffer.extend(cmd.encode('ascii'))
    return []


def format_ascii_atom(buffer, conts, s):
    buffer.extend(s.encode('ascii'))


def format_astring(buffer, conts, s):
    """Format an astring."""
    if _astring_re.fullmatch(s):
        # Atom
        buffer.extend(s)
    else:
        # String
        _format_string(buffer, conts, s)


def format_mailbox(buffer, conts, mailbox):
    """Format a mailbox name."""
    assert type(mailbox) == bytes
    if _list_re.fullmatch(mailbox):
        buffer.extend(mailbox)
    else:
        _format_string(buffer, conts, mailbox)


def format_paren_list(buffer, conts, l, format):
    """
    Format a parenthesized list.

    l - the list
    format - formatter to use for each element of the list
    """
    buffer.extend(b'(')
    for i, item in enumerate(l):
        if i > 0:
            buffer.extend(b' ')
        format(buffer, conts, item)
    buffer.extend(b')')


def _format_string(buffer, conts, s):
    if len(s) == 0:
        buffer.extend(b'""')
    elif _text_re.fullmatch(s):
        # Quoted
        escaped = s.replace(b'\\', b'\\\\').replace(b'"', b'\\"')
        buffer.extend(b'"%b"' % escaped)
    else:
        # Literal
        buffer.extend(b'{%d}\r\n' % len(s))
        conts.append(len(buffer))
        buffer.extend(s)


def format_capability(buffer, tag):
    """Format CAPABLITY command."""
    conts = _format_common(buffer, tag, 'CAPABILITY')
    buffer.extend(b'\r\n')
    return conts


def format_check(buffer, tag):
    """Format CHECK command."""
    conts = _format_common(buffer, tag, 'CHECK')
    buffer.extend(b'\r\n')
    return conts


def format_close(buffer, tag):
    """Format CLOSE command."""
    conts = _format_common(buffer, tag, 'CLOSE')
    buffer.extend(b'\r\n')
    return conts


def format_enable(buffer, tag, *capabilities):
    """
    Format ENABLE command (requires ENABLE capability).

    capabilities - capabilities to enable
    """
    conts = _format_common(buffer, tag, 'ENABLE')
    buffer.extend(b' ')
    buffer.extend(b' '.join(cap.encode('ascii') for cap in capabilities))
    buffer.extend(b'\r\n')
    return conts


def format_examine(buffer, tag, mailbox):
    """
    Format EXAMINE command.

    mailbox - mailbox name
    """
    conts = _format_common(buffer, tag, 'EXAMINE')
    buffer.extend(b' ')
    format_mailbox(buffer, conts, mailbox)
    buffer.extend(b'\r\n')
    return conts


def format_fetch(buffer, tag, seq_set, *items, uid=False, changedsince=None):
    """
    Format FETCH command.

    uid - use UID FETCH to use unique identifiers instead of sequence numbers
    seq_set - identifiers to fetch; see sequence_set()
    items - items to fetch
    """
    conts = _format_common(buffer, tag, 'UID FETCH' if uid else 'FETCH')
    buffer.extend(b' ')
    for i, seq in enumerate(seq_set):
        if i != 0:
            buffer.extend(b',')
        if seq is None:
            buffer.extend(b'*')
        elif isinstance(seq, int):
            buffer.extend(b'%d' % seq)
        else:
            buffer.extend(b'*' if seq[0] is None else b'%d' % seq[0])
            buffer.extend(b':*' if seq[1] is None else b':%d' % seq[1])
    buffer.extend(b' ')
    if len(items) == 1:
        buffer.extend(items[0].encode('ascii'))
    else:
        format_paren_list(buffer, conts, items, format_ascii_atom)
    if changedsince is not None:
        buffer.extend(b' (CHANGEDSINCE %d)' % changedsince)
    buffer.extend(b'\r\n')
    return conts


def format_idle(buffer, tag):
    """Format IDLE command."""
    conts = _format_common(buffer, tag, 'IDLE')
    buffer.extend(b'\r\n')
    conts.append(len(buffer))
    buffer.extend(b'DONE\r\n')
    return conts


def format_list(buffer, tag, reference, mailbox, status_items=[]):
    """
    Format LIST command.

    reference - starting point for listing
    mailbox - mailbox name with possible * and % wildcards
    status_items - also get the statuses of the listed mailboxes (requires
    LIST-STATUS capability)
    """
    conts = _format_common(buffer, tag, 'LIST')
    buffer.extend(b' ')
    format_mailbox(buffer, conts, reference)
    buffer.extend(b' ')
    format_mailbox(buffer, conts, mailbox)
    if status_items:
        buffer.extend(b' RETURN (STATUS ')
        format_paren_list(buffer, conts, status_items, format_ascii_atom)
        buffer.extend(b')')
    buffer.extend(b'\r\n')
    return conts


def format_login(buffer, tag, username, password):
    """
    Format LOGIN command.

    username - user name
    password - password
    """
    conts = _format_common(buffer, tag, 'LOGIN')
    buffer.extend(b' ')
    format_astring(buffer, conts, username.encode('ascii'))
    buffer.extend(b' ')
    format_astring(buffer, conts, password.encode('ascii'))
    buffer.extend(b'\r\n')
    return conts


def format_logout(buffer, tag):
    """Format LOGOUT command."""
    conts = _format_common(buffer, tag, 'LOGOUT')
    buffer.extend(b'\r\n')
    return conts


def format_noop(buffer, tag):
    """Format NOOP command."""
    conts = _format_common(buffer, tag, 'NOOP')
    buffer.extend(b'\r\n')
    return conts


def format_search(buffer, tag, *criteria, uid=False, esearch=None):
    """
    Format SEARCH command.

    uid - use UID SEARCH to use unique identifiers instead of sequence numbers
    criteria - tuples representing search criteria as follows:

    ALL: all messages in mailbox
    ANSWERED: messages that have the \\Answered flag set
    BEFORE <date>: messages whose internal date is earlier than the specified date
    BCC <string>: messages with the given string in the Bcc field
    BODY <string>: messages with the given string in the message body
    CC <string>: messages with the given string in the Cc field
    DELETED: messages that have the \\Deleted flag set
    DRAFT: messages that have the \\Draft flag set
    FLAGGED: messages that have the \\Flagged flag set
    FROM <string>: messages with the given string in the From field
    HEADER <field-name> <string>: messages with the given string in the given field
    KEYWORD <string>: messages with the given keyword flag set
    LARGER <n>: messages larger than the given number of octets
    MODSEQ <n>: messages with a CONDSTORE modification value greater than the given value
    NEW: messages that have the \\Recent flag set but not the \\Seen flag
    NOT <search-key>: messages that do not match the specified search key
    OLD: messages that do not have the \\Recent flag set
    ON <date>: messages whose internal date is on the given date
    OR <search-key1> <search-key2>: messages that match either search key
    RECENT: messages that have the \\Recent flag set
    SEEN: messages that have the \\Seen flag set
    SENTBEFORE <date>: messages whose Date header is earlier than the given date
    SENTON <date>: messages whose Date header is on the given date
    SENTSINCE <date>: messages whose Date header is on or later than the given date
    SINCE <date>: messages whose internal date is on or later than the given date
    SMALLER <n>: messages smaller than the given number of octets
    SUBJECT <string>: messages with the given string in the Subject field
    TEXT <string>: messages with the given string in the message header or body
    TO <string>: messages with the given string in the To field
    UID <sequence set>: messages with unique identifiers in the given sequence set
    UNANSWERED: messages that do not have the \\Answered flag set
    UNDELETED: messages that do not have the \\Deleted flag set
    UNDRAFT: messages that do not have the \\Draft flag set
    UNFLAGGED: messages that do not have the \\Flagged flag set
    UNKEYWORD <string>: messages that do not have the given keyword flag set
    UNSEEN: messages that do not have the \\Seen flag set
    X-GM-RAW <string>: messages matching the given Gmail search syntax
    seq <sequence set>: messages with message sequence numbers in the given sequence set

    Not implemented: BEFORE <date>, ON <date>, SENTBEFORE <date>, SENTON <date>,
    SENTSINCE <date>, SINCE <date>, UID

    esearch - iterable of strings controlling what is returned with the ESEARCH
    capability; an empty iterable is equivalent to an iterable containing only
    'ALL'

    MIN: the lowest message number/UID satisfying the criteria
    MAX: the highest message number/UID satisfying the criteria
    ALL: all message numbers/UIDs satisfying the criteria
    COUNT: the number of messages satisfying the criteria
    """
    conts = _format_common(buffer, tag, 'UID SEARCH' if uid else 'SEARCH')
    if esearch is not None:
        buffer.extend(b' RETURN (%b)' % b' '.join(s.encode('ascii') for s in esearch))
    for key in criteria:
        _format_search_key(buffer, conts, key)
    buffer.extend(b'\r\n')
    return conts


def _format_search_key(buffer, conts, key):
    if key[0] in ['ALL', 'ANSWERED', 'DELETED', 'DRAFT', 'FLAGGED', 'NEW',
                  'OLD', 'RECENT', 'SEEN', 'UNANSWERED', 'UNDELETED',
                  'UNDRAFT', 'UNFLAGGED', 'UNSEEN']:
        assert len(key) == 1
        buffer.extend(b' %b' % key[0].encode('ascii'))
    elif key[0] in ['BEFORE', 'ON', 'SENTBEFORE', 'SENTON', 'SENTSINCE', 'SINCE']:
        assert len(key) == 2
        buffer.extend(b' %b ' % key[0].encode('ascii'))
        buffer.extend(key[1].strftime('%d-%b-%Y').encode('ascii'))
    elif key[0] in ['BCC', 'BODY', 'CC', 'FROM', 'SUBJECT', 'TEXT', 'TO']:
        assert len(key) == 2
        buffer.extend(b' %b ' % key[0].encode('ascii'))
        format_astring(buffer, conts, key[1].encode('ascii'))
    elif key[0] == 'HEADER':
        assert len(key) == 3
        buffer.extend(b' %b ' % key[0].encode('ascii'))
        format_astring(buffer, conts, key[1].encode('ascii'))
        buffer.extend(b' ')
        format_astring(buffer, conts, key[2].encode('ascii'))
    elif key[0] in ['KEYWORD', 'UNKEYWORD']:
        assert len(key) == 2
        buffer.extend(b' %b ' % key[0].encode('ascii'))
        format_ascii_atom(buffer, conts, key[1])
    elif key[0] in ['LARGER', 'MODSEQ', 'SMALLER']:
        assert len(key) == 2
        buffer.extend(b' %b %d' % (key[0].encode('ascii'), key[1]))
    elif key[0] == 'NOT':
        assert len(key) == 2
        buffer.extend(b' NOT')
        _format_search_key(buffer, conts, key[1])
    elif key[0] == 'OR':
        assert len(key) == 3
        buffer.extend(b' OR')
        _format_search_key(buffer, conts, key[1])
        _format_search_key(buffer, conts, key[2])
    elif key[0] == 'UID':
        assert len(key) == 2
        buffer.extend(b' UID ')
        buffer.extend(key[1].encode('ascii'))
    elif key[0] == 'X-GM-RAW':
        assert len(key) == 2
        buffer.extend(b' X-GM-RAW ')
        _format_string(buffer, conts, key[1].encode('ascii'))
    elif key[0] == 'seq':
        assert len(key) == 2
        buffer.extend(b' ')
        buffer.extend(key[1].encode('ascii'))
    else:
        raise ValueError('Unknown SEARCH criteria "%s"' % key)


def format_select(buffer, tag, mailbox):
    """
    Format SELECT command.

    mailbox - mailbox name
    """
    conts = _format_common(buffer, tag, 'SELECT')
    buffer.extend(b' ')
    format_mailbox(buffer, conts, mailbox)
    buffer.extend(b'\r\n')
    return conts


def format_status(buffer, tag, mailbox, *items):
    """
    Format STATUS command.

    mailbox - mailbox name
    items - status items to get
    """
    conts = _format_common(buffer, tag, 'STATUS')
    buffer.extend(b' ')
    format_mailbox(buffer, conts, mailbox)
    buffer.extend(b' ')
    format_paren_list(buffer, conts, items, format_ascii_atom)
    buffer.extend(b'\r\n')
    return conts
