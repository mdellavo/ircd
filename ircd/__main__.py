import sys
import time
import asyncio
import logging
import argparse
import socket

from .irc import IRC
from .net import Client
from .message import parsemsg, TERMINATOR

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(name)s - %(levelname)s - %(message)s',
)

log = logging.getLogger("ircd.main")

CLIENT_PORT = "9999"
CLIENT_LISTEN_ADDRESS = "0.0.0.0:" + CLIENT_PORT

LINK_PORT = "6666"
LINK_LISTEN_ADDRESS = "0.0.0.0:" + LINK_PORT

PING_INTERVAL = 60
PING_GRACE = 5
IDENT_TIMEOUT = 10

QUIT_MESSAGE = "goodbye"


def parse_address(s):
    parts = s.split(":")
    host, port = parts
    return host, int(port)


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

    def __init__(self, irc):
        self.irc = irc
        self.servers = []
        self.links = []
        self.clients = []

    async def run(self, client_listen_addr=None, client_listen_port=None, link_listen_addr=None, link_listen_port=None):
        log.info("Server %s start", self.irc.host)
        incoming = asyncio.Queue()
        irc_processor = asyncio.create_task(self._irc_processor(incoming))
        client_listener = asyncio.create_task(self._listener(client_listen_addr, client_listen_port, False, incoming))
        link_listener = asyncio.create_task(self._listener(link_listen_addr, link_listen_port, True, incoming))

        coros = [irc_processor, client_listener, link_listener]
        if False:
            peer_conn = asyncio.create_task(self.connect())
            coros.append(peer_conn)

        await asyncio.gather(*coros)
        await self.shutdown

    async def shutdown(self):
        for client, stream in self.clients:
            await self._drop_client(client, stream)

        for link in self.links:
            link.close()
            await link.wait_closed()

        for server in self.servers:
            server.close()
            await server.wait_closed()
        self.servers = []

    async def _client_writer(self, client, stream):
        last_ping = time.time()
        while client.connected:
            try:
                message = await asyncio.wait_for(client.outgoing.get(), PING_INTERVAL)
            except asyncio.TimeoutError:
                message = None

            if message:
                await write_message(client, stream, message)

            diff = time.time() - last_ping
            if diff > PING_INTERVAL:
                self.irc.ping(client)
                last_ping = time.time()
                client.ping_count += 1
                if client.ping_count > PING_GRACE:
                    break

        await self._drop_client(client, stream)
        log.debug("client writer for %s (%s) shutdown", client.address, client.host)

    async def _on_connect(self, stream, link, incoming):
        client_address, client_port, client_host = await resolve_peerinfo(stream)
        log.info("connection from %s (%s)", client_address, client_host)

        client = Client(client_address, client_host, link=link)
        self.clients.append((client, stream))

        start_writer = False
        writer_task = None
        while client.connected and not stream.at_eof():
            try:
                line = await readline(stream)
            except asyncio.streams.IncompleteReadError:
                break

            message = parsemsg(line)
            log.debug("read from %s: %s", client_address, message)
            await incoming.put((client, message))
            if not start_writer:
                writer_task = asyncio.create_task(self._client_writer(client, stream))
                start_writer = True
        await self._drop_client(client, stream)
        await writer_task
        log.debug("client reader for %s (%s) shutdown", client.address, client.host)

    async def _drop_client(self, client, writer):
        self.irc.drop_client(client, QUIT_MESSAGE)
        # FIXME make sure we drain outgoing
        if writer.is_closing():
            return
        await writer.drain()
        writer.write_eof()
        writer.close()
        await writer.wait_closed()

    async def _listener(self, addr, port, link, incoming):
        log.info("serving %s on %s:%s", "links" if link else "clients", addr, port)

        def _start(stream):
            return asyncio.create_task(self._on_connect(stream, link, incoming))

        server = asyncio.StreamServer(_start, addr, port)
        self.servers.append(server)
        async with server:
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


async def main(args):
    addr, port = args.listen
    irc = IRC(args.host)
    server = Server(irc)
    await server.run(
        client_listen_addr=args.listen[0],
        client_listen_port=args.listen[1],
        link_listen_addr=args.link[0],
        link_listen_port=args.link[1],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="irc server")
    parser.add_argument("--host", help="host name", default=socket.gethostname())
    parser.add_argument("--listen", help="listen address", type=parse_address, default=CLIENT_LISTEN_ADDRESS)
    parser.add_argument("--link", help="link address", type=parse_address, default=LINK_LISTEN_ADDRESS)
    parser.add_argument("--peer", help="peer address", type=parse_address)
    parser.add_argument("--verbose", help="verbose mode", action="store_true")
    args = parser.parse_args(sys.argv[1:])

    try:
        asyncio.run(main(args), debug=args.verbose)
    except KeyboardInterrupt:
        log.info("shutting down")
