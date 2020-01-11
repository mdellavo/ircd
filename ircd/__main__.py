import sys
import asyncio
import logging
import argparse
import socket
import signal

from . import IRC, Server

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(name)s - %(levelname)s - %(message)s',
)

log = logging.getLogger("ircd.main")

CLIENT_PORT = "9999"
CLIENT_LISTEN_ADDRESS = "0.0.0.0:" + CLIENT_PORT

LINK_PORT = "6666"
LINK_LISTEN_ADDRESS = "0.0.0.0:" + LINK_PORT


def parse_address(s):
    parts = s.split(":")
    host, port = parts
    return host, int(port)


async def resolve_address(host, port):
    addresses = await asyncio.get_event_loop().getaddrinfo(host, port)
    return addresses[0][-1][0] if addresses else host


async def main(args):
    addr, port = args.listen
    irc = IRC(args.host)
    server = Server(irc)

    async def _shutdown():
        log.info("shutdown")
        await server.shutdown()

    for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, lambda: asyncio.create_task(_shutdown()))

    await server.run(
        client_listen_addr=args.listen[0],
        client_listen_port=args.listen[1],
        link_listen_addr=args.link[0],
        link_listen_port=args.link[1],
        peer_addr=await resolve_address(args.peer[0], args.peer[1]) if args.peer else None,
        peer_port=args.peer[1] if args.peer else None,
        ws_addr=args.ws[0] if args.ws else None,
        ws_port=args.ws[1] if args.ws else None,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="irc server")
    parser.add_argument("--host", help="host name", default=socket.gethostname())
    parser.add_argument("--listen", help="listen address", type=parse_address, default=CLIENT_LISTEN_ADDRESS)
    parser.add_argument("--link", help="link address", type=parse_address, default=LINK_LISTEN_ADDRESS)
    parser.add_argument("--peer", help="peer address", type=parse_address)
    parser.add_argument("--ws", help="websocket listen address", type=parse_address)
    parser.add_argument("--verbose", help="verbose mode", action="store_true")
    args = parser.parse_args(sys.argv[1:])

    try:
        asyncio.run(main(args), debug=args.verbose)
    except asyncio.CancelledError:
        pass
