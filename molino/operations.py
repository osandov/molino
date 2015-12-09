import collections
import enum
import logging
import os
import selectors
import signal
import socket
import ssl
import sys

from molino.callbackstack import CallbackStack, callback_stack
import molino.imap.parser
import molino.imap.formatter
import molino.imap as imap
import molino.model as model
from molino.view import StatusLevel
from molino.seque import SequenceQueue
import molino.signalfd as signalfd
import molino.timerfd as timerfd


class Operation:
    """
    An Operation represents a single action taken by the application (i.e.,
    connecting to a server, loading a mailbox, etc.). When an Operation is
    started, it kicks off actions it needs done and keeps track of the number
    of pending actions it is waiting on (e.g., a child sub-operation, a
    response on the network, or an event from the user). When all of its
    pending operations have completed, it cleans up after itself and decrements
    the number of pending operations on its parent operation.
    """

    def __init__(self, parent):
        self._pending = 0
        self._parent = parent
        self.callback = None

    def start(self):
        """
        Start the execution of the operation, registering event handlers and
        starting any initial actions. The number of pending actions should be
        non-zero upon returning.
        """
        if self._parent:
            self._parent.inc_pending()

    def done(self):
        """
        Cleanup after the execution, unregistering event handlers, etc.
        """
        assert self._pending is None
        if self.callback:
            self.callback(self)
        elif self._parent:
            self._parent.dec_pending()

    def inc_pending(self):
        """
        Increment the count of pending actions this operation is waiting on.
        """
        assert self._pending is not None
        logging.debug('%r +1 = %d' % (self, self._pending + 1))
        self._pending += 1

    def dec_pending(self):
        """
        Decrement the count pending actions this operation is waiting on. If
        the count reaches zero, call self.done() to cleanup.
        """
        logging.debug('%r -1 = %d' % (self, self._pending - 1))
        self._pending -= 1
        if self._pending == 0:
            self._pending = None
            self.done()


class MainOperation(Operation):
    """
    Main application operation: runs select() loop and dispatches events on the
    contained file descriptors, in particular, stdin and a signalfd, as well as
    anything additional that is registered.
    """

    def __init__(self, config, model, view):
        super().__init__(None)
        self._config = config
        self._model = model
        self._view = view

        self._quit = False

        signals = [signal.SIGWINCH]
        signalfd.sigprocmask(signalfd.SIG_BLOCK, signals)
        flags = signalfd.SFD_CLOEXEC | signalfd.SFD_NONBLOCK
        self._signalfd = signalfd.SignalFD(signals, flags)

        self._sel = selectors.DefaultSelector()
        self._sel.register(sys.stdin, selectors.EVENT_READ, self._select_stdin)
        self._sel.register(self._signalfd, selectors.EVENT_READ, self._select_signal)

    def start(self):
        super().start()
        op = _IMAPManagerOperation(self)
        op.start()
        while not self._quit:
            events = self._sel.select()
            for key, mask in events:
                callback = key.data
                callback(mask)
        self._sel.close()

    def done(self):
        self._quit = True
        super().done()

    def _select_stdin(self, mask):
        self._view.handle_input()

    def _select_signal(self, mask):
        siginfo = self._signalfd.read()
        if siginfo.signo == signal.SIGWINCH:
            self._view.resize()


class MainSubOperation(Operation):
    """
    Sub-operation of the MainOperation.
    """

    def __init__(self, main, parent=None):
        super().__init__(parent if parent else main)
        self._main = main
        self._model = self._main._model

    def update_status(self, msg, level):
        """Display a status update to the user."""
        self._main._view.update_status(msg, level)


def _view_event_handler(event):
    def decorator(f):
        f._view_event = event
        return f
    return decorator


class _IMAPManagerOperation(MainSubOperation):
    """
    Operation which manages cached IMAP connections and dispatches events from
    the view.
    """

    def __init__(self, main):
        super().__init__(main)
        # Cache of connections to the IMAP server.
        self._selected_cache = collections.OrderedDict()
        self._workqueue = None

    def start(self):
        super().start()
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if hasattr(attr, '_view_event'):
                getattr(self._main._view, 'on_' + attr._view_event).register(attr)

        # This can be extended to multiple workqueues <=> multiple connections
        # in the future.
        self._workqueue = IMAPWorkqueueOperation(self)
        self._workqueue.start()
        self._workqueue.refresh_mailbox_list()
        self._workqueue.select_mailbox(self._model.get_mailbox(b'INBOX'))

    def done(self):
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if hasattr(attr, '_view_event'):
                getattr(self._main._view, 'on_' + attr._view_event).unregister(attr)
        super().done()

    @_view_event_handler('quit')
    def _handle_quit(self):
        if self._workqueue:
            self._workqueue.quit()
            self._workqueue = None
        return True

    @_view_event_handler('refresh')
    def _handle_refresh(self):
        if self._workqueue:
            self._workqueue.refresh_mailbox_list()
        return True

    @_view_event_handler('select_mailbox')
    def _handle_select_mailbox(self, mailbox):
        if self._workqueue:
            self._workqueue.select_mailbox(mailbox)
        return True

    @_view_event_handler('open_message')
    def _handle_open_message(self, mailbox, uid):
        if self._workqueue:
            self._workqueue.select_mailbox(mailbox)
            self._workqueue.fetch_bodystructure(uid)
        return True

    @_view_event_handler('read_body_sections')
    def _handle_open_body_sections(self, mailbox, uid, sections):
        if self._workqueue:
            self._workqueue.select_mailbox(mailbox)
            self._workqueue.fetch_body_sections(uid, sections)
        return True


