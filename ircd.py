from gevent import monkey
monkey.patch_all()

import logging
import socket

from ircd import Server, IRC


ADDRESS = "0.0.0.0", 9999
KEY_FILE = "key.pem"

log = logging.getLogger("ircd")


def main():
    logging.basicConfig(level=logging.DEBUG)

    host = socket.getfqdn(ADDRESS[0])
    irc = IRC(host)
    irc.start()
    server = Server(irc, ADDRESS, KEY_FILE)
    server.serve()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
