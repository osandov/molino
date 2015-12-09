import collections
import ctypes
import numbers
import os
import struct
import time

# From /usr/include/timerfd.h
TFD_TIMER_ABSTIME = 1 << 0

# From /usr/include/bits/timerfd.h
TFD_CLOEXEC = 0o02000000
TFD_NONBLOCK = 0o00004000

# From /usr/include/bits/types.h and /usr/include/bits/typesizes.h.
_time_t = ctypes.c_long


class _timespec(ctypes.Structure):
    _fields_ = [
            ('tv_sec', _time_t),
            ('tv_nsec', ctypes.c_long)
    ]


class _itimerspec(ctypes.Structure):
    _fields_ = [
            ('it_interval', _timespec),
            ('it_value', _timespec)
    ]


_libc = ctypes.CDLL('libc.so.6', use_errno=True)

_libc.timerfd_create.restype = ctypes.c_int
_libc.timerfd_create.argtypes = [ctypes.c_int, ctypes.c_int]

_libc.timerfd_settime.restype = ctypes.c_int
_libc.timerfd_settime.argtypes = [ctypes.c_int, ctypes.c_int,
                                  ctypes.POINTER(_itimerspec),
                                  ctypes.POINTER(_itimerspec)]

_libc.timerfd_gettime.restype = ctypes.c_int
_libc.timerfd_gettime.argtypes = [ctypes.c_int, ctypes.POINTER(_itimerspec)]


Timespec = collections.namedtuple('Timespec', ['sec', 'nsec'])
Itimerspec = collections.namedtuple('Itimerspec', ['interval', 'value'])


def secs_to_timespec(value):
    sec = int(value)
    nsec = round((value - sec) * 1e9)
    return Timespec(sec, nsec)


def timespec_to_secs(ts):
    return ts.sec + ts.nsec / 1e9


class TimerFD:
    def __init__(self, clockid=time.CLOCK_MONOTONIC, flags=TFD_CLOEXEC):
        self._fd = _libc.timerfd_create(clockid, flags)
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
        buf = os.read(self._fd, 8)
        return struct.unpack('Q', buf)[0]

    def settime(self, value, interval=Timespec(0, 0), absolute=False):
        if isinstance(value, numbers.Number):
            value = secs_to_timespec(value)
        if isinstance(interval, numbers.Number):
            interval = secs_to_timespec(interval)
        new_value = _itimerspec(_timespec(interval[0], interval[1]),
                                _timespec(value[0], value[1]))
        old_value = _itimerspec()
        flags = TFD_TIMER_ABSTIME if absolute else 0
        ret = _libc.timerfd_settime(self._fd, flags, new_value, ctypes.byref(old_value))
        if ret == -1:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))
        return Itimerspec(Timespec(old_value.it_interval.tv_sec, old_value.it_interval.tv_nsec),
                          Timespec(old_value.it_value.tv_sec, old_value.it_value.tv_nsec))

    def disarm(self):
        return self.settime(Timespec(0, 0))

    def gettime(self):
        curr_value = _itimerspec()
        ret = _libc.timerfd_gettime(self._fd, ctypes.byref(curr_value))
        assert ret == 0
        return Itimerspec(Timespec(curr_value.it_interval.tv_sec, curr_value.it_interval.tv_nsec),
                          Timespec(curr_value.it_value.tv_sec, curr_value.it_value.tv_nsec))