class Work:
    Type = enum.IntEnum('Type', [
        # Any state
        'logout',
        # Authenticated state
        'refresh_list',
        'select',
        # Selected state (make sure to update is_selected_state())
        'close',
        'fetch_bodystructure',
        'fetch_body_sections',
    ])

    def __init__(self, type_, *args):
        self.type = type_
        self.args = args

    def is_selected_state(self):
        return self.type >= Work.Type.close


class IMAPWorkqueueOperation(MainSubOperation):
    """
    Operation which manages a queue of high-level IMAP work items which have to
    be completed. It keeps a single worker connection which is restarted if it
    dies.
    """

    def __init__(self, parent):
        super().__init__(parent._main, parent)
        self.selected = None
        self._quit = False
        self._queue = collections.deque()
        self._callback = None

    def start(self):
        super().start()
        imap_op = _IMAPConnectionOperation(self)
        imap_op.callback = self._conn_closed
        imap_op.start()

    def _conn_closed(self, op):
        if self._quit:
            self.dec_pending()
        else:
            assert False, "TODO"

    def have_work(self):
        return len(self._queue) > 0

    def get_work(self):
        return self._queue[0]

    def finish_work(self, work):
        assert work == self._queue[0]
        self._queue.popleft()

    def fail_work(self, work):
        assert False

    def fail_selected_work(self, work):
        assert work == self._queue[0]
        self._queue.popleft()
        stack = []
        while self._queue and self._queue[0].type != Work.Type.select:
            work2 = self._queue.popleft()
            if not work2.is_selected_state():
                stack.append(work2)
        if not self._queue == 0:
            self.selected = None
        self._queue.extendleft(reversed(stack))

    def wait_for_work(self, callback):
        assert self._callback is None, self._callback
        self._callback = callback

    def cancel_wait(self, callback):
        assert self._callback == callback
        self._callback = None

    def _work_added(self):
        if self._callback:
            callback = self._callback
            self._callback = None
            callback()

    def quit(self):
        self._quit = True
        if self.selected:
            self._queue.append(Work(Work.Type.close))
            self.selected = None
        self._queue.append(Work(Work.Type.logout))
        self._work_added()

    def refresh_mailbox_list(self):
        self._queue.append(Work(Work.Type.refresh_list))
        self._work_added()

    def select_mailbox(self, mailbox):
        if mailbox == self.selected:
            return
        if self.selected:
            self._queue.append(Work(Work.Type.close))
        self._queue.append(Work(Work.Type.select, mailbox))
        self.selected = mailbox
        self._work_added()

    def fetch_bodystructure(self, uid):
        message = self.selected.get_message(uid)
        if not message.bodystructure:
            self._queue.append(Work(Work.Type.fetch_bodystructure, uid))
            self._work_added()

    def fetch_body_sections(self, uid, sections):
        message = self.selected.get_message(uid)
        sections = [s for s in sections if not message.have_body_section(s)]
        if sections:
            self._queue.append(Work(Work.Type.fetch_body_sections, uid, sections))
            self._work_added()


