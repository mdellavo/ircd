from unittest import TestCase

from ircd import IRC
from ircd.net import parsemsg, Client
from ircd.irc import SERVER_NAME, SERVER_VERSION


class TestIRC(TestCase):
    def setUp(self):
        self.irc = IRC("localhost")

    def get_client(self):
        return Client(self.irc, None, ("127.0.0.1", -1))

    def process(self, client, messages):
        for message in messages:
            msg = parsemsg(message)
            self.irc.process(client, msg)

    def assertReplies(self, client, values):
        replies = []
        while not client.outgoing.empty() and len(replies) < len(values):
            replies.append(client.outgoing.get(block=False))

        self.assertEqual(len(replies), len(values))
        for reply, value in zip(replies, values):
            self.assertEqual(reply.format(), value)

    def ident(self, client, nick):
        self.process(client, [
            "NICK {}".format(nick),
            "USER {} 0 * :{}".format(nick, nick)
        ])
        self.assertReplies(client, [
            ":{} NICK :{}".format(client.identity, nick),
            ":localhost 001 {} :Welcome to the Internet Relay Network {}".format(nick, client.identity),
            ":localhost 002 {} :Your host is {}, running version {}".format(nick, SERVER_NAME, SERVER_VERSION),
            ":localhost 003 {} :This server was created {}".format(nick, self.irc.created),
            ":localhost 004 {} :{} {} abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ".format(nick, SERVER_NAME, SERVER_VERSION)
        ])
        self.assertEqual(client.nickname, nick)
        self.assertEqual(client.user, nick)
        self.assertEqual(client.realname, nick)
        self.assertEqual(client.host, "localhost")
        self.assertTrue(client.has_nickname)
        self.assertTrue(client.has_identity)

    def join(self, client, chan, others=None):

        members = sorted([client.nickname] + (others or []))

        self.process(client, [
            "JOIN {}".format(chan)
        ])

        self.assertReplies(client, [
            ":{} JOIN :{}".format(client.identity, chan),
            ":localhost 331 {} :{}".format(client.nickname, chan),
            ":localhost 353 {} = {} :{}".format(client.nickname, chan, " ".join(members)),
            ":localhost 355 {} {} :End of /NAMES list.".format(client.nickname, chan),
        ])

        channel = self.irc.get_channel(chan)
        self.assertTrue(channel)
        self.assertIn(client.nickname, channel.members)

    def part(self, client, chan):
        self.process(client, [
            "PART {}".format(chan)
        ])

        self.assertReplies(client, [
            ":{} PART :{}".format(client.identity, chan),
        ])

        channel = self.irc.get_channel(chan)
        self.assertTrue(channel)
        self.assertNotIn(client.nickname, channel.members)

    def test_ident(self):
        self.ident(self.get_client(), "foo")

        self.assertIn("foo", self.irc.clients)
        client = self.irc.clients["foo"]
        self.assertTrue(client.has_identity)
        self.assertTrue(client.has_nickname)

    def test_join_part(self):
        client = self.get_client()
        self.ident(client, "foo")
        self.join(client, "#")

        self.assertIn("#", self.irc.channels)
        channel = self.irc.channels["#"]
        self.assertEqual(channel.name, "#")
        self.assertEqual(channel.members, ["foo"])
        self.assertEqual(channel.owner, "foo")

        self.part(client, "#")
        self.assertEqual(channel.members, [])

    def test_privmsg_channel(self):
        client_a = self.get_client()
        self.ident(client_a, "foo")

        # not joined yet
        self.process(client_a, [
            "PRIVMSG # :hello world"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost 403 :# No such nick/channel"
        ])

        self.join(client_a, "#")

        client_b = self.get_client()
        self.ident(client_b, "bar")
        self.join(client_b, "#", others=[client_a.nickname])

        channel = self.irc.channels["#"]
        self.assertEqual(channel.members, ["foo", "bar"])

        self.process(client_a, [
            "PRIVMSG # :hello world"
        ])
        self.assertReplies(client_a, [
            ":bar!bar@localhost JOIN :#"
        ])  # no reply to self

        self.assertReplies(client_b, [
            ":foo!foo@localhost PRIVMSG # :hello world"
        ])

        self.part(client_a, "#")
        self.process(client_a, [
            "PRIVMSG # :hello world"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost 441"
        ])

    def test_privmsg_client(self):
        client_a = self.get_client()
        self.ident(client_a, "foo")

        client_b = self.get_client()
        self.ident(client_b, "bar")

        self.process(client_a, [
            "PRIVMSG bar :hello world"
        ])

        self.assertReplies(client_b, [
            ":foo!foo@localhost PRIVMSG bar :hello world"
        ])

    def test_user_mode(self):
        client_a = self.get_client()
        self.ident(client_a, "foo")

        nickname = self.irc.nicknames["foo"]

        self.process(client_a, [
            "MODE foo :+i"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost MODE foo :+i"
        ])
        self.assertTrue(nickname.mode.user_is_invisible)

        self.process(client_a, [
            "MODE foo :-i"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost MODE foo :-i"
        ])

        self.assertFalse(nickname.mode.user_is_invisible)
        self.assertEqual(nickname.mode.mode, "")
