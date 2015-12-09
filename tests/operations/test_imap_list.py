import unittest

from molino.imap.parser import *
from molino.operations import IMAPListOperation
import tests
from tests.operations import TestIMAPOperation, TestServer, op_callback


class TestIMAPListOperation(unittest.TestCase):
    def setUp(self):
        self.test_op = TestIMAPOperation()
        self.server = TestServer(self.test_op)
        self.test_op.server_callback = self.server.handle_cmd

    def _check_model(self):
        expected_names = {mailbox.name for mailbox in self.server.model.mailboxes()}
        names = {mailbox.name for mailbox in self.test_op._model.mailboxes()}
        self.assertEqual(names, expected_names)
        for expected in self.server.model.mailboxes():
            mailbox = self.test_op._model.get_mailbox(expected.name)
            self.assertEqual(mailbox.attributes, expected.attributes)
            self.assertEqual(mailbox.delimiter, expected.delimiter)
            self.assertEqual(mailbox.exists, expected.exists)
            self.assertEqual(mailbox.num_unseen(), expected.num_unseen())

    def test_list(self):
        self.op = IMAPListOperation(self.test_op)
        self.op.callback = op_callback()
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self._check_model()
        self.assertTrue(self.test_op.is_done())

    def test_list_status(self):
        self.server.capabilities.add('LIST-STATUS')
        self.test_op._capabilities = self.server.capabilities
        self.op = IMAPListOperation(self.test_op)
        self.op.callback = op_callback()
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self._check_model()
        self.assertTrue(self.test_op.is_done())

    def test_deleted_mailbox(self):
        self.test_op.inc_pending()

        self.op = IMAPListOperation(self.test_op)
        self.op.callback = op_callback()
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self._check_model()

        self.server.model.delete_mailbox(b'LKML')

        self.op = IMAPListOperation(self.test_op)
        self.op.callback = op_callback()
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)
        self._check_model()

        self.test_op.dec_pending()
        self.assertTrue(self.test_op.is_done())

    def test_list_status_selected(self):
        inbox = self.test_op._model.get_mailbox(b'INBOX')
        inbox.exists = 11
        inbox.set_num_unseen(1)

        self.server.capabilities.add('LIST-STATUS')
        self.test_op._capabilities = self.server.capabilities
        self.op = IMAPListOperation(self.test_op, {b'INBOX'})
        self.op.callback = op_callback()
        self.op.start()
        self.op.callback.assert_called_once_with(self.op)

        inbox = self.server.model.get_mailbox(b'INBOX')
        inbox.exists = 11
        inbox.set_num_unseen(1)

        self._check_model()
        self.assertTrue(self.test_op.is_done())
