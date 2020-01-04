import asyncio
import contextlib
from unittest import mock
import datetime
import base64

import pytest

from ircd import IRC, Server
from ircd.irc import SERVER_NAME, SERVER_VERSION

pytestmark = pytest.mark.asyncio

HOST = "localhost"
ADDRESS = "127.0.0.1"
PORT = 9001


@contextlib.asynccontextmanager
async def connect(address=ADDRESS, port=PORT):
    reader, writer = await asyncio.open_connection(address, port)
    yield reader, writer
    writer.close()


@contextlib.asynccontextmanager
async def server_conn(address=ADDRESS, port=PORT):
    irc = IRC(HOST)
    server = Server(irc, ping_interval=5)

    asyncio.create_task(server.run(address, port))
    await server.running.wait()

    async with connect(address, port) as (reader, writer):
        yield irc, reader, writer

    await server.shutdown()


async def send(conn, messages):
    conn.write(("\r\n".join(messages) + "\r\n").encode())
    await conn.drain()


# FIXME nasty hack
async def readall(reader):
    lines = []
    while True:
        try:
            b = await asyncio.wait_for(reader.readline(), .1)
            if not b:
                break
        except asyncio.exceptions.TimeoutError:
            break
        line = b.strip().decode()
        assert " PING " not in line
        lines.append(line)

    return lines


async def ident(reader, writer, irc, nick):
    await send(writer, [
        "NICK {}".format(nick),
        "USER {} 0 * :{}".format(nick, nick)
    ])
    assert await readall(reader) == [
        ":{}!{}@{} NICK :{}".format(nick, nick, HOST, nick),
        ":localhost 001 {} :Welcome to the Internet Relay Network {}!{}@{}".format(nick, nick, nick, HOST),
        ":localhost 002 {} :Your host is {}, running version {}".format(nick, SERVER_NAME, SERVER_VERSION),

        ":localhost 003 {} :This server was created {}".format(nick, irc.created),
        ":localhost 004 {} :{} {} abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ".format(nick, SERVER_NAME, SERVER_VERSION)
    ]


async def join(reader, writer, irc, nickname, channel_name):
    await send(writer, [
        "JOIN {}".format(channel_name)
    ])
    replies = await readall(reader)

    channel = irc.get_channel(channel_name)
    assert channel
    assert irc.get_nickname(nickname) in channel.members

    members = sorted([member.nickname for member in channel.members])
    assert replies == [
        ":{}!{}@{} JOIN :{}".format(nickname, nickname, HOST, channel_name),
        ":localhost 331 {} :{}".format(nickname, channel_name),
        ":localhost 353 {} = {} :{}".format(nickname, channel_name, " ".join(members)),
        ":localhost 366 {} {} :End of /NAMES list.".format(nickname, channel_name),
    ]


async def part(reader, writer, irc, nickname, chan, message=None):
    if message:
        cmd = "PART {} :{}".format(chan, message)
    else:
        cmd = "PART {}".format(chan)

    await send(writer, [cmd])

    if message:
        value = ":{}!{}@{} PART {} :{}".format(nickname, nickname, HOST, chan, message)
    else:
        value = ":{}!{}@{} PART :{}".format(nickname, nickname, HOST, chan)

    assert await readall(reader) == [value]

    channel = irc.get_channel(chan)
    nickname = irc.get_nickname(nickname)
    if nickname and channel:
        assert nickname not in channel.members


@pytest.mark.asyncio
async def test_ident():
    async with server_conn() as (irc, reader, writer):
        await ident(reader, writer, irc, "foo")
        "foo" in irc.nick_client
        "foo" in irc.nicknames
        client = irc.lookup_client("foo")
        assert client.has_identity
        assert client.has_nickname


@pytest.mark.asyncio
async def test_nick():
    async with server_conn() as (irc, reader, writer):
        await ident(reader, writer, irc, "foo")
        client = irc.lookup_client("foo")
        assert client.name == "foo"
        assert "foo" in irc.nicknames
        await send(writer, [
            "NICK :bar"
        ])
        assert await readall(reader) == [":foo!foo@localhost NICK :bar"]
        assert "foo" not in irc.nicknames
        assert client.name == "bar"
        assert "bar" in irc.nicknames


