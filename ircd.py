from gevent import monkey
monkey.patch_all()

import logging
import socket
import time

import gevent

from ircd import Server, Client, IRC


PORT = 9999
ADDRESS = "0.0.0.0", PORT
KEY_FILE = "key.pem"
SOCKET_TIMEOUT = 10
IDENT_TIMEOUT = 10

log = logging.getLogger("ircd")


def client_reader(irc, client, sock):
    start = time.time()
    while client.is_connected:
        try:
            data = sock.recv(4096)
        except socket.error as e:
            timeout = "timed out" in str(e)  # bug in python ssl, doesnt raise timeout
            if not timeout and client.is_connected:
                log.error("error reading from client: %s", e)
                irc.drop_client(client)
                break
            data = None

        if data:
            client.feed(data)

        elapsed = time.time() - start
        if elapsed > IDENT_TIMEOUT:
            log.error("client ident timeout: %s", client.host)
            irc.drop_client(client)


def client_writer(irc, client, sock):
    for msg in client.take():

        log.debug("<<< %s", msg.strip())
        try:
            sock.write(msg)
        except socket.error as e:
            if client.is_connected:
                log.error("error writing to client: %s", e)
                irc.drop_client(client)
                break


class AsyncServer(Server):
    def setup_client_socket(self, sock):
        sock = super(AsyncServer, self).setup_client_socket(sock)
        sock.settimeout(SOCKET_TIMEOUT)
        return sock

    def on_connect(self, client_sock, address):
        log.info("new client connection %s", address)
        sock = self.setup_client_socket(client_sock)

        client = Client(self.irc, sock, address)
        gevent.spawn(client_reader, self.irc, client, sock)
        gevent.spawn(client_writer, self.irc, client, sock)


def irc_worker(irc):
    while True:
        client, msg = irc.incoming.get()
        irc.process(client, msg)


def main():
    logging.basicConfig(level=logging.DEBUG)

    host = socket.getfqdn(ADDRESS[0])
    irc = IRC(host)

    gevent.spawn(irc_worker, irc)

    server = AsyncServer(irc, ADDRESS, KEY_FILE)
    server.serve()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
