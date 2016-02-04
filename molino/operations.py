import collections
import enum
import errno
import logging
import os
import selectors
import signal
import socket
import ssl
import sys

import imap4
import imap4.parser
from molino.callbackstack import CallbackStack, callback_stack
from molino.imap import decode_mailbox_name
import molino.imap.formatter
import molino.imap as imap
from molino.view import StatusLevel
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
        # logging.debug('%r +1 = %d' % (self, self._pending + 1))
        self._pending += 1

    def dec_pending(self):
        """
        Decrement the count pending actions this operation is waiting on. If
        the count reaches zero, call self.done() to cleanup.
        """
        # logging.debug('%r -1 = %d' % (self, self._pending - 1))
        assert self._pending > 0
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

    def __init__(self, config, cache, view):
        super().__init__(None)
        self._config = config
        self._cache = cache
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
        self._cache = self._main._cache

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
        self._workqueue.select_mailbox('INBOX')

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
    def _handle_open_message(self, mailbox, uid, fetch_bodystructure):
        if self._workqueue:
            self._workqueue.select_mailbox(mailbox)
            if fetch_bodystructure:
                self._workqueue.fetch_bodystructure(uid)
        return True

    @_view_event_handler('read_body_sections')
    def _handle_open_body_sections(self, mailbox, uid, sections):
        if self._workqueue:
            self._workqueue.select_mailbox(mailbox)
            if sections:
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

    def __eq__(self, other):
        return self.type == other.type and self.args == other.args

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
        NotConnectedOperation(self).start()

    def have_work(self):
        return len(self._queue) > 0

    def get_work(self):
        return self._queue[0]

    def finish_work(self, work):
        assert work == self._queue[0]
        self._queue.popleft()

    def fail_selected_work(self, work):
        assert work == self._queue[0]
        self._queue.popleft()
        stack = []
        while self._queue and self._queue[0].type not in [Work.Type.select, Work.Type.close]:
            work2 = self._queue.popleft()
            if not work2.is_selected_state():
                stack.append(work2)
        if not self._queue == 0:
            self.selected = None
        self._queue.extendleft(reversed(stack))

    def fail_all_work(self):
        while self.have_work():
            work = self.get_work()
            if work.type == Work.Type.select or work.is_selected_state():
                self.fail_selected_work(work)
            else:
                self.finish_work(work)

    def wait_for_work(self, callback):
        assert self._callback is None, self._callback
        self._callback = callback

    def cancel_wait(self, callback):
        assert self._callback == callback
        self._callback = None

    def _add_work(self, work, combine_duplicates=True):
        if combine_duplicates and self._queue and self._queue[-1] == work:
            return
        self._queue.append(work)

    def _work_added(self):
        if self._callback:
            callback = self._callback
            self._callback = None
            callback()

    def quit(self):
        self._quit = True
        if self.selected:
            self._add_work(Work(Work.Type.close), False)
            self.selected = None
        self._add_work(Work(Work.Type.logout), False)
        self._work_added()

    def refresh_mailbox_list(self):
        self._add_work(Work(Work.Type.refresh_list))
        self._work_added()

    def select_mailbox(self, mailbox):
        if mailbox != self.selected:
            if self.selected:
                self._add_work(Work(Work.Type.close), False)
            self.selected = mailbox
            self._add_work(Work(Work.Type.select, mailbox), False)
            self._work_added()

    def fetch_bodystructure(self, uid):
        self._add_work(Work(Work.Type.fetch_bodystructure, uid))
        self._work_added()

    def fetch_body_sections(self, uid, sections):
        self._add_work(Work(Work.Type.fetch_body_sections, uid, sections))
        self._work_added()


class NotConnectedOperation(MainSubOperation):
    """
    Operation while there is no open connection to the IMAP server. When work
    arrives, attempts to open a new connection.
    """

    def __init__(self, workqueue):
        super().__init__(workqueue._main, workqueue)
        self._workqueue = workqueue
        self.socket = None

    def start(self):
        super().start()
        self.inc_pending()
        self._process_work()

    def _process_work(self):
        if self._workqueue._quit:
            self.dec_pending()
            return
        if self._workqueue.have_work():
            addr = (self._main._config.imap.host, self._main._config.imap.port)
            tcp_connect_op = TCPConnectOperation(self, addr)
            tcp_connect_op.callback = self._tcp_connect_done
            tcp_connect_op.start()
        else:
            self._workqueue.wait_for_work(self._process_work)

    def _tcp_connect_done(self, op):
        if op.socket:
            if self._main._config.imap.ssl:
                handshake_op = SSLHandshakeOperation(self, op.socket,
                                                     self._main._config.imap.host)
                handshake_op.callback = self._ssl_done
                handshake_op.start()
            else:
                self._success(op.socket)
        else:
            self._failure()
        self.dec_pending()

    def _ssl_done(self, op):
        if op.socket:
            self._success(op.socket)
        else:
            self._failure()
        self.dec_pending()

    def _success(self, sock):
        _IMAPConnectionOperation(self._workqueue, sock).start()
        self.dec_pending()

    def _failure(self):
        self._workqueue.fail_all_work()
        if self._workqueue._quit:
            self.dec_pending()
            return
        self._workqueue.wait_for_work(self._process_work)


