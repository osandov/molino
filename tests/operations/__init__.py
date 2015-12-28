import contextlib
import re
import selectors
import socket
import sqlite3
import subprocess
from unittest.mock import MagicMock, NonCallableMagicMock

from molino.callbackstack import CallbackStack
from molino.operations import Operation
from molino.imap.parser import *
import molino.model as model


class MockMainOperation(Operation):
    def __init__(self):
        super().__init__(None)
        self._sel = selectors.DefaultSelector()
        self._view = NonCallableMagicMock(spec_set=['update_status'])
        self._view.update_status = MagicMock()
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        self._model = model.Model(db)


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
        self._model = self._main._model
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


class TestServer:
    def __init__(self, test_op):
        self.test_op = test_op
        self.capabilities = {'IMAP4rev1', 'AUTH=PLAIN'}
        self.correct_password = 'password'
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        self.model = model.Model(db)

        mailbox = self.model.get_mailbox(b'INBOX')
        mailbox.attributes = {'\\HasNoChildren'}
        message = model.Message(self.model, 1)
        message.envelope = Envelope(None, b'Hello', None, None, None, None,
                                    None, None, None, None)
        message.flags = {'\\Seen'}
        mailbox.add_message(700, message)
        for i in range(3):
            message = model.Message(self.model, 1001 + i)
            message.envelope = Envelope(None, b'Message %d' % i, None, None,
                                        None, None, None, None, None, None)
            message.flags = {}
            mailbox.add_message(999 + 2 * i, message)
        mailbox.set_unseen({999, 1001, 1003})
        mailbox.uids = [None, 700, 999, 1001, 1003]

        mailbox = model.Mailbox(self.model, b'LKML', ord('/'), {'\\HasNoChildren'})
        message = model.Message(self.model, 1)
        message.flags = {'\\Seen'}
        mailbox.add_message(7, message)
        mailbox.set_unseen({})
        self.model.add_mailbox(mailbox)

        self.selected = None

    def _status(self, mailbox_name, items):
        try:
            mailbox = self.model.get_mailbox(mailbox_name)
        except KeyError:
            assert False, 'Unknown mailbox %s' % mailbox_name
        status = {}
        for item in items:
            if item == 'MESSAGES':
                status['MESSAGES'] = mailbox.exists
            elif item == 'UNSEEN':
                status['UNSEEN'] = mailbox.num_unseen()
            else:
                assert False, 'Unexpected item %s' % item
        resp = UntaggedResponse('STATUS', Status(mailbox.name, status))
        self.test_op.dispatch(resp)

    def _ok(self, tag):
        resp = TaggedResponse(tag, 'OK', ResponseText('Success', None, None))
        self.test_op.dispatch(resp)

    def handle_cmd(self, tag, cmd, *args, **kwds):
        if cmd == 'CAPABILITY':
            resp = UntaggedResponse('CAPABILITY', self.capabilities)
            self.test_op.dispatch(resp)
            self._ok(tag)
        elif cmd == 'FETCH':
            if not self.selected:
                resp = TaggedResponse(tag, 'BAD', ResponseText('Not allowed now', None, None))
                self.test_op.dispatch(resp)
            else:
                mailbox = self.model.get_mailbox(self.selected)
                seq_set, *items = args
                for seq in seq_set:
                    if isinstance(seq, int):
                        start = end = seq
                    else:
                        start, end = seq
                    for msg in range(start, end + 1):
                        fetch = {}
                        if kwds.get('uid'):
                            fetch['UID'] = msg
                            for i, uid in enumerate(mailbox.uids):
                                if uid == msg:
                                    seqnum = i
                                    break
                            uid = msg
                        else:
                            seqnum = msg
                            uid = mailbox.uids[msg]
                        message = mailbox.get_message(uid)
                        for item in items:
                            if item == 'UID':
                                fetch['UID'] = uid
                            elif item == 'ENVELOPE':
                                assert message.envelope is not None
                                fetch['ENVELOPE'] = message.envelope
                            elif item == 'FLAGS':
                                assert message.flags is not None
                                fetch['FLAGS'] = message.flags
                            elif item == 'X-GM-MSGID':
                                assert message.id is not None
                                fetch['X-GM-MSGID'] = message.id
                            else:
                                assert False, 'Unexpected item %s' % item
                        resp = UntaggedResponse('FETCH', Fetch(seqnum, fetch))
                        self.test_op.dispatch(resp)
                self._ok(tag)
        elif cmd == 'LIST':
            reference, mailbox = args
            assert reference == b''
            assert mailbox == b'*'
            if 'LIST-STATUS' in self.capabilities:
                assert kwds.get('status_items') is not None
            else:
                assert kwds.get('status_items') is None
            for mailbox in self.model.mailboxes():
                l = List(mailbox.attributes, mailbox.delimiter, mailbox.name)
                resp = UntaggedResponse('LIST', l)
                self.test_op.dispatch(resp)
                if kwds.get('status_items'):
                    self._status(mailbox.name, kwds['status_items'])
            self._ok(tag)
        elif cmd == 'LOGIN':
            username, password = args
            if username == 'user' and password == self.correct_password:
                resp = TaggedResponse(tag, 'OK', ResponseText('Success', None, None))
                self.test_op.dispatch(resp)
            else:
                resp = TaggedResponse(tag, 'NO', ResponseText('Failure', None, None))
                self.test_op.dispatch(resp)
        elif cmd == 'SEARCH':
            if not self.selected:
                resp = TaggedResponse(tag, 'BAD', ResponseText('Not allowed now', None, None))
                self.test_op.dispatch(resp)
            else:
                assert kwds.get('uid')
                mailbox = self.model.get_mailbox(self.selected)
                criteria = args
                for c in criteria:
                    if c[0] == 'UNSEEN':
                        resp = UntaggedResponse('SEARCH', mailbox.unseen)
                        self.test_op.dispatch(resp)
                    else:
                        assert False, 'Unexpected search criteria %s' % c[0]
                self._ok(tag)
        elif cmd == 'STATUS':
            mailbox, *items = args
            self._status(mailbox, items)
            self._ok(tag)
        else:
            assert False, ('Unexpected %s' % cmd)


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
