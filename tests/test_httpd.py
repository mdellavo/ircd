import unittest

from webtest import TestApp

from ircd import IRC, Nickname, Channel, Client
from httpd import build_app

from test_ircd import MockTransport


class FunctionalTestCase(unittest.TestCase):
    def setUp(self):
        super(FunctionalTestCase, self).setUp()

        self.irc = IRC("localhost")
        app = build_app(self.irc)
        self.app = TestApp(app)


class TestAPI(FunctionalTestCase):
    def test_channels(self):
        owner = Nickname("joe")

        chans = sorted(["#foo", "#bar", "#baz"])
        for chan in chans:
            self.irc.set_channel(Channel(chan, owner))

        r = self.app.get("/channels").json

        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(r["channels"]), len(chans))
        self.assertEqual(sorted([c["name"] for c in r["channels"]]), chans)

        r = self.app.get("/channels/foo").json
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["channel"]["name"], "#foo")

    def test_nicknames(self):
        nicks = sorted(["foo", "bar", "baz"])
        for nick in nicks:
            self.irc.set_nick(Client(self.irc, MockTransport()), nick)

        r = self.app.get("/nicknames").json

        self.assertEqual(r["status"], "ok")
        self.assertEqual(sorted([n["nickname"] for n in r["nicknames"]]), nicks)

        r = self.app.get("/nicknames/foo").json
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["nickname"]["nickname"], "foo")


    def test_socket(self):
        pass