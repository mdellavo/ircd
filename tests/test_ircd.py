from unittest import TestCase

from ircd import IRC
from ircd.net import parsemsg, Client
from ircd.irc import SERVER_NAME, SERVER_VERSION


class TestIRC(TestCase):
    def setUp(self):
        self.irc = IRC("localhost")
        self.client = Client(self.irc, None, "127.0.0.1")

    def process(self, messages):
        for message in messages:
            msg = parsemsg(message)
            self.irc.dispatch(self.client, msg)

    def assertReplies(self, values):
        replies = []
        while not self.client.outgoing.empty():
            replies.append(self.client.outgoing.get(block=False))

        self.assertEqual(len(replies), len(values))
        for reply, value in zip(replies, values):
            self.assertEqual(reply.format(), value)

    def test_ident(self):
        self.process([
            "NICK foo",
            "USER foo foo 127.0.0.1 :foo"
        ])

        self.assertReplies([
            ":foo!foo@127.0.0.1 NICK :foo",
            ":localhost 001 foo :Welcome to the Internet Relay Network foo!foo@127.0.0.1",
            ":localhost 002 foo :Your host is {}, running version {}".format(SERVER_NAME, SERVER_VERSION),
            ":localhost 003 foo :This server was created {}".format(self.irc.created),
            ":localhost 004 foo :{} {} abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ".format(SERVER_NAME, SERVER_VERSION)
        ])
