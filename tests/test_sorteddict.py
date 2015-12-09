import unittest

import molino.sorteddict
from molino.sorteddict import SortedDict, _RBTree, _RBNode, _RED, _BLACK


molino.sorteddict._CHECK_INVARIANTS = True


class TestSortedDict(unittest.TestCase):
    def setUp(self):
        self.dict = SortedDict()

    def test_empty(self):
        with self.assertRaises(KeyError):
            self.dict['a']
        with self.assertRaises(KeyError):
            del self.dict['a']
        self.assertEqual(len(self.dict), 0)
        self.assertEqual(list(self.dict), [])
        self.assertRaises(IndexError, self.dict.min_key)
        self.assertRaises(IndexError, self.dict.max_key)
        self.assertRaises(IndexError, self.dict.max_value)
        self.assertRaises(IndexError, self.dict.min_value)
        self.assertRaises(IndexError, self.dict.next_key, 'a')
        self.assertRaises(IndexError, self.dict.prev_key, 'a')
        self.assertRaises(KeyError, self.dict.index, 'a')
        self.assertRaises(IndexError, self.dict.ith_key, 0)
        self.assertRaises(IndexError, self.dict.ith_key, -1)
        self.assertRaises(IndexError, self.dict.ith_value, 0)
        self.assertRaises(IndexError, self.dict.ith_value, -1)
        self.assertRaises(IndexError, self.dict.ith_item, 0)
        self.assertRaises(IndexError, self.dict.ith_item, -1)

    def test_insert_overwrite(self):
        self.dict['a'] = 1
        self.assertEqual(self.dict['a'], 1)
        self.dict['a'] = 2
        self.assertEqual(self.dict['a'], 2)
        self.assertEqual(list(self.dict), ['a'])

    def _test_insert(self, keys, sort_key=None):
        if sort_key:
            self.dict = SortedDict(sort_key)
        for i, key in enumerate(keys):
            self.dict[key] = str(key)
            sorted_keys = sorted(keys[:i + 1], key=sort_key)
            for key2 in keys[:i + 1]:
                self.assertEqual(self.dict[key2], str(key2))
                index = sorted_keys.index(key2)
                self.assertEqual(self.dict.index(key2), index)
                self.assertEqual(self.dict.ith_item(index), (key2, str(key2)))
            self.assertEqual(list(self.dict), sorted_keys)
            self.assertEqual(len(self.dict), i + 1)
            self.assertEqual(self.dict.min_key(), sorted_keys[0])
            self.assertEqual(self.dict.min_value(), str(sorted_keys[0]))
            self.assertEqual(self.dict.ith_key(0), sorted_keys[0])
            self.assertEqual(self.dict.ith_value(0), str(sorted_keys[0]))
            self.assertEqual(self.dict.max_key(), sorted_keys[-1])
            self.assertEqual(self.dict.max_value(), str(sorted_keys[-1]))
            self.assertEqual(self.dict.ith_key(-1), sorted_keys[-1])
            self.assertEqual(self.dict.ith_value(-1), str(sorted_keys[-1]))

    def test_insert_ascending(self):
        self._test_insert(list(range(10)))

    def test_insert_descending(self):
        self._test_insert(list(range(9, -1, -1)))

    def test_insert_alternating_right(self):
        self._test_insert([0, 1, -1, 2, -2, 3, -3, 4, -4])

    def test_insert_alternating_left(self):
        self._test_insert([0, -1, 1, -2, 2, -3, 3, -4, 4])

    def test_insert_example(self):
        self._test_insert([11, 2, 14, 1, 15, 7, 5, 8, 4])

    def test_insert_example_negative(self):
        self._test_insert([11, 2, 14, 1, 15, 7, 5, 8, 4], lambda key: -key)

    def _test_delete(self, keys, del_keys, sort_key=None):
        if sort_key:
            self.dict = SortedDict(sort_key)
        for key in keys:
            self.dict[key] = str(key)
        sorted_keys = sorted(keys, key=sort_key)
        for key in del_keys:
            del self.dict[key]
            sorted_keys.remove(key)
        self.assertEqual(list(self.dict), sorted_keys)

    def test_delete_ascending(self):
        self._test_delete(list(range(10)), list(range(10)))

    def test_delete_descending(self):
        self._test_delete(list(range(10)), list(range(9, -1, -1)))

    def test_delete_alternating_right(self):
        l = [0, 1, -1, 2, -2, 3, -3, 4, -4]
        self._test_delete(list(range(-4, 5)), l)

    def test_delete_alternating_left(self):
        l = [0, -1, 1, -2, 2, -3, 3, -4, 4]
        self._test_delete(list(range(-4, 5)), l)

    def test_delete_example(self):
        l = [11, 2, 14, 1, 15, 7, 5, 8, 4]
        self._test_delete(l, l)

    def test_delete_example_negative(self):
        l = [11, 2, 14, 1, 15, 7, 5, 8, 4]
        self._test_delete(l, l, lambda key: -key)

    def test_iters(self):
        self.dict.update({1: 'b', 2: 'a'})
        self.assertEqual(list(self.dict.keys()), [1, 2])
        self.assertEqual(list(self.dict.values()), ['b', 'a'])
        self.assertEqual(list(self.dict.items()), [(1, 'b'), (2, 'a')])

    def test_clear(self):
        self.dict.update({1: 'b', 2: 'a'})
        self.dict.clear()
        self.assertEqual(len(self.dict), 0)
        self.assertEqual(list(self.dict.keys()), [])
        self.assertEqual(list(self.dict.values()), [])
        self.assertEqual(list(self.dict.items()), [])

    def test_resort(self):
        self.dict.update({1: 'b', 2: 'a'})
        self.dict.resort(lambda key: -key)
        self.assertEqual(list(self.dict.keys()), [2, 1])
        self.assertEqual(list(self.dict.values()), ['a', 'b'])
        self.assertEqual(list(self.dict.items()), [(2, 'a'), (1, 'b')])
        self.assertRaises(ValueError, self.dict.resort, lambda key: 0)

    def test_next_key(self):
        l = [11, 2, 14, 1, 15, 7, 5, 8, 4]
        for key in l:
            self.dict[key] = str(key)
        for i in range(min(l) - 1, max(l)):
            self.assertEqual(self.dict.next_key(i), sorted(x for x in l if x > i)[0])
        self.assertRaises(IndexError, self.dict.next_key, max(l))

    def test_next_key_negative(self):
        self.dict = SortedDict(lambda key: -key)
        l = [11, 2, 14, 1, 15, 7, 5, 8, 4]
        for key in l:
            self.dict[key] = str(key)
        for i in range(min(l) + 1, max(l) + 2):
            self.assertEqual(self.dict.next_key(i), sorted(x for x in l if x < i)[-1])
        self.assertRaises(IndexError, self.dict.next_key, min(l))

    def test_prev_key(self):
        l = [11, 2, 14, 1, 15, 7, 5, 8, 4]
        for key in l:
            self.dict[key] = str(key)
        for i in range(min(l) + 1, max(l) + 2):
            self.assertEqual(self.dict.prev_key(i), sorted(x for x in l if x < i)[-1])
        self.assertRaises(IndexError, self.dict.prev_key, min(l))

    def test_prev_key_negative(self):
        self.dict = SortedDict(lambda key: -key)
        l = [11, 2, 14, 1, 15, 7, 5, 8, 4]
        for key in l:
            self.dict[key] = str(key)
        for i in range(min(l) - 1, max(l)):
            self.assertEqual(self.dict.prev_key(i), sorted(x for x in l if x > i)[0])
        self.assertRaises(IndexError, self.dict.prev_key, max(l))