class _IMAPConnectionOperation(MainSubOperation):
    """
    Operation for the entire lifetime of a IMAP connection, responsible for:

    1. Handling receiving and parsing from the server and dispatching events
    2. Sending requests to the server
    3. Shutting down and closing the socket
    """

    def __init__(self, workqueue, socket):
        super().__init__(workqueue._main, workqueue)
        self._workqueue = workqueue
        self._sock = socket
        self._capabilities = None

        self._untagged_handlers = {}
        self._tagged_handlers = {}
        self._tag = 0

        self._scanner = imap4.parser.IMAPScanner()
        self._recv_want = 0
        self._recv_buf = bytearray(4096)

        self._send_want = 0
        self._send_pos = 0
        self._send_queue = collections.deque()

        self._select_events = 0
        self.disconnected = False

    # Connection state machine.

    def start(self):
        super().start()
        # See issue #26273; TCP_USER_TIMEOUT isn't defined in the socket
        # module.
        self._sock.setsockopt(socket.IPPROTO_TCP, 18, 60000)
        self._start_greeting()

    def done(self):
        if self._select_events != 0:
            self._main._sel.unregister(self._sock)
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError as e:
                if e.errno != errno.ENOTCONN:
                    raise e
            self._sock.close()
        super().done()

    def _start_greeting(self):
        self.inc_pending()  # Until the socket disconnects
        self.update_status('Connected', StatusLevel.info)
        greeting_op = IMAPGreetingOperation(self)
        greeting_op.callback = self._greeting_done
        greeting_op.start()
        self._try_recv()

    def _greeting_done(self, op):
        if op.result == imap4.OK:
            state = IMAPNotAuthenticatedState(self, self._main._config.imap.user,
                                              self._main._config.imap.password)
            state.callback = self._not_authenticated_done
            state.start()
        elif op.result == imap4.PREAUTH:
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
        return tag

    def _select_sock(self, mask):
        if mask & self._recv_want:
            self._try_recv()
        if mask & self._send_want:
            self._try_send()

    def _try_recv(self):
        self._recv_want = 0
        while not self.disconnected:
            try:
                n = self._sock.recv_into(self._recv_buf)
                # logging.debug('S: %s' % self._recv_buf[:n])
                if n == 0:
                    self._sock_disconnected()
                    return
                self._try_parse(self._recv_buf, n)
            except BlockingIOError:
                self._recv_want = selectors.EVENT_READ
                break
            except ssl.SSLWantReadError:
                self._recv_want = selectors.EVENT_READ
                break
            except ssl.SSLWantWriteError:
                self._recv_want = selectors.EVENT_WRITE
                break
            except TimeoutError:
                self._sock_disconnected()
                return
        self._modify_selector()

    def _sock_disconnected(self):
        self.update_status('Disconnected', StatusLevel.error)
        self.disconnected = True
        self._workqueue.fail_all_work()
        if not self._workqueue._quit:
            NotConnectedOperation(self._workqueue).start()
        for handler in self._tagged_handlers.values():
            handler(None, True)
        self.dec_pending()

    def _try_parse(self, buf, n):
        self._scanner.feed(buf, n)
        while True:
            try:
                line = self._scanner.get()
            except imap4.parser.ScanError:
                break
            resp = imap4.parser.parse_response_line(line)
            self._scanner.consume(len(line))
            # logging.debug('Parsed %s' % repr(resp))
            if isinstance(resp, imap4.parser.UntaggedResponse):
                self._untagged_handlers[resp.type](resp)
            elif isinstance(resp, imap4.parser.TaggedResponse):
                self._tagged_handlers.pop(resp.tag)(resp, False)
            elif isinstance(resp, imap4.parser.ContinueReq):
                self._handle_continue_req()
            else:
                assert False

    def _try_send(self):
        self._send_want = 0
        while not self.disconnected:
            if len(self._send_queue) == 0:
                break
            send_buf, conts = self._send_queue[0]
            if conts and self._send_pos == conts[0]:
                break
            end = conts[0] if conts else len(send_buf)
            try:
                n = self._sock.send(send_buf[self._send_pos:end])
                # logging.debug('C: %s' % send_buf[self._send_pos:self._send_pos + n])
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
            except TimeoutError:
                self._sock_disconnected()
                return
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
        self._cache = self._main._cache

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

    def _handle_tagged(self, resp, disconnected):
        if disconnected:
            self.dec_pending()
            return
        if resp.type != imap4.OK:
            self._bad_response(resp)
        self.dec_pending()

    def _enqueue_cmd(self, callback, cmd, *args, **kwds):
        self.inc_pending()
        return self._imap._enqueue_cmd(callback, cmd, *args, **kwds)

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

    @_untagged_handler(imap4.OK)
    def _handle_ok(self, resp):
        self.result = imap4.OK
        self.dec_pending()
        return True

    @_untagged_handler(imap4.PREAUTH)
    def _handle_preauth(self, resp):
        self.result = imap4.PREAUTH
        self.dec_pending()
        return True

    @_untagged_handler(imap4.BYE)
    def _handle_bye(self, resp):
        self.result = imap4.BYE
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

    @_untagged_handler(imap4.CAPABILITY)
    def _handle_capability(self, resp):
        self._imap._capabilities = resp.data
        return True

    def _handle_tagged_capability(self, resp, disconnected):
        if disconnected:
            self.dec_pending()  # Exit state
            return
        if resp.type == imap4.OK:
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

    def _handle_tagged_login(self, resp, disconnected):
        if disconnected:
            self.dec_pending()  # Exit state
            return
        if resp.type == imap4.OK:
            self.update_status('Login succeeded', StatusLevel.info)
            self.authed = True
        else:
            self.update_status('Login failed', StatusLevel.error)
        self.dec_pending()


