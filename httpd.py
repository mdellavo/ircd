import json
import socket
import logging

import gevent
from gevent.pywsgi import WSGIServer

from pyramid.config import Configurator
from pyramid.view import view_config
from pyramid.httpexceptions import HTTPBadRequest

import geventwebsocket
from geventwebsocket.handler import WebSocketHandler

from ircd import Client, Transport, TransportError
from ircd.message import parsemsg

ADDRESS = ('0.0.0.0', 8080)

log = logging.getLogger("httpd")

response = lambda status, **kwargs: dict(status=status, **kwargs)
ok = lambda **kwargs: response("ok", **kwargs)
error = lambda **kwargs: response("error", **kwargs)


class WebsocketTransport(Transport):
    def __init__(self, sock, address):
        self.sock = sock
        self.host = socket.getfqdn(address)

    def close(self):
        self.sock.close()

    def read(self):
        while True:
            try:
                data = self.sock.receive()
            except geventwebsocket.WebSocketError as e:
                raise TransportError(e)

            if not data:
                break

            yield parsemsg(data)

        self.sock.close()

    def write(self, msg):
        try:
            self.sock.send(json.dumps(msg.to_dict()))
        except geventwebsocket.WebSocketError as e:
            raise TransportError(e)


def project_channel(channel):
    return {
        "name": channel.name,
        "topic": channel.topic,
        "mode": channel.mode.mode,
        "owner": project_nickname(channel.owner),
        "members": [project_nickname(n) for n in channel.members]
    }


def project_nickname(nickname):
    return {
        "nickname": nickname.nickname,
        "last_scene": nickname.last_seen.isoformat(),
        "mode": nickname.mode.mode
    }


@view_config(route_name="channel", renderer="json")
def get_channel(request):
    name = request.matchdict.get("name")
    name = name if name[0] == "#" else "#" + name
    channel = request.irc.get_channel(name)
    if not channel:
        return error(message="unknown channel")
    return ok(channel=project_channel(channel))


@view_config(route_name="channels", renderer="json")
def channels_index(request):
    return ok(channels=[project_channel(c) for c in request.irc.get_channels()])


@view_config(route_name="nicknames", renderer="json")
def nickname_index(request):
    return ok(nicknames=[project_nickname(n) for n in request.irc.get_nicknames()])


@view_config(route_name="nickname", renderer="json")
def get_nickname(request):
    name = request.matchdict.get("name")
    nickname = request.irc.get_nickname(name)
    if not nickname:
        return error(message="unknown nickname")
    return ok(nickname=project_nickname(nickname))


@view_config(route_name="socket", renderer="json")
def get_socket(request):
    if "wsgi.websocket" not in request.environ:
        raise HTTPBadRequest()

    socket = request.environ['wsgi.websocket']
    transport = WebsocketTransport(socket, request.environ['REMOTE_ADDR'])
    client = Client(request.irc, transport)
    reader = gevent.spawn(client.reader)
    writer = gevent.spawn(client.writer)

    gevent.joinall([reader, writer])

    return {"status": "ok"}


def build_app(irc):
    config = Configurator()

    config.add_request_method(lambda _: irc, 'irc', reify=True)

    config.add_route("channel", "/channels/{name}")
    config.add_route("channels", "/channels")
    config.add_route("nickname", "/nicknames/{name}")
    config.add_route("nicknames", "/nicknames")
    config.add_route("socket", "/")

    config.scan()

    return config.make_wsgi_app()


def http_worker(irc):
    app = build_app(irc)
    server = WSGIServer(ADDRESS, app, handler_class=WebSocketHandler)
    log.info("serving on %s:%s", *ADDRESS)
    server.serve_forever()