class TestRBTree(unittest.TestCase):
    """
    This tests the red-black tree implementation at a fine-grained level based
    on the discussion in Introduction to Algorithms, 3rd edition (CLRS). The
    properties of a red-black tree are:

    1. Every node is either red or black.
    2. The root is black.
    3. Every leaf (NIL) is black.
    4. If a node is red, then both its children are black.
    5. For each node, all simple paths from the node to descendant leaves
    contain the same number of black nodes.
    """

    def setUp(self):
        self.rb = _RBTree()

    def test_first_insert(self):
        # When a node is inserted, it is colored red. If it is the first node
        # to be inserted, then it will violate property 4.
        self.rb.insert(_RBNode('A', None, None))
        self.rb.check_invariants()
        self.assertEqual(self.rb.root.key, 'A')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left, self.rb.nil)
        self.assertEqual(self.rb.root.right, self.rb.nil)

    def test_insert_fixup_case_1(self):
        # Case 1 on page 319: z's uncle y is red.
        self.rb.insert(_RBNode('C', None, None))
        self.rb.check_invariants()
        self.rb.insert(_RBNode('A', None, None))
        self.rb.check_invariants()
        self.rb.insert(_RBNode('D', None, None))
        self.rb.check_invariants()

        r"""
        The tree should look like
           C (B)
          / \
         /   \
        A (R) D (R)
        """
        self.assertEqual(self.rb.root.key, 'C')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _RED)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'D')
        self.assertEqual(self.rb.root.right.color, _RED)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)

        self.rb.insert(_RBNode('B', None, None))
        self.rb.check_invariants()

        r"""
        Now the tree should look like
           C (B)
          / \
         /   \
        A (B) D (B)
         \
          B (R)
        """
        self.assertEqual(self.rb.root.key, 'C')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _BLACK)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right.key, 'B')
        self.assertEqual(self.rb.root.left.right.color, _RED)
        self.assertEqual(self.rb.root.left.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'D')
        self.assertEqual(self.rb.root.right.color, _BLACK)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)

    def test_insert_fixup_case_1_mirror(self):
        # Mirror of case 1 on page 319.
        self.rb.insert(_RBNode('B', None, None))
        self.rb.check_invariants()
        self.rb.insert(_RBNode('A', None, None))
        self.rb.check_invariants()
        self.rb.insert(_RBNode('C', None, None))
        self.rb.check_invariants()

        r"""
        The tree should look like
           B (B)
          / \
         /   \
        A (R) C (R)
        """
        self.assertEqual(self.rb.root.key, 'B')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _RED)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'C')
        self.assertEqual(self.rb.root.right.color, _RED)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)

        self.rb.insert(_RBNode('D', None, None))
        self.rb.check_invariants()

        r"""
        Now the tree should look like
           B (B)
          / \
         /   \
        A (B) C (B)
               \
                D (R)
        """
        self.assertEqual(self.rb.root.key, 'B')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _BLACK)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'C')
        self.assertEqual(self.rb.root.right.color, _BLACK)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right.key, 'D')
        self.assertEqual(self.rb.root.right.right.color, _RED)
        self.assertEqual(self.rb.root.right.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right.right, self.rb.nil)

    def test_insert_fixup_cases_2_and_3(self):
        # Case 2 on page 320: z's uncle y is black and z is a right child.
        # Case 3 on page 320: z's uncle y is black and z is a left child.
        # Case 2 falls through to case 3.

        self.rb.insert(_RBNode('C', None, None))
        self.rb.check_invariants()
        self.rb.insert(_RBNode('A', None, None))
        self.rb.check_invariants()

        r"""
        The tree should look like
          C (B)
         /
        A (R)
        """
        self.assertEqual(self.rb.root.key, 'C')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _RED)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right, self.rb.nil)

        self.rb.insert(_RBNode('B', None, None))
        self.rb.check_invariants()

        r"""
        Now the tree should look like
           B (B)
          / \
         /   \
        A (R) C (R)
        """
        self.assertEqual(self.rb.root.key, 'B')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _RED)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'C')
        self.assertEqual(self.rb.root.right.color, _RED)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)

    def test_insert_fixup_cases_2_and_3_mirror(self):
        # Mirror of cases 2 and 3 on page 320.

        self.rb.insert(_RBNode('A', None, None))
        self.rb.check_invariants()
        self.rb.insert(_RBNode('C', None, None))
        self.rb.check_invariants()

        r"""
        The tree should look like
        A (B)
         \
          C (R)
        """
        self.assertEqual(self.rb.root.key, 'A')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'C')
        self.assertEqual(self.rb.root.right.color, _RED)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)

        self.rb.insert(_RBNode('B', None, None))
        self.rb.check_invariants()

        r"""
        Now the tree should look like
           B (B)
          / \
         /   \
        A (R) C (R)
        """
        self.assertEqual(self.rb.root.key, 'B')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _RED)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'C')
        self.assertEqual(self.rb.root.right.color, _RED)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)

    def test_delete_fixup_cases_1_and_2(self):
        # Case 1 on page 327: x's sibling w is red.
        # Case 2 on page 328: x's sibling w is black, and both of w's children
        # are black.
        # Case 1 can fall through to case 2, 3, or 4. Here we fall through to
        # case 2.

        r"""
        Construct the tree
           B (B)
          / \
         /   \
        A (B) D (R)
             / \
            /   \
           C (B) E(B)
        """
        self.rb.root = _RBNode('B', None, None)
        self.rb.root.p = self.rb.nil
        self.rb.root.color = _BLACK
        self.rb.root.len = 5

        self.rb.root.left = _RBNode('A', None, None)
        self.rb.root.left.p = self.rb.root
        self.rb.root.left.color = _BLACK
        self.rb.root.left.len = 1
        self.rb.root.left.left = self.rb.nil
        self.rb.root.left.right = self.rb.nil

        self.rb.root.right = _RBNode('D', None, None)
        self.rb.root.right.p = self.rb.root
        self.rb.root.right.color = _RED
        self.rb.root.right.len = 3

        self.rb.root.right.left = _RBNode('C', None, None)
        self.rb.root.right.left.p = self.rb.root.right
        self.rb.root.right.left.color = _BLACK
        self.rb.root.right.left.len = 1
        self.rb.root.right.left.left = self.rb.nil
        self.rb.root.right.left.right = self.rb.nil

        self.rb.root.right.right = _RBNode('E', None, None)
        self.rb.root.right.right.p = self.rb.root.right
        self.rb.root.right.right.color = _BLACK
        self.rb.root.right.right.len = 1
        self.rb.root.right.right.left = self.rb.nil
        self.rb.root.right.right.right = self.rb.nil

        self.rb.check_invariants()

        self.rb.delete(self.rb.root.left)
        self.rb.check_invariants()

        r"""
        Now the tree should look like
           D (B)
          / \
         /   \
        B (B) E (B)
         \
          \
           C (R)
        """
        self.assertEqual(self.rb.root.key, 'D')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'B')
        self.assertEqual(self.rb.root.left.color, _BLACK)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right.key, 'C')
        self.assertEqual(self.rb.root.left.right.color, _RED)
        self.assertEqual(self.rb.root.left.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'E')
        self.assertEqual(self.rb.root.right.color, _BLACK)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)

    def test_delete_fixup_cases_1_and_2_mirror(self):
        # Mirror of cases 1 and 2 on pages 327 and 328.

        r"""
        Construct the tree
              D (B)
             / \
            /   \
           B (R) E (B)
          / \
         /   \
        A (B) C(B)
        """
        self.rb.root = _RBNode('D', None, None)
        self.rb.root.p = self.rb.nil
        self.rb.root.color = _BLACK
        self.rb.root.len = 5

        self.rb.root.left = _RBNode('B', None, None)
        self.rb.root.left.p = self.rb.root
        self.rb.root.left.color = _RED
        self.rb.root.left.len = 3

        self.rb.root.left.left = _RBNode('A', None, None)
        self.rb.root.left.left.p = self.rb.root.left
        self.rb.root.left.left.color = _BLACK
        self.rb.root.left.left.len = 1
        self.rb.root.left.left.left = self.rb.nil
        self.rb.root.left.left.right = self.rb.nil

        self.rb.root.left.right = _RBNode('C', None, None)
        self.rb.root.left.right.p = self.rb.root.left
        self.rb.root.left.right.color = _BLACK
        self.rb.root.left.right.len = 1
        self.rb.root.left.right.left = self.rb.nil
        self.rb.root.left.right.right = self.rb.nil

        self.rb.root.right = _RBNode('E', None, None)
        self.rb.root.right.p = self.rb.root
        self.rb.root.right.color = _BLACK
        self.rb.root.right.len = 1
        self.rb.root.right.left = self.rb.nil
        self.rb.root.right.right = self.rb.nil

        self.rb.check_invariants()

        self.rb.delete(self.rb.root.right)
        self.rb.check_invariants()

        r"""
        Now the tree should look like
           B (B)
          / \
         /   \
        A (B) D (B)
             /
            /
           C (R)
        """
        self.assertEqual(self.rb.root.key, 'B')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _BLACK)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'D')
        self.assertEqual(self.rb.root.right.color, _BLACK)
        self.assertEqual(self.rb.root.right.left.key, 'C')
        self.assertEqual(self.rb.root.right.left.color, _RED)
        self.assertEqual(self.rb.root.right.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)

    def test_delete_fixup_cases_3_and_4(self):
        # Case 3 on page 328: x's sibling w is black, w's left child is red,
        # and w's right child is black.
        # Case 4 on page 328: x's sibling w is black, and w's right child is
        # red.
        # Case 3 falls through to case 4.

        r"""
        Contruct the tree
           B (B)
          / \
         /   \
        A (B) D (B)
             /
            /
           C (R)
        """
        self.rb.root = _RBNode('B', None, None)
        self.rb.root.p = self.rb.nil
        self.rb.root.color = _BLACK
        self.rb.root.len = 4

        self.rb.root.left = _RBNode('A', None, None)
        self.rb.root.left.p = self.rb.root
        self.rb.root.left.color = _BLACK
        self.rb.root.left.len = 1
        self.rb.root.left.left = self.rb.nil
        self.rb.root.left.right = self.rb.nil

        self.rb.root.right = _RBNode('D', None, None)
        self.rb.root.right.p = self.rb.root
        self.rb.root.right.color = _BLACK
        self.rb.root.right.len = 2
        self.rb.root.right.right = self.rb.nil

        self.rb.root.right.left = _RBNode('C', None, None)
        self.rb.root.right.left.p = self.rb.root.right
        self.rb.root.right.left.color = _RED
        self.rb.root.right.left.len = 1
        self.rb.root.right.left.left = self.rb.nil
        self.rb.root.right.left.right = self.rb.nil

        self.rb.check_invariants()

        self.rb.delete(self.rb.root.left)
        self.rb.check_invariants()

        r"""
        Now the tree should look like
           C (B)
          / \
         /   \
        B (B) D (B)
        """

        self.assertEqual(self.rb.root.key, 'C')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'B')
        self.assertEqual(self.rb.root.left.color, _BLACK)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'D')
        self.assertEqual(self.rb.root.right.color, _BLACK)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)

    def test_delete_fixup_cases_3_and_4_mirror(self):
        # Mirror of cases 3 and 4 on page 328.

        r"""
        Contruct the tree
           C (B)
          / \
         /   \
        A (B) D (B)
         \
          \
           B (R)
        """
        self.rb.root = _RBNode('C', None, None)
        self.rb.root.p = self.rb.nil
        self.rb.root.color = _BLACK
        self.rb.root.len = 4

        self.rb.root.left = _RBNode('A', None, None)
        self.rb.root.left.p = self.rb.root
        self.rb.root.left.color = _BLACK
        self.rb.root.left.len = 2
        self.rb.root.left.left = self.rb.nil

        self.rb.root.left.right = _RBNode('B', None, None)
        self.rb.root.left.right.p = self.rb.root.left
        self.rb.root.left.right.color = _RED
        self.rb.root.left.right.len = 1
        self.rb.root.left.right.left = self.rb.nil
        self.rb.root.left.right.right = self.rb.nil

        self.rb.root.right = _RBNode('D', None, None)
        self.rb.root.right.p = self.rb.root
        self.rb.root.right.color = _BLACK
        self.rb.root.right.len = 1
        self.rb.root.right.left = self.rb.nil
        self.rb.root.right.right = self.rb.nil

        self.rb.check_invariants()

        self.rb.delete(self.rb.root.right)
        self.rb.check_invariants()

        r"""
        Now the tree should look like
           B (B)
          / \
         /   \
        A (B) C (B)
        """

        self.assertEqual(self.rb.root.key, 'B')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _BLACK)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'C')
        self.assertEqual(self.rb.root.right.color, _BLACK)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)

    def test_delete_no_left_child(self):
        r"""
        Contruct the tree
        B (B)
         \
          C (R)
        """
        self.rb.root = _RBNode('B', None, None)
        self.rb.root.p = self.rb.nil
        self.rb.root.color = _BLACK
        self.rb.root.len = 2
        self.rb.root.left = self.rb.nil

        self.rb.root.right = _RBNode('C', None, None)
        self.rb.root.right.p = self.rb.root
        self.rb.root.right.color = _RED
        self.rb.root.right.len = 1
        self.rb.root.right.left = self.rb.nil
        self.rb.root.right.right = self.rb.nil

        self.rb.check_invariants()

        self.rb.delete(self.rb.root)
        self.rb.check_invariants()

        r"""
        Now the tree should look like
        C (B)
        """
        self.assertEqual(self.rb.root.key, 'C')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left, self.rb.nil)
        self.assertEqual(self.rb.root.right, self.rb.nil)

    def test_delete_no_right_child(self):
        r"""
        Contruct the tree
          B (B)
         /
        A(R)
        """
        self.rb.root = _RBNode('B', None, None)
        self.rb.root.p = self.rb.nil
        self.rb.root.color = _BLACK
        self.rb.root.len = 2
        self.rb.root.right = self.rb.nil

        self.rb.root.left = _RBNode('A', None, None)
        self.rb.root.left.p = self.rb.root
        self.rb.root.left.color = _RED
        self.rb.root.left.len = 1
        self.rb.root.left.left = self.rb.nil
        self.rb.root.left.right = self.rb.nil

        self.rb.check_invariants()

        self.rb.delete(self.rb.root)
        self.rb.check_invariants()

        r"""
        Now the tree should look like
        A (B)
        """
        self.assertEqual(self.rb.root.key, 'A')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left, self.rb.nil)
        self.assertEqual(self.rb.root.right, self.rb.nil)

    def test_delete_both_children(self):
        r"""
        Construct the tree
           B (B)
          / \
         /   \
        A (R) C (R)
        """
        self.rb.root = _RBNode('B', None, None)
        self.rb.root.p = self.rb.nil
        self.rb.root.color = _BLACK
        self.rb.root.len = 3

        self.rb.root.left = _RBNode('A', None, None)
        self.rb.root.left.p = self.rb.root
        self.rb.root.left.color = _RED
        self.rb.root.left.len = 1
        self.rb.root.left.left = self.rb.nil
        self.rb.root.left.right = self.rb.nil

        self.rb.root.right = _RBNode('C', None, None)
        self.rb.root.right.p = self.rb.root
        self.rb.root.right.color = _RED
        self.rb.root.right.len = 1
        self.rb.root.right.left = self.rb.nil
        self.rb.root.right.right = self.rb.nil

        self.rb.check_invariants()

        self.rb.delete(self.rb.root)
        self.rb.check_invariants()

        r"""
        Now the tree should look like
          C (B)
         /
        A (R)
        """
        self.assertEqual(self.rb.root.key, 'C')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.right, self.rb.nil)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _RED)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)

    def test_delete_both_children_transplant(self):
        r"""
        Construct the tree
           B (B)
          / \
         /   \
        A (B) D (B)
             /
            /
           C (R)
        """
        self.rb.root = _RBNode('B', None, None)
        self.rb.root.p = self.rb.nil
        self.rb.root.color = _BLACK
        self.rb.root.len = 4

        self.rb.root.left = _RBNode('A', None, None)
        self.rb.root.left.p = self.rb.root
        self.rb.root.left.color = _BLACK
        self.rb.root.left.len = 1
        self.rb.root.left.left = self.rb.nil
        self.rb.root.left.right = self.rb.nil

        self.rb.root.right = _RBNode('D', None, None)
        self.rb.root.right.p = self.rb.root
        self.rb.root.right.color = _BLACK
        self.rb.root.right.len = 2
        self.rb.root.right.right = self.rb.nil

        self.rb.root.right.left = _RBNode('C', None, None)
        self.rb.root.right.left.p = self.rb.root.right
        self.rb.root.right.left.color = _RED
        self.rb.root.right.left.len = 1
        self.rb.root.right.left.left = self.rb.nil
        self.rb.root.right.left.right = self.rb.nil

        self.rb.check_invariants()

        self.rb.delete(self.rb.root)
        self.rb.check_invariants()

        r"""
        Now the tree should look like
           C (B)
          / \
         /   \
        A (B) D (B)
        """
        self.assertEqual(self.rb.root.key, 'C')
        self.assertEqual(self.rb.root.color, _BLACK)
        self.assertEqual(self.rb.root.left.key, 'A')
        self.assertEqual(self.rb.root.left.color, _BLACK)
        self.assertEqual(self.rb.root.left.left, self.rb.nil)
        self.assertEqual(self.rb.root.left.right, self.rb.nil)
        self.assertEqual(self.rb.root.right.key, 'D')
        self.assertEqual(self.rb.root.right.color, _BLACK)
        self.assertEqual(self.rb.root.right.left, self.rb.nil)
        self.assertEqual(self.rb.root.right.right, self.rb.nil)
