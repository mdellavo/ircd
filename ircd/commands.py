import logging
from functools import wraps

from ircd.message import IRCMessage
from ircd.common import IRCError

log = logging.getLogger(__name__)


def validate(nickname=False, identity=False, num_params=None):
    def _validate(func):
        @wraps(func)
        def __validate(self, msg):

            if (nickname and not self.client.has_nickname) or (identity and not self.client.has_identity):
                self.irc.drop_client(self.client, "invalid")
                return None

            if num_params is not None and len(msg.args) < num_params:
                raise IRCError(IRCMessage.error_needs_more_params(self.irc.host, self.client.get_name(), msg.command))

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
        self.irc.add_link(self.client, name, hop_count, token, info)

    @validate(nickname=True, num_params=4)
    def user(self, msg):
        user, mode, _, realname = msg.args
        self.irc.set_ident(self.client, user, realname)

    @validate(identity=True, num_params=1)
    def ping(self, msg):
        self.client.send(IRCMessage.reply_pong(msg.prefix, msg.args[0]))

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

        if self.irc.has_channel(target):
            self.irc.send_private_message_to_channel(self.client, target, msg.args[1])
        elif self.irc.has_nickname(target):
            self.irc.send_private_message_to_client(self.client, target, msg.args[1])
        else:
            raise IRCError(IRCMessage.error_no_such_channel(self.irc.host, self.client.get_name(), target))

    @validate(identity=True, num_params=1)
    def mode(self, msg):
        target = msg.args[0]
        flags = msg.args[1] if len(msg.args) > 1 else None
        param = msg.args[2] if len(msg.args) > 2 else None

        if self.irc.has_nickname(target):
            if flags:
                self.irc.set_user_mode(self.client, target, flags)
            else:
                self.irc.send_user_mode(self.client, target)
        elif self.irc.has_channel(target):
            if flags:
                self.irc.set_channel_mode(self.client, target, flags, param=param)
            else:
                self.irc.send_channel_mode(self.client, target)

    @validate(identity=True, num_params=1)
    def topic(self, msg):
        channel_name = msg.args[0]
        channel = self.irc.get_channel(channel_name)
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.irc.host,  self.client.get_name(), channel_name))

        if len(msg.args) > 1:
            self.irc.set_topic(self.client, channel, msg.args[1])

        self.irc.send_topic(self.client, channel)

    @validate(identity=True, num_params=2)
    def invite(self, msg):
        nickname = self.irc.get_nickname(msg.args[0])
        if not nickname:
            raise IRCError(IRCMessage.error_no_such_nickname(self.irc.host, self.client.get_name(), msg.args[0]))

        channel = self.irc.get_channel(msg.args[1])
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.irc.host, self.client.get_name(), msg.args[1]))

        if not channel.is_operator(self.irc.get_nickname(self.client.get_name())):
            raise IRCError(IRCMessage.error_channel_operator_needed(self.irc.host, self.client.get_name(), msg.args[1]))

        self.irc.invite(self.client, nickname, channel)

    @validate(identity=True, num_params=2)
    def kick(self, msg):
        channel = self.irc.get_channel(msg.args[0])
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.irc.host, self.client.get_name(), msg.args[0]))

        if not channel.is_operator(self.irc.get_nickname(self.client.get_name())):
            raise IRCError(IRCMessage.error_channel_operator_needed(self.irc.host, self.client.get_name(), msg.args[0]))

        nickname = self.irc.get_nickname(msg.args[1])
        if not nickname:
            raise IRCError(IRCMessage.error_no_such_nickname(self.irc.host, self.client.get_name(), msg.args[1]))

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
            msg = IRCMessage.reply_nowaway(self.irc.host, self.client.get_name())
        else:
            nickname.clear_away()
            msg = IRCMessage.reply_unaway(self.irc.host, self.client.get_name())
        self.client.send(msg)
