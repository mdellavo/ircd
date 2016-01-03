import logging
from Queue import Queue
from functools import wraps
from datetime import datetime

from .message import IRCMessage
from .mode import Mode

SERVER_NAME = "ircd"
SERVER_VERSION = "0.1"
CHAN_START_CHARS = "&#!+"

log = logging.getLogger(__name__)


class IRCError(Exception):
    def __init__(self, msg):
        self.msg = msg


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


class Nickname(object):
    def __init__(self, nickname):
        self.nickname = nickname
        self.mode = Mode.for_nickname(self)
        self.last_seen = datetime.utcnow()
        self.channels = []

    def __repr__(self):
        return "Nickname({})".format(self.nickname)

    def __eq__(self, other):
        return other and self.nickname == other.nickname

    def set_nick(self, nickname):
        self.nickname = nickname

    def set_mode(self, flags, param=None):
        return self.mode.set_flags(flags, param=param)

    def clear_mode(self, flags):
        return self.mode.clear_flags(flags)

    def seen(self):
        self.last_seen = datetime.utcnow()

    def joined_channel(self, channel):
        if channel not in self.channels:
            self.channels.append(channel)

    def parted_channel(self, channel):
        if channel in self.channels:
            self.channels.remove(channel)

    is_away = property(lambda self: self.mode.has_flag(Mode.AWAY))
    is_invisible = property(lambda self: self.mode.has_flag(Mode.INVISIBLE))
    has_wallops = property(lambda self: self.mode.has_flag(Mode.WALLOPS))
    is_restricted = property(lambda self: self.mode.has_flag(Mode.RESTRICTED))
    is_operator = property(lambda self: self.mode.has_flag(Mode.OPERATOR))
    is_local_operator = property(lambda self: self.mode.has_flag(Mode.OPERATOR))
    has_server_notices = property(lambda self: self.mode.has_flag(Mode.SERVER_NOTICES))


# FIXME need a NickChannel that is an abstraction over client
class Channel(object):
    def __init__(self, name, owner, key=None):
        self.name = name
        self.owner = owner
        self.key = key
        self.topic = None
        self.members = [owner]
        self.operators = [owner]
        self.mode = Mode.for_channel(self)

    def __eq__(self, other):
        return other and self.name == other.name

    def __repr__(self):
        return "Channel({}, {})".format(self.name, self.owner)

    def join(self, nickname, key=None):
        if self.key and key != self.key:
            return False

        if nickname not in self.members:
            log.info("%s joined %s", nickname, self.name)
            self.members.append(nickname)
        nickname.joined_channel(self)

    def part(self, nickname):
        if nickname in self.members:
            log.info("%s parted %s", nickname, self.name)
            self.members.remove(nickname)
        nickname.parted_channel(self)

    def set_mode(self, flags):
        return self.mode.set_flags(flags)

    def clear_mode(self, flags):
        return self.mode.clear_flags(flags)


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

    def pong(self, _):
        self.client.clear_ping_count()

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
        self.irc.join_channel(chan_name, self.client)

    @validate(identity=True)
    def part(self, msg):
        chan_name = msg.args[0]
        self.irc.part_channel(chan_name, self.client)

    @validate(identity=True)
    def privmsg(self, msg):
        target = msg.args[0]

        if target in self.irc.channels:
            self.irc.send_private_message_to_channel(self.client, target, msg.args[1])
        elif target in self.irc.clients:
            self.irc.send_private_message_to_client(self.client, target, msg.args[1])
        else:
            self.client.send(IRCMessage.error_no_such_channel(self.client.identity, target))

    @validate(identity=True)
    def mode(self, msg):
        target = msg.args[0]
        flags = msg.args[1]

        if target in self.irc.clients:
            self.irc.set_user_mode(self.client, target, flags)
        elif target in self.irc.channels:
            self.irc.set_channel_mode(self.client, target, flags)


