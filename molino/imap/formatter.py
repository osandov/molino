import codecs
import re

from molino.imap.parser import _astring_re, _list_re, _text_re
import molino.imap.codecs


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


def format_fetch(buffer, tag, seq_set, *items, uid=False):
    """
    Format FETCH command.

    uid - use UID FETCH to use unique identifiers instead of sequence numbers
    seq_set - identifiers to fetch; see sequence_set()
    items - items to fetch
    """
    conts = _format_common(buffer, tag, 'UID FETCH' if uid else 'FETCH')
    buffer.extend(b' ')
    buffer.extend(b','.join(b'%d' % seq if isinstance(seq, int) else b'%d:%d' % seq
                            for seq in seq_set))
    buffer.extend(b' ')
    if len(items) == 1:
        buffer.extend(items[0].encode('ascii'))
    else:
        format_paren_list(buffer, conts, items, format_ascii_atom)
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

    ALL: (no arguments) all messages in mailbox
    UNSEEN: (no arguments) messages that do not have the \\Seen flag set

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
    for c in criteria:
        key, args = c[0], c[1:]
        if key == 'ALL':
            assert len(args) == 0
            buffer.extend(b' ALL')
        elif key == 'UNSEEN':
            assert len(args) == 0
            buffer.extend(b' UNSEEN')
        else:
            raise ValueError('Unknown SEARCH criteria "%s"' % key)
    buffer.extend(b'\r\n')
    return conts


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
