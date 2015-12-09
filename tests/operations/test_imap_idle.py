import unittest

from molino.imap.parser import *
from molino.operations import IMAPIdleOperation
import tests
from tests.operations import TestIMAPOperation, TestServer, op_callback


class TestIMAPIdleOperation(unittest.TestCase):
    def setUp(self):
        self.test_op = TestIMAPOperation()
        self.server = TestServer(self.test_op)
        self.test_op.server_callback = self.server.handle_cmd
        def handle_fetch(resp):
            return _IMAPSelectedState._handle_fetch(self.test_op, resp)
        self.test_op.register_untagged('FETCH', handle_fetch)

    #  def test_exists(self):
        #  inbox = self.test_op._model.get_mailbox(b'INBOX')
        #  self.test_op._mailbox = inbox
        #  op = IMAPIdleOperation(self.test_op)
        #  op.callback = op_callback()
        #  op.start()
