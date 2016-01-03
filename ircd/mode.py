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

    ALL_USER_MODES = (UserAwayFlagFlag, UserInvisibleFlagFlag, UserWallopsFlagFlag, UserRestrictedFlagFlag,
                      UserLocalOperatorFlagFlag, UserServerNoticesFlagFlag, UserOperatorFlagFlag)
    ALL_CHANNEL_MODES = (ChannelPrivateFlagFlag, ChannelSecretFlagFlag, ChannelInviteOnlyFlagFlag,
                         ChannelTopicClosedFlagFlag, ChannelNoMessagesFlagFlag, ChannelModeratedFlagFlag,
                         ChannelUserLimitFlagFlag, ChannelBanMaskFlagFlag, ChannelVoiceFlagFlag, ChannelKeyFlagFlag,
                         ChannelOperatorFlagFlag)

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

    def clear_flags(self, flags):
        cleared_flags = []
        for flag in flags:
            if self.clear_flag(flag):
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
