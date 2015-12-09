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
