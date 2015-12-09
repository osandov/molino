import collections.abc


_CHECK_INVARIANTS = False


class _RBNode:
    __slots__ = ['key', 'old_key', 'value', 'color', 'p', 'left', 'right', 'len']

    def __init__(self, key, old_key, value):
        self.key = key
        self.old_key = old_key
        self.value = value
        self.color = None
        self.p = None
        self.left = None
        self.right = None
        self.len = 1


_BLACK = 0
_RED = 1


class _RBTree:
    def __init__(self):
        self.nil = _RBNode(None, None, None)
        self.nil.color = _BLACK
        self.nil.p = self.nil
        self.nil.left = self.nil
        self.nil.right = self.nil
        self.nil.len = 0
        self.root = self.nil

    def search(self, x, key):
        while x != self.nil:
            if key < x.key:
                x = x.left
            elif key > x.key:
                x = x.right
            else:
                break
        return x

    def insert(self, z):
        y = self.nil
        x = self.root
        while x != self.nil:
            y = x
            y.len += z.len
            if z.key < x.key:
                x = x.left
            else:
                x = x.right
        z.p = y
        if y == self.nil:
            self.root = z
        elif z.key < y.key:
            y.left = z
        else:
            y.right = z
        z.left = self.nil
        z.right = self.nil
        z.color = _RED
        self._insert_fixup(z)

    def _insert_fixup(self, z):
        while z.p.color == _RED:
            if z.p == z.p.p.left:
                y = z.p.p.right
                if y.color == _RED:
                    z.p.color = _BLACK
                    y.color = _BLACK
                    z.p.p.color = _RED
                    z = z.p.p
                else:
                    if z == z.p.right:
                        z = z.p
                        self._left_rotate(z)
                    z.p.color = _BLACK
                    z.p.p.color = _RED
                    self._right_rotate(z.p.p)
            else:
                y = z.p.p.left
                if y.color == _RED:
                    z.p.color = _BLACK
                    y.color = _BLACK
                    z.p.p.color = _RED
                    z = z.p.p
                else:
                    if z == z.p.left:
                        z = z.p
                        self._right_rotate(z)
                    z.p.color = _BLACK
                    z.p.p.color = _RED
                    self._left_rotate(z.p.p)
        self.root.color = _BLACK

    def _left_rotate(self, x):
        y = x.right
        x.right = y.left
        if y.left != self.nil:
            y.left.p = x
        y.p = x.p
        if x.p == self.nil:
            self.root = y
        elif x == x.p.left:
            x.p.left = y
        else:
            x.p.right = y
        y.left = x
        x.p = y
        x.len = 1 + x.left.len + x.right.len
        y.len = 1 + y.left.len + y.right.len

    def _right_rotate(self, x):
        y = x.left
        x.left = y.right
        if y.right != self.nil:
            y.right.p = x
        y.p = x.p
        if x.p == self.nil:
            self.root = y
        elif x == x.p.right:
            x.p.right = y
        else:
            x.p.left = y
        y.right = x
        x.p = y
        x.len = 1 + x.right.len + x.left.len
        y.len = 1 + y.right.len + y.left.len

    def delete(self, z):
        y = z
        y_original_color = y.color
        if z.left == self.nil:
            x = z.right
            self._transplant(z, z.right)
        elif z.right == self.nil:
            x = z.left
            self._transplant(z, z.left)
        else:
            y = self.minimum(z.right)
            y_original_color = y.color
            x = y.right
            if y.p == z:
                x.p = y
            else:
                self._transplant(y, y.right)
                y.right = z.right
                y.right.p = y
                y.len = 1 + y.left.len + y.right.len
            self._transplant(z, y)
            y.left = z.left
            y.left.p = y
            self._fixup_lens(y)
            y.color = z.color
        if y_original_color == _BLACK:
            self._delete_fixup(x)
        self.nil.p = self.nil

    def _transplant(self, u, v):
        if u.p == self.nil:
            self.root = v
        elif u == u.p.left:
            u.p.left = v
        else:
            u.p.right = v
        v.p = u.p
        self._fixup_lens(u.p)

    def _fixup_lens(self, x):
        while x != self.nil:
            x.len = 1 + x.left.len + x.right.len
            x = x.p

    def _delete_fixup(self, x):
        while x != self.root and x.color == _BLACK:
            if x == x.p.left:
                w = x.p.right
                if w.color == _RED:
                    w.color = _BLACK
                    x.p.color = _RED
                    self._left_rotate(x.p)
                    w = x.p.right
                if w.left.color == _BLACK and w.right.color == _BLACK:
                    w.color = _RED
                    x = x.p
                else:
                    if w.right.color == _BLACK:
                        w.left.color = _BLACK
                        w.color = _RED
                        self._right_rotate(w)
                        w = x.p.right
                    w.color = x.p.color
                    x.p.color = _BLACK
                    w.right.color = _BLACK
                    self._left_rotate(x.p)
                    x = self.root
            else:
                w = x.p.left
                if w.color == _RED:
                    w.color = _BLACK
                    x.p.color = _RED
                    self._right_rotate(x.p)
                    w = x.p.left
                if w.right.color == _BLACK and w.left.color == _BLACK:
                    w.color = _RED
                    x = x.p
                else:
                    if w.left.color == _BLACK:
                        w.right.color = _BLACK
                        w.color = _RED
                        self._left_rotate(w)
                        w = x.p.left
                    w.color = x.p.color
                    x.p.color = _BLACK
                    w.left.color = _BLACK
                    self._right_rotate(x.p)
                    x = self.root
        x.color = _BLACK

    def clear(self):
        self.root = self.nil
        self.root = self.nil

    def minimum(self, x):
        while x.left != self.nil:
            x = x.left
        return x

    def maximum(self, x):
        while x.right != self.nil:
            x = x.right
        return x

    def successor(self, x):
        if x.right != self.nil:
            return self.minimum(x.right)
        y = x.p
        while y != self.nil and x == y.right:
            x = y
            y = y.p
        return y

    def predecessor(self, x):
        if x.left != self.nil:
            return self.maximum(x.left)
        y = x.p
        while y != self.nil and x == y.left:
            x = y
            y = y.p
        return y

    def ith(self, x, i):
        if i < 0:
            i += x.len
        if i < 0 or i >= x.len:
            raise IndexError()
        x = self.root
        while True:
            if i < x.left.len:
                x = x.left
            elif i > x.left.len:
                i -= x.left.len + 1
                x = x.right
            else:
                return x

    def index(self, x):
        assert x != self.nil
        i = x.left.len
        while x.p != self.nil:
            if x == x.p.right:
                i += x.p.left.len + 1
            x = x.p
        return i

    def traverse_inorder(self, x):
        if x != self.nil:
            yield x
            yield from self.traverse_inorder(x.left)
            yield from self.traverse_inorder(x.right)

    def nearest_gt(self, x, key):
        if x == self.nil:
            return self.nil
        while True:
            if key < x.key:
                if x.left == self.nil:
                    return x
                x = x.left
            elif key > x.key:
                if x.right == self.nil:
                    return self.successor(x)
                x = x.right
            else:
                return self.successor(x)

    def nearest_lt(self, x, key):
        if x == self.nil:
            return self.nil
        while True:
            if key < x.key:
                if x.left == self.nil:
                    return self.predecessor(x)
                x = x.left
            elif key > x.key:
                if x.right == self.nil:
                    return x
                x = x.right
            else:
                return self.predecessor(x)

    def check_invariants(self):
        if _CHECK_INVARIANTS:
            assert self.root.color == _BLACK
            assert self.root.p == self.nil
            assert self.nil.color == _BLACK
            assert self.nil.p == self.nil
            assert self.nil.left == self.nil
            assert self.nil.right == self.nil
            assert self.nil.len == 0
            self._check_tree(self.root)

    def _check_tree(self, x):
        assert x is not None

        if x == self.nil:
            return 0, 0

        # Is a binary search tree
        if x.left != self.nil:
            assert x.left.key < x.key
            assert x.left.p == x
        if x.right != self.nil:
            assert x.right.key > x.key
            assert x.right.p == x

        # If a node is red, both of its children are black
        if x.color == _RED:
            assert x.left.color == _BLACK
            assert x.right.color == _BLACK

        left_len, left_black_height = self._check_tree(x.left)
        right_len, right_black_height = self._check_tree(x.right)

        # Length is correct
        len = 1 + left_len + right_len
        assert x.len == len

        # Same number of black nodes in any path to NIL
        black_height = left_black_height + (1 if x.left.color == _BLACK else 0)
        black_height2 = right_black_height + (1 if x.right.color == _BLACK else 0)
        assert black_height == black_height2

        return len, black_height


