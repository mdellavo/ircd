import ssl
import logging
import socket
from threading import Thread
from Queue import Queue

log = logging.getLogger(__name__)

BACKLOG = 10
TERMINATOR = "\r\n"


# https://stackoverflow.com/questions/930700/python-parsing-irc-messages
def parsemsg(s):
    """
    Breaks a message from an IRC server into its prefix, command, and arguments.
    """
    prefix = ''
    if not s:
        raise ValueError("Empty line.")
    if s[0] == ':':
        prefix, s = s[1:].split(' ', 1)
    if s.find(' :') != -1:
        s, trailing = s.split(' :', 1)
        args = s.split()
        args.append(trailing)
    else:
        args = s.split()
    command = args.pop(0)
    return prefix, command, args


# FIXME set a timeout and drop if they dont ident in N seconds
class Client(object):
    def __init__(self, irc, sock, address):
        self.socket = sock
        self.address = address

        self.nickname = None
        self.user = None
        self.realname = None
        self.mode = ""
        self.host = socket.getfqdn(address[0]) or address[0]

        self.irc = irc

        self.outgoing = Queue()
        self.running = True

        self.reader_thread = None
        self.writer_thread = None

    @property
    def identity(self):
        return "{nickname}!{user}@{host}".format(nickname=self.nickname, user=self.user, host=self.host)

    def start(self):
        self.reader_thread = Thread(target=self.reader_main)
        self.reader_thread.setDaemon(True)
        self.reader_thread.start()

        self.writer_thread = Thread(target=self.writer_main)
        self.writer_thread.setDaemon(True)
        self.writer_thread.start()

    def stop(self):
        if self.socket:
            self.disconnect()

        self.running = False
        for thread in [self.reader_thread, self.writer_thread]:
            thread.join()

    def send(self, msg):
        self.outgoing.put(msg)

    def disconnect(self):
        self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()
        self.socket = None

    @property
    def has_nickname(self):
        return bool(self.nickname)

    @property
    def has_identity(self):
        return self.has_nickname and all([self.user, self.realname])

    def reader_main(self):
        buffer = ""

        while self.socket is not None and self.running:
            data = self.socket.recv(1024)
            if not data:
                self.running = False
                break
            buffer += data
            while TERMINATOR in buffer:
                line, buffer = buffer.split(TERMINATOR, 1)
                log.debug(">>> %s", line)
                self.irc.submit(self, parsemsg(line))

    def writer_main(self):
        while self.running:
            msg = self.outgoing.get()
            log.debug("<<< %s", msg.format())
            self.socket.write(msg.format() + TERMINATOR)


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
        log.info("new client connection %s", address)
        client = Client(self.irc, self.setup_client_socket(client_sock), address)
        client.start()

    def serve(self):
        self.server_sock = self.create_socket()

        running = True
        while running:
            client, address = self.server_sock.accept()
            self.on_connect(client, address)
