import sys
import ssl
import socket


def main(args):
    address = args[0], args[1]

    print "connecting to", address, "..."
    sock = ssl.wrap_socket(socket.create_connection(address))

    for line in sys.stdin:
        line = line.strip()
        print "<<<", line
        sock.send(line + "\r\n")

    print

    for line in sock.makefile():
        print ">>>", line.strip()


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        pass
