import contextlib
import re
import selectors
import socket
import sqlite3
import subprocess
from unittest.mock import MagicMock, NonCallableMagicMock

from molino.callbackstack import CallbackStack
from molino.cache import Cache
from molino.operations import Operation
from molino.imap.parser import *


class MockMainOperation(Operation):
    def __init__(self):
        super().__init__(None)
        self._sel = selectors.DefaultSelector()
        self._view = NonCallableMagicMock(spec_set=['update_status'])
        self._view.update_status = MagicMock()
        db = sqlite3.connect(':memory:')
        self._cache = Cache(db)


class TestOperation(Operation):
    def __init__(self):
        self._main = MockMainOperation()
        super().__init__(self._main)

    def is_done(self):
        assert len(self._main._sel.get_map()) == 0
        return self._pending is None

    def updated_with(self, regex, case_sensitive=False):
        for args, kwds in self._main._view.update_status.call_args_list:
            if re.search(regex, args[0], 0 if case_sensitive else re.IGNORECASE):
                return True
        return False

    def run_selector(self, priority=None):
        events = self._main._sel.select()
        if priority == 'socket':
            events.sort(key=lambda x: 0 if isinstance(x[0].fileobj, socket.socket) else 1)
        elif priority == 'timer':
            events.sort(key=lambda x: 1 if isinstance(x[0].fileobj, socket.socket) else 0)
        for key, mask in events:
            callback = key.data
            callback(mask)


class TestIMAPOperation(TestOperation):
    def __init__(self):
        super().__init__()
        self._cache = self._main._cache
        self._imap = self
        self._tag = 0
        self._untagged_handlers = {}
        self._tagged_handlers = {}
        self.server_callback = None
        self._capabilities = {'IMAP4rev1'}

    def dispatch(self, resp):
        if isinstance(resp, UntaggedResponse):
            self._untagged_handlers[resp.type](resp)
        elif isinstance(resp, TaggedResponse):
            self._tagged_handlers[resp.tag](resp)
            del self._tagged_handlers[resp.tag]
        #  elif isinstance(resp, ContinueReq):
            #  self._handle_continue_req()
        else:
            assert False

    def _enqueue_cmd(self, callback, cmd, *args, **kwds):
        self._tag += 1
        tag = 'A%03d' % self._tag
        self._tagged_handlers[tag] = callback
        if self.server_callback:
            self.server_callback(tag, cmd, *args, **kwds)

    def have_capability(self, capability):
        return capability in self._capabilities

    def register_untagged(self, type, callback):
        try:
            self._untagged_handlers[type].register(callback)
        except KeyError:
            callback_stack = CallbackStack()
            callback_stack.register(callback)
            self._untagged_handlers[type] = callback_stack


def op_callback():
    return MagicMock(side_effect=lambda op: op._parent.dec_pending(),
                     spec_set=[])


@contextlib.contextmanager
def drop_connection(port):
    subprocess.check_call(['sudo', '-n', 'iptables', '-A', 'INPUT',
                           '-p', 'tcp', '--dport', str(port), '-j', 'DROP'])
    yield
    subprocess.check_call(['sudo', '-n', 'iptables', '-D', 'INPUT',
                           '-p', 'tcp', '--dport', str(port), '-j', 'DROP'])
