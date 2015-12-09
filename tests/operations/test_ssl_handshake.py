import socket
import ssl
import tempfile
import threading
import time
import unittest

from molino.operations import SSLHandshakeOperation
import tests
from tests.operations import TestOperation, op_callback, drop_connection


# openssl genpkey -algorithm RSA -out ca.key
ca_key = b"""\
-----BEGIN PRIVATE KEY-----
MIICdQIBADANBgkqhkiG9w0BAQEFAASCAl8wggJbAgEAAoGBAL/xCsBM5fzknYJ0
oZle79s+QKTu/cgAN0t4qQaUmJFMq+501LZgPurTCdatRNBjZYTN2QtLDUDLAQFM
HIoznximI96JNM0RYS489+MaFTYjtQHbLxU5DKRQXdDVuywpyqjT8xLTM1ONX3zT
o646DQJ4uN0SNdyr746TmHe8mYGnAgMBAAECgYAlKPV75WdhXqFf8FSY7NhjCdpa
FCrt3ZzW77VJoNsoxj9DGztTU67ap6Dv/vujnJq6619p4E3gjWzUY3fjCbtzI6Rk
icKeJ84CiYynZG+JbWI3LH/Yt8L+/mbr0yIaATZUnbqB+KaAs05wS6XpP3NPziDi
VOEyOYfpX3kn5En3gQJBAPzJxJqCvqD1m+9spqWSxAdcqwYfw9QuKpSczCzLvig3
euybExrz4T1xMICPxKGtWjbTaEqIzl53cJaC61cPF3MCQQDCYVx4uFpqXSiWMh4W
bYFYend2p0Nb6ptHavDDxYUuw3xEqGNoqXeaMqoQILoII/Mfqbls5B2U7okEdUdd
HBf9AkAJvkUjp3Jthcny2n851oRTvFCjNco4fWcKv1hnSZsUtb65K+j6mvfNhHVY
HzJ3ANV/U3qrlMZPgc8HHhiwDFbdAkATh+bbtmJXV57xYH3HcR9S/ZMtV+cbwDnz
9hnVAe684SWGXIkIhiafVsHhtvgaQ0p1fv9DorQaN9GKoiIWh/EdAkBwHOcWWCX3
ZHHVRvvG8EjgYCGnc+e9VmK4UBBFQARaO+jjEEYgi4GKXmaMkwttcA+L/vukzSaB
4QrIsePeVcha
-----END PRIVATE KEY-----
"""


# openssl req -x509 -new -key ca.key -out ca.pem
# Common Name: localhost
ca_pem = b"""\
-----BEGIN CERTIFICATE-----
MIIB9jCCAV+gAwIBAgIJAMRBzRIpebM/MA0GCSqGSIb3DQEBCwUAMBQxEjAQBgNV
BAMMCWxvY2FsaG9zdDAeFw0xNTEyMDUwOTIzMTBaFw0xNjAxMDQwOTIzMTBaMBQx
EjAQBgNVBAMMCWxvY2FsaG9zdDCBnzANBgkqhkiG9w0BAQEFAAOBjQAwgYkCgYEA
v/EKwEzl/OSdgnShmV7v2z5ApO79yAA3S3ipBpSYkUyr7nTUtmA+6tMJ1q1E0GNl
hM3ZC0sNQMsBAUwcijOfGKYj3ok0zRFhLjz34xoVNiO1AdsvFTkMpFBd0NW7LCnK
qNPzEtMzU41ffNOjrjoNAni43RI13KvvjpOYd7yZgacCAwEAAaNQME4wHQYDVR0O
BBYEFP3lruXKDZEh708blWDAJ9rug5cIMB8GA1UdIwQYMBaAFP3lruXKDZEh708b
lWDAJ9rug5cIMAwGA1UdEwQFMAMBAf8wDQYJKoZIhvcNAQELBQADgYEAbFN0IMPf
cNPfl8UMsuUFD5NPeNDJDdpDvwSirtL955xG84cjBk/GKj9EExeYqXcbGsEcyZNI
ygWW9wwE3+g4Gj++gM8/qsQs6jfWxgmU3bQ+3GPS/RgFHxQExm5fiTNk87lmgm5U
4cljLggezhkQSEjDBjrAXPjZKiE7EjDO6qA=
-----END CERTIFICATE-----
"""