@pytest.mark.asyncio
async def test_join_part():
    async with server_conn() as (irc, reader, writer):
        await ident(reader, writer, irc, "foo")
        await join(reader, writer, irc, "foo", "#")

        assert "#" in irc.channels
        channel = irc.channels["#"]
        assert channel.name == "#"
        assert [member.nickname for member in channel.members] == ["foo"]
        assert channel.owner.nickname == "foo"

        nickname = irc.get_nickname("foo")
        assert [chan.name for chan in nickname.channels] == ["#"]

        await part(reader, writer, irc, "foo", "#", message="byebye")
        assert channel.members == []
        assert [chan.name for chan in nickname.channels] == []

        await join(reader, writer, irc, "foo", "#")

    assert "#" not in irc.channels


@pytest.mark.asyncio
async def test_join_key():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):
        await ident(reader_a, writer_a, irc, "foo")
        await join(reader_a, writer_a, irc, "foo", "#")

        await send(writer_a, [
            "MODE # +k :sekret"
        ])

        assert await readall(reader_a) == [
            ":foo!foo@localhost MODE # +k :sekret"
        ]

        assert irc.channels["#"].key == "sekret"
        await ident(reader_b, writer_b, irc, "bar")

        await send(writer_b, [
            "JOIN :#"
        ])
        assert await readall(reader_b) == [
            ":localhost 475 bar :# :Cannot join channel (+k)"
        ]

        await send(writer_b, [
            "JOIN # :sekret"
        ])
        assert (await readall(reader_b))[:1] == [
            ":bar!bar@localhost JOIN :#"
        ]


@pytest.mark.asyncio
async def test_privmsg_channel():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):
        await ident(reader_a, writer_a, irc, "foo")

        # not joined yet
        await send(writer_a, [
            "PRIVMSG # :hello world"
        ])
        assert await readall(reader_a) == [
            ":localhost 403 foo :# No such nick/channel"
        ]

        await join(reader_a, writer_a, irc, "foo", "#")

        await ident(reader_b, writer_b, irc, "bar")
        await join(reader_b, writer_b, irc, "bar", "#")

        channel = irc.channels["#"]
        assert [member.nickname for member in channel.members] == ["foo", "bar"]

        await send(writer_a, [
            "PRIVMSG # :hello world"
        ])
        assert await readall(reader_a) == [
            ":bar!bar@localhost JOIN :#"
        ]  # no reply to self

        assert await readall(reader_b) == [
            ":foo!foo@localhost PRIVMSG # :hello world"
        ]

        await part(reader_a, writer_a, irc, "foo", "#")
        await send(writer_a, [
            "PRIVMSG # :hello world"
        ])
        assert await readall(reader_a) == [
            ":localhost 441 :foo"
        ]


@pytest.mark.asyncio
async def test_privmsg_client():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):
        await ident(reader_a, writer_a, irc, "foo")
        await ident(reader_b, writer_b, irc, "bar")

        await send(writer_a, [
            "PRIVMSG bar :hello world"
        ])

        assert await readall(reader_b) == [
            ":foo!foo@localhost PRIVMSG bar :hello world"
        ]


@pytest.mark.asyncio
async def test_user_mode():
    async with server_conn() as (irc, reader, writer):
        await ident(reader, writer, irc, "foo")

        nickname = irc.nicknames["foo"]

        await send(writer, [
            "MODE foo :+i"
        ])
        assert await readall(reader) == [
            ":foo!foo@localhost MODE foo :+i"
        ]
        assert nickname.is_invisible

        await send(writer, [
            "MODE foo :-i"
        ])
        assert await readall(reader) == [
            ":foo!foo@localhost MODE foo :-i"
        ]

        assert not nickname.is_invisible
        assert nickname.mode.mode == ""


@pytest.mark.asyncio
async def test_channel_mode():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):

        await ident(reader_a, writer_a, irc, "foo")
        await join(reader_a, writer_a, irc, "foo", "#")

        await ident(reader_b, writer_b, irc, "bar")
        await join(reader_b, writer_b, irc, "bar", "#")

        assert await readall(reader_a) == [
            ":bar!bar@localhost JOIN :#"
        ]

        channel = irc.channels["#"]

        # check operator
        await send(writer_b, [
            "MODE # :+n"
        ])
        assert await readall(reader_b) == [
            ":localhost 482 bar :# You're not channel operator"
        ]

        await send(writer_a, [
            "MODE # :+n"
        ])
        assert await readall(reader_a) == [
            ":foo!foo@localhost MODE # :+n"
        ]

        assert await readall(reader_b) == [
            ":foo!foo@localhost MODE # :+n"
        ]

        assert channel.mode.mode == "n"
        await send(writer_a, [
            "MODE # :-n"
        ])
        assert await readall(reader_a) == [
            ":foo!foo@localhost MODE # :-n"
        ]

        assert channel.mode.mode == ""


