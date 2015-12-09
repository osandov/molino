import unittest

from molino.imap.parser import *
from molino.operations import IMAPPopulateUnseenOperation
import tests
from tests.operations import TestIMAPOperation, TestServer, op_callback


class TestPopulateUnseenOperation(unittest.TestCase):
    def setUp(self):
        self.test_op = TestIMAPOperation()
        self.server = TestServer(self.test_op)
        self.test_op.server_callback = self.server.handle_cmd
        self.op = IMAPPopulateUnseenOperation(self.test_op)
        self.op.callback = op_callback()

    def test_ok(self):
        self.server.selected = b'INBOX'
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self.assertEqual(self.op.unseen, self.server.model.get_mailbox(self.server.selected).unseen)
        self.assertTrue(self.test_op.is_done())

    def test_bad(self):
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self.assertIsNotNone(self.op.bad)
        self.assertTrue(self.test_op.is_done())