# openssl genpkey -algorithm RSA -out ca2.key
# openssl req -x509 -new -key ca2.key -out ca2.pem
# Common Name: localhost
ca2_pem = b"""\
-----BEGIN CERTIFICATE-----
MIIB9jCCAV+gAwIBAgIJAJiY63L4xWBGMA0GCSqGSIb3DQEBCwUAMBQxEjAQBgNV
BAMMCWxvY2FsaG9zdDAeFw0xNTEyMDUwOTQ1NTBaFw0xNjAxMDQwOTQ1NTBaMBQx
EjAQBgNVBAMMCWxvY2FsaG9zdDCBnzANBgkqhkiG9w0BAQEFAAOBjQAwgYkCgYEA
9mGQq8UfW62CwdhCuo5AwQ1SYT6q7XG458qaYdPESrbDDX6Ya9dRnDiGYC8EUS6+
xC8mkJkgvYFSoqE4FAQeOVCdF4svbZYAYJEKkBAEBoRQScv6oWX80C3VwjyBLjOP
0Xmh5m6IJA23xqb1+EoMo4f/u1nw3lZz9Zg19EBE6F0CAwEAAaNQME4wHQYDVR0O
BBYEFOm4j+P6MDucTSGLEfh+CpWQp7B9MB8GA1UdIwQYMBaAFOm4j+P6MDucTSGL
Efh+CpWQp7B9MAwGA1UdEwQFMAMBAf8wDQYJKoZIhvcNAQELBQADgYEAEJSwT6DC
oqw3K7SdKmMXLhjVfj79dYicAKjCXj+44kfW+sFkdifMx0ZhcEOazwwEN/upvPv6
rlBYgeGs04KoDK3191EoYpwbJfqmAeqNc2A4baF6rs9JeVWSrkbIywFK3br5ACKl
pclmGK9xcw1aeN9vuIuiqPGY5vzfE4b13No=
-----END CERTIFICATE-----
"""


class TestSSLHandshakeOperation(unittest.TestCase):
    def setUp(self):
        self.keyfile = tempfile.NamedTemporaryFile(prefix='test_ca_', suffix='.key')
        self.keyfile.write(ca_key)
        self.keyfile.flush()

        self.certfile = tempfile.NamedTemporaryFile(prefix='test_ca_', suffix='.pem')
        self.certfile.write(ca_pem)
        self.certfile.flush()

        self.certfile2 = tempfile.NamedTemporaryFile(prefix='test_ca_', suffix='.pem')
        self.certfile2.write(ca2_pem)
        self.certfile2.flush()

        self.test_op = TestOperation()
        self.sock = None

    def tearDown(self):
        if self.sock:
            if self.shutdown:
                self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
        self.keyfile.close()
        self.certfile.close()
        self.certfile2.close()

    def start_server(self, wrap_ssl=True):
        self.sock = socket.socket()
        if wrap_ssl:
            context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            context.load_cert_chain(certfile=self.certfile.name, keyfile=self.keyfile.name)
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
                                   self.certfile.name)
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
                                   self.certfile2.name)
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
                                   self.certfile.name)
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
                                   self.certfile.name)
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
                                       self.certfile.name, 0.01)
            op.callback = op_callback()
            op.start()
            time.sleep(0.01)
            self.test_op.run_selector()
            op.callback.assert_called_once_with(op)
            self.assertIsNone(op.socket)
            self.assertTrue(self.test_op.updated_with('Timed out'))
            self.assertTrue(self.test_op.is_done())
