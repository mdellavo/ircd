import re


class Mask(object):
    def __init__(self, nickname=None, user=None, host=None):
        self.nickname = nickname or "*"
        self.user = user or "*"
        self.host = host or "*"
        self.pattern = re.compile(self.build_pattern(), re.IGNORECASE)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and all([
            self.nickname == other.nickname,
            self.user == other.user,
            self.host == other.host
        ])

    def __str__(self):
        return "{nickname}!{user}@{host}".format(nickname=self.nickname, user=self.user, host=self.host)

    def __repr__(self):
        return "<{}({})>".format(self.__class__.__name__, str(self))

    def build_pattern(self):
        glob = lambda s: "(" + s.replace(".", "\.").replace("*", ".+?") + ")"
        return "{nickname}!{user}@{host}$".format(nickname=glob(self.nickname), user=glob(self.user), host=glob(self.host))

    def match(self, identity):
        return self.pattern.match(identity) is not None

    @classmethod
    def parse(cls, s):
        pattern = re.compile("([\w\*]+?)!([\w\*]+?)@([\w\*\.\-]+?)$", re.IGNORECASE)
        match = pattern.match(s)
        return cls(*match.groups()) if match else None