class IRC(object):
    def __init__(self, host):
        self.host = host
        self.running = True
        self.incoming = Queue()
        self.created = datetime.utcnow()

        self.clients = {}
        self.channels = {}
        self.nicknames = {}

    def get_channel(self, name):
        return self.channels.get(name)

    def set_channel(self, channel):
        self.channels[channel.name] = channel

    def has_channel(self, name):
        return name in self.channels

    def get_client(self, nickname):
        return self.clients.get(nickname)

    def set_client(self, client):
        self.clients[client.nickname] = client

    def remove_client(self, nickname):
        if nickname in self.clients:
            del self.clients[nickname]

    def has_nickname(self, nickname):
        return nickname in self.nicknames

    def get_nickname(self, nickname):
        return self.nicknames.get(nickname)

    def process(self, client, msg):
        msg = IRCMessage(msg[0], msg[1], *msg[2])
        handler = Handler(self, client)
        handler(msg)

    def submit(self, client, msg):
        self.incoming.put((client, msg))

    def set_nick(self, client, new_nickname):
        if client.nickname == new_nickname:
            return

        if self.has_nickname(new_nickname):
            raise IRCError(IRCMessage.error_nick_in_use(client.identity, new_nickname))

        old = client.nickname

        # assemble our message before changing nick
        msg = IRCMessage.nick(client.identity, new_nickname)

        client.set_nickname(new_nickname)
        self.set_client(client)

        nickname = self.get_nickname(old) if old else None
        if nickname:
            del self.nicknames[old]
            nickname.set_nick(new_nickname)
        else:
            nickname = Nickname(new_nickname)

        self.nicknames[nickname.nickname] = nickname

        if client.has_identity:
            client.send(msg)

            if old:
                self.remove_client(old)

            for channel_name in nickname.channels:
                channel = self.get_channel(channel_name)
                self.send_to_channel(client, channel.name, msg, skip_self=True)

    def set_ident(self, client, user, realname):

        client.set_identity(user, realname)

        log.info("%s connected", client.identity)

        client.send(IRCMessage.nick(client.identity, client.nickname))
        client.send(IRCMessage.reply_welcome(self.host, client.nickname, client.nickname, client.user, client.host))
        client.send(IRCMessage.reply_yourhost(self.host, client.nickname, SERVER_NAME, SERVER_VERSION))
        client.send(IRCMessage.reply_created(self.host, client.nickname, self.created))
        client.send(IRCMessage.reply_myinfo(self.host, client.nickname, SERVER_NAME, SERVER_VERSION))

    def drop_client(self, client):
        if client.nickname:
            self.remove_client(client.nickname)
        if client.is_connected:
            log.info("%s disconnected", client.identity)
            client.disconnect()

    def join_channel(self, name, client, key=None):
        nickname = self.get_nickname(client.nickname)
        channel = self.get_channel(name)
        if not channel:
            if name[0] not in CHAN_START_CHARS:
                raise IRCError(IRCMessage.error_no_such_channel(client.identity, name))

            channel = Channel(name, nickname, key=key)
            self.set_channel(channel)

        channel.join(nickname, key=key)

        self.send_to_channel(client, name, IRCMessage.join(client.identity, name))

        if channel.topic:
            client.send(IRCMessage.reply_topic(self.host, client.nickname, channel))
        else:
            client.send(IRCMessage.reply_notopic(self.host, client.nickname, channel))

        client.send(IRCMessage.reply_names(self.host, client.nickname, channel))
        client.send(IRCMessage.reply_endnames(self.host, client.nickname, channel))

        return channel

    def part_channel(self, name, client):
        channel = self.get_channel(name)
        if not channel:
            return
        nickname = self.get_nickname(client.nickname)
        self.send_to_channel(client, name, IRCMessage.part(client.identity, name))
        channel.part(nickname)

    def send_to_channel(self, client, channel_name, msg, skip_self=False):
        channel = self.get_channel(channel_name)
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(client.identity, channel_name))

        nickname = self.get_nickname(client.nickname)
        if nickname not in channel.members:
            raise IRCError(IRCMessage.error_not_in_channel(client.identity))

        for member in channel.members:
            if skip_self and member.nickname == client.nickname:
                continue
            member_client = self.clients.get(member.nickname)
            if member_client:
                member_client.send(msg)

    def send_private_message_to_channel(self, client, channel_name, text):
        self.send_to_channel(client, channel_name, IRCMessage.private_message(client.identity, channel_name, text), skip_self=True)

    def send_private_message_to_client(self, client, nickname, text):
        other = self.get_client(nickname)
        if not other:
            raise IRCError(IRCMessage.error_no_such_nickname(client.identity, nickname))
        other.send(IRCMessage.private_message(client.identity, nickname, text))

    def ping(self, client):
        client.send(IRCMessage.ping(self.host))

    def set_channel_mode(self, client, target, flags):
        channel = self.get_channel(target)
        op, flags = flags[0], flags[1:]

        modified = None
        if op == "+":
            modified = channel.set_mode(flags)
        elif op == "-":
            modified = channel.clear_mode(flags)

        if modified:
            self.send_to_channel(client, channel.name, IRCMessage.mode(client.identity, target, op + flags))

    def set_user_mode(self, client, target, flags):
        op, flags = flags[0], flags[1:]

        to_self = client.nickname == target

        if not to_self:
            raise IRCError(IRCMessage.error_users_dont_match(client.identity))

        nickname = self.get_nickname(client.nickname)

        if Mode.AWAY in flags or Mode.OPERATOR in flags:
            return

        modified = None
        if op == "+":
            modified = nickname.set_mode(flags)
        elif op == "-":
            modified = nickname.clear_mode(flags)

        if modified:
            client.send(IRCMessage.mode(client.identity, target, op + flags))