class _IMAPConnectionOperation(MainSubOperation):
    """
    Operation for the entire lifetime of a IMAP connection, responsible for:

    1. Opening the TCP socket, wrapping it in SSL if necessary
    2. Handling receiving and parsing from the server and dispatching events
    3. Sending requests to the server
    4. Shutting down and closing the socket
    """

    def __init__(self, parent):
        super().__init__(parent._main, parent)
        self._sock = None
        self._capabilities = None

        self._untagged_handlers = {}
        self._tagged_handlers = {}
        self._tag = 0

        self._parser = imap.parser.IMAP4Parser()
        self._recv_want = 0
        self._recv_buf = bytearray(4096)

        self._send_want = 0
        self._send_pos = 0
        self._send_queue = collections.deque()

        self._select_events = 0

    # Connection state machine.

    def start(self):
        super().start()
        addr = (self._main._config.imap.host, self._main._config.imap.port)
        tcp_connect_op = TCPConnectOperation(self, addr)
        tcp_connect_op.callback = self._tcp_connect_done
        tcp_connect_op.start()

    def done(self):
        if self._select_events != 0:
            self._main._sel.unregister(self._sock)
        if self._sock:
            self._sock.shutdown(socket.SHUT_RDWR)
            self._sock.close()
        super().done()

    def _tcp_connect_done(self, op):
        if op.socket:
            if self._main._config.imap.ssl:
                handshake_op = SSLHandshakeOperation(self, op.socket,
                                                     self._main._config.imap.host)
                handshake_op.callback = self._ssl_done
                handshake_op.start()
            else:
                self._sock = op.socket
                self._start_greeting()
        self.dec_pending()

    def _ssl_done(self, op):
        if op.socket:
            self._sock = op.socket
            self._start_greeting()
        self.dec_pending()

    def _start_greeting(self):
        self.inc_pending()  # Until the socket disconnects
        self.update_status('Connected', StatusLevel.info)
        greeting_op = IMAPGreetingOperation(self)
        greeting_op.callback = self._greeting_done
        greeting_op.start()
        self._try_recv()

    def _greeting_done(self, op):
        if op.result == 'OK':
            state = IMAPNotAuthenticatedState(self, self._main._config.imap.user,
                                              self._main._config.imap.password)
            state.callback = self._not_authenticated_done
            state.start()
        elif op.result == 'PREAUTH':
            assert False, "TODO"
        self.dec_pending()

    def _not_authenticated_done(self, op):
        if op.authed:
            state = _IMAPAuthenticatedState(self)
            state.callback = self._authenticated_done
            state.start()
        self.dec_pending()

    def _authenticated_done(self, op):
        if op._selected:
            state = _IMAPSelectedState(self, op._mailbox)
            state.callback = self._selected_done
            state.start()
        self.dec_pending()

    def _selected_done(self, op):
        if op._closed:
            state = _IMAPAuthenticatedState(self)
            state.callback = self._authenticated_done
            state.start()
        self.dec_pending()

    # Send/receive.

    @callback_stack
    def _handle_continue_req(self):
        self.continue_cmd()
        return True

    def continue_cmd(self):
        self._send_queue[0][1].pop(0)
        self._try_send()

    def _enqueue_cmd(self, callback, cmd, *args, **kwds):
        format = getattr(imap.formatter, 'format_' + cmd.lower())
        buf = bytearray()
        self._tag += 1
        tag = 'A%03d' % self._tag
        conts = format(buf, tag, *args, **kwds)
        self._send_queue.append((buf, conts))
        self._tagged_handlers[tag] = callback
        self._try_send()

    def _select_sock(self, mask):
        if mask & self._recv_want:
            self._try_recv()
        if mask & self._send_want:
            self._try_send()

    def _try_recv(self):
        self._recv_want = 0
        while True:
            try:
                n = self._sock.recv_into(self._recv_buf)
                if n == 0:
                    self.update_status('Disconnected', StatusLevel.error)
                    self.dec_pending()
                    return
                self._try_parse(self._recv_buf[:n])
            except BlockingIOError:
                self._recv_want = selectors.EVENT_READ
                break
            except ssl.SSLWantReadError:
                self._recv_want = selectors.EVENT_READ
                break
            except ssl.SSLWantWriteError:
                self._recv_want = selectors.EVENT_WRITE
                break
        self._modify_selector()

    def _try_parse(self, buf):
        self._parser.feed(buf)
        while True:
            try:
                resp = self._parser.parse_response_line()
                self._parser.advance()
            except imap.parser.IMAPShortParse:
                break
            #  logging.debug('Parsed %s' % repr(resp))
            if isinstance(resp, imap.parser.UntaggedResponse):
                self._untagged_handlers[resp.type](resp)
            elif isinstance(resp, imap.parser.TaggedResponse):
                self._tagged_handlers[resp.tag](resp)
                del self._tagged_handlers[resp.tag]
            elif isinstance(resp, imap.parser.ContinueReq):
                self._handle_continue_req()
            else:
                assert False

    def _try_send(self):
        self._send_want = 0
        while True:
            if len(self._send_queue) == 0:
                break
            send_buf, conts = self._send_queue[0]
            if conts and self._send_pos == conts[0]:
                break
            end = conts[0] if conts else len(send_buf)
            # logging.debug('Sending %r' % send_buf[self._send_pos:end])
            try:
                n = self._sock.send(send_buf[self._send_pos:end])
                self._send_pos += n
                if self._send_pos >= len(send_buf):
                    self._send_queue.popleft()
                    self._send_pos = 0
            except BlockingIOError:
                self._send_want = selectors.EVENT_WRITE
                break
            except ssl.SSLWantReadError:
                self._send_want = selectors.EVENT_READ
                break
            except ssl.SSLWantWriteError:
                self._send_want = selectors.EVENT_WRITE
                break
        self._modify_selector()

    def _modify_selector(self):
        events = self._recv_want | self._send_want
        if events == self._select_events:
            return
        if events == 0:
            self._main._sel.unregister(self._sock)
        elif self._select_events == 0:
            self._main._sel.register(self._sock, events, self._select_sock)
        else:
            self._main._sel.modify(self._sock, events, self._select_sock)
        self._select_events = events

    # Misc.

    def have_capability(self, capability):
        """Return whether the server supports the given capability."""
        return capability in self._capabilities