class _IMAPAuthenticatedState(_IMAPStateOperation):
    """
    IMAP Authenticated state.
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

    def done(self):
        self._cache.commit()
        super().done()

    def _process_work(self):
        if self._imap.disconnected:
            self.dec_pending()  # Exit state
        if self._workqueue.have_work():
            work = self._workqueue.get_work()
            if work.type == Work.Type.logout:
                self.update_status('Logging out', StatusLevel.info)
                self._enqueue_cmd(lambda resp, dis: self._handle_tagged_logout(resp, dis, work),
                                  'LOGOUT')
            elif work.type == Work.Type.refresh_list:
                list_op = IMAPListOperation(self)
                list_op.callback = lambda op: self._list_done(op, work)
                list_op.start()
            elif work.type == Work.Type.select:
                self._mailbox, = work.args
                encoded_name = self._cache.mailbox_encoded_name(self._mailbox)
                self.update_status('Selecting %s...' % self._mailbox,
                                   StatusLevel.info)
                self._enqueue_cmd(lambda resp, dis: self._handle_tagged_select(resp, dis, work),
                                  'EXAMINE', encoded_name)
            else:
                assert False, work.type
        else:
            self._workqueue.wait_for_work(self._process_work)

    def _handle_tagged_logout(self, resp, disconnected, work):
        if disconnected:
            self.dec_pending()
            self.dec_pending()  # Exit state
            return
        if resp.type == imap4.OK:
            self._workqueue.finish_work(work)
            self.dec_pending()  # Change state
        else:
            self._bad_response(resp)
            assert False, "Logout failed"
        self.dec_pending()

    def _list_done(self, op, work):
        self._workqueue.finish_work(work)
        self._process_work()
        self.dec_pending()

    def _handle_tagged_select(self, resp, disconnected, work):
        if disconnected:
            self.dec_pending()
            self.dec_pending()  # Exit state
            return
        if resp.type == imap4.OK:
            self._imap.select = None
            self._selected = True
            self._workqueue.finish_work(work)
            self.dec_pending()  # Change state
        elif resp.type == imap4.NO:
            self.update_status('Could not open %s' % self._mailbox.name_decoded,
                               StatusLevel.error)
            self._mailbox = None
            self._workqueue.fail_selected_work(work)
            self._process_work()
        else:
            self._bad_response(resp)
            self._workqueue.fail_selected_work(work)
            self._process_work()
        self.dec_pending()

    @_untagged_handler(imap4.BYE)
    def _handle_bye(self, resp):
        self._logged_out = True
        return True

    @_untagged_handler(imap4.RECENT)
    def _handle_recent(self, resp):
        self._cache.update_mailbox(self._mailbox, recent=resp.data)
        return True

    @_untagged_handler(imap4.FLAGS)
    def _handle_flags(self, resp):
        self._cache.update_mailbox(self._mailbox, attributes=resp.data)
        return True

    @_untagged_handler(imap4.EXISTS)
    def _handle_exists(self, resp):
        self._cache.update_mailbox(self._mailbox, exists=resp.data)
        return True

    @_untagged_handler(imap4.OK)
    def _handle_ok(self, resp):
        if resp.data.code == imap4.UIDVALIDITY:
            old_uidvalidity = self._cache.get_mailbox_uidvalidity(self._mailbox)
            if old_uidvalidity is not None:
                assert resp.data.code_data == old_uidvalidity, "UIDVALIDITY has changed"
            self._cache.update_mailbox(self._mailbox, uidvalidity=resp.data.code_data)
        return True


class IMAPListOperation(_IMAPSubOperation):
    """Refresh the list of mailboxes."""

    def __init__(self, state, selected=None):
        super().__init__(state)
        self._list_status = self._imap.have_capability('LIST-STATUS')
        self._selected = set() if selected is None else selected

    def start(self):
        super().start()
        self.update_status('Refreshing mailbox list...', StatusLevel.info)
        self._cache.create_temp_mailbox_list()
        if self._list_status:
            status_items = ['MESSAGES', 'UNSEEN']
        else:
            status_items = None
        self._enqueue_cmd(self._handle_tagged_list, 'LIST', b'', b'*',
                          status_items=status_items)

    def done(self):
        self._cache.drop_temp_mailbox_list()
        self._cache.commit()
        super().done()

    @_untagged_handler(imap4.LIST)
    def _handle_list(self, resp):
        attributes, delimiter, raw_name = resp.data
        name = decode_mailbox_name(raw_name)
        if self._cache.has_mailbox(name):
            self._cache.update_mailbox(name, delimiter=delimiter,
                                       attributes=attributes)
        else:
            self._cache.add_mailbox(name, raw_name, delimiter=delimiter,
                                    attributes=attributes)
        self._cache.add_listing_mailbox(name)
        if not self._list_status:
            assert False, "TODO"
        return True

    @_untagged_handler(imap4.STATUS)
    def _handle_status(self, resp):
        if resp.data.mailbox in self._selected:
            # If we're using LIST-STATUS, the server might still send a STATUS
            # response for the selected mailbox. We want the EXISTS/EXPUNGE
            # responses to take precedence, so ignore it.
            return True
        name = decode_mailbox_name(resp.data.mailbox)
        self._cache.update_mailbox(name, exists=resp.data.status[imap4.MESSAGES],
                                   unseen=resp.data.status[imap4.UNSEEN])
        return True

    def _handle_tagged_list(self, resp, disconnected):
        if disconnected:
            self.dec_pending()
            return
        if resp.type == imap4.OK:
            self._cache.delete_unlisted_mailboxes()
            self.update_status('Refreshed mailbox list', StatusLevel.info)
        else:
            self._bad_response(resp)
        self.dec_pending()


GMAIL_SPECIAL_LABELS = {
    'INBOX': {b'\\Inbox'},
    '[Gmail]/All Mail': set(),
    '[Gmail]/Drafts': {b'\\Drafts'},
    '[Gmail]/Important': {b'\\Important'},
    '[Gmail]/Sent Mail': {b'\\Sent'},
    '[Gmail]/Spam': {b'\\Spam'},
    '[Gmail]/Starred': {b'\\Starred'},
    '[Gmail]/Trash': {b'\\Trash'},
}


class _IMAPSelectedState(_IMAPStateOperation):
    """
    IMAP Selected state.
    """

    def __init__(self, imap, mailbox):
        super().__init__(imap)
        self._mailbox = mailbox
        self._gmail = self._imap.have_capability('X-GM-EXT-1')
        self._idle = self._imap.have_capability('IDLE')
        self._esearch = self._imap.have_capability('ESEARCH')
        self._mailbox_labels = None
        self._uids = None
        self._unseen = None
        self._fetching_cursor = None
        self._fetching = False
        self._new_messages = 0
        self._closed = False

    def start(self):
        super().start()
        self.inc_pending()  # Until we change state
        if self._gmail:
            # XXX: For some reason, Gmail omits the label for the currently
            # selected mailbox when fetching X-GM-LABELS, so we have to add it
            # back in. Gmail's special folders have special labels, and the
            # only way to get those is with XLIST, which Google's own
            # documentation discourages using, which means that we have to
            # hard-code them.
            if self._mailbox == 'INBOX' or self._mailbox.startswith('[Gmail]'):
                self._mailbox_labels = GMAIL_SPECIAL_LABELS[self._mailbox]
            else:
                self._mailbox_labels = {self._cache.mailbox_encoded_name(self._mailbox)}
        self.update_status('Selected %s' % self._mailbox, StatusLevel.info)
        assert self._esearch, "TODO"
        search_op = IMAPPopulateEsearchOperation(self)
        search_op.callback = self._search_done
        search_op.start()

    def _search_done(self, op):
        if op.bad is not None:
            self.update_status('Could not populate message list',
                               StatusLevel.error)
            self._gmail_hack(op.bad)
        else:
            self._uids = op.uids
            self._unseen = op.unseen
            self._cache.update_mailbox(self._mailbox, exists=len(self._uids) - 1,
                                       unseen=len(self._unseen))
            self._cache.commit()
            # Fetching cursor is the lowest sequence number that we've fetched.
            self._fetching_cursor = len(self._uids)
            self._process_work()
        self.dec_pending()

    def _process_work(self):
        if self._imap.disconnected:
            self.dec_pending()  # Exit state
        elif self._workqueue.have_work():
            work = self._workqueue.get_work()
            if work.type == Work.Type.refresh_list:
                list_op = IMAPListOperation(self, {self._mailbox})
                list_op.callback = lambda op: self._list_done(op, work)
                list_op.start()
            elif work.type == Work.Type.close:
                # TODO: when should we expunge instead?
                self._enqueue_cmd(lambda resp, dis: self._handle_tagged_close(resp, dis, work),
                                  'CLOSE')
            elif work.type == Work.Type.fetch_bodystructure:
                uid, = work.args
                self._enqueue_cmd(lambda resp, dis: self._handle_tagged_fetch(resp, dis, work),
                                  'FETCH', [uid], 'BODYSTRUCTURE', uid=True)
            elif work.type == Work.Type.fetch_body_sections:
                # TODO: partial fetches if too big/background downloads?
                uid, sections = work.args
                self._enqueue_cmd(lambda resp, dis: self._handle_tagged_fetch(resp, dis, work),
                                  'FETCH', [uid], *['BODY.PEEK[%s]' % section for section in sections], uid=True)
            else:
                assert False
        elif self._new_messages > 0:
            self._fetch_new_messages()
        elif self._fetching_cursor > 1:
            self._fetch_disconnected_messages()
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

    def _handle_tagged_close(self, resp, disconnected, work):
        if disconnected:
            self.dec_pending()
            self.dec_pending()  # Exit state
            return
        if resp.type == imap4.OK:
            self._closed = True
            self._workqueue.finish_work(work)
            self.dec_pending()  # Change state
        elif resp.type == imap4.BAD:
            self._gmail_hack(resp, work)
        else:
            assert False
        self.dec_pending()

    def _gmail_hack(self, resp, work=None):
        self._enqueue_cmd(lambda resp2, dis: self._handle_gmail_hack(resp2, resp, dis, work),
                          'CHECK')

    def _handle_gmail_hack(self, resp, orig_resp, disconnected, orig_work):
        # XXX: At the time of this writing on 11/15/15, if the selected mailbox
        # gets deleted, Gmail will kick you out of the Selected state into the
        # Authenticated state as soon as you execute a NOOP or IDLE command
        # (maybe others). Then, commands which are only valid in the Selected
        # state will result in a BAD response. So, when we get a BAD response,
        # we're forced to assume that this is the case and try a CHECK to
        # verify that this is what happened.
        if disconnected:
            self.dec_pending()
            self.dec_pending()  # Exit state
            return
        if resp.type == imap4.OK:
            # If CHECK succeeded, the previous response was a legitimate BAD
            # response
            self._bad_response(orig_resp)
            if orig_work:
                assert orig_work.type != Work.Type.close, "CLOSE failed"
                self._workqueue.finish_work(orig_work)
            self._process_work()
        elif resp.type == imap4.BAD:
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

    def _handle_tagged_fetch(self, resp, disconnected, work):
        if disconnected:
            self.dec_pending()
            self.dec_pending()  # Exit state
            return
        if resp.type == imap4.OK:
            self._workqueue.finish_work(work)
            self._process_work()
        elif resp.type == imap4.BAD:
            self.update_status('Could not fetch message', StatusLevel.error)
            self._gmail_hack(resp, work)
        elif resp.type == imap4.NO:
            assert False, "TODO"
        else:
            assert False
        self.dec_pending()

    def _fetch_new_messages(self):
        assert not self._fetching
        self._fetching = True
        uidnext = self._uids[-self._new_messages - 1] + 1
        fetch_op = GmailFetchNewMessagesOperation(self, uidnext)
        fetch_op.callback = self._fetch_new_messages_done
        fetch_op.start()

    def _fetch_new_messages_done(self, op):
        self._fetching = False
        if op.bad is not None:
            self.update_status('Could not fetch messages', StatusLevel.error)
            self._gmail_hack(op.bad)
        else:
            fetched = self._uids[-self._new_messages - 1:-self._new_messages + op.new_fetched]
            assert not any(uid == 0 for uid in fetched)
            self._new_messages -= op.new_fetched
            self._process_work()
        self.dec_pending()

    def _fetch_disconnected_messages(self):
        assert not self._fetching
        self._fetching = True
        self.update_status('Fetching %s (%d)' % (self._mailbox, self._fetching_cursor - 1),
                           StatusLevel.info)
        i = max(1, self._fetching_cursor - 250)
        j = self._fetching_cursor
        start_uid = self._uids[i]
        if j < len(self._uids):
            end_uid = self._uids[j]
        else:
            end_uid = self._uids[-1] + 1
        uids = self._uids[i:j]
        self._fetching_cursor = i
        fetch_op = GmailFetchDisconnectedMessagesOperation(self, uids,
                                                           start_uid, end_uid)
        fetch_op.callback = self._fetch_disconnected_messages_done
        fetch_op.start()

    def _fetch_disconnected_messages_done(self, op):
        self._fetching = False
        if op.bad is not None:
            self.update_status('Could not fetch messages', StatusLevel.error)
            self._gmail_hack(op.bad)
        else:
            self._process_work()
        self.dec_pending()

    def _idle_done(self, op):
        self._process_work()
        self.dec_pending()

    @_untagged_handler(imap4.RECENT)
    def _handle_recent(self, resp):
        self._cache.update_mailbox(self._mailbox, recent=resp.data)
        if not self._fetching:
            self._cache.commit()
        return True

    @_untagged_handler(imap4.EXISTS)
    def _handle_exists(self, resp):
        exists = resp.data
        old_exists = len(self._uids) - 1
        assert exists >= old_exists
        if exists > old_exists:
            self._new_messages += (exists - old_exists)
            self._uids.extend([0] * (exists - old_exists))
            self._cache.update_mailbox(self._mailbox, exists=exists)
            if not self._fetching:
                self._cache.commit()
        return True

    @_untagged_handler(imap4.EXPUNGE)
    def _handle_expunge(self, resp):
        old_exists = len(self._uids) - 1
        assert resp.data <= old_exists
        update = {'exists': old_exists - 1}

        if resp.data < self._fetching_cursor:
            self._fetching_cursor -= 1

        uid = self._uids.pop(resp.data)
        self._cache.delete_mailbox_uid(self._mailbox, uid)

        old_unseen = len(self._unseen)
        self._unseen.discard(uid)
        if len(self._unseen) != old_unseen:
            update['unseen'] = len(self._unseen)

        self._cache.update_mailbox(self._mailbox, **update)
        if not self._fetching:
            self._cache.commit()
        return True

    @_untagged_handler(imap4.FETCH)
    def _handle_fetch(self, resp):
        fetch = resp.data
        want_commit = False
        if imap4.UID in fetch.items:
            uid = fetch.items[imap4.UID]
        else:
            uid = self._uids[fetch.msg]
        update = {}
        if imap4.BODYSTRUCTURE in fetch.items:
            update['bodystructure'] = fetch.items[imap4.BODYSTRUCTURE]
        if imap4.FLAGS in fetch.items:
            update['flags'] = fetch.items[imap4.FLAGS]
            old_unseen = len(self._unseen)
            if '\\Seen' in fetch.items[imap4.FLAGS]:
                self._unseen.discard(uid)
            else:
                self._unseen.add(uid)
            if len(self._unseen) != old_unseen:
                self._cache.update_mailbox(self._mailbox, unseen=len(self._unseen))
                want_commit = True
        if imap4.X_GM_LABELS in fetch.items:
            update['labels'] = fetch.items[imap4.X_GM_LABELS]
            update['labels'].update(self._mailbox_labels)
        if imap4.BODYSECTIONS in fetch.items:
            bodysections = fetch.items[imap4.BODYSECTIONS]
            self._cache.add_body_sections_by_uid(self._mailbox, uid, bodysections)
            want_commit = True
        if update:
            self._cache.update_message_by_uid(self._mailbox, uid, **update)
            want_commit = True
        if want_commit and not self._fetching:
            self._cache.commit()
        return True


class IMAPPopulateEsearchOperation(_IMAPSubOperation):
    def __init__(self, state):
        super().__init__(state)
        self._unseen = None
        self.uids = None
        self.bad = None

    def start(self):
        super().start()
        self._esearch_all()
        self._esearch_unseen()

    def _esearch_all(self):
        self.uids = None
        self._all_tag = self._enqueue_cmd(self._handle_tagged_search, 'SEARCH',
                                          ('ALL',), uid=True, esearch=())

    def _esearch_unseen(self):
        self.unseen = None
        self._unseen_tag = self._enqueue_cmd(self._handle_tagged_search, 'SEARCH',
                                             ('UNSEEN',), uid=True, esearch=())

    @_untagged_handler(imap4.EXISTS)
    def _handle_exists(self, resp):
        # If new messages have come in, our information is out of date. Since
        # this probably won't happen very often, we can keep things simple and
        # just redo the searches.
        if self.uids is not None:
            self._esearch_all()
        if self.unseen is not None:
            self._esearch_unseen()
        return True

    @_untagged_handler(imap4.EXPUNGE)
    def _handle_expunge(self, resp):
        if self.uids is not None:
            # If we've already gotten the ESEARCH ALL response, then we need to
            # remove the message that was expunged.
            uid = self.uids.pop(resp.data)
            if self.unseen is not None:
                self.unseen.discard(uid)
        elif self.unseen:
            # If we haven't gotten the ESEARCH ALL response yet, then the
            # expunged message will not be in the response when we get it.
            # However, if we already got the ESEARCH UNSEEN response, we might
            # need to remove the expunged message from the set of of unseen
            # messages, which we can't do without being able to map the
            # sequence number to a UID. Since this is probably a rare case,
            # just redo the search.
            self._esearch_unseen()
        return True

    @_untagged_handler(imap4.ESEARCH)
    def _handle_esearch(self, resp):
        esearch = resp.data
        if esearch.tag == self._all_tag:
            seq_set = esearch.returned.get(imap4.ALL, [])
            self.uids = imap.seq_set_to_array(seq_set, True)
            return True
        elif esearch.tag == self._unseen_tag:
            seq_set = esearch.returned.get(imap4.ALL, [])
            self.unseen = imap.seq_set_to_set(seq_set)
            return True
        else:
            return False

    def _handle_tagged_search(self, resp, disconnected):
        if disconnected:
            self.dec_pending()
            return
        if resp.type == imap4.BAD:
            self.bad = resp
        elif resp.type != imap4.OK:
            assert False, "TODO"
        self.dec_pending()


class _GmailFetchMessagesOperation(_IMAPSubOperation):
    def __init__(self, state):
        super().__init__(state)
        self._state = state
        self._mailbox = self._state._mailbox
        self.bad = None
        self.new_fetched = 0

    def done(self):
        self._cache.drop_temp_fetching_table()
        self._cache.commit()
        super().done()

    def _handle_tagged_fetch_gm_msgids(self, resp, disconnected):
        if disconnected:
            self.dec_pending()
            return
        if resp.type == imap4.BAD:
            self.bad = resp
            self.dec_pending()
            return True
        elif resp.type != imap4.OK:
            assert False, "TODO"
        old, new = self._cache.get_fetching_old_new_gm_msgids()
        if new:
            self._new_gm_msgids = new
            seq_set = imap.sequence_set(new)
            self._enqueue_cmd(self._handle_tagged_fetch_envelopes,
                              'FETCH', seq_set, 'ENVELOPE', 'FLAGS',
                              'X-GM-LABELS', uid=True)
        if old:
            seq_set = imap.sequence_set(old)
            self._enqueue_cmd(self._handle_tagged, 'FETCH', seq_set, 'FLAGS',
                              'X-GM-LABELS', uid=True)
        self.dec_pending()

    def _handle_tagged_fetch_envelopes(self, resp, disconnected):
        if disconnected:
            self.dec_pending()
            return
        if resp.type == imap4.BAD:
            self.bad = resp
            self.dec_pending()
            return True
        elif resp.type != imap4.OK:
            assert False, "TODO"
        self.new_fetched = self._cache.add_fetching_uids()
        self.dec_pending()

    @_untagged_handler(imap4.EXPUNGE)
    def _handle_expunge(self, resp):
        uid = self._state._uids[resp.data]
        self._cache.db.delete_fetching_uid(uid)
        return False

    def _handle_fetch(self, resp):
        fetch = resp.data
        if imap4.X_GM_MSGID in fetch.items:
            uid = fetch.items.pop(imap4.UID)
            gm_msgid = fetch.items.pop(imap4.X_GM_MSGID)
            self._cache.update_fetching_gm_msgid(uid, gm_msgid)
            return True
        elif imap4.ENVELOPE in fetch.items:
            uid = fetch.items.pop(imap4.UID)
            envelope = fetch.items.pop(imap4.ENVELOPE)
            flags = fetch.items.pop(imap4.FLAGS)
            labels = fetch.items.pop(imap4.X_GM_LABELS)
            labels.update(self._state._mailbox_labels)
            gm_msgid = self._new_gm_msgids[uid]
            self._cache.add_message_with_envelope(gm_msgid, envelope,
                                                  flags=flags, labels=labels)
            return True
        else:
            return False


class GmailFetchNewMessagesOperation(_GmailFetchMessagesOperation):
    def __init__(self, state, uidnext):
        super().__init__(state)
        self._uidnext = uidnext

    def start(self):
        super().start()
        self._cache.create_temp_fetching_table(self._mailbox)
        self._enqueue_cmd(self._handle_tagged_fetch_gm_msgids,
                          'FETCH', [(self._uidnext, None)], 'X-GM-MSGID', uid=True)

    @_untagged_handler(imap4.FETCH)
    def _handle_fetch(self, resp):
        fetch = resp.data
        if imap4.X_GM_MSGID in fetch.items:
            uid = fetch.items[imap4.UID]
            gm_msgid = fetch.items[imap4.X_GM_MSGID]
            self._state._uids[resp.data.msg] = uid
            self._cache.add_fetching_uid(uid, gm_msgid)
        super()._handle_fetch(resp)


class GmailFetchDisconnectedMessagesOperation(_GmailFetchMessagesOperation):
    def __init__(self, state, uids, start_uid, end_uid):
        super().__init__(state)
        self._uids = uids
        self._start_uid = start_uid
        self._end_uid = end_uid

    def start(self):
        super().start()
        self._cache.create_temp_fetching_table(self._mailbox, self._uids)
        self._cache.delete_fetching_missing(self._start_uid, self._end_uid)
        old, new = self._cache.get_fetching_old_new_uids()
        if new:
            seq_set = imap.sequence_set(new)
            self._enqueue_cmd(self._handle_tagged_fetch_gm_msgids,
                              'FETCH', seq_set, 'X-GM-MSGID', uid=True)
        if old:
            seq_set = imap.sequence_set(old)
            self._enqueue_cmd(self._handle_tagged,
                              'FETCH', seq_set, 'FLAGS', 'X-GM-LABELS',
                              uid=True)

    @_untagged_handler(imap4.FETCH)
    def _handle_fetch(self, resp):
        super()._handle_fetch(resp)


class IMAPIdleOperation(_IMAPSubOperation):
    def __init__(self, state, timeout=180):
        super().__init__(state)
        self._mailbox = state._mailbox
        self._uids = state._uids
        self._got_continue_req = False
        self._done = False
        self._refresh = False
        self._timeout = timeout
        self._timerfd = None

    def start(self):
        super().start()
        self.update_status('Idling', StatusLevel.info)

        flags = timerfd.TFD_CLOEXEC | timerfd.TFD_NONBLOCK
        self._timerfd = timerfd.TimerFD(flags=flags)
        self._timerfd.settime(self._timeout)
        self._main._sel.register(self._timerfd, selectors.EVENT_READ,
                                 self._select_timer)

        self._enqueue_cmd(self._handle_tagged, 'IDLE')
        self._workqueue.wait_for_work(self._idle_done)

    def done(self):
        self._timerfd.close()
        self._main._sel.unregister(self._timerfd)
        super().done()

    def _idle_done(self):
        self._done = True
        if self._got_continue_req:
            self._imap.continue_cmd()

    def _select_timer(self, mask):
        self._timerfd.read()
        if not self._done:
            self._workqueue.cancel_wait(self._idle_done)
            self._idle_done()

    @_continue_req_handler
    def _handle_continue_req(self):
        self._got_continue_req = True
        if self._done:
            self._imap.continue_cmd()
        return True

    @_untagged_handler(imap4.EXISTS)
    def _handle_exists(self, resp):
        old_exists = len(self._uids) - 1
        if resp.data > old_exists:
            self._workqueue.cancel_wait(self._idle_done)
            self._idle_done()
        # _IMAPSelectedState needs to update the cache.
        return False