@pytest.mark.asyncio
async def test_channel_operator():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):
        await ident(reader_a, writer_a, irc, "foo")
        await join(reader_a, writer_a, irc, "foo", "#")

        await ident(reader_b, writer_b, irc, "bar")
        await join(reader_b, writer_b, irc, "bar", "#")

        assert await readall(reader_a) == [
            ":bar!bar@localhost JOIN :#"
        ]

        channel = irc.channels["#"]

        await send(writer_a, [
            "MODE # +o :bar"
        ])
        assert await readall(reader_a) == [
            ":foo!foo@localhost MODE # +o :bar"
        ]
        assert await readall(reader_b) == [
            ":foo!foo@localhost MODE # +o :bar"
        ]

        nickname = irc.get_nickname("bar")
        assert nickname in channel.operators

        await send(writer_a, [
            "MODE # -o :bar"
        ])
        assert await readall(reader_a) == [
            ":foo!foo@localhost MODE # -o :bar"
        ]
        assert await readall(reader_b) == [
            ":foo!foo@localhost MODE # -o :bar"
        ]
        assert nickname not in channel.operators


@pytest.mark.asyncio
async def test_set_channel_secret():
    async with server_conn() as (irc, reader, writer):
        await ident(reader, writer, irc, "foo")
        await join(reader, writer, irc, "foo", "#")

        await send(writer, [
            "MODE # :+k"
        ])
        assert await readall(reader) == [
            ":localhost 461 foo MODE :Not enough parameters"
        ]

        await send(writer, [
            "MODE # +k :sekret"
        ])
        assert await readall(reader) == [
            ":foo!foo@localhost MODE # +k :sekret"
        ]

        assert irc.channels["#"].key == "sekret"

        await send(writer, [
            "MODE # -k"
        ])
        assert await readall(reader) == [
            ":foo!foo@localhost MODE # :-k"
        ]
        assert irc.channels["#"].key is None


@pytest.mark.asyncio
async def test_topic():
    async with server_conn() as (irc, reader, writer):
        with mock.patch("time.time") as time_patch:
            time_patch.return_value = 1562815441

            await ident(reader, writer, irc, "foo")
            await join(reader, writer, irc, "foo", "#")

            await send(writer, [
                "TOPIC #"
            ])

            assert await readall(reader) == [
                ":localhost 331 foo :#"
            ]
            await send(writer, [
                "TOPIC # :hello world"
            ])
            assert await readall(reader) == [
                ":localhost 332 foo # :hello world",
                ":localhost 333 foo # foo :1562815441",
            ]
            channel = irc.get_channel("#")
            assert channel.topic == "hello world"

            await send(writer, [
                "TOPIC #"
            ])
            assert await readall(reader) == [
                ":localhost 332 foo # :hello world",
            ]


@pytest.mark.asyncio
async def test_invite():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):

        await ident(reader_a, writer_a, irc, "foo")
        await join(reader_a, writer_a, irc, "foo", "#")

        await ident(reader_b, writer_b, irc, "bar")

        await send(writer_a, [
            "MODE # +i"
        ])
        assert await readall(reader_a) == [
            ":foo!foo@localhost MODE # :+i"
        ]

        channel = irc.get_channel("#")
        nick_b = irc.get_nickname("bar")

        assert channel.is_invite_only
        assert not channel.can_join_channel(nick_b)

        await send(writer_b, [
            "JOIN #"
        ])
        assert await readall(reader_b) == [
            ":localhost 473 bar :# :Cannot join channel (+i)"
        ]

        await send(writer_a, [
            "INVITE bar #"
        ])
        assert await readall(reader_a) == [
            ":localhost 341 foo # :bar"
        ]

        assert channel.can_join_channel(nick_b)

        assert await readall(reader_b) == [
            ":foo!foo@localhost INVITE bar :#"
        ]

        await send(writer_b, [
            "JOIN #"
        ])
        assert (await readall(reader_b))[:1] == [
            ":bar!bar@localhost JOIN :#"
        ]