class TCPConnectOperation(MainSubOperation):
    """
    Operation for opening a TCP connection to the server.

    Arguments:
    parent -- parent operation
    address -- TCP address (host, port) to connect to
    timeout -- number of seconds to wait for the connection

    Attributes:
    socket -- when the operation is done, this will either be a connected
    TCP socket on success or None on error
    """

    def __init__(self, parent, address, timeout=30):
        super().__init__(parent._main, parent)
        self.socket = None
        self._addr = address
        self._timeout = timeout
        self._timerfd = None

    def start(self):
        super().start()
        self.update_status('Connecting...', StatusLevel.info)
        self.inc_pending()  # Until connection completes
        try:
            self.socket = socket.socket()
            self.socket.setblocking(False)
            self.socket.connect(self._addr)
        except BlockingIOError:
            pass
        except OSError as e:
            self.update_status("Error connecting to server: '%s'" % e.strerror,
                               StatusLevel.error)
            self.socket.close()
            self.socket = None
            self.dec_pending()
            return
        self._main._sel.register(self.socket, selectors.EVENT_WRITE,
                                 self._select_connect)
        flags = timerfd.TFD_CLOEXEC | timerfd.TFD_NONBLOCK
        self._timerfd = timerfd.TimerFD(flags=flags)
        self._timerfd.settime(self._timeout)
        self._main._sel.register(self._timerfd, selectors.EVENT_READ,
                                 self._select_timer)

    def _select_connect(self, mask):
        if not self._pending:
            return
        self._main._sel.unregister(self.socket)
        self._main._sel.unregister(self._timerfd)
        self._timerfd.close()

        errno = self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if errno:
            self.update_status("Error connecting to server: '%s'" % os.strerror(errno),
                               StatusLevel.error)
            self.socket.close()
            self.socket = None
        self.dec_pending()

    def _select_timer(self, mask):
        if not self._pending:
            return
        self._main._sel.unregister(self.socket)
        self._main._sel.unregister(self._timerfd)
        self._timerfd.close()

        self.update_status('Timed out while connecting', StatusLevel.error)
        self.socket.close()
        self.socket = None
        self.dec_pending()


class SSLHandshakeOperation(MainSubOperation):
    """
    Operation for wrapping a socket in SSL and doing the handshake.

    Arguments:
    parent -- parent operation
    socket -- TCP socket to wrap
    timeout -- number of seconds to wait for the handshake to complete

    Attributes:
    socket -- when the operation is done, this will either be a connected SSL
    socket on success or None on error, in which case the original TCP socket
    will be closed
    """

    def __init__(self, parent, socket, server_hostname, cafile=None, timeout=30):
        super().__init__(parent._main, parent)
        self.socket = socket
        self._server_hostname = server_hostname
        self._cafile = cafile
        self._timeout = timeout
        self._timerfd = None

    def start(self):
        super().start()
        self.update_status('Doing SSL handshake...', StatusLevel.info)
        self.inc_pending()  # Until SSL handshake completes
        context = ssl.create_default_context()
        try:
            if self._cafile:
                context.load_verify_locations(cafile=self._cafile)
        except OSError as e:
            self.update_status("Error opening CA file: '%s'" % e.strerror,
                               StatusLevel.error)
            self.socket.shutdown(socket.SHUT_RDWR)
            self.socket.close()
            self.socket = None
            self.dec_pending()
            return
        self.socket = context.wrap_socket(self.socket, do_handshake_on_connect=False,
                                          server_hostname=self._server_hostname)
        self._main._sel.register(self.socket, selectors.EVENT_READ | selectors.EVENT_WRITE,
                                 self._select_handshake)
        flags = timerfd.TFD_CLOEXEC | timerfd.TFD_NONBLOCK
        self._timerfd = timerfd.TimerFD(flags=flags)
        self._timerfd.settime(self._timeout)
        self._main._sel.register(self._timerfd, selectors.EVENT_READ,
                                 self._select_timer)

    def _select_handshake(self, mask):
        if not self._pending:
            return
        try:
            self.socket.do_handshake()
        except ssl.SSLWantReadError:
            self._main._sel.modify(self.socket, selectors.EVENT_READ,
                                   self._select_handshake)
            return
        except ssl.SSLWantWriteError:
            self._main._sel.modify(self.socket, selectors.EVENT_WRITE,
                                   self._select_handshake)
            return
        except ssl.SSLError as e:
            self.update_status("Error during SSL handshake: '%s'" % e.reason,
                               StatusLevel.error)
            self._tear_down()
            self.dec_pending()
            return
        except ssl.CertificateError as e:
            self.update_status("Error during SSL handshake: '%s'" % e,
                               StatusLevel.error)
            self._tear_down()
            self.dec_pending()
            return
        except OSError as e:
            self.update_status("Error during SSL handshake: '%s'" % e.strerror,
                               StatusLevel.error)
            self._tear_down()
            self.dec_pending()
            return
        self._main._sel.unregister(self.socket)
        self._main._sel.unregister(self._timerfd)
        self._timerfd.close()
        self.dec_pending()

    def _select_timer(self, mask):
        if not self._pending:
            return
        self._tear_down()
        self.update_status('Timed out during SSL handshake', StatusLevel.error)
        self.dec_pending()

    def _tear_down(self):
        self._main._sel.unregister(self._timerfd)
        self._timerfd.close()
        self._main._sel.unregister(self.socket)
        self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()
        self.socket = None


def _untagged_handler(type_):
    def decorator(f):
        f._untagged_type = type_
        return f
    return decorator


def _continue_req_handler(f):
    f._continue_req = True
    return f


