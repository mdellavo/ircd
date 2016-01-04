import ssl
import time
import logging
import socket
from Queue import Queue, Empty

from .message import parsemsg, TERMINATOR

log = logging.getLogger(__name__)

BACKLOG = 10
PING_INTERVAL = 60
PING_GRACE = 5


# FIXME set a timeout and drop if they dont ident in N seconds
class Client(object):
    def __init__(self, irc, sock, address):
        self.irc = irc
        self.socket = sock
        self.address = address

        self.nickname = None
        self.user = None
        self.realname = None
        self.host = socket.getfqdn(address[0]) or address[0]

        self.buffer = ""
        self.outgoing = Queue()
        self.ping_count = 0

    @property
    def identity(self):
        parts = [self.nickname or "(unknown)"]
        if self.user:
            parts.append("!")
            parts.append(self.user)
        parts.append("@")
        parts.append(self.host)
        return "".join(parts)

    @property
    def is_connected(self):
        return self.socket is not None

    def feed(self, data):
        self.buffer += data
        while TERMINATOR in self.buffer:
            line, self.buffer = self.buffer.split(TERMINATOR, 1)
            log.debug(">>> %s", line)
            self.irc.submit(self, parsemsg(line))

    def take(self):
        last_ping = time.time()
        while self.is_connected:
            try:
                msg = self.outgoing.get(timeout=PING_INTERVAL)
            except Empty:
                msg = None

            if msg:
                yield msg.format() + TERMINATOR

            diff = time.time() - last_ping
            if diff > PING_INTERVAL:
                self.irc.ping(self)
                last_ping = time.time()
                self.ping_count += 1
                if self.ping_count > PING_GRACE:
                    self.irc.drop_client(self, message="ping timeout")
                    break

    def set_nickname(self, nickname):
        self.nickname = nickname

    def set_identity(self, user, realname):
        self.user, self.realname = user, realname

    def send(self, msg):
        self.outgoing.put(msg)

    def disconnect(self):
        self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()
        self.socket = None

    def clear_ping_count(self):
        self.ping_count = 0

    @property
    def has_nickname(self):
        return bool(self.nickname)

    @property
    def has_identity(self):
        return self.has_nickname and all([self.user, self.realname])


class Server(object):
    def __init__(self, irc, address, cert_file):
        self.address = address
        self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self.ssl_context.load_cert_chain(certfile=cert_file)
        self.server_sock = None

        self.irc = irc

    def setup_socket(self, sock):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def setup_client_socket(self, sock):
        self.setup_socket(sock)
        return self.ssl_context.wrap_socket(sock, server_side=True)

    def create_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.setup_socket(sock)

        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(self.address)
        sock.listen(BACKLOG)

        log.info("listening on %s:%s", *self.address)

        return sock

    def on_connect(self, client_sock, address):
        raise NotImplemented("Server must implement on_connect")

    def serve(self):
        self.server_sock = self.create_socket()

        running = True
        while running:
            client, address = self.server_sock.accept()
            self.on_connect(client, address)
