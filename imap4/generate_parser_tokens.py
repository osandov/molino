#!/usr/bin/env python3

import re
import os.path
import sys
import subprocess


tokens = [
    b'ALERT',
    b'ALL',
    b'BAD',
    b'BODY',
    b'BODYSTRUCTURE',
    b'BYE',
    b'CAPABILITY',
    b'COUNT',
    b'ENABLED',
    b'ENVELOPE',
    b'ESEARCH',
    b'EXISTS',
    b'EXPUNGE',
    b'FETCH',
    b'FLAGS',
    b'HIGHESTMODSEQ',
    b'INTERNALDATE',
    b'LIST',
    b'LSUB',
    b'MAX',
    b'MESSAGES',
    b'MIN',
    b'MODSEQ',
    b'NO',
    b'OK',
    b'PARSE',
    b'PREAUTH',
    b'READ-ONLY',
    b'READ-WRITE',
    b'RECENT',
    b'RFC822',
    b'RFC822.HEADER',
    b'RFC822.SIZE',
    b'RFC822.TEXT',
    b'SEARCH',
    b'STATUS',
    b'TRYCREATE',
    b'UID',
    b'UIDNEXT',
    b'UIDVALIDITY',
    b'UNSEEN',
    b'X-GM-MSGID',
]


assert len(tokens) == len(set(tokens))
assert tokens == sorted(tokens)


def to_enum(token):
    return re.sub(b'\W', b'_', token)


def create_imap4_init(path):
    with open(path, 'wb') as f:
        f.write(b"""\
import enum


@enum.unique
class Token(enum.IntEnum):
    UNKNOWN = 0
""")
        for i, token in enumerate(tokens, 1):
            f.write(b'    %s = %d\n' % (to_enum(token), i))
        f.write(b'    BODYSECTIONS = %d\n' % (len(tokens) + 1))
        f.write(b'\n')
        for token in tokens + [b'BODYSECTIONS']:
            f.write(b'%s = Token.%s\n' % (to_enum(token), to_enum(token)))


def create_header_file(path):
    with open(path, 'wb') as f:
        f.write(b"""\
#ifndef IMAPPARSER_TOKENS_H
#define IMAPPARSER_TOKENS_H

enum {
""")
        for i, token in enumerate(tokens, 1):
            f.write(b'\tIMAP4_%b = %d,\n' % (to_enum(token), i))
        f.write(b'\tIMAP4_BODYSECTIONS = %d,\n' % (len(tokens) + 1))
        f.write(b"""\
};

#endif /* IMAPPARSER_TOKENS_H */
""")


def create_gperf_output(path):
    cmd = ['gperf', '--compare-strncmp', '--ignore-case', '--includes',
           '--language=ANSI-C', '--readonly-tables', '--seven-bit',
           '--struct-type', '--output-file=%s' % path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    proc.stdin.write(b"""\
%{
#include <Python.h>

#include "tokens.h"
%}
struct imap_token {
	char *name;
	long constant;
};
%%
""")
    for token in tokens:
        proc.stdin.write(b'%b, IMAP4_%b\n' % (token, to_enum(token)))
    proc.stdin.write(b"""\
%%
long imap4_token(const char *str, Py_ssize_t len)
{
	const struct imap_token *token;

	token = in_word_set(str, len);
	if (token == NULL)
		return 0;
	else
		return token->constant;
}
""")
    proc.stdin.close()


if __name__ == '__main__':
    directory = sys.argv[1]
    create_imap4_init(os.path.join(directory, '__init__.py'))
    create_header_file(os.path.join(directory, 'parser/tokens.h'))
    create_gperf_output(os.path.join(directory, 'parser/tokens.c'))