class _IMAPOperation(MainSubOperation):
    def __init__(self, imap, parent=None):
        super().__init__(parent if parent else imap)
        self._imap = imap
        self._workqueue = self._imap._parent
        self._main = self._imap._main
        self._model = self._main._model

    def start(self):
        super().start()
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if hasattr(attr, '_untagged_type'):
                try:
                    self._imap._untagged_handlers[attr._untagged_type].register(attr)
                except KeyError:
                    callback_stack = CallbackStack()
                    callback_stack.register(attr)
                    self._imap._untagged_handlers[attr._untagged_type] = callback_stack
            if hasattr(attr, '_continue_req'):
                self._imap._handle_continue_req.register(attr)

    def done(self):
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if hasattr(attr, '_untagged_type'):
                self._imap._untagged_handlers[attr._untagged_type].unregister(attr)
            if hasattr(attr, '_continue_req'):
                self._imap._handle_continue_req.unregister(attr)
        super().done()

    def _handle_tagged(self, resp):
        if resp.type != 'OK':
            self._bad_response(resp)
        self.dec_pending()

    def _enqueue_cmd(self, callback, cmd, *args, **kwds):
        self.inc_pending()
        self._imap._enqueue_cmd(callback, cmd, *args, **kwds)

    def _bad_response(self, resp):
        # TODO
        self.update_status('IMAP command failed', StatusLevel.error)
        assert False, repr(resp)


class _IMAPStateOperation(_IMAPOperation):
    pass


class _IMAPSubOperation(_IMAPOperation):
    def __init__(self, parent):
        super().__init__(parent._imap, parent)


class IMAPGreetingOperation(_IMAPOperation):
    """Operation for waiting for the greeting from the IMAP server."""

    def __init__(self, imap):
        super().__init__(imap)
        self.result = None

    def start(self):
        super().start()
        self.inc_pending()  # Until we get the greeting

    @_untagged_handler('OK')
    def _handle_ok(self, resp):
        self.result = 'OK'
        self.dec_pending()
        return True

    @_untagged_handler('PREAUTH')
    def _handle_preauth(self, resp):
        self.result = 'PREAUTH'
        self.dec_pending()
        return True

    @_untagged_handler('BYE')
    def _handle_bye(self, resp):
        self.result = 'BYE'
        self.update_status("Rejected by server: '%s'" % resp.data.text,
                           StatusLevel.error)
        self.dec_pending()
        return True


class IMAPNotAuthenticatedState(_IMAPStateOperation):
    """
    IMAP Not Authenticated state: immediately attempts to authenticate.
    """

    def __init__(self, imap, user, password):
        super().__init__(imap)
        self._user = user
        self._password = password
        self.authed = False

    def start(self):
        super().start()
        self._enqueue_cmd(self._handle_tagged_capability, 'CAPABILITY')

    @_untagged_handler('CAPABILITY')
    def _handle_capability(self, resp):
        self._imap._capabilities = resp.data
        return True

    def _handle_tagged_capability(self, resp):
        if resp.type == 'OK':
            if not self._imap.have_capability('IMAP4rev1'):
                self.update_status('Server is missing IMAP4rev1 capability',
                                   StatusLevel.error)
                self.dec_pending()
                return
            if not self._imap.have_capability('AUTH=PLAIN') or \
               self._imap.have_capability('LOGINDISABLED'):
                self.update_status('Cannot authenticate', StatusLevel.error)
                self.dec_pending()
                return
            self.update_status('Authenticating...', StatusLevel.info)
            username = self._user
            password = self._password
            self._enqueue_cmd(self._handle_tagged_login, 'LOGIN', username, password)
        else:
            self._bad_response(resp)
        self.dec_pending()

    def _handle_tagged_login(self, resp):
        if resp.type == 'OK':
            self.update_status('Login succeeded', StatusLevel.info)
            self.authed = True
        else:
            self.update_status('Login failed', StatusLevel.error)
        self.dec_pending()


class _IMAPAuthenticatedState(_IMAPStateOperation):
    """
    IMAP Authenticated state: immediately attempts to select a mailbox.
    """

    def __init__(self, imap):
        super().__init__(imap)
        self._mailbox = None
        self._selected = False
        self._logged_out = False

    def start(self):
        super().start()
        self.inc_pending()  # Until we change state
        self._process_work()

    def _process_work(self):
        if self._workqueue.have_work():
            work = self._workqueue.get_work()
            if work.type == Work.Type.logout:
                self.update_status('Logging out', StatusLevel.info)
                self._enqueue_cmd(lambda op: self._handle_tagged_logout(op, work),
                                  'LOGOUT')
            elif work.type == Work.Type.refresh_list:
                list_op = IMAPListOperation(self)
                list_op.callback = lambda op: self._list_done(op, work)
                list_op.start()
            elif work.type == Work.Type.select:
                self._mailbox, = work.args
                self.update_status('Selecting %s...' % self._mailbox.name_decoded,
                                   StatusLevel.info)
                self._enqueue_cmd(lambda op: self._handle_tagged_select(op, work),
                                  'EXAMINE', self._mailbox.name)
            else:
                assert False, work.type
        else:
            self._workqueue.wait_for_work(self._process_work)

    def _handle_tagged_logout(self, resp, work):
        if resp.type == 'OK':
            self._workqueue.finish_work(work)
            self.dec_pending()  # Change state
        else:
            self._bad_response(resp)
            self._workqueue.fail_work(work)
        self.dec_pending()

    def _list_done(self, op, work):
        self._workqueue.finish_work(work)
        self._process_work()
        self.dec_pending()

    def _handle_tagged_select(self, resp, work):
        if resp.type == 'OK':
            self._imap.select = None
            self._selected = True
            self._workqueue.finish_work(work)
            self.dec_pending()  # Change state
        elif resp.type == 'NO':
            self.update_status('Could not open %s' % self._mailbox.name_decoded,
                               StatusLevel.error)
            self._mailbox = None
            self._workqueue.fail_selected_work(work)
            self._process_work()
        else:
            self._bad_response(resp)
            self._workqueue.fail_work(work)
            self._process_work()
        self.dec_pending()

    @_untagged_handler('BYE')
    def _handle_bye(self, resp):
        self._logged_out = True
        return True

    @_untagged_handler('RECENT')
    def _handle_recent(self, resp):
        self._mailbox.recent = resp.data
        return True

    @_untagged_handler('FLAGS')
    def _handle_flags(self, resp):
        self._mailbox.flags = resp.data
        return True

    @_untagged_handler('EXISTS')
    def _handle_exists(self, resp):
        self._mailbox.exists = resp.data
        return True

    @_untagged_handler('OK')
    def _handle_ok(self, resp):
        # TODO
        return True


