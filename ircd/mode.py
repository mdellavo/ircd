from ircd.mask import Mask


class ModeParamMissing(ValueError):
    pass


class ModeFlag(object):
    KEY = None

    def __init__(self):
        self.value = False

    def set(self, param=None):
        self.value = True

    def clear(self, param=None):
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


class UserAwayFlag(UserModeFlag):
    KEY = "a"


class UserInvisibleFlag(UserModeFlag):
    KEY = "i"


class UserWallopsFlag(UserModeFlag):
    KEY = "w"


class UserRestrictedFlag(UserModeFlag):
    KEY = "r"


class UserLocalOperatorFlag(UserModeFlag):
    KEY = "O"


class UserOperatorFlag(UserModeFlag):
    KEY = "o"


class UserServerNoticesFlag(UserModeFlag):
    KEY = "s"


class ChannelPrivateFlag(ChannelModeFlag):
    KEY = "p"


class ChannelInviteOnlyFlag(ChannelModeFlag):
    KEY = "i"


class ChannelTopicClosedFlag(ChannelModeFlag):
    KEY = "t"


class ChannelNoMessagesFlag(ChannelModeFlag):
    KEY = "n"


class ChannelModeratedFlag(ChannelModeFlag):
    KEY = "m"


class ChannelUserLimitFlag(ChannelModeFlag):
    KEY = "l"


class MaskFlag(ChannelModeFlag):

    def add_mask(self, mask):
        pass

    def clear_mask(self, mask):
        pass

    def parse(self, param):
        return Mask.parse(param) if param else None

    def set(self, param=None):
        super(MaskFlag, self).set(param=param)
        mask = self.parse(param)
        if mask:
            self.add_mask(mask)

    def clear(self, param=None):
        super(MaskFlag, self).clear(param=param)
        mask = self.parse(param)
        if mask:
            self.clear_mask(mask)


class ChannelBanMaskFlag(MaskFlag):
    KEY = "b"

    def add_mask(self, mask):
        self.channel.add_ban(mask)

    def clear_mask(self, mask):
        self.channel.remove_ban(mask)


class ChannelExceptionMaskFlag(MaskFlag):
    KEY = "e"

    def add_mask(self, mask):
        self.channel.add_exception(mask)

    def clear_mask(self, mask):
        self.channel.remove_exception(mask)


class ChannelVoiceFlag(ChannelModeFlag):
    KEY = "v"


class ChannelKeyFlag(ChannelModeFlag):
    KEY = "k"

    def set(self, param=None):
        if not param:
            raise ModeParamMissing()

        super(ChannelKeyFlag, self).set(param=param)
        self.channel.key = param

    def clear(self, param=None):
        super(ChannelKeyFlag, self).clear(param=param)
        self.channel.key = None


class ChannelSecretFlag(ChannelModeFlag):
    KEY = "s"


class ChannelOperatorFlag(ChannelModeFlag):
    KEY = "o"

    def set(self, param=None):
        if not param:
            raise ModeParamMissing()

        super(ChannelOperatorFlag, self).set(param=param)
        nickname = self.channel.get_member(param)
        if nickname not in self.channel.operators:
            self.channel.operators.append(nickname)

    def clear(self, param=None):
        if not param:
            raise ModeParamMissing()

        nickname = self.channel.get_member(param)
        if nickname and nickname in self.channel.operators:
            self.channel.operators.remove(nickname)


class Mode(object):

    AWAY = "a"
    INVISIBLE = "i"
    WALLOPS = "w"
    RESTRICTED = "r"
    OPERATOR = "o"
    LOCAL_OPERATOR = "O"
    SERVER_NOTICES = "s"

    CHANNEL_TOPIC_CLOSED = "t"
    CHANNEL_IS_PRIVATE = "p"
    CHANNEL_IS_SECRET = "s"
    CHANNEL_KEY = "k"
    CHANNEL_IS_INVITE_ONLY = "i"

    ALL_USER_MODES = (UserAwayFlag, UserInvisibleFlag, UserWallopsFlag, UserRestrictedFlag,
                      UserLocalOperatorFlag, UserServerNoticesFlag, UserOperatorFlag)
    ALL_CHANNEL_MODES = (ChannelPrivateFlag, ChannelSecretFlag, ChannelInviteOnlyFlag,
                         ChannelTopicClosedFlag, ChannelNoMessagesFlag, ChannelModeratedFlag,
                         ChannelUserLimitFlag, ChannelBanMaskFlag, ChannelExceptionMaskFlag,
                         ChannelVoiceFlag, ChannelKeyFlag, ChannelOperatorFlag)

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
        return self.mode

    @property
    def mode(self):
        return "".join(key for key, flag in self.flags.items() if flag.is_set())

    def has_flag(self, flag):
        if flag not in self.flags:
            return False
        return self.flags[flag].is_set()

    def clear_flag(self, flag, param=None):
        is_set = self.has_flag(flag)
        if is_set:
            self.flags[flag].clear(param=param)
        return is_set

    def clear_flags(self, flags, param=None):
        cleared_flags = []
        for flag in flags:
            if self.clear_flag(flag, param=param):
                cleared_flags.append(flag)
        return "".join(cleared_flags)

    def set_flag(self, flag, param=None):
        flag_set = False
        if flag in self.flags:
            self.flags[flag].set(param=param)
            flag_set = True
        return flag_set

    def set_flags(self, flags, param=None):
        set_flags = []
        for flag in flags:
            if self.set_flag(flag, param=param):
                set_flags.append(flag)
        return "".join(set_flags)
