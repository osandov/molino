import collections
import ctypes
import os
import struct


# From /usr/include/bits/signalfd.h
SFD_CLOEXEC = 0o02000000
SFD_NONBLOCK = 0o00004000

# From /usr/include/bits/signal.h
_sigset_t = ctypes.c_ubyte * 128

# From /usr/include/bits/sigaction.h
SIG_BLOCK = 0
SIG_UNBLOCK = 1
SIG_SETMASK = 2

_libc = ctypes.CDLL('libc.so.6', use_errno=True)

_libc.sigemptyset.restype = ctypes.c_int
_libc.sigemptyset.argtypes = [ctypes.POINTER(_sigset_t)]

_libc.sigfillset.restype = ctypes.c_int
_libc.sigfillset.argtypes = [ctypes.POINTER(_sigset_t)]

_libc.sigaddset.restype = ctypes.c_int
_libc.sigaddset.argtypes = [ctypes.POINTER(_sigset_t), ctypes.c_int]

_libc.sigdelset.restype = ctypes.c_int
_libc.sigdelset.argtypes = [ctypes.POINTER(_sigset_t), ctypes.c_int]

_libc.sigismember.restype = ctypes.c_int
_libc.sigismember.argtypes = [ctypes.POINTER(_sigset_t), ctypes.c_int]

_libc = ctypes.CDLL('libc.so.6', use_errno=True)
_libc.sigemptyset.restype = ctypes.c_int

_libc.sigprocmask.restype = ctypes.c_int
_libc.sigprocmask.argtypes = [ctypes.c_int, ctypes.POINTER(_sigset_t),
                              ctypes.POINTER(_sigset_t)]

_libc.signalfd.restype = ctypes.c_int
_libc.signalfd.argtypes = [ctypes.c_int, ctypes.POINTER(_sigset_t), ctypes.c_int]


Siginfo = collections.namedtuple('Siginfo', [
    'signo', 'errno', 'code', 'pid', 'uid', 'fd', 'tid', 'band', 'overrun',
    'trapno', 'status', 'int', 'ptr', 'utime', 'stime', 'addr',
])


def _signals_to_sigset(signals):
    sigset = _sigset_t()
    ret = _libc.sigemptyset(sigset)
    assert ret == 0
    for signal in signals:
        ret = _libc.sigaddset(sigset, signal)
        if ret == -1:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))
    return sigset


def sigprocmask(how, signals):
    sigset = _signals_to_sigset(signals)
    ret = _libc.sigprocmask(how, sigset, None)
    if ret == -1:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))


class SignalFD:
    def __init__(self, signals, flags=SFD_CLOEXEC):
        sigset = _signals_to_sigset(signals)
        self._fd = _libc.signalfd(-1, sigset, flags)
        if self._fd == -1:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))

    def __del__(self):
        self.close()

    def close(self):
        if self._fd != -1:
            os.close(self._fd)
            self._fd = -1

    def fileno(self):
        return self._fd

    def read(self):
        buf = os.read(self._fd, 128)
        return Siginfo(*struct.unpack('LllLLlLLLLllQQQQ', buf))
