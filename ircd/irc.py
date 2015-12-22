import string
import logging
from Queue import Queue
from functools import wraps
from datetime import datetime

SERVER_NAME = "ircd"
SERVER_VERSION = "0.1"
CHAN_START_CHARS = "&#!+"

log = logging.getLogger(__name__)


class IRCError(Exception):
    def __init__(self, msg):
        self.msg = msg


class Prefix(object):
    def __init__(self, prefix):
        self.prefix = prefix

        self.name = None

        self.nickname = None
        self.user = None
        self.host = None

        if "@" in prefix:
            if "!" in prefix:
                self.nickname, rest = prefix.split("!", 1)
                self.user, self.host = rest.split("@", 1)
            else:
                self.nickname, self.host = prefix.split("@", 1)
        else:
            self.name = prefix

    def __str__(self):
        return self.prefix


class IRCMessage(object):
    def __init__(self, prefix, command, *args):
        self.prefix = Prefix(prefix)
        self.command = command
        self.args = args

    def __str__(self):
        return "{}<command={}, args={}, prefix={}>".format(self.__class__.__name__, self.command, self.args,
                                                            self.prefix)

    def format(self):
        parts = []
        if self.prefix:
            parts.append(":" + str(self.prefix))
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
    def reply_welcome(cls, prefix, target, nickname, user, hostname):
        return cls(prefix, "001", target,
                   "Welcome to the Internet Relay Network {}!{}@{}".format(nickname, user, hostname))

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
        return cls(prefix, "353", target, "=", channel.name, " ".join(sorted(channel.members)))

    @classmethod
    def reply_endnames(cls, prefix, target, channel):
        return cls(prefix, "355", target, channel.name, "End of /NAMES list.")

    @classmethod
    def error_nick_in_use(cls, prefix, nickname):
        return cls(prefix, "433", nickname)

    @classmethod
    def error_not_in_channel(cls, prefix):
        return cls(prefix, "441")

    @classmethod
    def error_no_such_channel(cls, prefix, name):
        return cls(prefix, "403", name)

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
        def __validate(self,msg):
            if (nickname and not self.client.has_nickname) or (identity and not self.client.has_identity):
                self.irc.drop_client(self.client)
                return None
            return func(self, msg)
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
    def __init__(self, irc, client):
        self.irc = irc
        self.client = client

    def __call__(self, msg):
        handler = msg.command.lower()
        callback = getattr(self, handler, None)
        if callback and callable(callback):
            try:
                callback(msg)
            except IRCError as e:
                self.client.send(e.msg)
            except:
                log.exception("error applying message: %s", msg)

    def nick(self, msg):
        nickname = msg.args[0]
        self.irc.set_nick(self.client, nickname)

    @validate(nickname=True)
    def user(self, msg):
        user, mode, _, realname = msg.args
        self.irc.set_ident(self.client, user, realname)

    @validate(identity=True)
    def ping(self, msg):
        self.client.send(IRCMessage.reply_pong(self.irc.host, msg.args[0]))

    def quit(self, _):
        self.irc.drop_client(self.client)

    @validate(identity=True)
    def join(self, msg):
        chan_name = msg.args[0]
        self.irc.validate_chan_name(self.client, chan_name)
        self.irc.join_channel(chan_name, self.client)

    @validate(identity=True)
    def part(self, msg):
        chan_name = msg.args[0]
        self.irc.validate_chan_name(self.client, chan_name)
        self.irc.part_channel(chan_name, self.client)

    @validate(identity=True)
    def privmsg(self, msg):
        if msg.args[0] in CHAN_START_CHARS:
            chan_name = msg.args[0]
            self.irc.validate_chan_name(self.client, chan_name)
            self.irc.send_private_message_to_channel(self.client, chan_name, msg.args[1])
        elif msg.args[0] in self.irc.clients:
            nickname = msg.args[0]
            self.irc.send_private_message_to_client(self.client, nickname, msg.args[1])


class IRC(object):
    def __init__(self, host):
        self.host = host
        self.running = True
        self.incoming = Queue()
        self.created = datetime.utcnow()

        self.clients = {}
        self.channels = {}

    def process(self, client, msg):
        msg = IRCMessage(msg[0], msg[1], *msg[2])
        handler = Handler(self, client)
        handler(msg)

    def submit(self, client, msg):
        self.incoming.put((client, msg))

    def set_nick(self, client, nickname):
        if client.nickname == nickname:
            return

        if nickname in self.clients:
            raise IRCError(IRCMessage.error_nick_in_use(client.identity))

        old = client.nickname
        msg = IRCMessage.nick(client.identity, nickname)

        client.nickname = nickname
        self.clients[client.nickname] = client

        if client.has_identity:
            client.send(msg)

            if old:
                del self.clients[old]
                # FIXME need
                for channel in self.channels.values():
                    if channel.update_nick(old, nickname):
                        self.send_to_channel(client, channel.name, msg, skip_self=True)

    def set_ident(self, client, user, realname):
        client.user, client.realname = user, realname

        log.info("%s connected", client.identity)

        client.send(IRCMessage.nick(client.identity, client.nickname))
        client.send(IRCMessage.reply_welcome(self.host, client.nickname, client.nickname, client.user, client.host))
        client.send(IRCMessage.reply_yourhost(self.host, client.nickname, SERVER_NAME, SERVER_VERSION))
        client.send(IRCMessage.reply_created(self.host, client.nickname, self.created))
        client.send(IRCMessage.reply_myinfo(self.host, client.nickname, SERVER_NAME, SERVER_VERSION))

    def drop_client(self, client):
        log.info("%s disconnected", client.identity)
        if client.nickname and client.nickname in self.clients:
            del self.clients[client.nickname]
        client.stop()

    def join_channel(self, name, client, key=None):
        channel = self.channels.get(name.lower())
        if not channel:
            channel = Channel(name, client.nickname, key=key)
            self.channels[name.lower()] = channel

        channel.join(client.nickname, key=key)

        self.send_to_channel(client, name, IRCMessage.join(client.identity, name))

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
        self.send_to_channel(client, name, IRCMessage.part(client.identity, name))
        channel.part(client.nickname)

    def send_to_channel(self, client, channel_name, msg, skip_self=False):
        channel = self.channels.get(channel_name.lower())
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(client.identity, channel_name))
        if client.nickname not in channel.members:
            raise IRCError(IRCMessage.error_not_in_channel(client.identity))

        for member in channel.members:
            if skip_self and member == client.nickname:
                continue
            member_client = self.clients.get(member)
            if member_client:
                member_client.send(msg)

    def send_private_message_to_channel(self, client, channel_name, text):
        self.send_to_channel(client, channel_name, IRCMessage.private_message(client.identity, channel_name, text), skip_self=True)

    def send_private_message_to_client(self, client, nickname, text):
        other = self.clients[nickname]
        other.send(IRCMessage.private_message(client.identity, nickname, text))

    def validate_chan_name(self, client, chan_name):
        if not chan_name[0] in CHAN_START_CHARS:
            raise IRCError(IRCMessage.error_no_such_channel(client.identity, chan_name))
