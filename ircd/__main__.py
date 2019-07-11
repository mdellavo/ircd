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

LISTEN_ADDRESS, LISTEN_PORT = "127.0.0.1", 8888
LINK_ADDRESS, LINK_PORT = "127.0.0.1", 8887

PING_INTERVAL = 60
PING_GRACE = 5
IDENT_TIMEOUT = 10

QUIT_MESSAGE = "goodbye"


async def readline(reader):
    return (await reader.readuntil(TERMINATOR.encode())).decode().strip()


async def write_message(client, writer, message):
    line = message.format() + TERMINATOR
    bytes = line.encode()
    writer.write(bytes)
    await writer.drain()
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

    async def _on_client_connected(reader, writer, is_link=False):
        client_address, client_port, client_host = await resolve_peerinfo(writer)
        log.info("connection from %s (%s)", client_address, client_host)

        client = Client(client_address, client_host)

        start_writer = False
        writer_task = None
        while client.connected and not reader.at_eof():
            try:
                line = await readline(reader)
            except asyncio.streams.IncompleteReadError:
                break

            message = parsemsg(line)
            log.debug("read from %s: %s", client_address, message)
            await incoming.put((client, message))
            if not start_writer:
                writer_task = asyncio.create_task(_client_writer(client, writer))
                start_writer = True
        await _drop_client(client, writer)
        await writer_task
        log.debug("client reader for %s (%s) shutdown", client.address, client.host)

    async def _client_writer(client, writer):
        while client.connected:
            message = await client.outgoing.get()
            if not message:
                continue
            await write_message(client, writer, message)
        await _drop_client(client, writer)
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

    def _start_client(reader, writer):
        asyncio.create_task(_on_client_connected(reader, writer))

    async def _client_listener():
        server = await asyncio.start_server(_start_client, args.listen_address, args.listen_port)
        log.info("serving clients on %s:%s", args.listen_address, args.listen_port)
        async with server:
            await server.serve_forever()
    client_listener = asyncio.create_task(_client_listener())

    def _start_link(reader, writer):
        asyncio.create_task(_on_client_connected(reader, writer))

    async def _link_listener():
        server = await asyncio.start_server(_start_link, args.link_address, args.link_port)
        log.info("serving links on %s:%s", args.link_address, args.link_port)
        async with server:
            await server.serve_forever()
    link_listener = asyncio.create_task(_link_listener())

    await asyncio.gather(irc_processor, client_listener, link_listener)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="irc server")
    parser.add_argument("--listen_address", help="listen address", default=LISTEN_ADDRESS)
    parser.add_argument("--listen_port", help="listen port", default=LISTEN_PORT, type=int)
    parser.add_argument("--link_address", help="link address", default=LINK_ADDRESS)
    parser.add_argument("--link_port", help="link port", default=LINK_PORT, type=int)
    parser.add_argument("--verbose", help="verbose mode", action="store_true")
    args = parser.parse_args(sys.argv[1:])

    try:
        asyncio.run(main(args), debug=args.verbose)
    except KeyboardInterrupt:
        log.info("shutting down")
