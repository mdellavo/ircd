from gevent import monkey
monkey.patch_all()

from gevent import socket, ssl, queue
import gevent

import string
import logging
from functools import wraps
from datetime import datetime
from collections import defaultdict

SERVER_NAME = "ircd"
SERVER_VERSION = "0.1"

BACKLOG = 10
ADDRESS = "0.0.0.0", 9999
KEY_FILE = "key.pem"

TERMINATOR = "\r\n"
CHAN_START_CHARS = "&#!+"
BUFFER_SIZE = 4096

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("ircd")


# https://stackoverflow.com/questions/930700/python-parsing-irc-messages
def parsemsg(s):
    """
    Breaks a message from an IRC server into its prefix, command, and arguments.
    """
    prefix = ''
    trailing = []
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


class Prefix(object):
    def __init__(self, prefix):
        self.prefix = prefix


class IRCMessage(object):
    def __init__(self, prefix, command, *args):
        self.prefix = prefix
        self.command = command
        self.args = args

    def __str__(self):
        return u"{}<command={}, args={}, prefix={}>".format(self.__class__.__name__, self.command, self.args, self.prefix)

    @classmethod
    def from_message(cls, message):
        prefix, command, args = parsemsg(message)
        return cls(prefix, command, *args)

    def format(self):
        parts = []
        if self.prefix:
            parts.append(":" + self.prefix)
        parts.append(self.command)
        if self.args:
            head = self.args[:-1]
            if head:
                parts.extend(head)
            tail = self.args[-1]
            if tail:
                parts.append(":" + tail)
        rv = " ".join(parts)
        return rv

    @classmethod
    def reply_welcome(cls, prefix, target, nickname, username, hostname):
        return cls(prefix, "001", target, "Welcome to the Internet Relay Network {}!{}@{}".format(nickname, username, hostname))

    @classmethod
    def reply_yourhost(cls, prefix, target, name, version):
        return cls(prefix, "002", target, "Your host is {}, running version {}".format(name, version))

    @classmethod
    def reply_created(cls, prefix, target, dt):
        return cls(prefix, "003", target, "This server was created {}".format(dt))

    @classmethod
    def reply_myinfo(cls, prefix, target, name, verison):
        return cls(prefix, "004", target, "{} {} {} {}".format(name, verison, string.letters, string.letters))

    @classmethod
    def reply_pong(cls, prefix, server):
        return cls(prefix, "PONG", server)

    @classmethod
    def reply_notopic(cls, prefix, target, channel):
        return cls(prefix, "331", target, channel.name)

    @classmethod
    def reply_topic(cls, prefix, target, channel):
        return cls(prefix, "332", channel.name, channel.topic)

    @classmethod
    def reply_names(cls, prefix, target, channel):
        return cls(prefix, "353", target, "=", channel.name, " ".join(channel.members))

    @classmethod
    def reply_endnames(cls, prefix, target, channel):
        return cls(prefix, "355", target, channel.name, "End of /NAMES list.")

    @classmethod
    def private_message(cls, prefix, target, msg):
        return cls(prefix, "PRIVMSG", target, msg)


# FIXME set a timeout and drop if they dont ident in N seconds
class Client(object):
    def __init__(self, irc, socket, address):
        self.socket = socket
        self.address = address

        self.nickname = None
        self.username = None
        self.hostname = None
        self.servername = None
        self.realname = None
        self.mode = ""

        self.irc = irc

        self.outgoing = queue.Queue()
        self.running = True
        self.reader_thread = gevent.spawn(self.reader_main)
        self.writer_thread = gevent.spawn(self.writer_main)

    @property
    def identity(self):
        return "{nickname}!{username}@{hostname}".format(nickname=self.nickname, username=self.username, hostname=self.hostname)

    def stop(self):
        if self.socket:
            self.disconnect()

        self.running = False
        gevent.joinall([self.reader_thread, self.writer_thread])

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
        return self.has_nickname and all([self.username, self.hostname, self.servername, self.realname])

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
                self.irc.process(self, IRCMessage.from_message(line))

    def writer_main(self):
        while self.running:
            msg = self.outgoing.get()
            log.debug("<<< %s", msg.format())
            self.socket.write(msg.format() + TERMINATOR)


def validate(nickname=False, identity=False):
    def _validate(func):
        @wraps(func)
        def __validate(self, client, msg):
            if (nickname and not client.has_nickname) or (identity and not client.has_identity):
                self.drop_client(client)
                return None
            return func(self, client, msg)
        return __validate
    return _validate


