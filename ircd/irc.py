import time
import logging
from queue import Queue
from datetime import datetime

from ircd.chan import Channel
from ircd.nick import Nickname
from ircd.message import IRCMessage
from ircd.commands import Handler
from ircd.mode import Mode, ModeParamMissing
from ircd.common import IRCError

SERVER_NAME = "ircd"
SERVER_VERSION = "0.1"
CHAN_START_CHARS = "&#!+"

log = logging.getLogger(__name__)

CAPABILITIES = [
    "message-tags",
    "server-time",
    "message-ids",
    "sasl",
]

ISUPPORT = {
    "AWAYLEN": "",
    "CASEMAPPING": "ascii",
    "CHANLIMIT": "",
    "CHANTYPES": "#",
}


class IRC:
    def __init__(self, host):
        self.host = host
        self.running = True
        self.incoming = Queue()
        self.created = datetime.utcnow()
        self.clients = {}
        self.links = []
        self.channels = {}
        self.nicknames = {}
        self.nick_client = {}
        self.known_identities = {}
        self.motd = "hello world"
        self.operators = []

    def add_link(self, client, name, hop_count, token, info):
        client.set_server(name, hop_count, token, info)
        if client not in self.links:
            self.links.append(client)

    def get_capabilities(self):
        return CAPABILITIES

    def authenticate(self, nickname, identity, password):
        owner = self.known_identities.get(nickname)
        if not owner:
            self.known_identities[nickname] = {"identity": identity, "password": password}
            return True
        valid = owner["identity"] == identity and owner["password"] == password
        return valid

    def get_channels(self):
        return self.channels.values()

    def get_channel(self, name):
        return self.channels.get(name)

    def set_channel(self, channel):
        self.channels[channel.name] = channel

    def has_channel(self, name):
        return name in self.channels

    def list_channels(self, client, names=None):
        nickname = self.get_nickname(client.name)

        def include_channel(channel):
            return (not channel.is_secret or channel.is_member(nickname)) and (not names or channel.name in names)

        return [channel for channel in self.channels.values() if include_channel(channel)]

    def get_client(self, identity):
        return self.clients.get(identity)

    def set_client(self, client):
        self.clients[client.identity] = client

    def remove_client(self, identity):
        if identity in self.clients:
            del self.clients[identity]

    def get_nicknames(self):
        return self.nicknames.values()

    def has_nickname(self, nickname):
        return nickname in self.nicknames

    def get_nickname(self, nickname):
        return self.nicknames.get(nickname)

    def lookup_client(self, nickname):
        return self.nick_client.get(nickname)

    def process(self, client, msg):
        handler = Handler(self, client)
        handler(msg)

        for link in self.links:
            if link == client:
                continue
            link.send(msg)

    def set_nick(self, client, new_nickname):
        if self.has_nickname(new_nickname):
            raise IRCError(IRCMessage.error_nick_in_use(self.host, client.name, new_nickname))

        old = client.name
        # assemble our message before changing nick
        msg = IRCMessage.nick(client.identity, new_nickname)

        client.set_nickname(new_nickname)

        # FIXME add helper
        nickname = self.get_nickname(old) if old else None
        if nickname:
            del self.nicknames[old]
            nickname.set_nick(new_nickname)
        else:
            nickname = Nickname(new_nickname)

        self.nicknames[nickname.nickname] = nickname
        self.nick_client[nickname.nickname] = client

        if client.has_identity:
            client.send(msg)

            if old:
                self.remove_client(old)

            for channel in nickname.channels:
                self.send_to_channel(client, channel, msg, skip_self=True)

    def set_ident(self, client, user, realname):
        client.set_identity(user, realname)
        self.set_client(client)
        log.info("%s connected", client.identity)

        client.send(IRCMessage.nick(client.identity, client.name))
        client.send(IRCMessage.reply_welcome(self.host, client.name, client.name, client.user, client.host))
        client.send(IRCMessage.reply_yourhost(self.host, client.name, SERVER_NAME, SERVER_VERSION))
        client.send(IRCMessage.reply_created(self.host, client.name, self.created))
        client.send(IRCMessage.reply_myinfo(self.host, client.name, SERVER_NAME, SERVER_VERSION))

        client.send(IRCMessage.reply_isupport(self.host, client.name, ISUPPORT.items()))

        client.send(IRCMessage.reply_luser_client(self.host, len(self.nicknames), len(self.links) + 1))
        client.send(IRCMessage.reply_luser_op(self.host, len(self.operators)))
        client.send(IRCMessage.reply_luser_chan(self.host, len(self.channels)))
        client.send(IRCMessage.reply_luser_me(self.host, len(self.clients), len(self.links) + 1))

        self.send_user_mode(client, client.name)

        self.send_motd(client)

    def send_motd(self, client):
        if self.motd:
            client.send(IRCMessage.reply_start_motd(self.host, client.name))
            client.send(IRCMessage.reply_motd(self.host, client.name, self.motd))
            client.send(IRCMessage.reply_end_motd(self.host, client.name))
        else:
            client.send(IRCMessage.reply_no_motd(self.host, client.name))

    def drop_client(self, client, message=None):
        if not client.connected:
            return

        log.info("%s disconnected (%s)", client.identity, message or "none")
        client.disconnect()

        nickname = self.get_nickname(client.name)
        if nickname:
            for channel in nickname.channels:
                self.part_channel(channel.name, client)
                try:
                    self.send_to_channel(client, channel, IRCMessage.quit(client.identity, message), skip_self=True)
                except IRCError:
                    pass

            if nickname.nickname in self.nick_client:
                del self.nick_client[nickname.nickname]
            if nickname.nickname in self.nicknames:
                del self.nicknames[nickname.nickname]

        self.remove_client(client.identity)

    def join_channel(self, name, client, key=None):
        nickname = self.get_nickname(client.name)
        channel = self.get_channel(name)
        if not channel:
            if name[0] not in CHAN_START_CHARS:
                raise IRCError(IRCMessage.error_no_such_channel(self.host, client.name, name))

            channel = Channel(name, nickname)
            self.set_channel(channel)

        if not channel.can_join_channel(nickname):
            raise IRCError(IRCMessage.error_invite_only_channel(self.host, client.name, name))

        if channel.is_banned(client.identity):
            raise IRCError(IRCMessage.error_banned_from_channel(self.host, client.name, name))

        joined = channel.join(nickname, key=key)
        if not joined:
            client.send(IRCMessage.error_bad_channel_key(self.host, client.name, channel.name))
            return

        self.send_to_channel(client, channel, IRCMessage.join(client.identity, name))
        self.send_topic(client, channel)
        self.send_names(client, channel)

    def send_capabilities(self, client):
        nickname = self.get_nickname(client.name)
        client.send(IRCMessage.reply_list_capabilities(self.host, nickname, self.get_capabilities()))

    def request_capabilities(self, client, caps):
        available_caps = self.get_capabilities()
        accepted = [cap for cap in caps if cap in available_caps]
        if accepted:
            client.send(IRCMessage.reply_ack_capabilities(self.host, client.name, accepted))
            client.add_capabilities(accepted)

        rejected = [cap for cap in caps if cap not in available_caps]
        if rejected:
            client.send(IRCMessage.reply_nak_capabilities(self.host, client.name, rejected))

    def send_names(self, client, channel):
        nickname = self.get_nickname(client.name)
        if not (channel.is_private or channel.is_secret) or channel.is_member(nickname):
            client.send(IRCMessage.reply_names(self.host, client.name, channel))
            client.send(IRCMessage.reply_endnames(self.host, client.name, channel))

    def send_list(self, client, channels):
        client.send(IRCMessage.reply_list_start(self.host, client.name))
        for channel in channels:
            client.send(IRCMessage.reply_list(self.host, client.name, channel))
        client.send(IRCMessage.reply_list_end(self.host, client.name))

    def send_topic(self, client, channel):
        if channel.topic:
            client.send(IRCMessage.reply_topic(self.host, client.name, channel))
        else:
            client.send(IRCMessage.reply_notopic(self.host, client.name, channel))

    def set_topic(self, client, channel, topic):
        nickname = self.get_nickname(client.name)
        if channel.is_operator(nickname) or channel.is_topic_open:
            channel.set_topic(topic)

        for member in channel.members:
            member_client = self.lookup_client(member.nickname)
            if member_client:
                member_client.send(IRCMessage.reply_topic(self.host, member_client.name, channel))
                member_client.send(IRCMessage.reply_topic_who_time(self.host, member_client.name, channel, nickname, time.time()))

    def part_channel(self, name, client, message=None):
        channel = self.get_channel(name)
        if not channel:
            return
        nickname = self.get_nickname(client.name)
        self.send_to_channel(client, channel, IRCMessage.part(client.identity, name, message=message))
        channel.part(nickname)
        if not channel.members:
            del self.channels[name]

    def send_to_channel(self, client, channel, msg, skip_self=False, caps=None):
        nickname = self.get_nickname(client.name)
        if nickname not in channel.members:
            raise IRCError(IRCMessage.error_not_in_channel(self.host, client.name))

        for member in channel.members:
            if skip_self and member.nickname == client.name:
                continue
            member_client = self.lookup_client(member.nickname)

            if caps:
                missing = [cap for cap in caps if cap not in client.capabilities]
                if missing:
                    continue

            if member_client:
                member_client.send(msg)

    def send_private_message_to_channel(self, client, channel_name, msg):
        channel = self.get_channel(channel_name)
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.host, client.name, channel_name))

        self.send_to_channel(client, channel, IRCMessage.private_message(client.identity, channel_name, msg.args[1], tags=msg.client_tags), skip_self=True)

    def send_private_message_to_client(self, client, nickname, msg):
        other = self.lookup_client(nickname)
        if not other:
            raise IRCError(IRCMessage.error_no_such_nickname(self.host, client.name, nickname))

        other_nick = self.get_nickname(nickname)
        if other_nick.is_away:
            client.send(IRCMessage.reply_away(other.identity, client.name, nickname, other_nick.away_message))
        else:
            other.send(IRCMessage.private_message(client.identity, nickname, msg.args[1], tags=msg.client_tags))

    def send_notice_to_channel(self, client, channel_name, msg):
        channel = self.get_channel(channel_name)
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.host, client.name, channel_name))

        self.send_to_channel(client, channel, IRCMessage.notice(client.identity, channel_name, msg.args[1], tags=msg.client_tags), skip_self=True)

    def send_notice_to_client(self, client, nickname, msg):
        other = self.lookup_client(nickname)
        if not other:
            raise IRCError(IRCMessage.error_no_such_nickname(self.host, client.name, nickname))

        other.send(IRCMessage.notice(client.identity, nickname, msg.args[1], tags=msg.client_tags))

    def send_tag_message_to_channel(self, client, channel_name, msg):
        channel = self.get_channel(channel_name)
        if not channel:
            raise IRCError(IRCMessage.error_no_such_channel(self.host, client.name, channel_name))

        self.send_to_channel(client, channel, IRCMessage.tag_message(client.identity, channel_name, tags=msg.client_tags), skip_self=True, caps=["message-tags"])

    def send_tag_message_to_client(self, client, nickname, msg):
        other = self.lookup_client(nickname)
        if not other:
            raise IRCError(IRCMessage.error_no_such_nickname(self.host, client.name, nickname))
        if "message-tags" in other.capabilities:
            other.send(IRCMessage.tag_message(client.identity, nickname, tags=msg.client_tags))

    def ping(self, client):
        client.send(IRCMessage.ping(self.host))

    def send_channel_mode(self, client, chan_name):
        channel = self.get_channel(chan_name)
        if not channel:
            raise IRCError(IRCMessage.error_no_such_nickname(self.host, client.name, chan_name))
        client.send(IRCMessage.reply_channel_mode_is(self.host, client.name, channel.name, str(channel.mode.mode)))

    def set_channel_mode(self, client, target, flags, param=None):
        channel = self.get_channel(target)
        nickname = self.get_nickname(client.name)
        if not channel.is_operator(nickname):
            raise IRCError(IRCMessage.error_channel_operator_needed(self.host, client.name, channel.name))

        op, flags = flags[0], flags[1:]

        modified = None
        try:
            if op == "+":
                modified = channel.set_mode(flags, param=param)
            elif op == "-":
                modified = channel.clear_mode(flags, param=param)
        except ModeParamMissing:
            raise IRCError(IRCMessage.error_needs_more_params(self.host, client.name, "MODE"))

        if modified:
            self.send_to_channel(client, channel, IRCMessage.mode(client.identity, target, op + flags, param))

    def send_user_mode(self, client, nick):
        nickname = self.get_nickname(nick)
        if not nickname:
            raise IRCError(IRCMessage.error_no_such_nickname(self.host, client.name, nickname))
        client.send(IRCMessage.reply_user_mode_is(self.host, client.name, nickname.mode))

    def set_user_mode(self, client, target, flags):
        op, flags = flags[0], flags[1:]

        to_self = client.name == target

        if not to_self:
            raise IRCError(IRCMessage.error_users_dont_match(self.host, client.name))

        nickname = self.get_nickname(client.name)
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
        client.send(IRCMessage.reply_inviting(self.host, client.name, channel, nickname))

        other_client = self.lookup_client(nickname.nickname)
        other_client.send(IRCMessage.invite(client.identity, nickname, channel))

    def kick(self, client, channel, nickname, comment=None):
        channel.kick(nickname)

        other_client = self.lookup_client(nickname.nickname)
        other_client.send(IRCMessage.kick(client.identity, channel, nickname, comment=comment))
