from gevent import monkey
monkey.patch_all()

import logging
import socket

import gevent

from ircd import Server, Client, IRC


ADDRESS = "0.0.0.0", 9999
KEY_FILE = "key.pem"

log = logging.getLogger("ircd")


def client_reader(irc, client, sock):
    while client.is_running:
        try:
            data = sock.recv(4096)
        except socket.error as e:
            if client.is_running:
                log.error("error reading from client: %s", e)
            data = None

        if not data:
            if client.is_running:
                irc.drop_client(client)
            break

        client.feed(data)


def client_writer(irc, client, sock):
    for msg in client.take():
        client.take()

        log.debug("<<< %s", msg.strip())
        try:
            sock.write(msg)
        except socket.error as e:
            if client.is_running:
                log.error("error writing to client: %s", e)
                irc.drop_client(client)
                break


class AsyncServer(Server):
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
