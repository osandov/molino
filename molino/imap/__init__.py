import array


def decode_mailbox_name(name):
    try:
        return name.decode('imap-utf-7')
    except UnicodeDecodeError:
        # If the mailbox isn't valid modified UTF-7, assume it's UTF-8 and
        # be robust to errors.
        return name.decode('utf-8', errors='backslashreplace')


def sequence_set(ids):
    """
    Convert a list of IDs into a sequence set, that is, a list comprising
    numbers and pairs of numbers representing a range, inclusive on both ends.
    For example, the list [1, 3, 4, 5, 7] would become [1, (3, 5), 7].

    ids - iterable of ints
    """
    ids = sorted(ids)
    if not ids:
        return []
    seq_set = []
    start = end = ids[0]
    for id in ids[1:]:
        if id == end + 1:
            end = id
        else:
            if start == end:
                seq_set.append(start)
            else:
                seq_set.append((start, end))
            start = end = id
    if start == end:
        seq_set.append(start)
    else:
        seq_set.append((start, end))
    return seq_set


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