@pytest.mark.asyncio
async def test_ban():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):

        await ident(reader_a, writer_a, irc, "foo")
        await join(reader_a, writer_a, irc, "foo", "#")

        await ident(reader_b, writer_b, irc, "bar")

        channel = irc.get_channel("#")
        assert not channel.is_banned("bar!bar@localhost")

        await send(writer_a, [
            "MODE # +b *!*@localhost"
        ])
        assert await readall(reader_a) == [
            ":foo!foo@localhost MODE # +b :*!*@localhost"
        ]

        assert channel.is_banned("bar!bar@localhost")

        await send(writer_b, [
            "JOIN #"
        ])
        assert await readall(reader_b) == [
            ":localhost 474 bar :# :Cannot join channel (+b)"
        ]

        await send(writer_a, [
            "MODE # +e *!*@localhost"
        ])
        await readall(reader_a)
        assert not channel.is_banned("bar!bar@localhost")

        await send(writer_a, [
            "MODE # -e *!*@localhost"
        ])
        await readall(reader_a)

        assert channel.is_banned("bar!bar@localhost")

        await send(writer_a, [
            "MODE # -b *!*@localhost"
        ])
        await readall(reader_a)

        assert not channel.is_banned("bar!bar@localhost")


@pytest.mark.asyncio
async def test_kick():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):

        await ident(reader_a, writer_a, irc, "foo")
        await join(reader_a, writer_a, irc, "foo", "#")

        await ident(reader_b, writer_b, irc, "bar")

        await send(writer_a, [
            "MODE # +i"
        ])
        assert await readall(reader_a) == [
            ":foo!foo@localhost MODE # :+i"
        ]

        channel = irc.get_channel("#")
        nick_b = irc.get_nickname("bar")

        assert channel.is_invite_only
        assert not channel.can_join_channel(nick_b)

        await send(writer_a, [
            "INVITE bar #"
        ])
        assert await readall(reader_a) == [
            ":localhost 341 foo # :bar"
        ]

        assert channel.can_join_channel(nick_b)

        assert await readall(reader_b) == [
            ":foo!foo@localhost INVITE bar :#"
        ]

        await join(reader_b, writer_b, irc, "bar", "#")

        assert nick_b in channel.members

        await send(writer_a, [
            "KICK # bar :get out!"
        ])
        assert await readall(reader_b) == [
            ":foo!foo@localhost KICK # bar :get out!"
        ]
        assert nick_b not in channel.members
        assert not channel.can_join_channel(nick_b)


@pytest.mark.asyncio
async def test_names():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):

        await ident(reader_a, writer_a, irc, "foo")
        await join(reader_a, writer_a, irc, "foo", "#")

        await ident(reader_b, writer_b, irc, "bar")
        await join(reader_b, writer_b, irc, "bar", "#")

        assert await readall(reader_a) == [
            ":bar!bar@localhost JOIN :#",
        ]
        await send(writer_a, [
            "NAMES #"
        ])
        assert await readall(reader_a) == [
            ":localhost 353 foo = # :bar foo",
            ":localhost 366 foo # :End of /NAMES list."
        ]


@pytest.mark.asyncio
async def test_list():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):

        await ident(reader_a, writer_a, irc, "foo")
        await ident(reader_b, writer_b, irc, "bar")

        for name in ["#foo", "#bar", "#baz"]:
            await join(reader_a, writer_a, irc, "foo", name)
            channel = irc.channels[name]
            await join(reader_b, writer_b, irc, "bar", name)
            assert await readall(reader_a) == [
                ":bar!bar@localhost JOIN :" + name,
            ]
            channel.topic = name * 3

        await send(writer_a, [
            "LIST"
        ])
        assert await readall(reader_a) == [
            ":localhost 321 foo Channel Users :Name",
            ":localhost 322 foo #foo 2 :#foo#foo#foo",
            ":localhost 322 foo #bar 2 :#bar#bar#bar",
            ":localhost 322 foo #baz 2 :#baz#baz#baz",
            ":localhost 323 foo :End of /LIST",
        ]


