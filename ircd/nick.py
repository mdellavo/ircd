from datetime import datetime

from ircd.mode import Mode


class Nickname:
    def __init__(self, nickname):
        self.nickname = nickname
        self.mode = Mode.for_nickname(self)
        self.last_seen = datetime.utcnow()
        self.channels = []
        self.away_message = None

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

    def set_away(self, message):
        self.set_mode(Mode.AWAY)
        self.away_message = message

    def clear_away(self):
        self.clear_mode(Mode.AWAY)
        self.away_message = None

    is_away = property(lambda self: self.mode.has_flag(Mode.AWAY))
    is_invisible = property(lambda self: self.mode.has_flag(Mode.INVISIBLE))
    has_wallops = property(lambda self: self.mode.has_flag(Mode.WALLOPS))
    is_restricted = property(lambda self: self.mode.has_flag(Mode.RESTRICTED))
    is_operator = property(lambda self: self.mode.has_flag(Mode.OPERATOR))
    is_local_operator = property(lambda self: self.mode.has_flag(Mode.OPERATOR))
    has_server_notices = property(lambda self: self.mode.has_flag(Mode.SERVER_NOTICES))
