import unittest

from molino.imap.parser import *
from molino.operations import IMAPNotAuthenticatedState
import tests
from tests.operations import TestIMAPOperation, TestServer, op_callback


class TestIMAPNotAuthenticatedState(unittest.TestCase):
    def setUp(self):
        self.test_op = TestIMAPOperation()
        self.server = TestServer(self.test_op)
        self.test_op.server_callback = self.server.handle_cmd

        self.op = IMAPNotAuthenticatedState(self.test_op, 'user', 'password')
        self.op.callback = op_callback()

    def test_ok(self):
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self.assertTrue(self.op.authed)
        self.assertTrue(self.test_op.is_done())

    def test_incorrect_password(self):
        self.server.correct_password = '12345'
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self.assertFalse(self.op.authed)
        self.assertTrue(self.test_op.is_done())

    def test_login_disabled(self):
        self.server.capabilities.add('LOGINDISABLED')
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self.assertFalse(self.op.authed)
        self.assertTrue(self.test_op.is_done())

    def test_not_imap4rev1(self):
        self.server.capabilities.remove('IMAP4rev1')
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self.assertFalse(self.op.authed)
        self.assertTrue(self.test_op.is_done())
