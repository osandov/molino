import unittest
import os


timed_test = unittest.skipUnless(
    os.getenv('TEST_TIMED'),
    'Skipping timed test unless TEST_TIMED is set')

root_test = unittest.skipUnless(
        os.getuid() == 0 or os.getenv('TEST_SUDO'),
        'Test requires root priviledges TEST_SUDO to be set')
