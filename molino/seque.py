class SequenceQueue:
    def __init__(self):
        self._list = []
        self._len = 0

    def get(self, n):
        l = []
        while n > 0 and self._list:
            first, last = self._list.pop()
            self._len -= last - first + 1
            if last - first + 1 > n:
                old_first = first
                first = last - (n - 1)
                self._list.append((old_first, first - 1))
                self._len += (first - 1) - old_first + 1
            assert last >= first
            l.append((first, last))
            n -= last - first + 1
            assert n >= 0
        return l

    def put(self, first, last):
        assert first <= last
        assert not self._list or first > self._list[-1][1]
        if self._list and self._list[-1][1] + 1 == first:
            self._list[-1] = (self._list[-1][0], last)
        else:
            self._list.append((first, last))
        self._len += last - first + 1

    def delete(self, index):
        # This is O(n) where n is the number of ranges in the list, but this is
        # expected to be small. For the fetching use case, he only way n could
        # end up large would be if EXISTS keep coming in after the previous one
        # has been partially fetched.
        for i in range(len(self._list) - 1, -1, -1):
            first, last = self._list[i]
            if index < first:
                self._list[i] = (first - 1, last - 1)
            elif index == first == last:
                del self._list[i]
                self._len -= 1
                break
            elif index <= last:
                self._list[i] = (first, last - 1)
                self._len -= 1
            else:
                break

    def __len__(self):
        return self._len
