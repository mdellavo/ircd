import string
import logging
from Queue import Queue
from functools import wraps
from threading import Thread
from datetime import datetime

SERVER_NAME = "ircd"
SERVER_VERSION = "0.1"
CHAN_START_CHARS = "&#!+"

log = logging.getLogger(__name__)


class Prefix(object):
    def __init__(self, prefix):
        self.prefix = prefix


class IRCMessage(object):
    def __init__(self, prefix, command, *args):
        self.prefix = prefix
        self.command = command
        self.args = args

    def __str__(self):
        return u"{}<command={}, args={}, prefix={}>".format(self.__class__.__name__, self.command, self.args,
                                                            self.prefix)

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
        return cls(prefix, "001", target,
                   "Welcome to the Internet Relay Network {}!{}@{}".format(nickname, username, hostname))

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
    def nick(cls, prefix, nickname):
        return cls(prefix, "NICK", nickname)

    @classmethod
    def join(cls, prefix, channel):
        return cls(prefix, "JOIN", channel)

    @classmethod
    def part(cls, prefix, channel):
        return cls(prefix, "PART", channel)

    @classmethod
    def private_message(cls, prefix, target, msg):
        return cls(prefix, "PRIVMSG", target, msg)


def validate(nickname=False, identity=False):
    def _validate(func):
        @wraps(func)
        def __validate(self, client, msg):
            if (nickname and not client.has_nickname) or (identity and not client.has_identity):
                self.irc.drop_client(client)
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
            log.info("%s joined %s", nick, self.name)
            self.members.append(nick)

    def part(self, nick):
        if nick in self.members:
            log.info("%s parted %s", nick, self.name)
            self.members.remove(nick)

    def update_nick(self, old, new):
        is_member = old in self.members
        if is_member:
            self.members.remove(old)
            self.members.append(new)
        return is_member


class Handler(object):
    def __init__(self, irc):
        self.irc = irc

    def __call__(self, client, msg):
        handler = msg.command.lower()
        callback = getattr(self, handler, None)
        if callback and callable(callback):
            try:
                callback(client, msg)
            except:
                log.exception("error applying message: %s", msg)

    def nick(self, client, msg):
        nickname = msg.args[0]
        self.irc.set_nick(client, nickname)

    @validate(nickname=True)
    def user(self, client, msg):
        username, hostname, servername, realname = msg.args
        self.irc.set_ident(client, username, hostname, servername, realname)

    @validate(identity=True)
    def ping(self, client, msg):
        client.send(IRCMessage.reply_pong(self.irc.host, msg.args[0]))

    def quit(self, client, _):
        self.irc.drop_client(client)

    @validate(identity=True)
    def join(self, client, msg):
        chan_name = msg.args[0]
        self.irc.validate_chan_name(chan_name)
        self.irc.join_channel(chan_name, client)

    @validate(identity=True)
    def part(self, client, msg):
        chan_name = msg.args[0]
        self.irc.validate_chan_name(chan_name)
        self.irc.part_channel(chan_name, client)

    @validate(identity=True)
    def privmsg(self, client, msg):
        if msg.args[0] in CHAN_START_CHARS:
            chan_name = msg.args[0]
            self.irc.validate_chan_name(chan_name)
            self.irc.send_private_message(client, chan_name, msg.args[1])


class IRC(object):
    def __init__(self, host):
        self.host = host
        self.running = True
        self.incoming = Queue()
        self.created = datetime.utcnow()
        self.worker = Thread(target=self.main)
        self.worker.setDaemon(True)
        self.worker.start()

        self.clients = {}
        self.channels = {}

    def stop(self):
        self.running = False

    def main(self):
        while self.running:
            client, msg = self.incoming.get()
            msg = IRCMessage(msg[0], msg[1], *msg[2])
            self.dispatch(client, msg)

    def dispatch(self, client, msg):
        handler = Handler(self)
        handler(client, msg)

    def process(self, client, msg):
        self.incoming.put((client, msg))

    def set_nick(self, client, nickname):
        if client.nickname == nickname:
            return

        if nickname in self.clients:
            raise ValueError("nickname {} already in use".format(nickname))

        log.info("%s connected", client.nickname)
        old = client.nickname
        client.nickname = nickname
        self.clients[client.nickname] = client

        if old:
            del self.clients[old]
            for channel in self.channels.values():
                if channel.update_nick(old, nickname):
                    self.send_to_channel(client, channel.name, IRCMessage.nick(client.identity, nickname))

    def set_ident(self, client, username, hostname, servername, realname):
        client.username, client.hostname, client.servername, client.realname = username, hostname, servername, realname

        client.send(IRCMessage.reply_welcome(self.host, client.nickname, client.nickname, client.username, client.hostname))
        client.send(IRCMessage.reply_yourhost(self.host, client.nickname, SERVER_NAME, SERVER_VERSION))
        client.send(IRCMessage.reply_created(self.host, client.nickname, self.created))
        client.send(IRCMessage.reply_myinfo(self.host, client.nickname, SERVER_NAME, SERVER_VERSION))

    def drop_client(self, client):
        log.info("%s disconnected", client.nickname)
        if client.nickname and client.nickname in self.clients:
            del self.clients[client.nickname]
        client.stop()

    def join_channel(self, name, client, key=None):
        channel = self.channels.get(name.lower())
        if not channel:
            channel = Channel(name, client.nickname, key=key)
            self.channels[name.lower()] = channel

        channel.join(client.nickname, key=key)

        self.send_to_channel(client, name, IRCMessage.join(client.nickname, name))

        if channel.topic:
            client.send(IRCMessage.reply_topic(self.host, client.nickname, channel))
        else:
            client.send(IRCMessage.reply_notopic(self.host, client.nickname, channel))

        client.send(IRCMessage.reply_names(self.host, client.nickname, channel))
        client.send(IRCMessage.reply_endnames(self.host, client.nickname, channel))

        return channel

    def part_channel(self, name, client):
        channel = self.channels.get(name.lower())
        if not channel:
            return
        channel.part(client.nickname)
        self.send_to_channel(client, name, IRCMessage.part(client.nickname, name))

    def send_to_channel(self, client, channel_name, msg, skip_self=False):
        channel = self.channels.get(channel_name.lower())
        if not channel:
            return
        if client.nickname not in channel.members:
            raise ValueError("must be a member of the channel")

        for member in channel.members:
            if skip_self and member == client.nickname:
                continue
            member_client = self.clients.get(member)
            if member_client:
                member_client.send(msg)

    def send_private_message(self, client, channel_name, text):
        self.send_to_channel(client, channel_name, IRCMessage.private_message(client.identity, channel_name, text), skip_self=True)

    def validate_chan_name(self, chan_name):
        if not chan_name[0] in CHAN_START_CHARS:
            raise ValueError("bad chan name")
