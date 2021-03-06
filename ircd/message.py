import uuid
import string
import datetime

TERMINATOR = "\r\n"


def utcnow():
    return datetime.datetime.utcnow()


def generate_id():
    return uuid.uuid4().hex


# https://stackoverflow.com/questions/930700/python-parsing-irc-messages
def parsemsg(s):
    """
    Breaks a message from an IRC server into its prefix, command, and arguments.
    """
    prefix = ''
    tags = ''
    if not s:
        raise ValueError("Empty line.")
    if s[0] == "@":
        all_tags, s = s[1:].split(' ', 1)
        tags = all_tags.split(";")
    if s[0] == ':':
        prefix, s = s[1:].split(' ', 1)
    if s.find(' :') != -1:
        s, trailing = s.split(' :', 1)
        args = s.split()
        args.append(trailing)
    else:
        args = s.split()
    command = args.pop(0)

    return tags, prefix, command, args


class Prefix:
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


class Tag:
    def __init__(self, tag):
        self.tag = tag

        parts = tag.split("=", 1)
        self.name = parts[0]
        self.value = parts[1] if len(parts) > 1 else None
        self.is_client_tag = self.name[0] == "+"

    @classmethod
    def build(cls, name, value):
        return cls(name + "=" + value)

    def __str__(self):
        return "{}<tag={}>".format(self.__class__.__name__, self.tag)


class IRCMessage:
    def __init__(self, prefix, command, *args, tags=None):
        self.prefix = prefix
        self.command = command
        self.args = [arg for arg in args if arg]
        self.time = utcnow()
        self.id = generate_id()
        self.tags = {}
        if tags:
            self.tags.update({t.name: t for t in [Tag(tag) for tag in tags]})

    def __str__(self):
        return "{}<command={}, args={}, prefix={}, tags={}, id={}>".format(self.__class__.__name__, self.command, self.args,
                                                                           self.prefix, self.tags, self.id)

    def format(self, with_tags=False, with_time=False, with_id=False):
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

        if with_time:
            self.tags["time"] = Tag.build("time", self.time.isoformat() + "Z")
        if with_id:
            self.tags["msgid"] = Tag.build("msgid", self.id)
        if with_tags and self.tags:
            tags = ";".join([tag.tag for tag in self.tags.values()])
            rv = "@" + tags + " " + rv
        return rv

    @property
    def client_tags(self):
        return [tag.tag for tag in self.tags.values() if tag.is_client_tag]

    @classmethod
    def parse(cls, s):
        tags, prefix, command, args = parsemsg(s)
        return cls(prefix, command, *args, tags=tags)

    @classmethod
    def error_invalid_cap_subcommand(cls, prefix, nickname, command):
        return cls(prefix, "410", nickname or "*", command, "Invalid capability command")

    @classmethod
    def reply_list_capabilities(cls, prefix, nickname, capabilities):
        return cls(prefix, "CAP", nickname or "*", "LS", " ".join(capabilities) or " ")

    @classmethod
    def reply_ack_capabilities(cls, prefix, nickname, capabilities):
        return cls(prefix, "CAP", nickname or "*", "ACK", " ".join(capabilities))

    @classmethod
    def reply_nak_capabilities(cls, prefix, nickname, capabilities):
        return cls(prefix, "CAP", nickname or "*", "NAK", " ".join(capabilities))

    @classmethod
    def error_sasl_mechanism(cls, prefix, nickname):
        return cls(prefix, "908", nickname or "*", "PLAIN", "are available sasl mechanisms")

    @classmethod
    def sasl_logged_in(cls, prefix, nickname, identity, account):
        return cls(prefix, "900", nickname or "*", "you are now logged in")

    @classmethod
    def sasl_success(cls, prefix, nickname):
        return cls(prefix, "903", nickname or "*", "SASL authentication successful")

    @classmethod
    def error_sasl_fail(cls, prefix, nickname):
        return cls(prefix, "904", nickname or "*", "SASL authentication failed")

    @classmethod
    def sasl_continue(cls, prefix):
        return cls(prefix, "AUTHENTICATE +")

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
        return cls(prefix, "004", target, "{} {} {} {}".format(name, verison, string.ascii_letters, string.ascii_letters))

    @classmethod
    def reply_pong(cls, prefix, server):
        return cls(prefix, "PONG", server)

    @classmethod
    def reply_user_mode_is(cls, prefix, target, mode):
        return cls(prefix, "221", target, "+" + str(mode.mode))

    @classmethod
    def reply_channel_mode_is(cls, prefix, target, channel, mode, params=None):
        return cls(prefix, "324", target, channel, "+" + str(mode), params or "")

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
    def reply_topic_who_time(cls, prefix, target, channel, nick, set_at):
        return cls(prefix, "333", target, channel.name, nick.nickname, str(int(set_at)))

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
    def private_message(cls, prefix, target, msg, tags=None):
        return cls(prefix, "PRIVMSG", target, msg, tags=tags)

    @classmethod
    def notice(cls, prefix, target, msg, tags=None):
        return cls(prefix, "NOTICE", target, msg, tags=tags)

    @classmethod
    def tag_message(cls, prefix, target, tags):
        return cls(prefix, "TAGMSG", target, tags=tags)

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

    @classmethod
    def reply_no_motd(cls, prefix, target):
        return cls(prefix, "422", target, "no message of the day")

    @classmethod
    def reply_start_motd(cls, prefix, target):
        return cls(prefix, "375", target, "- message of the day -")

    @classmethod
    def reply_end_motd(cls, prefix, target):
        return cls(prefix, "376", target, "- end of message -")

    @classmethod
    def reply_motd(cls, prefix, target, msg):
        return cls(prefix, "372", target, msg)

    @classmethod
    def reply_luser_client(cls, prefix, num_users, num_servers):
        return cls(prefix, "251", "*", "There are {} user(s) on {} server(s)".format(num_users, num_servers))

    @classmethod
    def reply_luser_op(cls, prefix, num_ops):
        return cls(prefix, "252", str(num_ops), "There are {} operator(s) online".format(num_ops))

    @classmethod
    def reply_luser_chan(cls, prefix, num_chans):
        return cls(prefix, "254", str(num_chans), "There are {} channels(s) formed".format(num_chans))

    @classmethod
    def reply_luser_me(cls, prefix, num_clients, num_servers):
        return cls(prefix, "255", "*", "I have {} client(s) and {} server(s)".format(num_clients, num_servers))

    @classmethod
    def reply_isupport(cls, prefix, target, tokens):
        parts = []
        for param, value in tokens:
            part = "{}={}".format(param, value)
            parts.append(part)

        return cls(prefix, "005", target, " ".join(parts))
