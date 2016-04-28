import string

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


class Prefix(object):
    def __init__(self, prefix):
        self.prefix = prefix

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
            self.host = prefix

    def __str__(self):
        return self.prefix

    @classmethod
    def from_parts(cls, nickname, user, host):
        return cls(u"{}!{}@{}".format(nickname, user, host))

    def to_dict(self):
        rv = {"host": self.host}
        if self.nickname:
            rv["nick"] = self.nickname
        if self.user:
            rv["user"] = self.user
        return rv


class IRCMessage(object):
    def __init__(self, prefix, command, *args):
        self.prefix = prefix
        self.command = command
        self.args = [args for args in args if args]

    def __str__(self):
        return "{}<command={}, args={}, prefix={}>".format(self.__class__.__name__, self.command, self.args, self.prefix)

    def to_dict(self):
        return {
            "prefix": self.prefix.to_dict() if self.prefix else None,
            "command": self.command,
            "args": self.args,
        }

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
                parts.append(":" + str(tail))
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
    def reply_away(cls, prefix, target, nickname, message):
        return cls(prefix, "301", target, nickname, message)

    @classmethod
    def reply_unaway(cls, prefix, target):
        return cls(prefix, "305", target, "You are no longer marked as being away")

    @classmethod
    def reply_nowaway(cls, prefix, target):
        return cls(prefix, "306", target, "You have been marked as being away")

    @classmethod
    def reply_notopic(cls, prefix, target, channel):
        return cls(prefix, "331", target, channel.name)

    @classmethod
    def reply_topic(cls, prefix, target, channel):
        return cls(prefix, "332", target, channel.name, channel.topic)

    @classmethod
    def reply_inviting(cls, prefix, target, channel, nick):
        return cls(prefix, "341", target, channel.name, nick.nickname)

    @classmethod
    def reply_names(cls, prefix, target, channel):
        members = sorted([member.nickname for member in channel.members])
        return cls(prefix, "353", target, "=", channel.name, " ".join(sorted(members)))

    @classmethod
    def reply_endnames(cls, prefix, target, channel):
        return cls(prefix, "366", target, channel.name, "End of /NAMES list.")

    @classmethod
    def reply_list_start(cls, prefix, target):
        return cls(prefix, "321", target, "Channel", "Users", "Name")

    @classmethod
    def reply_list(cls, prefix, target, channel):
        return cls(prefix, "322", target, channel.name, str(len(channel.members)), "(private)" if channel.is_private else channel.topic)

    @classmethod
    def reply_list_end(cls, prefix, target):
        return cls(prefix, "323", target, "End of /LIST")

    @classmethod
    def error_nick_in_use(cls, prefix, target, nickname):
        return cls(prefix, "433", target, nickname)

    @classmethod
    def error_not_in_channel(cls, prefix, target):
        return cls(prefix, "441", target)

    @classmethod
    def error_no_such_channel(cls, prefix, target, name):
        return cls(prefix, "403", target, "{channel} No such nick/channel".format(channel=name))

    @classmethod
    def error_no_such_nickname(cls, prefix, target, name):
        return cls(prefix, "401", target, "{nickname} No such nick/channel".format(nickname=name))

    @classmethod
    def error_needs_more_params(cls, prefix, target, command):
        return cls(prefix, "461", target, command, "Not enough parameters")

    @classmethod
    def error_invite_only_channel(cls, prefix, target, channel):
        return cls(prefix, "473", target, "{channel} :Cannot join channel (+i)".format(channel=channel))

    @classmethod
    def error_banned_from_channel(cls, prefix, target, channel):
        return cls(prefix, "474", target, "{channel} :Cannot join channel (+b)".format(channel=channel))

    @classmethod
    def error_bad_channel_key(cls, prefix, target, channel):
        return cls(prefix, "475", target, "{channel} :Cannot join channel (+k)".format(channel=channel))

    @classmethod
    def error_channel_operator_needed(cls, prefix, target, name):
        return cls(prefix, "482", target, "{channel} You're not channel operator".format(channel=name))

    @classmethod
    def error_users_dont_match(cls, prefix, target):
        return cls(prefix, "502", target, "Cant change mode for other users")

    @classmethod
    def nick(cls, prefix, nickname):
        return cls(prefix, "NICK", nickname)

    @classmethod
    def join(cls, prefix, channel):
        return cls(prefix, "JOIN", channel)

    @classmethod
    def part(cls, prefix, channel, message=None):
        args = (channel,)
        if message:
            args = args + (message,)
        return cls(prefix, "PART", *args)

    @classmethod
    def private_message(cls, prefix, target, msg):
        return cls(prefix, "PRIVMSG", target, msg)

    @classmethod
    def ping(cls, server):
        return cls(server, "PING", server)

    @classmethod
    def mode(cls, prefix, target, flags, params=None):
        return cls(prefix, "MODE", target, flags, params)

    @classmethod
    def quit(cls, prefix, message):
        return cls(prefix, "QUIT", message)

    @classmethod
    def invite(cls, prefix, nickname, channel):
        return cls(prefix, "INVITE", nickname.nickname, channel.name)

    @classmethod
    def kick(cls, prefix, channel, nickname, comment=None):
        return cls(prefix, "KICK", channel.name, nickname.nickname, comment)
