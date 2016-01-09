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
        members = sorted([member.nickname for member in channel.members])
        return cls(prefix, "353", target, "=", channel.name, " ".join(sorted(members)))

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
    def error_needs_more_params(cls, prefix, command):
        return cls(prefix, "461", command, "Not enough parameters")

    @classmethod
    def error_bad_channel_key(cls, prefix, channel):
        return cls(prefix, "475", "{channel} :Cannot join channel (+k)".format(channel=channel))

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

    @classmethod
    def quit(cls, prefix, message):
        return cls(prefix, "QUIT", message)
