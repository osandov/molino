import errno
import os
import selectors
import signal
import unittest

import molino.signalfd as signalfd


class TestSignalFD(unittest.TestCase):
    def test_signalfd(self):
        signals = [signal.SIGUSR1]
        signalfd.sigprocmask(signalfd.SIG_BLOCK, signals)
        fd = signalfd.SignalFD(signals)
        os.kill(os.getpid(), signal.SIGUSR1)
        siginfo = fd.read()
        self.assertEqual(siginfo.signo, signal.SIGUSR1)

    def test_nonblock(self):
        signals = [signal.SIGUSR1]
        flags = signalfd.SFD_CLOEXEC | signalfd.SFD_NONBLOCK
        signalfd.sigprocmask(signalfd.SIG_BLOCK, signals)
        fd = signalfd.SignalFD(signals, flags)

        self.assertRaises(BlockingIOError, fd.read)

        selector = selectors.DefaultSelector()
        key = selector.register(fd, selectors.EVENT_READ, None)
        self.assertEqual(selector.select(timeout=0), [])

        os.kill(os.getpid(), signal.SIGUSR1)
        self.assertEqual(selector.select(), [(key, selectors.EVENT_READ)])

    def test_errors(self):
        with self.assertRaises(OSError) as cm:
            signalfd._signals_to_sigset([-1])
        self.assertEqual(cm.exception.errno, errno.EINVAL)

        with self.assertRaises(OSError) as cm:
            signalfd.sigprocmask(-1, [signal.SIGUSR1])
        self.assertEqual(cm.exception.errno, errno.EINVAL)

        with self.assertRaises(OSError) as cm:
            signalfd.SignalFD([signal.SIGUSR1], -1)
        self.assertEqual(cm.exception.errno, errno.EINVAL)
