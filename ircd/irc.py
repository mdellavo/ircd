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


class ModeFlag(object):
    KEY = None

    def __init__(self):
        self.value = False

    def set(self, param=None):
        self.value = True

    def clear(self):
        self.value = False

    def is_set(self):
        return self.value


class UserModeFlag(ModeFlag):
    def __init__(self, nickname):
        super(UserModeFlag, self).__init__()
        self.nickname = nickname


class ChannelModeFlag(ModeFlag):
    def __init__(self, channel):
        super(ChannelModeFlag, self).__init__()
        self.channel = channel


class UserAwayFlagFlag(UserModeFlag):
    KEY = "a"


class UserInvisibleFlagFlag(UserModeFlag):
    KEY = "i"


class UserWallopsFlagFlag(UserModeFlag):
    KEY = "w"


class UserRestrictedFlagFlag(UserModeFlag):
    KEY = "r"


class UserLocalOperatorFlagFlag(UserModeFlag):
    KEY = "O"


class UserOperatorFlagFlag(UserModeFlag):
    KEY = "o"


class UserServerNoticesFlagFlag(UserModeFlag):
    KEY = "s"


class ChannelPrivateFlagFlag(ChannelModeFlag):
    KEY = "p"


class ChannelInviteOnlyFlagFlag(ChannelModeFlag):
    KEY = "i"


class ChannelTopicClosedFlagFlag(ChannelModeFlag):
    KEY = "t"


class ChannelNoMessagesFlagFlag(ChannelModeFlag):
    KEY = "n"


class ChannelModeratedFlagFlag(ChannelModeFlag):
    KEY = "m"


class ChannelUserLimitFlagFlag(ChannelModeFlag):
    KEY = "l"


class ChannelBanMaskFlagFlag(ChannelModeFlag):
    KEY = "b"


class ChannelVoiceFlagFlag(ChannelModeFlag):
    KEY = "v"


class ChannelKeyFlagFlag(ChannelModeFlag):
    KEY = "k"


class ChannelSecretFlagFlag(ChannelModeFlag):
    KEY = "s"


class ChannelOperatorFlagFlag(ChannelModeFlag):
    KEY = "o"


class Mode(object):

    AWAY = "a"
    INVISIBLE = "i"
    WALLOPS = "w"
    RESTRICTED = "r"
    OPERATOR = "o"
    LOCAL_OPERATOR = "O"
    SERVER_NOTICES = "s"

    ALL_USER_MODES = (UserAwayFlagFlag, UserInvisibleFlagFlag, UserWallopsFlagFlag, UserRestrictedFlagFlag, UserLocalOperatorFlagFlag,
                      UserServerNoticesFlagFlag, UserOperatorFlagFlag)
    ALL_CHANNEL_MODES = (ChannelPrivateFlagFlag, ChannelSecretFlagFlag, ChannelInviteOnlyFlagFlag, ChannelTopicClosedFlagFlag,
                         ChannelNoMessagesFlagFlag, ChannelModeratedFlagFlag, ChannelUserLimitFlagFlag, ChannelBanMaskFlagFlag,
                         ChannelVoiceFlagFlag, ChannelKeyFlagFlag, ChannelOperatorFlagFlag)

    def __init__(self, flags):
        self.flags = {flag.KEY: flag for flag in flags}

    @classmethod
    def for_nickname(cls, nickname):
        flags = [flag_class(nickname) for flag_class in cls.ALL_USER_MODES]
        return cls(flags)

    @classmethod
    def for_channel(cls, channel):
        flags = [flag_class(channel) for flag_class in cls.ALL_CHANNEL_MODES]
        return cls(flags)

    def __str__(self):
        return sorted(self.mode)

    @property
    def mode(self):
        return "".join(key for key, flag in self.flags.items() if flag.is_set())

    def has_flag(self, flag):
        if flag not in self.flags:
            return False
        return self.flags[flag].is_set()

    def clear_flag(self, flag):
        is_set = self.has_flag(flag)
        if is_set:
            self.flags[flag].clear()
        return is_set

    def set_flag(self, flag, param=None):
        flag_set = False
        if flag in self.flags:
            self.flags[flag].set(param=param)
            flag_set = True
        return flag_set


