import unittest

from molino.imap import sequence_set


class TestFormat(unittest.TestCase):
    def test_sequence_set(self):
        self.assertEqual(sequence_set([]), [])
        self.assertEqual(sequence_set([1, 2, 3]), [(1, 3)])
        self.assertEqual(sequence_set([1, 3, 4, 5, 7]), [1, (3, 5), 7])
        self.assertEqual(sequence_set([1, 3, 4, 5, 6, 7]), [1, (3, 7)])
        self.assertEqual(sequence_set([1, 2, 3, 4, 5, 7]), [(1, 5), 7])
        self.assertEqual(sequence_set([1, 3, 5, 7]), [1, 3, 5, 7])
