import time
import asyncio
import logging

from ircd.message import Prefix

log = logging.getLogger(__name__)


class Client:
    def __init__(self, address, host, link=False):
        self.address = address
        self.host = host or address
        self.link = link

        self.name = None
        self.connected_at = time.time()
        self.connected = True
        self.disconnected_at = None

        # fields if server
        self.server = False
        self.hop_count = None
        self.token = None
        self.info = None

        # fields if user
        self.user = None
        self.realname = None

        self.outgoing = asyncio.Queue()
        self.ping_count = 0

    def __str__(self):
        return "<Client({})>".format(self.identity)

    @property
    def identity(self):
        prefix = Prefix(self.host) if self.server else Prefix.from_parts(self.name, self.user, self.host)
        return str(prefix)

    def set_nickname(self, nickname):
        self.name = nickname

    def set_identity(self, user, realname):
        self.user, self.realname = user, realname

    def set_server(self, name, hop_count, token, info):
        self.server = True
        self.name = name
        self.hop_count = hop_count
        self.token = token
        self.info = info

    def send(self, msg):
        self.outgoing.put_nowait(msg)

    def disconnect(self):
        self.connected = False
        self.disconnected_at = time.time()
        self.send(None)

    def clear_ping_count(self):
        self.ping_count = 0

    @property
    def has_nickname(self):
        return bool(self.name)

    @property
    def has_identity(self):
        return self.has_nickname and all([self.user, self.realname])
