import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

from molino.operations import SSLHandshakeOperation
import tests
from tests.operations import TestOperation, op_callback, drop_connection


class TestSSLHandshakeOperation(unittest.TestCase):
    def setUp(self):
        fd, self.keyfile = tempfile.mkstemp(prefix='test_ca_', suffix='.key')
        subprocess.check_call(['openssl', 'genpkey', '-algorithm', 'RSA',
                               '-out', self.keyfile], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        os.close(fd)

        fd, self.certfile = tempfile.mkstemp(prefix='test_ca_', suffix='.pem')
        subprocess.check_call(['openssl', 'req', '-x509', '-new',
                               '-subj', '/CN=localhost',
                               '-key', self.keyfile, '-out', self.certfile],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(fd)

        fd, self.keyfile2 = tempfile.mkstemp(prefix='test_ca_', suffix='.key')
        subprocess.check_call(['openssl', 'genpkey', '-algorithm', 'RSA',
                               '-out', self.keyfile2], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        os.close(fd)

        fd, self.certfile2 = tempfile.mkstemp(prefix='test_ca_', suffix='.pem')
        subprocess.check_call(['openssl', 'req', '-x509', '-new',
                               '-subj', '/CN=localhost',
                               '-key', self.keyfile2, '-out', self.certfile2],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(fd)

        self.test_op = TestOperation()
        self.sock = None
        self.test_op.start()

    def tearDown(self):
        if self.sock:
            if self.shutdown:
                self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
        os.unlink(self.keyfile)
        os.unlink(self.certfile)
        os.unlink(self.keyfile2)
        os.unlink(self.certfile2)

    def start_server(self, wrap_ssl=True):
        self.sock = socket.socket()
        if wrap_ssl:
            context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            context.load_cert_chain(certfile=self.certfile, keyfile=self.keyfile)
            self.sock = context.wrap_socket(self.sock, server_side=True)
        self.sock.bind(('localhost', 0))
        self.sock.listen(0)
        self.shutdown = True

    def accept(self, send=None):
        class Accept:
            def __init__(self):
                self.thread = None
                self.sock = None
                self.addr = None
        accept = Accept()
        def aux(accept):
            try:
                accept.sock, accept.addr = self.sock.accept()
                if send:
                    accept.sock.sendall(send)
            except ssl.SSLError:
                pass
        accept.thread = threading.Thread(target=aux, args=(accept,))
        accept.thread.start()
        return accept

    def connect_client(self):
        sock = socket.socket()
        sock.connect(self.sock.getsockname())
        sock.setblocking(False)
        return sock

    def test_success(self):
        """
        Test a successful handshake.
        """
        self.start_server()
        sock = self.connect_client()
        op = SSLHandshakeOperation(self.test_op, sock, 'localhost',
                                   self.certfile)
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
            self.assertTrue(self.test_op.is_done())
        finally:
            accept.sock.close()

    def test_certificate_verify(self):
        """
        Test a handshake that fails because the certificate is not trusted.
        """
        self.start_server()
        sock = self.connect_client()
        # Notice that we're using ca2.pem as the CA file here.
        op = SSLHandshakeOperation(self.test_op, sock, 'localhost',
                                   self.certfile2)
        op.callback = op_callback()
        op.start()
        accept = self.accept()
        while not op.callback.called:
            self.test_op.run_selector()
        accept.thread.join()
        try:
            op.callback.assert_called_once_with(op)
            self.assertIsNone(op.socket)
            self.assertTrue(self.test_op.updated_with('CERTIFICATE_VERIFY_FAILED'))
            self.assertTrue(self.test_op.is_done())
        finally:
            if accept.sock:
                accept.sock.close()

    def test_hostname_verify(self):
        """
        Test a handshake that fails because the server hostname does not match.
        """
        self.start_server()
        sock = self.connect_client()
        # We're passing 'localghost' instead of 'localhost' as the server
        # hostname.
        op = SSLHandshakeOperation(self.test_op, sock, 'localghost',
                                   self.certfile)
        op.callback = op_callback()
        op.start()
        accept = self.accept()
        while not op.callback.called:
            self.test_op.run_selector()
        accept.thread.join()
        try:
            op.callback.assert_called_once_with(op)
            self.assertIsNone(op.socket)
            self.assertTrue(self.test_op.updated_with('hostname'))
            self.assertTrue(self.test_op.is_done())
        finally:
            if accept.sock:
                accept.sock.close()

    def test_missing_cafile(self):
        """
        Test a handshake that fails because the CA file doesn't exist.
        """
        self.start_server()
        sock = self.connect_client()
        op = SSLHandshakeOperation(self.test_op, sock, 'localhost',
                                   tempfile.mktemp())
        op.callback = op_callback()
        op.start()
        op.callback.assert_called_once_with(op)
        self.assertIsNone(op.socket)
        self.assertTrue(self.test_op.updated_with('No such file'))
        self.assertTrue(self.test_op.is_done())

    def test_invalid_handshake(self):
        """
        Test a handshake that fails because the server does something invalid
        (e.g., the server is not actually using SSL).
        """
        self.start_server(wrap_ssl=False)
        sock = self.connect_client()
        op = SSLHandshakeOperation(self.test_op, sock, 'localhost',
                                   self.certfile)
        op.callback = op_callback()
        op.start()
        accept = self.accept(send=b'* OK Hello\r\n')
        while not op.callback.called:
            self.test_op.run_selector()
        accept.thread.join()
        try:
            op.callback.assert_called_once_with(op)
            self.assertIsNone(op.socket)
            self.assertTrue(self.test_op.is_done())
        finally:
            if accept.sock:
                accept.sock.close()

    @tests.timed_test
    @tests.root_test
    def test_timeout(self):
        """
        Test a handshake that fails because it times out.
        """
        self.start_server()
        sock = self.connect_client()
        with drop_connection(port=self.sock.getsockname()[1]):
            op = SSLHandshakeOperation(self.test_op, sock, 'localhost',
                                       self.certfile, 0.01)
            op.callback = op_callback()
            op.start()
            time.sleep(0.01)
            self.test_op.run_selector()
            op.callback.assert_called_once_with(op)
            self.assertIsNone(op.socket)
            self.assertTrue(self.test_op.updated_with('Timed out'))
            self.assertTrue(self.test_op.is_done())