@pytest.mark.asyncio
async def test_away():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):

        await ident(reader_a, writer_a, irc, "foo")
        await ident(reader_b, writer_b, irc, "bar")

        await send(writer_a, [
            "AWAY :gone fishin"
        ])

        assert await readall(reader_a) == [
            ":localhost 306 foo :You have been marked as being away"
        ]

        nickname = irc.get_nickname("foo")
        assert nickname.is_away
        assert nickname.away_message == "gone fishin"

        await send(writer_b, [
            "PRIVMSG foo :hello"
        ])

        assert await readall(reader_b) == [
            ":foo!foo@localhost 301 bar foo :gone fishin"
        ]

        await send(writer_a, [
            "AWAY"
        ])

        assert await readall(reader_a) == [
            ":localhost 305 foo :You are no longer marked as being away"
        ]


@pytest.mark.asyncio
async def test_server():
    async with server_conn() as (irc, reader, writer):
        assert len(irc.links) == 0
        await send(writer, [
            "SERVER foo 0 abcdef hello"
        ])
        await readall(reader)

        assert len(irc.links) == 1


@pytest.mark.asyncio
async def test_capabilities():
    async with server_conn() as (irc, reader, writer):

        await send(writer, [
            "CAP BLAH",
        ])

        resp = await readall(reader)
        print(resp)
        assert resp == [
            ':localhost 410 * BLAH :Invalid capability command'
        ]

        await send(writer, [
            "CAP LS",
            "CAP REQ :foo bar baz",
        ])

        resp = await readall(reader)
        print(resp)
        assert resp == [
            ':localhost CAP * LS :message-tags server-time message-ids sasl',
            ':localhost CAP * NAK :foo bar baz',
        ]
        await ident(reader, writer, irc, "foo")
        client = irc.lookup_client("foo")
        assert client.capabilities == []

    async with server_conn() as (irc, reader, writer):
        with mock.patch("ircd.irc.IRC.get_capabilities") as caps_patch:
            caps_patch.return_value = ["foo"]

            await send(writer, [
                "CAP LS",
                "CAP REQ :foo",
            ])

            resp = await readall(reader)
            print(resp)
            assert resp == [
                ':localhost CAP * LS :foo',
                ':localhost CAP * ACK :foo',
            ]

        await ident(reader, writer, irc, "foo")
        client = irc.lookup_client("foo")
        assert client.capabilities == ["foo"]


@pytest.mark.asyncio
async def test_message_tags():
    async with server_conn() as (irc, reader, writer):

        # no tags cap
        await ident(reader, writer, irc, "foo")
        await send(writer, [
            "@aaa=bbb;ccc;example.com/ddd=eee PRIVMSG foo :Hello",
        ])
        resp = await readall(reader)
        assert resp == [
            ':foo!foo@localhost PRIVMSG foo :Hello'
        ]

        # enable tags cap
        await send(writer, [
            "CAP REQ :message-tags",
        ])
        resp = await readall(reader)
        assert resp == [
            ':localhost CAP foo ACK :message-tags'
        ]

        await send(writer, [
            "@aaa=bbb;ccc;+example.com/ddd=eee PRIVMSG foo :Hello",
        ])
        resp = await readall(reader)
        assert resp == [
            '@+example.com/ddd=eee :foo!foo@localhost PRIVMSG foo :Hello'
        ]


@pytest.mark.asyncio
async def test_server_time():

    time = datetime.datetime(2019, 12, 27, 1, 2, 3)

    async with server_conn() as (irc, reader, writer):
        await ident(reader, writer, irc, "foo")
        with mock.patch("ircd.message.utcnow") as time_patch:
            time_patch.return_value = time

            # enable tags cap
            await send(writer, [
                "CAP REQ :message-tags server-time",
            ])
            resp = await readall(reader)
            assert resp == [
                '@time=2019-12-27T01:02:03Z :localhost CAP foo ACK :message-tags server-time'
            ]
            await send(writer, [
                "@aaa=bbb;ccc;+example.com/ddd=eee  PRIVMSG foo :Hello",
            ])
            resp = await readall(reader)
            assert resp == [
                '@+example.com/ddd=eee;time=2019-12-27T01:02:03Z :foo!foo@localhost PRIVMSG foo :Hello'
            ]