class Channel(object):
    def __init__(self, name, owner, key=None):
        self.name = name
        self.owner = owner
        self.key = key
        self.topic = None
        self.members = [owner]
        self.mode = ""

    def join(self, nick, key=None):
        if self.key and key != self.key:
            return False

        if nick not in self.members:
            self.members.append(nick)

    def part(self, nick):
        if nick in self.members:
            self.members.remove(nick)


class IRC(object):
    def __init__(self, host):
        self.host = host
        self.running = True
        self.incoming = queue.Queue()
        self.created = datetime.utcnow()
        self.worker = gevent.spawn(self.main)

        self.clients = {}
        self.channels = {}

    def stop(self):
        self.running = False

    def main(self):
        while self.running:
            client, msg = self.incoming.get()

            handler = "irc_" + msg.command.lower()
            callback = getattr(self, handler, None)
            if callback:
                try:
                    callback(client, msg)
                except:
                    log.exception("error applying message: %s", msg)

    def process(self, client, msg):
        self.incoming.put((client, msg))

    def add_client(self, client):
        self.clients[client.nickname] = client

    def drop_client(self, client):
        del self.clients[client.nickname]
        client.stop()

    def join_channel(self, name, client, key=None):
        channel = self.channels.get(name.lower())
        if not channel:
            channel = Channel(name, client.nickname, key=key)
            self.channels[name.lower()] = channel

        channel.join(client.nickname, key=key)
        return channel

    def part_channel(self, name, client):
        channel = self.channels.get(name.lower())
        if channel:
            channel.part(client.nickname)

    def send_to_channel(self, client, channel_name, msg):
        channel = self.channels.get(channel_name.lower())
        if not channel:
            return
        for member in channel.members:
            if member == client.nickname:
                continue
            member_client = self.clients.get(member)
            if member_client:
                member_client.send(IRCMessage.private_message(client.identity, channel_name, msg))

    def irc_nick(self, client, msg):
        client.nickname = msg.args[0]

    @validate(nickname=True)
    def irc_user(self, client, msg):
        client.username, client.hostname, client.servername, client.realname = msg.args

        self.add_client(client)

        client.send(IRCMessage.reply_welcome(self.host, client.nickname, client.nickname, client.username, client.hostname))
        client.send(IRCMessage.reply_yourhost(self.host, client.nickname, SERVER_NAME, SERVER_VERSION))
        client.send(IRCMessage.reply_created(self.host, client.nickname, self.created))
        client.send(IRCMessage.reply_myinfo(self.host, client.nickname, SERVER_NAME, SERVER_VERSION))

    @validate(identity=True)
    def irc_ping(self, client, msg):
        client.send(IRCMessage.reply_pong(self.host, msg.args[0]))

    def irc_quit(self, client, _):
        self.drop_client(client)

    def validate_chan_name(self, chan_name):
        if not chan_name[0] in CHAN_START_CHARS:
            raise ValueError("bad chan name")

    @validate(identity=True)
    def irc_join(self, client, msg):
        chan_name = msg.args[0]
        self.validate_chan_name(chan_name)
        channel = self.join_channel(chan_name, client)

        if channel.topic:
            client.send(IRCMessage.reply_topic(self.host, client.nickname, channel))
        else:
            client.send(IRCMessage.reply_notopic(self.host, client.nickname, channel))

        client.send(IRCMessage.reply_names(self.host, client.nickname, channel))
        client.send(IRCMessage.reply_endnames(self.host, client.nickname, channel))

    @validate(identity=True)
    def irc_part(self, client, msg):
        chan_name = msg.args[0]
        self.validate_chan_name(chan_name)
        self.part_channel(chan_name, client)

    @validate(identity=True)
    def irc_privmsg(self, client, msg):
        if msg.args[0] in CHAN_START_CHARS:
            chan_name = msg.args[0]
            self.validate_chan_name(chan_name)
            self.send_to_channel(client, chan_name, msg.args[1])


class Server(object):
    def __init__(self, irc, address):
        self.address = address
        self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self.ssl_context.load_cert_chain(certfile=KEY_FILE)
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
        Client(self.irc, self.setup_client_socket(client_sock), address)

    def serve(self):
        self.server_sock = self.create_socket()

        running = True
        while running:
            client, address = self.server_sock.accept()
            self.on_connect(client, address)


def main():
    host = socket.getfqdn(ADDRESS[0])
    irc = IRC(host)
    server = Server(irc, ADDRESS)
    server.serve()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
