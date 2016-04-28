import ssl
import time
import logging
import socket
from Queue import Queue, Empty

from ircd.message import parsemsg, TERMINATOR, Prefix

log = logging.getLogger(__name__)

BACKLOG = 10
PING_INTERVAL = 60
PING_GRACE = 5
IDENT_TIMEOUT = 10


class Client(object):
    def __init__(self, irc, transport):
        self.irc = irc
        self.transport = transport

        self.server = False
        self.name = None

        # fields if server
        self.hop_count = None
        self.token = None
        self.info = None

        # fields if user
        self.user = None
        self.realname = None

        self.outgoing = Queue()
        self.ping_count = 0

    def get_name(self):
        return self.name

    @property
    def host(self):
        return self.transport.host if self.transport else None

    @property
    def identity(self):
        prefix = Prefix(self.host) if self.server else Prefix.from_parts(self.name, self.user, self.host)
        return str(prefix)

    @property
    def is_connected(self):
        return self.transport is not None

    def reader(self):
        start = time.time()
        try:
            for msg in self.transport.read():

                elapsed = time.time() - start
                if elapsed > IDENT_TIMEOUT and not self.has_identity:
                    log.error("client ident timeout: %s", self.host)
                    self.irc.drop_client(self, message="ident timeout")
                    break

                if msg:
                    log.debug("read: %s", msg)
                    self.irc.submit(self, msg)

        except TransportError as e:
            log.error("error reading from client: %s", e)
            self.irc.drop_client(self, message=str(e))

    def writer(self):
        last_ping = time.time()

        while self.is_connected:
            try:
                msg = self.outgoing.get(timeout=PING_INTERVAL)
            except Empty:
                msg = None

            if msg and self.transport:
                try:
                    log.debug("wrie: %s", msg)
                    self.transport.write(msg)
                except TransportError as e:
                    log.error("error writing from client: %s", e)
                    self.irc.drop_client(self, message=str(e))

            diff = time.time() - last_ping
            if diff > PING_INTERVAL:
                self.irc.ping(self)
                last_ping = time.time()
                self.ping_count += 1
                if self.ping_count > PING_GRACE:
                    self.irc.drop_client(self, message="ping timeout")
                    break

    def set_nickname(self, nickname):
        self.name = nickname

    def set_identity(self, user, realname):
        self.user, self.realname = user, realname

    def set_server(self, name, hop_count, token, info):
        self.server = True
        self.name = name
        self.hop_count = hop_count
        self.token = token
        self.info = info

    def send(self, msg):
        self.outgoing.put(msg)

    def disconnect(self):
        self.transport.close()
        self.transport = None

    def clear_ping_count(self):
        self.ping_count = 0

    @property
    def has_nickname(self):
        return bool(self.name)

    @property
    def has_identity(self):
        return self.has_nickname and all([self.user, self.realname])


class Transport(object):

    def close(self):
        pass

    def read(self):
        pass

    def write(self, msg):
        pass


class TransportError(Exception):
    def __init__(self, e):
        super(TransportError, self).__init__(str(e))


class SocketTransport(Transport):
    def __init__(self, sock, address):
        self.sock = sock
        self.host = socket.getfqdn(address[0]) or address[0]
        self.buffer = ""

    def close(self):
        self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()

    def read(self):
        while True:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
            except socket.error as e:
                timeout = "timed out" in str(e)  # bug in python ssl, doesnt raise timeout
                if not timeout:
                    raise TransportError(e)
                data = None

            if not data:
                yield None
                continue

            self.buffer += data
            while TERMINATOR in self.buffer:
                line, self.buffer = self.buffer.split(TERMINATOR, 1)
                log.debug(">>> %s", line)
                yield parsemsg(line)

    def write(self, msg):
        try:
            self.sock.write(msg.format() + TERMINATOR)
        except socket.error as e:
            raise TransportError(e)


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
