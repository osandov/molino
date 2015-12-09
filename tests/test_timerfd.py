import errno
import os
import selectors
import time
import unittest

import molino.timerfd as timerfd
from molino.timerfd import Itimerspec, Timespec
import tests


DELTA_TS = Timespec(0, 1000000)
DELTA = timerfd.timespec_to_secs(DELTA_TS)
TEST_TS = Timespec(0, 5000000)
TEST = timerfd.timespec_to_secs(TEST_TS)


class TestTimerFD(unittest.TestCase):
    @tests.timed_test
    def test_settime_one_shot(self):
        fd = timerfd.TimerFD()
        before = time.monotonic()
        fd.settime(TEST)
        elapsed = fd.read()
        after = time.monotonic()
        self.assertEqual(elapsed, 1)
        self.assertAlmostEqual(after - before, TEST, delta=DELTA)

        fd = timerfd.TimerFD()
        before = time.monotonic()
        fd.settime(TEST_TS)
        elapsed = fd.read()
        after = time.monotonic()
        self.assertEqual(elapsed, 1)
        self.assertAlmostEqual(after - before, TEST, delta=DELTA)

    def test_settime_old_value(self):
        fd = timerfd.TimerFD()
        fd.settime(7.7)
        old_value = fd.settime(0.1)
        self.assertAlmostEqual(timerfd.timespec_to_secs(old_value.value),
                               7.7, delta=DELTA)

    @tests.timed_test
    def test_settime_absolute(self):
        fd = timerfd.TimerFD()
        before = time.monotonic()
        fd.settime(before + TEST, absolute=True)
        elapsed = fd.read()
        after = time.monotonic()
        self.assertEqual(elapsed, 1)
        self.assertAlmostEqual(after - before, TEST, delta=DELTA)

    @tests.timed_test
    def test_settime_repeat(self):
        fd = timerfd.TimerFD()
        fd.settime(TEST / 2, TEST / 2)
        time.sleep(TEST)
        self.assertEqual(fd.read(), 2)

    @tests.timed_test
    def test_settime_nonblocking(self):
        fd = timerfd.TimerFD(flags=timerfd.TFD_NONBLOCK)
        self.assertRaises(BlockingIOError, fd.read)

        fd.settime(TEST)
        self.assertRaises(BlockingIOError, fd.read)

        selector = selectors.DefaultSelector()
        key = selector.register(fd, selectors.EVENT_READ, None)
        self.assertEqual(selector.select(timeout=0), [])

        time.sleep(TEST)
        self.assertEqual(selector.select(), [(key, selectors.EVENT_READ)])

    @tests.timed_test
    def test_disarm(self):
        fd = timerfd.TimerFD(flags=timerfd.TFD_NONBLOCK)
        fd.settime(TEST / 2)
        fd.disarm()
        time.sleep(TEST)
        self.assertRaises(BlockingIOError, fd.read)

    def test_gettime(self):
        fd = timerfd.TimerFD()

        curr_value = fd.gettime()
        self.assertEqual(curr_value, Itimerspec(Timespec(0, 0), Timespec(0, 0)))

        fd.settime(7.7)
        curr_value = fd.gettime()
        self.assertAlmostEqual(timerfd.timespec_to_secs(curr_value.value),
                               7.7, delta=DELTA)

    def test_errors(self):
        with self.assertRaises(OSError) as cm:
            fd = timerfd.TimerFD(clockid=-1)
        self.assertEqual(cm.exception.errno, errno.EINVAL)

        with self.assertRaises(OSError) as cm:
            fd = timerfd.TimerFD(flags=-1)
        self.assertEqual(cm.exception.errno, errno.EINVAL)

        fd = timerfd.TimerFD()
        with self.assertRaises(OSError) as cm:
            fd.settime(timerfd.Timespec(0, -1))
        self.assertEqual(cm.exception.errno, errno.EINVAL)
