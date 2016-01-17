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

    def join(self, client, channel_name):
        self.process(client, [
            "JOIN {}".format(channel_name)
        ])

        channel = self.irc.get_channel(channel_name)
        self.assertTrue(channel)
        nickname = self.irc.get_nickname(client.nickname)
        self.assertIn(nickname, channel.members)

        members = sorted([member.nickname for member in channel.members])
        self.assertReplies(client, [
            ":{} JOIN :{}".format(client.identity, channel_name),
            ":localhost 331 {} :{}".format(client.nickname, channel_name),
            ":localhost 353 {} = {} :{}".format(client.nickname, channel_name, " ".join(members)),
            ":localhost 355 {} {} :End of /NAMES list.".format(client.nickname, channel_name),
        ])

    def part(self, client, chan, message=None):
        if message:
            cmd = "PART {} :{}".format(chan, message)
        else:
            cmd = "PART {}".format(chan)

        self.process(client, [
            cmd
        ])

        if message:
            value = ":{} PART {} :{}".format(client.identity, chan, message)
        else:
            value = ":{} PART :{}".format(client.identity, chan)

        self.assertReplies(client, [
            value,
        ])

        channel = self.irc.get_channel(chan)
        self.assertTrue(channel)
        nickname = self.irc.get_nickname(client.nickname)
        self.assertNotIn(nickname, channel.members)

    def test_ident(self):
        self.ident(self.get_client(), "foo")

        self.assertIn("foo", self.irc.clients)
        client = self.irc.clients["foo"]
        self.assertTrue(client.has_identity)
        self.assertTrue(client.has_nickname)

    def test_nick(self):
        self.ident(self.get_client(), "foo")
        client = self.irc.clients["foo"]

        self.assertEqual(client.nickname, "foo")
        self.assertIn("foo", self.irc.nicknames)

        self.process(client, [
            "NICK :bar"
        ])

        self.assertReplies(client, [
            ":foo!foo@localhost NICK :bar"
        ])

        self.assertNotIn("foo", self.irc.nicknames)
        self.assertEqual(client.nickname, "bar")
        self.assertIn("bar", self.irc.nicknames)

    def test_join_part(self):
        client = self.get_client()
        self.ident(client, "foo")
        self.join(client, "#")

        self.assertIn("#", self.irc.channels)
        channel = self.irc.channels["#"]
        self.assertEqual(channel.name, "#")
        self.assertEqual([member.nickname for member in channel.members], ["foo"])
        self.assertEqual(channel.owner.nickname, "foo")

        nickname = self.irc.get_nickname(client.nickname)
        self.assertEqual([chan.name for chan in nickname.channels], ["#"])

        self.part(client, "#", message="byebye")
        self.assertEqual(channel.members, [])
        self.assertEqual([chan.name for chan in nickname.channels], [])

    def test_join_key(self):
        client_a = self.get_client()
        self.ident(client_a, "foo")
        self.join(client_a, "#")

        self.process(client_a, [
            "MODE # +k :sekret"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost MODE # +k :sekret"
        ])

        self.assertEqual(self.irc.channels["#"].key, "sekret")

        client_b = self.get_client()
        self.ident(client_b, "bar")

        self.process(client_b, [
            "JOIN :#"
        ])
        self.assertReplies(client_b, [
            ":bar!bar@localhost 475 :# :Cannot join channel (+k)"
        ])

        self.process(client_b, [
            "JOIN # :sekret"
        ])
        self.assertReplies(client_b, [
            ":bar!bar@localhost JOIN :#"
        ])

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
        self.join(client_b, "#")

        channel = self.irc.channels["#"]
        self.assertEqual([member.nickname for member in channel.members], ["foo", "bar"])

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
        self.assertTrue(nickname.is_invisible)

        self.process(client_a, [
            "MODE foo :-i"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost MODE foo :-i"
        ])

        self.assertFalse(nickname.is_invisible)
        self.assertEqual(nickname.mode.mode, "")

    def test_channel_mode(self):
        client_a = self.get_client()
        self.ident(client_a, "foo")
        self.join(client_a, "#")

        client_b = self.get_client()
        self.ident(client_b, "bar")
        self.join(client_b, "#")

        self.assertReplies(client_a, [
            ":bar!bar@localhost JOIN :#"
        ])

        channel = self.irc.channels["#"]

        # check operator
        self.process(client_b, [
            "MODE # :+n"
        ])
        self.assertReplies(client_b, [
            ":bar!bar@localhost 482 :# You're not channel operator"
        ])

        self.process(client_a, [
            "MODE # :+n"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost MODE # :+n"
        ])
        self.assertReplies(client_b, [
            ":foo!foo@localhost MODE # :+n"
        ])
        self.assertEqual(channel.mode.mode, "n")
        self.process(client_a, [
            "MODE # :-n"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost MODE # :-n"
        ])

        self.assertEqual(channel.mode.mode, "")

    def test_channel_operator(self):
        client_a = self.get_client()
        self.ident(client_a, "foo")
        self.join(client_a, "#")

        client_b = self.get_client()
        self.ident(client_b, "bar")
        self.join(client_b, "#")

        self.assertReplies(client_a, [
            ":bar!bar@localhost JOIN :#"
        ])

        channel = self.irc.channels["#"]

        self.process(client_a, [
            "MODE # +o :bar"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost MODE # +o :bar"
        ])
        self.assertReplies(client_b, [
            ":foo!foo@localhost MODE # +o :bar"
        ])

        nickname = self.irc.get_nickname(client_b.nickname)
        self.assertIn(nickname, channel.operators)

        self.process(client_a, [
            "MODE # -o :bar"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost MODE # -o :bar"
        ])
        self.assertReplies(client_b, [
            ":foo!foo@localhost MODE # -o :bar"
        ])

        self.assertNotIn(nickname, channel.operators)

    def test_set_channel_secret(self):
        client = self.get_client()
        self.ident(client, "foo")
        self.join(client, "#")

        self.process(client, [
            "MODE # :+k"
        ])
        self.assertReplies(client, [
            ":foo!foo@localhost 461 MODE :Not enough parameters"
        ])

        self.process(client, [
            "MODE # +k :sekret"
        ])
        self.assertReplies(client, [
            ":foo!foo@localhost MODE # +k :sekret"
        ])

        self.assertEqual(self.irc.channels["#"].key, "sekret")

        self.process(client, [
            "MODE # -k"
        ])
        self.assertReplies(client, [
            ":foo!foo@localhost MODE # :-k"
        ])
        self.assertIsNone(self.irc.channels["#"].key)

    def test_topic(self):
        client = self.get_client()
        self.ident(client, "foo")
        self.join(client, "#")

        self.process(client, [
            "TOPIC #"
        ])

        self.assertReplies(client, [
            ":localhost 331 foo :#"
        ])
        self.process(client, [
            "TOPIC # :hello world"
        ])
        self.assertReplies(client, [
            ":localhost 332 # :hello world"
        ])
        channel = self.irc.get_channel("#")
        self.assertEqual(channel.topic, "hello world")

        self.process(client, [
            "TOPIC #"
        ])
        self.assertReplies(client, [
            ":localhost 332 # :hello world"
        ])

    def test_invite(self):
        client_a = self.get_client()
        self.ident(client_a, "foo")

        self.join(client_a, "#")
        self.process(client_a, [
            "MODE # +i"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost MODE # :+i"
        ])

        client_b = self.get_client()
        self.ident(client_b, "bar")

        channel = self.irc.get_channel("#")
        nick_b = self.irc.get_nickname("bar")

        self.assertTrue(channel.is_invite_only)
        self.assertFalse(channel.can_join_channel(nick_b))

        self.process(client_b, [
            "JOIN #"
        ])
        self.assertReplies(client_b, [
            ":bar!bar@localhost 473 :# :Cannot join channel (+i)"
        ])

        self.process(client_a, [
            "INVITE bar #"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost 341 # :bar"
        ])

        self.assertTrue(channel.can_join_channel(nick_b))

        self.assertReplies(client_b, [
            ":foo!foo@localhost INVITE bar :#"
        ])

        self.process(client_b, [
            "JOIN #"
        ])
        self.assertReplies(client_b, [
            ":bar!bar@localhost JOIN :#"
        ])

    def test_kick(self):
        client_a = self.get_client()
        self.ident(client_a, "foo")

        self.join(client_a, "#")
        self.process(client_a, [
            "MODE # +i"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost MODE # :+i"
        ])

        client_b = self.get_client()
        self.ident(client_b, "bar")

        channel = self.irc.get_channel("#")
        nick_b = self.irc.get_nickname("bar")

        self.assertTrue(channel.is_invite_only)
        self.assertFalse(channel.can_join_channel(nick_b))

        self.process(client_a, [
            "INVITE bar #"
        ])
        self.assertReplies(client_a, [
            ":foo!foo@localhost 341 # :bar"
        ])

        self.assertTrue(channel.can_join_channel(nick_b))

        self.assertReplies(client_b, [
            ":foo!foo@localhost INVITE bar :#"
        ])

        self.join(client_b, "#")

        self.assertIn(nick_b, channel.members)

        self.process(client_a, [
            "KICK # bar :get out!"
        ])
        self.assertReplies(client_b, [
            ":foo!foo@localhost KICK # bar :get out!"
        ])
        self.assertNotIn(nick_b, channel.members)
        self.assertFalse(channel.can_join_channel(nick_b))

