import logging
from Queue import Queue
from functools import wraps
from datetime import datetime

from .message import IRCMessage
from .mode import Mode, ModeParamMissing
from .common import IRCError

SERVER_NAME = "ircd"
SERVER_VERSION = "0.1"
CHAN_START_CHARS = "&#!+"

log = logging.getLogger(__name__)


def validate(nickname=False, identity=False, num_params=None):
    def _validate(func):
        @wraps(func)
        def __validate(self, msg):

            if (nickname and not self.client.has_nickname) or (identity and not self.client.has_identity):
                self.irc.drop_client(self.client)
                return None

            if num_params is not None and len(msg.args) < num_params:
                raise IRCError(IRCMessage.error_needs_more_params(self.client.prefix, msg.command))

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


class Channel(object):
    def __init__(self, name, owner, key=None):
        self.name = name
        self.owner = owner
        self.key = key
        self.topic = None
        self.members = [owner]
        self.operators = [owner]
        self.invited = []
        self.mode = Mode.for_channel(self)

    def __eq__(self, other):
        return other and self.name == other.name

    def __repr__(self):
        return "Channel({})".format(self.name)

    @property
    def is_topic_open(self):
        return not self.mode.has_flag(Mode.CHANNEL_TOPIC_CLOSED)

    def is_operator(self, nickname):
        return nickname in self.operators

    @property
    def is_invite_only(self):
        return self.mode.has_flag(Mode.CHANNEL_IS_INVITE_ONLY)

    def can_join_channel(self, nickname):
        return nickname in self.invited if self.is_invite_only else True

    def set_topic(self, topic):
        self.topic = topic

    def join(self, nickname, key=None):
        if self.key and key != self.key:
            return False

        if nickname not in self.members:
            log.info("%s joined %s", nickname, self.name)
            self.members.append(nickname)
        nickname.joined_channel(self)
        return True

    def part(self, nickname):
        if nickname in self.members:
            log.info("%s parted %s", nickname, self.name)
            self.members.remove(nickname)
        nickname.parted_channel(self)

    def set_mode(self, flags, param=None):
        return self.mode.set_flags(flags, param=param)

    def clear_mode(self, flags):
        return self.mode.clear_flags(flags)

    def invite(self, nickname):
        if nickname not in self.invited:
            self.invited.append(nickname)

    def uninvite(self, nickname):
        if nickname in self.invited:
            self.invited.remove(nickname)


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

    @validate(nickname=True, num_params=4)
    def user(self, msg):
        user, mode, _, realname = msg.args
        self.irc.set_ident(self.client, user, realname)

    @validate(identity=True, num_params=1)
    def ping(self, msg):
        self.client.send(IRCMessage.reply_pong(self.irc.host, msg.args[0]))

    def quit(self, msg):
        message = msg.args[0] if msg.args else "client quit"
        self.irc.drop_client(self.client, message=message)

    @validate(identity=True, num_params=1)
    def join(self, msg):
        chan_name = msg.args[0]
        key = msg.args[1] if len(msg.args) > 1 else None
        self.irc.join_channel(chan_name, self.client, key=key)

    @validate(identity=True, num_params=1)
    def part(self, msg):
        chan_name = msg.args[0]
        message = msg.args[1] if len(msg.args) > 1 else None
        print chan_name, message, msg.args
        self.irc.part_channel(chan_name, self.client, message=message)

    @validate(identity=True, num_params=2)
    def privmsg(self, msg):
        target = msg.args[0]

        if target in self.irc.channels:
            self.irc.send_private_message_to_channel(self.client, target, msg.args[1])
        elif target in self.irc.clients:
            self.irc.send_private_message_to_client(self.client, target, msg.args[1])
        else:
            self.client.send(IRCMessage.error_no_such_channel(self.client.identity, target))

    @validate(identity=True, num_params=2)
    def mode(self, msg):
        target = msg.args[0]
        flags = msg.args[1]
        param = msg.args[2] if len(msg.args) > 2 else None

        if target in self.irc.clients:
            self.irc.set_user_mode(self.client, target, flags)
        elif target in self.irc.channels:
            self.irc.set_channel_mode(self.client, target, flags, param=param)

    @validate(identity=True, num_params=1)
    def topic(self, msg):
        channel_name = msg.args[0]
        channel = self.irc.get_channel(channel_name)
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.client.identity, channel_name))

        if len(msg.args) > 1:
            self.irc.set_topic(self.client, channel, msg.args[1])

        self.irc.send_topic(self.client, channel)

    @validate(identity=True, num_params=2)
    def invite(self, msg):
        nickname = self.irc.get_nickname(msg.args[0])
        if not nickname:
            raise IRCError(IRCMessage.error_no_such_nickname(self.client.prefix, msg.args[0]))

        channel = self.irc.get_channel(msg.args[1])
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.client.prefix, msg.args[1]))

        if not channel.is_operator(self.irc.get_nickname(self.client.nickname)):
            raise IRCError(IRCMessage.error_channel_operator_needed(self.client.prefix, msg.args[1]))

        channel.invite(nickname)
        self.client.send(IRCMessage.reply_inviting(self.client.identity, channel, nickname))

        other_client = self.irc.get_client(nickname.nickname)
        other_client.send(IRCMessage.invite(self.client.identity, nickname, channel))

    @validate(identity=True, num_params=1)
    def names(self, msg):
        pass


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
                self.send_to_channel(client, channel, msg, skip_self=True)

    def set_ident(self, client, user, realname):

        client.set_identity(user, realname)

        log.info("%s connected", client.identity)

        client.send(IRCMessage.nick(client.identity, client.nickname))
        client.send(IRCMessage.reply_welcome(self.host, client.nickname, client.nickname, client.user, client.host))
        client.send(IRCMessage.reply_yourhost(self.host, client.nickname, SERVER_NAME, SERVER_VERSION))
        client.send(IRCMessage.reply_created(self.host, client.nickname, self.created))
        client.send(IRCMessage.reply_myinfo(self.host, client.nickname, SERVER_NAME, SERVER_VERSION))

    def drop_client(self, client, message=None):
        if client.nickname:
            self.remove_client(client.nickname)
        if client.is_connected:
            log.info("%s disconnected", client.identity)
            client.disconnect()
        nickname = self.get_nickname(client.nickname)
        if nickname:
            for channel in nickname.channels:
                self.send_to_channel(client, channel, IRCMessage.quit(client.identity, message), skip_self=True)

    def join_channel(self, name, client, key=None):
        nickname = self.get_nickname(client.nickname)
        channel = self.get_channel(name)
        if not channel:
            if name[0] not in CHAN_START_CHARS:
                raise IRCError(IRCMessage.error_no_such_channel(client.identity, name))

            channel = Channel(name, nickname)
            self.set_channel(channel)

        if not channel.can_join_channel(nickname):
            raise IRCError(IRCMessage.error_invite_only_channel(client.identity, name))

        joined = channel.join(nickname, key=key)
        if not joined:
            client.send(IRCMessage.error_bad_channel_key(client.identity, channel.name))
            return

        self.send_to_channel(client, channel, IRCMessage.join(client.identity, name))

        self.send_topic(client, channel)

        client.send(IRCMessage.reply_names(self.host, client.nickname, channel))
        client.send(IRCMessage.reply_endnames(self.host, client.nickname, channel))

    def send_topic(self, client, channel):
        if channel.topic:
            client.send(IRCMessage.reply_topic(self.host, client.nickname, channel))
        else:
            client.send(IRCMessage.reply_notopic(self.host, client.nickname, channel))

    def set_topic(self, client, channel, topic):
        nickname = self.get_nickname(client.nickname)
        if channel.is_operator(nickname) or channel.is_topic_open:
            channel.set_topic(topic)

    def part_channel(self, name, client, message=None):
        channel = self.get_channel(name)
        if not channel:
            return
        nickname = self.get_nickname(client.nickname)
        self.send_to_channel(client, channel, IRCMessage.part(client.identity, name, message=message))
        channel.part(nickname)

    def send_to_channel(self, client, channel, msg, skip_self=False):
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
        channel = self.get_channel(channel_name)
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(client.identity, channel_name))

        self.send_to_channel(client, channel, IRCMessage.private_message(client.identity, channel_name, text), skip_self=True)

    def send_private_message_to_client(self, client, nickname, text):
        other = self.get_client(nickname)
        if not other:
            raise IRCError(IRCMessage.error_no_such_nickname(client.identity, nickname))
        other.send(IRCMessage.private_message(client.identity, nickname, text))

    def ping(self, client):
        client.send(IRCMessage.ping(self.host))

    def set_channel_mode(self, client, target, flags, param=None):
        channel = self.get_channel(target)
        op, flags = flags[0], flags[1:]

        modified = None
        if op == "+":
            try:
                modified = channel.set_mode(flags, param=param)
            except ModeParamMissing:
                raise IRCError(IRCMessage.error_needs_more_params(client.identity, "MODE"))
        elif op == "-":
            modified = channel.clear_mode(flags)

        if modified:
            self.send_to_channel(client, channel, IRCMessage.mode(client.identity, target, op + flags))

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
