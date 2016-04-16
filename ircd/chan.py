import logging

from ircd.mode import Mode

log = logging.getLogger(__name__)


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
        self.bans = []
        self.exceptions = []

    def __eq__(self, other):
        return other and self.name == other.name

    def __repr__(self):
        return "Channel({})".format(self.name)

    @property
    def is_topic_open(self):
        return not self.mode.has_flag(Mode.CHANNEL_TOPIC_CLOSED)

    def is_operator(self, nickname):
        return nickname in self.operators

    def is_member(self, nickname):
        return nickname in self.members

    def is_invited(self, nickname):
        return nickname in self.invited

    @property
    def is_invite_only(self):
        return self.mode.has_flag(Mode.CHANNEL_IS_INVITE_ONLY)

    @property
    def is_private(self):
        return self.mode.has_flag(Mode.CHANNEL_IS_PRIVATE)

    @property
    def is_secret(self):
        return self.mode.has_flag(Mode.CHANNEL_IS_SECRET)

    def can_join_channel(self, nickname):
        return self.is_invited(nickname) if self.is_invite_only else True

    def set_topic(self, topic):
        self.topic = topic

    def get_member(self, nickname):
        for member in self.members:
            if member.nickname == nickname:
                return member
        return None

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

    def clear_mode(self, flags, param=None):
        return self.mode.clear_flags(flags, param=param)

    def invite(self, nickname):
        if nickname not in self.invited:
            self.invited.append(nickname)

    def kick(self, nickname):
        if nickname in self.invited:
            self.invited.remove(nickname)
        if nickname in self.members:
            self.members.remove(nickname)

    def _add_mask(self, mask, collection):
        if mask not in collection:
            collection.append(mask)

    def _remove_mask(self, mask, collection):
        if mask in collection:
            collection.remove(mask)

    def add_ban(self, mask):
        self._add_mask(mask, self.bans)

    def remove_ban(self, mask):
        self._remove_mask(mask, self.bans)

    def add_exception(self, mask):
        self._add_mask(mask, self.exceptions)

    def remove_exception(self, mask):
        self._remove_mask(mask, self.exceptions)

    def is_banned(self, identity):
        has_match = lambda collection: any(mask.match(str(identity)) for mask in collection)
        return has_match(self.bans) and not has_match(self.exceptions)
