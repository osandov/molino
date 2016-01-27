import socket
import threading
import time
import unittest

from molino.operations import TCPConnectOperation
import tests
from tests.operations import TestOperation, op_callback, drop_connection


class TestTCPConnectOperation(unittest.TestCase):
    def setUp(self):
        self.test_op = TestOperation()
        self.sock = socket.socket()
        self.sock.bind(('localhost', 0))
        self.sock.listen(0)
        self.shutdown = True
        self.test_op.start()

    def tearDown(self):
        if self.shutdown:
            self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()

    def accept(self):
        class Accept:
            def __init__(self):
                self.thread = None
                self.sock = None
                self.addr = None
        accept = Accept()
        def aux(accept):
            accept.sock, accept.addr = self.sock.accept()
        accept.thread = threading.Thread(target=aux, args=(accept,))
        accept.thread.start()
        return accept

    def test_success(self):
        """
        Test a successful connection.
        """
        op = TCPConnectOperation(self.test_op, self.sock.getsockname())
        op.callback = op_callback()
        op.start()
        accept = self.accept()
        while not op.callback.called:
            self.test_op.run_selector()
        accept.thread.join()
        try:
            op.callback.assert_called_once_with(op)
            self.assertIsNotNone(op.socket)
            op.socket.close()
        finally:
            accept.sock.close()
        self.assertTrue(self.test_op.is_done())

    def test_gaierror(self):
        """
        Test a connection that fails on socket.connect() because of a name
        resolution error.
        """
        # See RFC 6761 for the .test TLD -- unless the DNS server is doing
        # something weird, this name should not resolve.
        op = TCPConnectOperation(self.test_op, ('example.test', 666))
        op.callback = op_callback()
        op.start()
        op.callback.assert_called_once_with(op)
        self.assertIsNone(op.socket)
        self.assertTrue(self.test_op.is_done())

    def test_connection_refused(self):
        """
        Test a connection that fails because the server refuses the connection.
        """
        self.sock.shutdown(socket.SHUT_RD)
        self.shutdown = False
        op = TCPConnectOperation(self.test_op, self.sock.getsockname())
        op.callback = op_callback()
        op.start()
        self.test_op.run_selector()
        op.callback.assert_called_once_with(op)
        self.assertIsNone(op.socket)
        self.assertTrue(self.test_op.updated_with('Connection refused'))
        self.assertTrue(self.test_op.is_done())

    @tests.timed_test
    @tests.root_test
    def test_timeout(self):
        """
        Test a connection that times out and fails.
        """
        with drop_connection(port=self.sock.getsockname()[1]):
            op = TCPConnectOperation(self.test_op, self.sock.getsockname(), 0.01)
            op.callback = op_callback()
            op.start()
            time.sleep(0.01)
            self.test_op.run_selector()
            op.callback.assert_called_once_with(op)
            self.assertIsNone(op.socket)
            self.assertTrue(self.test_op.updated_with('Timed out'))
            self.assertTrue(self.test_op.is_done())

    @tests.timed_test
    def test_connect_and_timeout(self):
        """
        Test the case where the connection succeeds but the timerfd still fires
        before we call select. This is the case where the socket comes before
        the timerfd in the list of events, so the connection should succeed.
        """
        op = TCPConnectOperation(self.test_op, self.sock.getsockname(), 0.01)
        op.callback = op_callback()
        op.start()
        accept = self.accept()
        time.sleep(0.01)
        while not op.callback.called:
            self.test_op.run_selector(priority='socket')
        try:
            op.callback.assert_called_once_with(op)
            self.assertIsNotNone(op.socket)
            op.socket.close()
            self.assertTrue(self.test_op.is_done())
        finally:
            accept.sock.close()

    @tests.timed_test
    def test_timeout_and_connect(self):
        """
        Test the same case as test_connect_and_timeout but where the timerfd
        event comes before the socket event.
        """
        op = TCPConnectOperation(self.test_op, self.sock.getsockname(), 0.01)
        op.callback = op_callback()
        op.start()
        accept = self.accept()
        time.sleep(0.01)
        while not op.callback.called:
            self.test_op.run_selector(priority='timer')
        try:
            op.callback.assert_called_once_with(op)
            self.assertIsNone(op.socket)
            self.assertTrue(self.test_op.updated_with('Timed out'))
            self.assertTrue(self.test_op.is_done())
        finally:
            accept.sock.close()
