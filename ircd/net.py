import time
import logging
from queue import Queue, Empty

from ircd.message import Prefix

log = logging.getLogger(__name__)

BACKLOG = 10


class Client(object):
    def __init__(self, address, host):
        self.address = address
        self.host = host

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

        self.outgoing = Queue()
        self.ping_count = 0

    @property
    def identity(self):
        prefix = Prefix(self.host) if self.server else Prefix.from_parts(self.name, self.user, self.host)
        return str(prefix)

    def writer(self):
        last_ping = time.time()

        while self.is_connected:
            try:
                msg = self.outgoing.get(timeout=PING_INTERVAL)
            except Empty:
                msg = None

            if msg and self.transport:
                try:
                    log.debug("wrie: %s", msg)
                    self.transport.write(msg)
                except TransportError as e:
                    log.error("error writing from client: %s", e)
                    self.irc.drop_client(self, message=str(e))

            diff = time.time() - last_ping
            if diff > PING_INTERVAL:
                self.irc.ping(self)
                last_ping = time.time()
                self.ping_count += 1
                if self.ping_count > PING_GRACE:
                    self.irc.drop_client(self, message="ping timeout")
                    break

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
        self.outgoing.put(msg)

    def disconnect(self):
        self.connected = False
        self.disconnected_at = time.time()

    def clear_ping_count(self):
        self.ping_count = 0

    @property
    def has_nickname(self):
        return bool(self.name)

    @property
    def has_identity(self):
        return self.has_nickname and all([self.user, self.realname])