class IRCMessage(object):
    def __init__(self, prefix, command, *args):
        self.prefix = Prefix(prefix) if prefix else None
        self.command = command
        self.args = args

    def __str__(self):
        return "{}<command={}, args={}, prefix={}>".format(self.__class__.__name__, self.command, self.args, self.prefix)

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
        return cls(prefix, "403", "{channel} No such nick/channel".format(channel=name))

    @classmethod
    def error_no_such_nickname(cls, prefix, name):
        return cls(prefix, "401", "{nickname} No such nick/channel".format(nickname=name))

    @classmethod
    def error_channel_operator_needed(cls, prefix, name):
        return cls(prefix, "482", "{channel} You're not channel operator".format(channel=name))

    @classmethod
    def error_users_dont_match(cls, prefix):
        return cls(prefix, "502", "Cant change mode for other users")

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

    @classmethod
    def ping(cls, server):
        return cls(None, "PING", server)

    @classmethod
    def mode(cls, prefix, target, flags):
        return cls(prefix, "MODE", target, flags)


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

    def set_mode(self, flags):
        self.mode.set_channel_flags(flags)

    def clear_mode(self, flags):
        self.mode.clear_flags(flags)


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
        self.channels[channel.name.lower()] = channel

    def has_channel(self, name):
        return name in self.channels

    def get_client(self, nickname):
        return self.clients.get(nickname)

    def set_client(self, client):
        nickname = client.nickname.lower()
        self.clients[nickname] = client
        if nickname not in self.nicknames:
            self.nicknames[nickname] = Nickname(nickname)

    def remove_client(self, nickname):
        if nickname in self.clients:
            del self.clients[nickname]

    def has_client(self, nickname):
        return nickname in self.clients

    def get_nickname(self, client):
        return self.nicknames.get(client.nickname)

    def process(self, client, msg):
        msg = IRCMessage(msg[0], msg[1], *msg[2])
        handler = Handler(self, client)
        handler(msg)

    def submit(self, client, msg):
        self.incoming.put((client, msg))

    def set_nick(self, client, nickname):
        if client.nickname == nickname:
            return

        if self.has_client(nickname):
            raise IRCError(IRCMessage.error_nick_in_use(client.identity, nickname))

        old = client.nickname
        msg = IRCMessage.nick(client.identity, nickname)

        client.set_nickname(nickname)
        self.set_client(client)

        if client.has_identity:
            client.send(msg)

            if old:
                self.remove_client(old)

                # FIXME hold channel memberships in Nickname
                for channel in self.channels.values():
                    if channel.update_nick(old, nickname):
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
        channel = self.get_channel(name)
        if not channel:
            if name[0] not in CHAN_START_CHARS:
                raise IRCError(IRCMessage.error_no_such_channel(client.identity, name))

            channel = Channel(name, client.nickname, key=key)
            self.set_channel(channel)

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
        channel = self.get_channel(name)
        if not channel:
            return
        self.send_to_channel(client, name, IRCMessage.part(client.identity, name))
        channel.part(client.nickname)

    def send_to_channel(self, client, channel_name, msg, skip_self=False):
        channel = self.get_channel(channel_name)
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
        other = self.get_client(nickname)
        if not other:
            raise IRCError(IRCMessage.error_no_such_nickname(client.identity, nickname))
        other.send(IRCMessage.private_message(client.identity, nickname, text))

    def ping(self, client):
        client.send(IRCMessage.ping(self.host))

    def set_channel_mode(self, client, target, flags):
        channel = self.get_channel(target)
        op, flags = flags[0], flags[1:]

        if op == "+":
            channel.set_mode(flags)
        elif op == "-":
            channel.clear_mode(flags)

    def set_user_mode(self, client, target, flag):
        op, flag = flag[0], flag[1:]

        to_self = client.nickname == target

        if not to_self:
            raise IRCError(IRCMessage.error_users_dont_match(client.identity))

        nickname = self.get_nickname(client)

        if Mode.AWAY in flag or Mode.OPERATOR in flag:
            return

        modified = None
        if op == "+":
            modified = nickname.mode.set_flag(flag)
        elif op == "-":
            modified = nickname.mode.clear_flag(flag)

        if modified:
            client.send(IRCMessage.mode(client.identity, target, op + flag))
