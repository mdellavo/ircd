import logging
from Queue import Queue
from functools import wraps
from datetime import datetime

from ircd.chan import Channel
from ircd.nick import Nickname
from ircd.message import IRCMessage
from ircd.mode import Mode, ModeParamMissing
from ircd.common import IRCError

SERVER_NAME = "ircd"
SERVER_VERSION = "0.1"
CHAN_START_CHARS = "&#!+"

log = logging.getLogger(__name__)


def validate(nickname=False, identity=False, num_params=None):
    def _validate(func):
        @wraps(func)
        def __validate(self, msg):

            if (nickname and not self.client.has_nickname) or (identity and not self.client.has_identity):
                self.irc.drop_client(self.client, "invalid")
                return None

            if num_params is not None and len(msg.args) < num_params:
                raise IRCError(IRCMessage.error_needs_more_params(self.client.identity, msg.command))

            return func(self, msg)
        return __validate
    return _validate


class Handler(object):
    def __init__(self, irc, client):
        self.irc = irc
        self.client = client

    def __call__(self, msg):
        handler = msg.command.lower()

        #log.debug("dispatching: %s", handler)

        callback = getattr(self, handler, None)
        if callback and callable(callback):
            try:
                callback(msg)
            except IRCError as e:
                self.client.send(e.msg)
            except:
                log.exception("error applying message: %s", msg)

        nickname = self.irc.get_nickname(self.client.get_name()) if self.client.get_name() else None
        if nickname:
            nickname.seen()

    def nick(self, msg):
        nickname = msg.args[0]
        self.irc.set_nick(self.client, nickname)

    def pong(self, _):
        self.client.clear_ping_count()

    @validate(num_params=4)
    def server(self, msg):
        name, hop_count, token, info = msg.args
        self.client.set_server(name, hop_count, token, info)
        self.irc.add_link(self.client)

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
            raise IRCError(IRCMessage.error_no_such_nickname(self.client.identity, msg.args[0]))

        channel = self.irc.get_channel(msg.args[1])
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.client.identity, msg.args[1]))

        if not channel.is_operator(self.irc.get_nickname(self.client.get_name())):
            raise IRCError(IRCMessage.error_channel_operator_needed(self.client.identity, msg.args[1]))

        self.irc.invite(self.client, nickname, channel)

    @validate(identity=True, num_params=2)
    def kick(self, msg):
        channel = self.irc.get_channel(msg.args[0])
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.client.identity, msg.args[0]))

        if not channel.is_operator(self.irc.get_nickname(self.client.get_name())):
            raise IRCError(IRCMessage.error_channel_operator_needed(self.client.identity, msg.args[0]))

        nickname = self.irc.get_nickname(msg.args[1])
        if not nickname:
            raise IRCError(IRCMessage.error_no_such_nickname(self.client.identity, msg.args[1]))

        comment = msg.args[2] if len(msg.args) > 2 else None
        self.irc.kick(self.client, channel, nickname, comment=comment)

    # FIXME push to IRC
    @validate(identity=True, num_params=1)
    def names(self, msg):
        channel_names = msg.args[0].split(",")
        for channel_name in channel_names:
            channel = self.irc.get_channel(channel_name)
            if channel:
                self.irc.send_names(self.client, channel)

    @validate(identity=True)
    def list(self, msg):
        channel_names = msg.args[0].split(",") if msg.args else None
        channels = self.irc.list_channels(self.client, names=channel_names)
        self.irc.send_list(self.client, channels)

    # FIXME push to IRC
    @validate(identity=True)
    def away(self, msg):
        message = msg.args[0] if msg.args else None
        nickname = self.irc.get_nickname(self.client.get_name())
        if message:
            nickname.set_away(message)
            msg = IRCMessage.reply_nowaway(self.client.identity)
        else:
            nickname.clear_away()
            msg = IRCMessage.reply_unaway(self.client.identity)
        self.client.send(msg)


