import sys
from websocket import create_connection


def main(args):
    address = args[0], args[1]

    print "connecting to", address, "..."
    ws = create_connection("ws://{}:{}/socket".format(*address))

    for line in sys.stdin:
        line = line.strip()
        print "<<<", line
        ws.send(line + "\r\n")

    print

    while ws.connected:
        msg = ws.recv()
        print ">>>", msg


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        pass
