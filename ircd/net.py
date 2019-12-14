import time
import asyncio
import logging

from .message import Prefix
from .message import parsemsg, TERMINATOR

PING_INTERVAL = 60
PING_GRACE = 5
IDENT_TIMEOUT = 10


QUIT_MESSAGE = "goodbye"


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


async def readline(stream):
    return (await stream.readuntil(TERMINATOR.encode())).decode().strip()


async def write_message(client, stream, message):
    line = message.format() + TERMINATOR
    bytes = line.encode()
    stream.write(bytes)
    await stream.drain()
    log.debug("wrote to %s: %s", client, bytes)


async def resolve_peerinfo(writer):
    client_address, client_port = writer.get_extra_info('peername')
    client_host, _ = await asyncio.get_event_loop().getnameinfo((client_address, client_port))
    return client_address, client_port, client_host


class Server:
    def __init__(self, irc, ping_interval=PING_INTERVAL):
        self.irc = irc
        self.servers = []
        self.clients = []
        self.tasks = []
        self.running = asyncio.Event()
        self.ping_interval = ping_interval

    async def run(self, client_listen_addr, client_listen_port, link_listen_addr=None, link_listen_port=None):
        log.info("Server %s start", self.irc.host)
        incoming = asyncio.Queue()
        irc_processor = asyncio.create_task(self._irc_processor(incoming))
        self.tasks.append(irc_processor)
        client_listener = asyncio.create_task(self._listener(client_listen_addr, client_listen_port, False, incoming))
        coros = [irc_processor, client_listener]

        if link_listen_addr and link_listen_port:
            link_listener = asyncio.create_task(self._listener(link_listen_addr, link_listen_port, True, incoming))
            coros.append(link_listener)

        if False:
            peer_conn = asyncio.create_task(self.connect())
            coros.append(peer_conn)

        await asyncio.gather(*coros)

    async def shutdown(self):
        for client, stream in self.clients:
            await self._drop_client(client, stream)

        for server in self.servers:
            server.close()
        self.servers = []

        for task in self.tasks:
            try:
                task.cancel()
                await task
            except asyncio.CancelledError:
                pass

        self.running.clear()

    async def _client_writer(self, client, stream):
        last_ping = time.time()
        while client.connected:
            try:
                message = await asyncio.wait_for(client.outgoing.get(), self.ping_interval)
            except asyncio.TimeoutError:
                message = None

            if message:
                await write_message(client, stream, message)

            diff = time.time() - last_ping

            if diff > self.ping_interval:
                self.irc.ping(client)
                last_ping = time.time()
                client.ping_count += 1
                if client.ping_count > PING_GRACE:
                    break

        await self._drop_client(client, stream)
        log.debug("client writer for %s (%s) shutdown", client.address, client.host)

    async def _on_connect(self, reader, writer, link, incoming):
        client_address, client_port, client_host = await resolve_peerinfo(writer)
        log.info("connection from %s (%s)", client_address, client_host)

        client = Client(client_address, client_host, link=link)
        self.clients.append((client, writer))

        start_writer = False
        writer_task = None
        while client.connected:
            try:
                line = await readline(reader)
            except asyncio.IncompleteReadError:
                log.info("error reading from: %s", client_address)
                break

            message = parsemsg(line)
            log.debug("read from %s: %s", client_address, message)
            await incoming.put((client, message))
            if not start_writer:
                writer_task = asyncio.create_task(self._client_writer(client, writer))
                start_writer = True
        await self._drop_client(client, writer)
        await writer_task
        log.debug("client reader for %s (%s) shutdown", client.address, client.host)

    async def _drop_client(self, client, writer):
        self.irc.drop_client(client, QUIT_MESSAGE)
        if writer.is_closing():
            return
        await writer.drain()
        writer.write_eof()
        writer.close()
        await writer.wait_closed()

    async def _listener(self, addr, port, link, incoming):
        log.info("serving %s on %s:%s", "links" if link else "clients", addr, port)

        def _start(reader, writer):
            return asyncio.create_task(self._on_connect(reader, writer, link, incoming))

        server = await asyncio.start_server(_start, addr, port)
        self.servers.append(server)
        async with server:
            if not link:
                self.running.set()
            await server.serve_forever()

    async def _irc_processor(self, incoming):
        while self.irc.running:
            client, message = await incoming.get()
            log.info("processing message from %s: %s", client, message)
            try:
                self.irc.process(client, message)
            except Exception as e:
                log.exception("error processing message from %s - %s - %s", client, message, str(e))
        log.debug("irc processor shutdown")

    async def connect(self, addr, port, incoming):
        log.info("linking to peer %s:%s", addr, port)
        async with asyncio.connect() as stream:
            await self._on_connect(stream, True, incoming)
