import sys
import time
import asyncio
import logging

from .irc import IRC
from .net import Client
from .message import parsemsg, TERMINATOR

logging.basicConfig(level=logging.DEBUG)

log = logging.getLogger("ircd.main")

PING_INTERVAL = 60
PING_GRACE = 5
IDENT_TIMEOUT = 10


async def main(args):
    host = "localhost"
    listen_address, listen_port = "127.0.0.1", 8888

    irc = IRC(host)
    incoming = asyncio.Queue()

    async def _on_client_connected(reader, writer):
        client_address, client_port = writer.get_extra_info('peername')
        client_host, _ = await asyncio.get_event_loop().getnameinfo((client_address, client_port))
        log.info("connection from %s (%s)", client_address, client_host)
        client = Client(client_address, client_host)

        start_writer = False
        quit_message = "goodbye"
        while client.connected:
            line = (await reader.readuntil(TERMINATOR.encode())).strip()

            elapsed = time.time() - client.connected_at
            if elapsed > IDENT_TIMEOUT and not client.has_identity:
                log.error("client ident timeout: %s", client.host)
                quit_message = "ident timeout"
                break

            if line:
                message = parsemsg(line.decode())
                log.debug("read from %s: %s", client_address, message)
                await incoming.put((client, message))
                if not start_writer:
                    asyncio.create_task(_client_writer(client, writer))
                    start_writer = True

        reader.close()
        irc.drop_client(client, message=quit_message)
        log.info("client disconnect: %s", client)

    async def _client_writer(client, writer):
        while client.connected:
            message = await client.outgoing.get()
            line = message.format() + TERMINATOR
            bytes = line.encode()
            log.debug("writing to %s: %s", client, bytes)
            writer.write(bytes)
            await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def _irc_processor():
        running = True
        while running:
            client, message = await incoming.get()
            log.info("processing message from %s: %s", client, message)
            irc.process(client, message)

    asyncio.create_task(_irc_processor())

    def _start_client(reader, writer):
        asyncio.create_task(_on_client_connected(reader, writer))

    server = await asyncio.start_server(_start_client, listen_address, listen_port)
    log.info("serving on %s:%s", listen_address, listen_port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1:]), debug=True)
    except KeyboardInterrupt:
        log.info("shutting down")
