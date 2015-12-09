import base64
import binascii
import codecs


def imap_utf7_encode(input, errors='strict'):
    output = bytearray()
    shifted = 0
    b64 = False
    for i, c in enumerate(input):
        b = ord(c)
        if 0x20 <= b <= 0x25 or 0x27 <= b <= 0x7e:
            if b64:
                output.extend(b'&')
                output.extend(base64.b64encode(input[shifted:i].encode('utf-16-be'), altchars=b'+,').rstrip(b'='))
                output.extend(b'-')
                shifted = i
                b64 = False
        else:
            if not b64:
                output.extend(input[shifted:i].encode('ascii'))
                if b == 0x26:  # '&'
                    output.extend(b'&-')
                    shifted = i + 1
                else:
                    shifted = i
                    b64 = True
    if b64:
        output.extend(b'&')
        output.extend(base64.b64encode(input[shifted:].encode('utf-16-be'), altchars=b'+,').rstrip(b'='))
        output.extend(b'-')
    else:
        output.extend(input[shifted:].encode('ascii'))
    return bytes(output), len(input)


def imap_utf7_decode(input, errors='strict'):
    error = codecs.lookup_error(errors)
    output = []
    shifted = 0
    b64 = False
    i = 0
    while i < len(input):
        b = input[i]
        if b64:
            if b == 0x2d:  # '-'
                if shifted == i:
                    output.append('&')
                else:
                    dec = bytes(input[shifted:i]) + b'=' * ((4 - (i - shifted)) % 4)
                    try:
                        utf16 = base64.b64decode(dec, altchars=b'+,', validate=True)
                        output.append(utf16.decode('utf-16-be'))
                    except (binascii.Error, UnicodeDecodeError) as e:
                        if isinstance(e, binascii.Error):
                            reason = 'invalid Base64'
                        else:
                            reason = 'invalid UTF-16BE'
                        exc = UnicodeDecodeError('imap-utf-7', input, shifted - 1, i + 1,
                                                 reason)
                        replace, i = error(exc)
                        shifted = i
                        output.append(replace)
                        b64 = False
                        continue
                shifted = i + 1
                b64 = False
        else:
            if b == 0x26:  # '&'
                output.append(codecs.decode(input[shifted:i], 'ascii'))
                shifted = i + 1
                b64 = True
            if b < 0x20 or b > 0x7e:
                output.append(codecs.decode(input[shifted:i], 'ascii'))
                exc = UnicodeDecodeError('imap-utf-7', input, i, i + 1,
                                         'character must be Base64 encoded')
                replace, i = error(exc)
                shifted = i
                output.append(replace)
                continue
        i += 1
    if b64:
        exc = UnicodeDecodeError('imap-utf-7', input, len(input), len(input),
                                 'input does not end in US-ASCII')
        replace, cont = error(exc)
        output.append(replace)
    else:
        output.append(codecs.decode(input[shifted:], 'ascii'))
    return ''.join(output), len(input)


def _search_function(name):
    if name.replace('_', '-') == 'imap-utf-7':
        return codecs.CodecInfo(imap_utf7_encode, imap_utf7_decode, name='imap-utf-7')


codecs.register(_search_function)
