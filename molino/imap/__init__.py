import array


def decode_mailbox_name(name):
    try:
        return name.decode('imap-utf-7')
    except UnicodeDecodeError:
        # If the mailbox isn't valid modified UTF-7, assume it's UTF-8 and
        # be robust to errors.
        return name.decode('utf-8', errors='backslashreplace')


def seq_set_to_array(seq_set, dummy=False):
    seq_set.sort(key=lambda seq: seq if isinstance(seq, int) else seq[0])
    arr = array.array('L', [0] if dummy else [])
    for seq in seq_set:
        if isinstance(seq, int):
            arr.append(seq)
        else:
            arr.extend(range(seq[0], seq[1] + 1))
    return arr


def seq_set_to_set(seq_set):
    s = set()
    for seq in seq_set:
        if isinstance(seq, int):
            s.add(seq)
        else:
            s.update(range(seq[0], seq[1] + 1))
    return s
