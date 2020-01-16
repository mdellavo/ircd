# IRCd

a small IRCd in python

## Features
    - basic IRCv3 support
    - asyncio based event loop
    - tests!

## Running

with docker:
```
# Run server
docker build -t mdellavo/ircd .
docker run --rm -i -t  -v $PWD:/home/ircd -p 127.0.0.1:5000:5000 mdellavo/ircd python3.8 -m ircd --listen 0.0.0.0:5000

# Run tests
docker run --rm -i -t  -v $PWD:/home/ircd mdellavo/ircd pytest

# Start up 2 nodes and link them, also startup thelounge to connect
docker-compose up
```

## Supported Commands
- [x] CAP
- [x] AUTHENTICATE (simple only)
- [x] NICK 
- [x] USER
- [x] QUIT
- [x] JOIN
- [x] PART
- [x] TOPIC
- [x] NAMES
- [x] INVITE
- [x] LIST
- [x] AWAY
- [x] MODE
- [x] TAGMSG
- [x] SERVER
- [x] KICK
- [x] NOTICE
- [x] PRIVMSG
- [ ] ISUPPORT
- [ ] LUSERS
- [x] MOTD
- [ ] VERSION
- [ ] ADMIN
- [ ] TIME
- [ ] STATS
- [ ] INFO
- [ ] OPERATOR
- [ ] CONNECT
- [ ] MAP
- [ ] WALLOPS

## Supported Capabilities
- [x] sasl
- [x] message-ids
- [x] message-tags
- [x] server-ime

## References

- https://modern.ircdocs.horse/

## Author

Marc DellaVolpe  (marc.dellavolpe@gmail.com)

## License
    The MIT License (MIT)

    Copyright (c) 2016 Marc DellaVolpe

    Permission is hereby granted, free of charge, to any person obtaining a copy of this
    software and associated documentation files (the "Software"), to deal in the Software
    without restriction, including without limitation the rights to use, copy, modify, merge,
    publish, distribute, sublicense, and/or sell copies of the Software, and to permit
    persons to whom the Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all copies
    or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
    INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
    PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
    FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
    OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
    DEALINGS IN THE SOFTWARE.