@pytest.mark.asyncio
async def test_tagmsg_channel():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):
        await ident(reader_a, writer_a, irc, "foo")
        await join(reader_a, writer_a, irc, "foo", "#")
        await send(writer_a, [
            "CAP REQ :message-tags",
        ])
        resp = await readall(reader_a)
        assert resp == [
            ':localhost CAP foo ACK :message-tags'
        ]

        await ident(reader_b, writer_b, irc, "bar")
        await join(reader_b, writer_b, irc, "bar", "#")
        await send(writer_b, [
            "CAP REQ :message-tags",
        ])
        resp = await readall(reader_b)
        assert resp == [
            ':localhost CAP bar ACK :message-tags'
        ]

        await send(writer_a, [
            "@+example.com/ddd=eee TAGMSG #"
        ])

        resp = await readall(reader_b)
        assert resp == [
            "@+example.com/ddd=eee :foo!foo@localhost TAGMSG :#"
        ]


@pytest.mark.asyncio
async def test_tagmsg_client():
    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):
        await ident(reader_a, writer_a, irc, "foo")
        await send(writer_a, [
            "CAP REQ :message-tags",
        ])
        resp = await readall(reader_a)
        assert resp == [
            ':localhost CAP foo ACK :message-tags'
        ]

        await ident(reader_b, writer_b, irc, "bar")

        await send(writer_a, [
            "@+example.com/ddd=eee TAGMSG bar"
        ])
        # no tagmsg
        resp = await readall(reader_b)
        assert resp == []

        await send(writer_b, [
            "CAP REQ :message-tags",
        ])
        resp = await readall(reader_b)
        assert resp == [
            ':localhost CAP bar ACK :message-tags'
        ]

        await send(writer_a, [
            "@+example.com/ddd=eee TAGMSG bar"
        ])

        resp = await readall(reader_b)
        assert resp == [
            "@+example.com/ddd=eee :foo!foo@localhost TAGMSG :bar"
        ]


@pytest.mark.asyncio
async def test_message_ids():
    async with server_conn() as (irc, reader, writer):
        await ident(reader, writer, irc, "foo")
        with mock.patch("ircd.message.generate_id") as id_patch:
            id_patch.return_value = "XXX"

            await send(writer, [
                "CAP REQ :message-tags message-ids",
            ])
            resp = await readall(reader)
            print(resp)
            assert resp == [
                '@msgid=XXX :localhost CAP foo ACK :message-tags message-ids'
            ]


@pytest.mark.asyncio
async def test_sasl():
    password = base64.b64encode(b"foo \x00 bar \x00 baz ")
    bad_pass = base64.b64encode(b"qux \x00 qux \x00 qux ")

    async with server_conn() as (irc, reader_a, writer_a), connect() as (reader_b, writer_b):

        await send(writer_a, [
            "CAP REQ :sasl",
        ])
        resp = await readall(reader_a)
        print(resp)
        assert resp == [
            ':localhost CAP * ACK :sasl'
        ]

        await send(writer_a, [
            "AUTHENTICATE PLAIN",
        ])
        resp = await readall(reader_a)
        print(resp)
        assert resp == [
            ':localhost AUTHENTICATE +'
        ]

        # bad auth
        await send(writer_a, [
            "AUTHENTICATE xxx"
        ])
        resp = await readall(reader_a)
        print(resp)
        assert resp == [
            ':localhost 904 * :SASL authentication failed',
        ]

        # good auth
        await send(writer_a, [
            "AUTHENTICATE " + password.decode("utf-8"),
        ])
        resp = await readall(reader_a)
        print(resp)
        assert resp == [
            ':localhost 900 * :you are now logged in',
            ':localhost 903 * :SASL authentication successful'
        ]

        await send(writer_b, [
            "CAP REQ :sasl",
        ])
        resp = await readall(reader_b)
        print(resp)
        assert resp == [
            ':localhost CAP * ACK :sasl'
        ]

        await send(writer_b, [
            "AUTHENTICATE PLAIN",
        ])
        resp = await readall(reader_b)
        print(resp)
        assert resp == [
            ':localhost AUTHENTICATE +'
        ]

        # bad auth
        await send(writer_b, [
            "AUTHENTICATE " + bad_pass.decode(),
        ])
        resp = await readall(reader_b)
        print(resp)
        assert resp == [
            ':localhost 904 * :SASL authentication failed',
        ]
