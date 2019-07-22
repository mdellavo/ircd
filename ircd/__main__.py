import sys
import time
import asyncio
import logging
import argparse

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


async def main(args):
    host = "localhost"

    irc = IRC(host)
    incoming = asyncio.Queue()

    async def _drop_client(client, writer):
        irc.drop_client(client, QUIT_MESSAGE)
        # FIXME make sure we drain outgoing
        if writer.is_closing():
            return
        await writer.drain()
        writer.write_eof()
        writer.close()
        await writer.wait_closed()

    async def _on_client_connected(stream, link=False):
        client_address, client_port, client_host = await resolve_peerinfo(stream)
        log.info("connection from %s (%s)", client_address, client_host)

        client = Client(client_address, client_host, link=link)

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
                writer_task = asyncio.create_task(_client_writer(client, stream))
                start_writer = True
        await _drop_client(client, stream)
        await writer_task
        log.debug("client reader for %s (%s) shutdown", client.address, client.host)

    async def _client_writer(client, stream):
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
                irc.ping(client)
                last_ping = time.time()
                client.ping_count += 1
                if client.ping_count > PING_GRACE:
                    break

        await _drop_client(client, stream)
        log.debug("client writer for %s (%s) shutdown", client.address, client.host)

    async def _irc_processor():
        while irc.running:
            client, message = await incoming.get()
            log.info("processing message from %s: %s", client, message)
            try:
                irc.process(client, message)
            except Exception as e:
                log.exception("error processing message from %s - %s - %s", client, message, str(e))
        log.debug("irc processor shutdown")
    irc_processor = asyncio.create_task(_irc_processor())

    def _start_client(stream):
        asyncio.create_task(_on_client_connected(stream))

    client_server = asyncio.StreamServer(_start_client, args.listen[0], args.listen[1])
    async def _client_listener():
        log.info("serving clients on %s:%s", args.listen[0], args.listen[1])
        async with client_server:
            await client_server.serve_forever()
    client_listener = asyncio.create_task(_client_listener())

    def _start_link(stream):
        asyncio.create_task(_on_client_connected(stream, link=True))

    link_server = asyncio.StreamServer(_start_link, args.link[0], args.link[1])
    async def _link_listener():
        log.info("serving links on %s:%s", args.link[0], args.link[1])
        async with link_server:
            await link_server.serve_forever()
    link_listener = asyncio.create_task(_link_listener())

    async def _start_peer():
        log.info("STARTING PEER: %s", args.peer)

    coros = [irc_processor, client_listener, link_listener]
    if args.peer:
        peer_conn = asyncio.create_task(_start_peer())
        coros.append(peer_conn)

    await asyncio.gather(*coros)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="irc server")
    parser.add_argument("--listen", help="listen address", type=parse_address, default=CLIENT_LISTEN_ADDRESS)
    parser.add_argument("--link", help="link address", type=parse_address, default=LINK_LISTEN_ADDRESS)
    parser.add_argument("--peer", help="peer address", type=parse_address)
    parser.add_argument("--verbose", help="verbose mode", action="store_true")
    args = parser.parse_args(sys.argv[1:])

    try:
        asyncio.run(main(args), debug=args.verbose)
    except KeyboardInterrupt:
        log.info("shutting down")