class IMAPListOperation(_IMAPSubOperation):
    """Refresh the list of mailboxes."""

    def __init__(self, state, selected=None):
        super().__init__(state)
        self._list_status = self._imap.have_capability('LIST-STATUS')
        self._missing = {mailbox.name for mailbox in self._model.mailboxes()}
        self._selected = set() if selected is None else selected

    def start(self):
        super().start()
        self.update_status('Refreshing mailbox list...', StatusLevel.info)
        if self._list_status:
            status_items = ['MESSAGES', 'UNSEEN']
        else:
            status_items = None
        self._enqueue_cmd(self._handle_tagged_list, 'LIST', b'', b'*',
                          status_items=status_items)

    @_untagged_handler('LIST')
    def _handle_list(self, resp):
        attributes, delimiter, mailbox_name = resp.data
        try:
            self._missing.remove(mailbox_name)
        except KeyError:
            pass
        try:
            mailbox = self._model.get_mailbox(mailbox_name)
            mailbox.delimiter = delimiter
            mailbox.attributes = attributes
        except KeyError:
            mailbox = model.Mailbox(self._model, mailbox_name, delimiter,
                                    attributes)
            self._model.add_mailbox(mailbox)
        if not self._list_status:
            if mailbox.name not in self._selected and mailbox.can_select():
                self._enqueue_cmd(self._handle_tagged_status, 'STATUS',
                                  mailbox_name, 'MESSAGES', 'UNSEEN')
        return True

    @_untagged_handler('STATUS')
    def _handle_status(self, resp):
        if resp.data.mailbox in self._selected:
            # If we're using LIST-STATUS, the server might still send a STATUS
            # response for the selected mailbox. We want the EXISTS/EXPUNGE
            # responses to take precedence, so ignore it.
            return True
        mailbox = self._model.get_mailbox(resp.data.mailbox)
        for key, value in resp.data.status.items():
            if key == 'MESSAGES':
                mailbox.exists = value
            elif key == 'UNSEEN':
                mailbox.set_num_unseen(value)
        return True

    def _handle_tagged_list(self, resp):
        if resp.type == 'OK':
            for mailbox_name in self._missing:
                assert mailbox_name != b'INBOX'
                self._model.delete_mailbox(mailbox_name)
            self.update_status('Refreshed mailbox list', StatusLevel.info)
        else:
            self._bad_response(resp)
        self.dec_pending()

    def _handle_tagged_status(self, resp):
        if resp.type != 'OK':
            self._bad_response(resp)
        self.dec_pending()


