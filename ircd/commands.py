import logging
import base64
import binascii
from functools import wraps

from ircd.message import IRCMessage
from ircd.common import IRCError

log = logging.getLogger(__name__)


def validate(nickname=False, identity=False, num_params=None):
    def _validate(func):
        @wraps(func)
        def __validate(self, msg):
            # log.debug("validate: %s", msg)
            if (nickname and not self.client.has_nickname) or (identity and not self.client.has_identity):
                self.irc.drop_client(self.client, "invalid")
                return None

            if num_params is not None and len(msg.args) < num_params:
                raise IRCError(IRCMessage.error_needs_more_params(self.irc.host, self.client.name, msg.command))

            return func(self, msg)
        return __validate
    return _validate


class Handler:
    def __init__(self, irc, client):
        self.irc = irc
        self.client = client

    def __call__(self, msg):
        handler = msg.command.lower()

        # log.debug("dispatching: %s", handler)

        callback = getattr(self, handler, None)
        if callback and callable(callback):
            try:
                callback(msg)
            except IRCError as e:
                self.client.send(e.msg)
            except Exception:
                log.exception("error applying message: %s", msg)

        nickname = self.irc.get_nickname(self.client.name) if self.client.name else None
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

    def cap(self, msg):
        command = msg.args[0].upper()
        if command in ("LS", "LIST"):
            self.irc.send_capabilities(self.client)
        elif command == "REQ":
            caps = msg.args[1].split()
            self.irc.request_capabilities(self.client, caps)
        elif command in ("END",):  # IGNORED
            pass
        else:
            self.client.send(IRCMessage.error_invalid_cap_subcommand(self.irc.host, self.client.name, command))

    def authenticate(self, msg):

        if not self.client.authentication_method:  # initial message
            if msg.args[0] != "PLAIN":
                self.client.send(IRCMessage.error_sasl_mechanism(self.irc.host, self.client.name))
                return

            self.client.authentication_method = msg.args[0]
            self.client.send(IRCMessage.sasl_continue(self.irc.host))
        else:  # authentication message
            try:
                auth = base64.b64decode(msg.args[0])
            except binascii.Error:
                self.client.send(IRCMessage.error_sasl_fail(self.irc.host, self.client.name))
                return

            parts = [part.decode().strip() for part in auth.split(b'\x00')]
            if len(parts) < 3:
                self.client.send(IRCMessage.error_sasl_fail(self.irc.host, self.client.name))
                return

            authzid, authcid, password = parts
            valid = self.irc.authenticate(self.client.name, authcid, password)
            if valid:
                self.client.send(IRCMessage.sasl_logged_in(self.irc.host, self.client.name, self.client.identity, authcid))
                self.client.send(IRCMessage.sasl_success(self.irc.host, self.client.name))
            else:
                self.client.send(IRCMessage.error_sasl_fail(self.irc.host, self.client.name))

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
            self.irc.send_private_message_to_channel(self.client, target, msg)
        elif self.irc.has_nickname(target):
            self.irc.send_private_message_to_client(self.client, target, msg)
        else:
            raise IRCError(IRCMessage.error_no_such_channel(self.irc.host, self.client.name, target))

    @validate(identity=True, num_params=2)
    def notice(self, msg):
        target = msg.args[0]

        if self.irc.has_channel(target):
            self.irc.send_notice_to_channel(self.client, target, msg)
        elif self.irc.has_nickname(target):
            self.irc.send_notice_to_client(self.client, target, msg)
        else:
            raise IRCError(IRCMessage.error_no_such_channel(self.irc.host, self.client.name, target))

    @validate(identity=True, num_params=1)
    def tagmsg(self, msg):
        target = msg.args[0]
        if self.irc.has_channel(target):
            self.irc.send_tag_message_to_channel(self.client, target, msg)
        elif self.irc.has_nickname(target):
            self.irc.send_tag_message_to_client(self.client, target, msg)
        else:
            raise IRCError(IRCMessage.error_no_such_channel(self.irc.host, self.client.name, target))

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
            raise IRCError(IRCMessage.error_no_such_channel(self.irc.host, self.client.name, channel_name))

        if len(msg.args) > 1:
            self.irc.set_topic(self.client, channel, msg.args[1])
        else:
            self.irc.send_topic(self.client, channel)

    @validate(identity=True, num_params=2)
    def invite(self, msg):
        nickname = self.irc.get_nickname(msg.args[0])
        if not nickname:
            raise IRCError(IRCMessage.error_no_such_nickname(self.irc.host, self.client.name, msg.args[0]))

        channel = self.irc.get_channel(msg.args[1])
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.irc.host, self.client.name, msg.args[1]))

        if not channel.is_operator(self.irc.get_nickname(self.client.name)):
            raise IRCError(IRCMessage.error_channel_operator_needed(self.irc.host, self.client.name, msg.args[1]))

        self.irc.invite(self.client, nickname, channel)

    @validate(identity=True, num_params=2)
    def kick(self, msg):
        channel = self.irc.get_channel(msg.args[0])
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.irc.host, self.client.name, msg.args[0]))

        if not channel.is_operator(self.irc.get_nickname(self.client.name)):
            raise IRCError(IRCMessage.error_channel_operator_needed(self.irc.host, self.client.name, msg.args[0]))

        nickname = self.irc.get_nickname(msg.args[1])
        if not nickname:
            raise IRCError(IRCMessage.error_no_such_nickname(self.irc.host, self.client.name, msg.args[1]))

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

    @validate(identity=True)
    def motd(self, msg):
        self.irc.send_motd(self.client)

    # FIXME push to IRC
    @validate(identity=True)
    def away(self, msg):
        message = msg.args[0] if msg.args else None
        nickname = self.irc.get_nickname(self.client.name)
        if message:
            nickname.set_away(message)
            msg = IRCMessage.reply_nowaway(self.irc.host, self.client.name)
        else:
            nickname.clear_away()
            msg = IRCMessage.reply_unaway(self.irc.host, self.client.name)
        self.client.send(msg)
