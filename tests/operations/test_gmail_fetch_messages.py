import unittest

from molino.imap.parser import *
import molino.imap as imap
import molino.model as model
from molino.operations import GmailFetchMessagesOperation, _IMAPSelectedState
import tests
from tests.operations import TestIMAPOperation, TestServer, op_callback


class TestGmailFetchMessagesOperation(unittest.TestCase):
    def setUp(self):
        self.test_op = TestIMAPOperation()
        self.server = TestServer(self.test_op)
        self.test_op.server_callback = self.server.handle_cmd
        def handle_fetch(resp):
            return _IMAPSelectedState._handle_fetch(self.test_op, resp)
        self.test_op.register_untagged('FETCH', handle_fetch)

    def _check_model(self):
        expected_mailbox = self.server.model.get_mailbox(self.server.selected)
        mailbox = self.test_op._model.get_mailbox(self.server.selected)
        expected_uids = {uid for uid, message in expected_mailbox.messages()}
        uids = {uid for uid, message in mailbox.messages()}
        for uid, expected_message in expected_mailbox.messages():
            message = mailbox.get_message(uid)
            self.assertEqual(message.id, expected_message.id)
            self.assertEqual(message.envelope, expected_message.envelope)
            self.assertEqual(message.flags, expected_message.flags)

    def test_ok(self):
        self.server.selected = b'INBOX'
        mailbox = self.server.model.get_mailbox(self.server.selected)
        seq_set = [(1, len(set(mailbox.messages())))]
        self.test_op._mailbox = self.test_op._model.get_mailbox(self.server.selected)
        self.test_op._mailbox.uids = [None] * (len(set(mailbox.messages())) + 1)
        self.op = GmailFetchMessagesOperation(self.test_op, seq_set)
        self.op.callback = op_callback()
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self._check_model()
        self.assertTrue(self.test_op.is_done())

    def test_old_uids(self):
        self.server.selected = b'INBOX'
        mailbox = self.server.model.get_mailbox(self.server.selected)
        seq_set = [(1, len(set(mailbox.messages())))]
        test_mailbox = self.test_op._model.get_mailbox(self.server.selected)
        uid, message = list(mailbox.messages())[0]
        test_message = model.Message(self.test_op._model, message.id)
        test_message.envelope = message.envelope
        test_message.flags = {'\\Invalid'}
        test_mailbox.add_message(uid, test_message)
        self.test_op._mailbox = test_mailbox
        self.test_op._mailbox.uids = [None] * (len(set(mailbox.messages())) + 1)
        self.op = GmailFetchMessagesOperation(self.test_op, seq_set)
        self.op.callback = op_callback()
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self._check_model()
        self.assertTrue(self.test_op.is_done())

    def test_bad_1(self):
        self.test_op._mailbox = self.test_op._model.get_mailbox(b'INBOX')
        self.op = GmailFetchMessagesOperation(self.test_op, [1])
        self.op.callback = op_callback()
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self.assertIsNotNone(self.op.bad)
        self.assertTrue(self.test_op.is_done())