class IRC(object):
    def __init__(self, host):
        self.host = host
        self.running = True
        self.incoming = Queue()
        self.created = datetime.utcnow()

        self.clients = {}
        self.links = []

        self.channels = {}
        self.nicknames = {}

    def add_link(self, link):
        self.links.append(link)

    def forward_message(self, msg):
        for link in self.links:
            link.send(msg)

    def get_channels(self):
        return self.channels.values()

    def get_channel(self, name):
        return self.channels.get(name)

    def set_channel(self, channel):
        self.channels[channel.name] = channel

    def has_channel(self, name):
        return name in self.channels

    def list_channels(self, client, names=None):
        nickname = self.get_nickname(client.get_name())

        def include_channel(channel):
            return (not channel.is_secret or channel.is_member(nickname)) and (not names or channel.name in names)

        return [channel for channel in self.channels.values() if include_channel(channel)]

    def get_client(self, nickname):
        return self.clients.get(nickname)

    def set_client(self, client):
        self.clients[client.get_name()] = client

    def remove_client(self, nickname):
        if nickname in self.clients:
            del self.clients[nickname]

    def get_nicknames(self):
        return self.nicknames.values()

    def has_nickname(self, nickname):
        return nickname in self.nicknames

    def get_nickname(self, nickname):
        return self.nicknames.get(nickname)

    def process(self, client, msg):
        msg = IRCMessage(msg[0], msg[1], *msg[2])
        handler = Handler(self, client)
        handler(msg)

    def processor(self):
        while True:
            client, msg = self.incoming.get()
            self.process(client, msg)

    def submit(self, client, msg):
        self.incoming.put((client, msg))

    def set_nick(self, client, new_nickname):
        if client.get_name() == new_nickname:
            return

        if self.has_nickname(new_nickname):
            raise IRCError(IRCMessage.error_nick_in_use(client.identity, new_nickname))

        old = client.get_name()

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

        client.send(IRCMessage.nick(client.identity, client.get_name()))
        client.send(IRCMessage.reply_welcome(self.host, client.get_name(), client.get_name(), client.user, client.host))
        client.send(IRCMessage.reply_yourhost(self.host, client.get_name(), SERVER_NAME, SERVER_VERSION))
        client.send(IRCMessage.reply_created(self.host, client.get_name(), self.created))
        client.send(IRCMessage.reply_myinfo(self.host, client.get_name(), SERVER_NAME, SERVER_VERSION))

    def drop_client(self, client, message=None):
        if client.get_name():
            self.remove_client(client.get_name())
        if client.is_connected:
            log.info("%s disconnected (%s)", client.identity, message or "none")
            client.disconnect()
        nickname = self.get_nickname(client.get_name())
        if nickname:
            for channel in nickname.channels:
                self.send_to_channel(client, channel, IRCMessage.quit(client.identity, message), skip_self=True)

    def join_channel(self, name, client, key=None):
        nickname = self.get_nickname(client.get_name())
        channel = self.get_channel(name)
        if not channel:
            if name[0] not in CHAN_START_CHARS:
                raise IRCError(IRCMessage.error_no_such_channel(client.identity, name))

            channel = Channel(name, nickname)
            self.set_channel(channel)

        if not channel.can_join_channel(nickname):
            raise IRCError(IRCMessage.error_invite_only_channel(client.identity, name))

        if channel.is_banned(client.identity):
            raise IRCError(IRCMessage.error_banned_from_channel(client.identity, name))

        joined = channel.join(nickname, key=key)
        if not joined:
            client.send(IRCMessage.error_bad_channel_key(client.identity, channel.name))
            return

        self.send_to_channel(client, channel, IRCMessage.join(client.identity, name))

        self.send_topic(client, channel)
        self.send_names(client, channel)

    def send_names(self, client, channel):
        nickname = self.get_nickname(client.get_name())
        if not (channel.is_private or channel.is_secret) or channel.is_member(nickname):
            client.send(IRCMessage.reply_names(self.host, client.get_name(), channel))
            client.send(IRCMessage.reply_endnames(self.host, client.get_name(), channel))

    def send_list(self, client, channels):
        client.send(IRCMessage.reply_list_start(client.identity))
        for channel in channels:
            client.send(IRCMessage.reply_list(client.identity, channel))
        client.send(IRCMessage.reply_list_end(client.identity))

    def send_topic(self, client, channel):
        if channel.topic:
            client.send(IRCMessage.reply_topic(self.host, client.get_name(), channel))
        else:
            client.send(IRCMessage.reply_notopic(self.host, client.get_name(), channel))

    def set_topic(self, client, channel, topic):
        nickname = self.get_nickname(client.get_name())
        if channel.is_operator(nickname) or channel.is_topic_open:
            channel.set_topic(topic)

    def part_channel(self, name, client, message=None):
        channel = self.get_channel(name)
        if not channel:
            return
        nickname = self.get_nickname(client.get_name())
        self.send_to_channel(client, channel, IRCMessage.part(client.identity, name, message=message))
        channel.part(nickname)

    def send_to_channel(self, client, channel, msg, skip_self=False):
        nickname = self.get_nickname(client.get_name())
        if nickname not in channel.members:
            raise IRCError(IRCMessage.error_not_in_channel(client.identity))

        for member in channel.members:
            if skip_self and member.nickname == client.get_name():
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

        other_nick = self.get_nickname(nickname)
        if other_nick.is_away:
            client.send(IRCMessage.reply_away(other.identity, nickname, other_nick.away_message))
        else:
            other.send(IRCMessage.private_message(client.identity, nickname, text))

    def ping(self, client):
        client.send(IRCMessage.ping(self.host))

    def set_channel_mode(self, client, target, flags, param=None):
        channel = self.get_channel(target)
        nickname = self.get_nickname(client.get_name())
        if not channel.is_operator(nickname):
            raise IRCError(IRCMessage.error_channel_operator_needed(client.identity, channel.name))

        op, flags = flags[0], flags[1:]

        modified = None
        try:
            if op == "+":
                modified = channel.set_mode(flags, param=param)
            elif op == "-":
                modified = channel.clear_mode(flags, param=param)
        except ModeParamMissing:
            raise IRCError(IRCMessage.error_needs_more_params(client.identity, "MODE"))

        if modified:
            self.send_to_channel(client, channel, IRCMessage.mode(client.identity, target, op + flags, param))

    def set_user_mode(self, client, target, flags):
        op, flags = flags[0], flags[1:]

        to_self = client.get_name() == target

        if not to_self:
            raise IRCError(IRCMessage.error_users_dont_match(client.identity))

        nickname = self.get_nickname(client.get_name())

        if Mode.AWAY in flags or Mode.OPERATOR in flags:
            return

        modified = None
        if op == "+":
            modified = nickname.set_mode(flags)
        elif op == "-":
            modified = nickname.clear_mode(flags)

        if modified:
            client.send(IRCMessage.mode(client.identity, target, op + flags))

    def invite(self, client, nickname, channel):
        channel.invite(nickname)
        client.send(IRCMessage.reply_inviting(client.identity, channel, nickname))

        other_client = self.get_client(nickname.nickname)
        other_client.send(IRCMessage.invite(client.identity, nickname, channel))

    def kick(self, client, channel, nickname, comment=None):
        channel.kick(nickname)
        other_client = self.get_client(nickname.nickname)
        other_client.send(IRCMessage.kick(client.identity, channel, nickname, comment=comment))