class _IMAPSelectedState(_IMAPStateOperation):
    """
    IMAP Selected state.
    """

    def __init__(self, imap, mailbox):
        super().__init__(imap)
        self._mailbox = mailbox
        self._seque = SequenceQueue()
        self._gmail = self._imap.have_capability('X-GM-EXT-1')
        self._idle = self._imap.have_capability('IDLE')
        self._fetching = False
        self._closed = False

    def start(self):
        super().start()
        self.inc_pending()  # Until we change state
        self.update_status('Selected %s' % self._mailbox.name_decoded,
                           StatusLevel.info)
        self._mailbox.uids = [None] * (self._mailbox.exists + 1)
        if self._mailbox.exists:
            self._seque.put(1, self._mailbox.exists)
        unseen_op = IMAPPopulateUnseenOperation(self)
        unseen_op.callback = self._unseen_done
        unseen_op.start()

    def _unseen_done(self, op):
        if op.bad is not None:
            self.update_status('Could not search unseen messages',
                               StatusLevel.error)
            self._gmail_hack(op.bad)
        else:
            self._mailbox.set_unseen(op.unseen)
            self._process_work()
        self.dec_pending()

    def _process_work(self):
        if self._workqueue.have_work():
            work = self._workqueue.get_work()
            if work.type == Work.Type.refresh_list:
                list_op = IMAPListOperation(self, {self._mailbox.name})
                list_op.callback = lambda op: self._list_done(op, work)
                list_op.start()
            elif work.type == Work.Type.close:
                # TODO: when should we expunge instead?
                self._enqueue_cmd(lambda resp: self._handle_tagged_close(resp, work),
                                  'CLOSE')
            elif work.type == Work.Type.fetch_bodystructure:
                uid, = work.args
                self._enqueue_cmd(lambda resp: self._handle_tagged_fetch(resp, work),
                                  'FETCH', [uid], 'BODYSTRUCTURE', uid=True)
            elif work.type == Work.Type.fetch_body_sections:
                # TODO: partial fetches if too big/background downloads?
                uid, sections = work.args
                self._enqueue_cmd(lambda resp: self._handle_tagged_fetch(resp, work),
                                  'FETCH', [uid], *['BODY.PEEK[%s]' % section for section in sections], uid=True)
            else:
                assert False
        elif len(self._seque) > 0:
            self._fetch_new_messages()
        elif self._idle:
            idle_op = IMAPIdleOperation(self)
            idle_op.callback = self._idle_done
            idle_op.start()
        else:
            self._workqueue.wait_for_work(self._process_work)

    def _list_done(self, op, work):
        self._workqueue.finish_work(work)
        self._process_work()
        self.dec_pending()

    def _handle_tagged_close(self, resp, work):
        if resp.type == 'OK':
            self._closed = True
            self._workqueue.finish_work(work)
            self.dec_pending()  # Change state
        elif resp.type == 'BAD':
            self._gmail_hack(resp, work)
        else:
            assert False
        self.dec_pending()
        return True

    def _gmail_hack(self, resp, work=None):
        self._enqueue_cmd(lambda resp2: self._handle_gmail_hack(resp2, resp, work),
                          'CHECK')

    def _handle_gmail_hack(self, resp, orig_resp, orig_work):
        # XXX: At the time of this writing on 11/15/15, if the selected mailbox
        # gets deleted, Gmail will kick you out of the Selected state into the
        # Authenticated state as soon as you execute a NOOP or IDLE command
        # (maybe others). Then, commands which are only valid in the Selected
        # state will result in a BAD response. So, when we get a BAD response,
        # we're forced to assume that this is the case and try a CHECK to
        # verify that this is what happened.
        if resp.type == 'OK':
            # If CHECK succeeded, the previous response was a legitimate BAD
            # response
            self._bad_response(orig_resp)
            if orig_work:
                assert orig_work.type != Work.Type.close, "CLOSE failed"
                self._workqueue.fail_work(orig_work)
            self._process_work()
        elif resp.type == 'BAD':
            # If CHECK also failed, this is probably because of the Gmail bug.
            # Fail the original work and fall back to the Authenticated state.
            self._closed = True
            if orig_work:
                self._workqueue.fail_selected_work(orig_work)
            self.dec_pending()  # Change state
        else:
            assert False
        self.dec_pending()
        return True

    def _handle_tagged_fetch(self, resp, work):
        if resp.type == 'OK':
            self._workqueue.finish_work(work)
            self._process_work()
        elif resp.type == 'BAD':
            self.update_status('Could not fetch message', StatusLevel.error)
            self._gmail_hack(resp, work)
        elif resp.type == 'NO':
            assert False, "TODO"
        else:
            assert False
        self.dec_pending()

    def _fetch_new_messages(self):
        assert not self._fetching
        self._fetching = True
        self.update_status('Fetching %s (%d)' % (self._mailbox.name_decoded, len(self._seque)),
                           StatusLevel.info)
        fetch_op = GmailFetchMessagesOperation(self, self._seque.get(50))
        fetch_op.callback = self._fetch_new_done
        fetch_op.start()

    def _fetch_new_done(self, op):
        self._fetching = False
        if op.bad is not None:
            self.update_status('Could not fetch messages', StatusLevel.error)
            self._gmail_hack(op.bad)
        else:
            # Do a NOOP after each FETCH to make sure we get new messages that
            # just arrived before old ones.
            self._enqueue_cmd(self._handle_tagged_noop, 'NOOP')
        self.dec_pending()

    def _handle_tagged_noop(self, resp):
        if resp.type == 'OK':
            self._process_work()
        else:
            self._bad_response(resp)
            self._process_work()
        self.dec_pending()

    def _idle_done(self, op):
        self._process_work()
        self.dec_pending()

    @_untagged_handler('RECENT')
    def _handle_recent(self, resp):
        self._mailbox.recent = resp.data
        return True

    @_untagged_handler('EXISTS')
    def _handle_exists(self, resp):
        exists = resp.data
        assert exists >= self._mailbox.exists
        if exists > self._mailbox.exists:
            self._seque.put(self._mailbox.exists + 1, exists)
            self._mailbox.uids.extend([None] * (exists - self._mailbox.exists))
            self._mailbox.exists = exists
            assert len(self._mailbox.uids) - 1 == self._mailbox.exists
        return True

    @_untagged_handler('EXPUNGE')
    def _handle_expunge(self, resp):
        assert resp.data <= self._mailbox.exists
        uid = self._mailbox.uids.pop(resp.data)
        self._mailbox.exists -= 1
        assert len(self._mailbox.uids) - 1 == self._mailbox.exists
        if uid is None:
            # TODO: garbage collection of UIDs that we don't fetch before they
            # get expunged.
            assert False
        else:
            self._mailbox.delete_message(uid)
        self._seque.delete(resp.data)
        return True

    @_untagged_handler('FETCH')
    def _handle_fetch(self, resp):
        fetch = resp.data
        try:
            uid = self._mailbox.uids[fetch.msg]
            message = self._mailbox.get_message(uid)
        except KeyError:
            # XXX
            return True
        if 'ENVELOPE' in fetch.items:
            message.envelope = fetch.items['ENVELOPE']
        if 'BODYSTRUCTURE' in fetch.items:
            message.bodystructure = fetch.items['BODYSTRUCTURE']
        if 'FLAGS' in fetch.items:
            message.flags = fetch.items['FLAGS']
            if '\\Seen' in message.flags:
                self._mailbox.remove_unseen(uid)
            else:
                self._mailbox.add_unseen(uid)
        if 'BODY[]' in fetch.items:
            message.add_body_sections(fetch.items['BODY[]'])
        return True