class SortedDict(collections.abc.MutableMapping):
    def __init__(self, sort_key=None):
        self._rb_tree = _RBTree()
        self.sort_key = sort_key

    def __getitem__(self, key):
        if self.sort_key:
            key = self.sort_key(key)
        x = self._rb_tree.search(self._rb_tree.root, key)
        if x == self._rb_tree.nil:
            raise KeyError()
        return x.value

    def __setitem__(self, key, value):
        old_key = key
        if self.sort_key:
            key = self.sort_key(key)
        x = self._rb_tree.search(self._rb_tree.root, key)
        if x != self._rb_tree.nil:
            x.value = value
            return
        z = _RBNode(key, old_key, value)
        self._rb_tree.insert(z)
        self._rb_tree.check_invariants()

    def __delitem__(self, key):
        if self.sort_key:
            key = self.sort_key(key)
        z = self._rb_tree.search(self._rb_tree.root, key)
        if z == self._rb_tree.nil:
            raise KeyError()
        self._rb_tree.delete(z)
        self._rb_tree.check_invariants()

    def __iter__(self):
        x = self._rb_tree.minimum(self._rb_tree.root)
        while x != self._rb_tree.nil:
            yield x.old_key
            x = self._rb_tree.successor(x)

    def values(self):
        x = self._rb_tree.minimum(self._rb_tree.root)
        while x != self._rb_tree.nil:
            yield x.value
            x = self._rb_tree.successor(x)

    def items(self):
        x = self._rb_tree.minimum(self._rb_tree.root)
        while x != self._rb_tree.nil:
            yield (x.old_key, x.value)
            x = self._rb_tree.successor(x)

    def __len__(self):
        return self._rb_tree.root.len

    def clear(self):
        self._rb_tree.clear()

    def resort(self, sort_key):
        """
        Change the sort key for the dictionary. Raises ValueError if this
        results in any duplicate keys.
        """
        new_rb_tree = _RBTree()
        keys = set()
        for x in self._rb_tree.traverse_inorder(self._rb_tree.root):
            key = old_key = x.old_key
            if sort_key:
                key = sort_key(old_key)
            if key in keys:
                raise ValueError()
            keys.add(key)
            z = _RBNode(key, old_key, x.value)
            new_rb_tree.insert(z)
        new_rb_tree.check_invariants()
        self._rb_tree = new_rb_tree
        self.sort_key = sort_key

    def next_key(self, key):
        """
        Returns the smallest key in the dictionary greater than the given key.
        Raises IndexError if it is there is no such key.
        """
        if self.sort_key:
            key = self.sort_key(key)
        x = self._rb_tree.nearest_gt(self._rb_tree.root, key)
        if x == self._rb_tree.nil:
            raise IndexError()
        return x.old_key

    def prev_key(self, key):
        """
        Returns the largest key in the dictionary greater than the given key.
        Raises IndexError if it is there is no such key.
        """
        if self.sort_key:
            key = self.sort_key(key)
        x = self._rb_tree.nearest_lt(self._rb_tree.root, key)
        if x == self._rb_tree.nil:
            raise IndexError()
        return x.old_key

    def min_key(self):
        """
        Return the minimum key in the dictionary. Raises IndexError if the
        dictionary is empty.
        """
        x = self._rb_tree.minimum(self._rb_tree.root)
        if x == self._rb_tree.nil:
            raise IndexError()
        return x.old_key

    def min_value(self):
        """
        Return the value with the minimum key in the dictionary. Raises
        IndexError if the dictionary is empty.
        """
        x = self._rb_tree.minimum(self._rb_tree.root)
        if x == self._rb_tree.nil:
            raise IndexError()
        return x.value

    def max_key(self):
        """
        Return the value with the maximum key in the dictionary. Raises
        IndexError if the dictionary is empty.
        """
        x = self._rb_tree.maximum(self._rb_tree.root)
        if x == self._rb_tree.nil:
            raise IndexError()
        return x.old_key

    def max_value(self):
        """
        Return the value with the minimum key in the dictionary. Raises
        IndexError if the dictionary is empty.
        """
        x = self._rb_tree.maximum(self._rb_tree.root)
        if x == self._rb_tree.nil:
            raise IndexError()
        return x.value

    def ith_key(self, i):
        """
        Get the i-th key in the dictionary. Raises IndexError if the dictionary
        is empty or the index is out of range.
        """
        return self._rb_tree.ith(self._rb_tree.root, i).old_key

    def ith_value(self, i):
        """
        Get the value with the i-th key in the dictionary. Raises IndexError if
        the dictionary is empty or the index is out of range.
        """
        return self._rb_tree.ith(self._rb_tree.root, i).value

    def ith_item(self, i):
        """
        Get the item with the i-th key in the dictionary. Raises IndexError if
        the dictionary is empty or the index is out of range.
        """
        x = self._rb_tree.ith(self._rb_tree.root, i)
        return (x.old_key, x.value)

    def index(self, key):
        """
        Return the numerical index of the key in the dictionary. Raises
        KeyError if the key is not present.
        """
        if self.sort_key:
            key = self.sort_key(key)
        x = self._rb_tree.search(self._rb_tree.root, key)
        if x == self._rb_tree.nil:
            raise KeyError()
        return self._rb_tree.index(x)
