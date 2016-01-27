import unittest

from molino.imap.parser import *
from molino.operations import IMAPGreetingOperation
import tests
from tests.operations import TestIMAPOperation, op_callback


class TestIMAPGreetingOperation(unittest.TestCase):
    def setUp(self):
        self.test_op = TestIMAPOperation()
        self.op = IMAPGreetingOperation(self.test_op)
        self.op.callback = op_callback()
        self.test_op.start()

    def test_ok(self):
        self.op.start()
        resp = UntaggedResponse('OK', ResponseText('Hello', None, None))
        self.test_op.dispatch(resp)
        self.op.callback.assert_called_once_with(self.op)
        self.assertEqual(self.op.result, 'OK')
        self.assertTrue(self.test_op.is_done())

    def test_preauth(self):
        self.op.start()
        resp = UntaggedResponse('PREAUTH', ResponseText('Preauthenticated', None, None))
        self.test_op.dispatch(resp)
        self.op.callback.assert_called_once_with(self.op)
        self.assertEqual(self.op.result, 'PREAUTH')
        self.assertTrue(self.test_op.is_done())

    def test_bye(self):
        self.op.start()
        resp = UntaggedResponse('BYE', ResponseText('Go away', None, None))
        self.test_op.dispatch(resp)
        self.op.callback.assert_called_once_with(self.op)
        self.assertEqual(self.op.result, 'BYE')
        self.assertTrue(self.test_op.updated_with('rejected'))
        self.assertTrue(self.test_op.is_done())
