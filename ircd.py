from gevent import monkey
monkey.patch_all()

import logging
import socket

import gevent

from ircd import Server, Client, IRC, SocketTransport
from httpd import http_worker

PORT = 9999
ADDRESS = "0.0.0.0", PORT
KEY_FILE = "key.pem"
SOCKET_TIMEOUT = 10

log = logging.getLogger("ircd")


class AsyncServer(Server):
    def setup_client_socket(self, sock):
        sock = super(AsyncServer, self).setup_client_socket(sock)
        sock.settimeout(SOCKET_TIMEOUT)
        return sock

    def on_connect(self, client_sock, address):
        log.info("new client connection from %s", address[0])

        client = Client(self.irc, SocketTransport(self.setup_client_socket(client_sock), address))
        gevent.spawn(client.reader)
        gevent.spawn(client.writer)


def main():
    logging.basicConfig(level=logging.DEBUG,
                        datefmt="%Y-%m-%d %H:%M:%S",
                        format="[%(asctime)s] %(name)s/%(levelname)s %(message)s")

    host = socket.getfqdn(ADDRESS[0])
    irc = IRC(host)

    gevent.spawn(irc.processor)
    gevent.spawn(http_worker, irc)

    server = AsyncServer(irc, ADDRESS, KEY_FILE)
    server.serve()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