class IMAPPopulateUnseenOperation(_IMAPSubOperation):
    def __init__(self, state):
        super().__init__(state)
        self.unseen = None
        self.bad = None

    def start(self):
        super().start()
        self._enqueue_cmd(self._handle_tagged_search, 'SEARCH', ('UNSEEN',), uid=True)

    @_untagged_handler('SEARCH')
    def _handle_search(self, resp):
        self.unseen = resp.data
        return True

    def _handle_tagged_search(self, resp):
        if resp.type == 'BAD':
            self.bad = resp
        elif resp.type != 'OK':
            assert False, "TODO"
        self.dec_pending()
        return True


class GmailFetchMessagesOperation(_IMAPSubOperation):
    def __init__(self, state, seq_set):
        super().__init__(state)
        self._mailbox = state._mailbox
        self._fetching_uids = False
        self._fetching_gm_msgids = False
        self._seq_set = seq_set
        self.bad = None

    def start(self):
        super().start()
        self._fetching_uids = True
        self._new_uids = set()
        self._old_uids = set()
        self._enqueue_cmd(self._handle_tagged_fetch_uids,
                          'FETCH', self._seq_set, 'UID')

    def _handle_tagged_fetch_uids(self, resp):
        if resp.type == 'BAD':
            self.bad = resp
            self.dec_pending()
            return True
        elif resp.type != 'OK':
            assert False, "TODO"
        new_uids = self._new_uids
        old_uids = self._old_uids
        del self._new_uids, self._old_uids
        self._fetching_uids = False
        if new_uids:
            self._fetching_gm_msgids = True
            seq_set = imap.sequence_set(new_uids)
            self._new_gm_msgids = set()
            self._enqueue_cmd(self._handle_tagged_fetch_gm_msgids,
                              'FETCH', seq_set, 'X-GM-MSGID')
        if old_uids:
            seq_set = imap.sequence_set(old_uids)
            self._enqueue_cmd(self._handle_tagged,
                              'FETCH', seq_set, 'FLAGS')
        self.dec_pending()
        return True

    def _handle_tagged_fetch_gm_msgids(self, resp):
        if resp.type == 'BAD':
            self.bad = resp
            self.dec_pending()
            return True
        elif resp.type != 'OK':
            assert False, "TODO"
        new_gm_msgids = self._new_gm_msgids
        del self._new_gm_msgids
        self._fetching_gm_msgids = False
        if new_gm_msgids:
            seq_set = imap.sequence_set(new_gm_msgids)
            self._enqueue_cmd(self._handle_tagged, 'FETCH', seq_set,
                              'ENVELOPE', 'FLAGS')
        self.dec_pending()
        return True

    @_untagged_handler('EXPUNGE')
    def _handle_expunge(self, resp):
        # This MUST NOT happen while we're doing a FETCH. If it did, there's a
        # bug in the server or the client, so fail hard before we do any
        # permanent damage because our sequence numbers got out of sync.
        assert False, "Got EXPUNGE during FETCH"

    @_untagged_handler('FETCH')
    def _handle_fetch(self, resp):
        fetch = resp.data
        if self._fetching_uids:
            uid = fetch.items['UID']
            self._mailbox.uids[fetch.msg] = uid
            if self._mailbox.contains_message(uid):
                self._old_uids.add(fetch.msg)
            else:
                self._new_uids.add(fetch.msg)
        if self._fetching_gm_msgids:
            uid = self._mailbox.uids[fetch.msg]
            assert uid is not None
            msgid = fetch.items['X-GM-MSGID']
            try:
                message = self._model.gmail_msgs[msgid]
            except KeyError:
                message = model.Message(self._model, msgid)
                self._model.gmail_msgs[msgid] = message
                self._new_gm_msgids.add(fetch.msg)
            self._mailbox.add_message(uid, message)
        # _IMAPSelectedState handles other FETCH items
        return False


class IMAPIdleOperation(_IMAPSubOperation):
    def __init__(self, state):
        super().__init__(state)
        self._mailbox = state._mailbox
        self._got_continue_req = False
        self._done = False
        self._refresh = False

    def start(self):
        super().start()
        self.update_status('Idling', StatusLevel.info)
        self._enqueue_cmd(self._handle_tagged, 'IDLE')
        self._workqueue.wait_for_work(self._idle_done)

    def _idle_done(self):
        self._done = True
        if self._got_continue_req:
            self._imap.continue_cmd()

    @_continue_req_handler
    def _handle_continue_req(self):
        self._got_continue_req = True
        if self._done:
            self._imap.continue_cmd()
        return True

    @_untagged_handler('EXISTS')
    def _handle_exists(self, resp):
        if resp.data > self._mailbox.exists:
            self._workqueue.cancel_wait(self._idle_done)
            self._idle_done()
        # _IMAPSelectedState needs to update the model.
        return False
