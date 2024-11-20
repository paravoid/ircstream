"""Test our server implementation for exceptional behavior.

Most IRC clients or libraries don't typically allow the flexibility to send
invalid commands, not respond to PING etc., so emulate the IRC protocol
manually, using a raw socket.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from typing import Any, Callable
from unittest.mock import patch

import pytest

from ircstream.ircserver import IRCClient, IRCServer

pytestmark = pytest.mark.asyncio(loop_scope="module")


class BareClient:
    """Bare client around socket operations to support a line-based protocol."""

    def __init__(self) -> None:
        """Initialize the client."""
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.close: Callable[[], None] = lambda: None
        self.write: Callable[[bytes], None] = lambda x: None
        self.readline: Any = None

    async def connect(self, address: str, port: int) -> None:
        """Connect to the socket."""
        self.reader, self.writer = await asyncio.open_connection(address, port)
        self.close = self.writer.close
        self.write = self.writer.write
        self.readline = self.reader.readline

    async def readlines(self) -> Sequence[bytes]:
        """Read and return all lines in input, until a timeout occurs."""
        output = []
        while True:
            try:
                line = await asyncio.wait_for(self.readline(), 0.1)
                output.append(line)
            except asyncio.TimeoutError:
                break

        return output


@pytest.fixture(name="clientsock")
async def clientsock_fixture(ircserver: IRCServer) -> AsyncGenerator[BareClient, None]:
    """Return an instance of our fake/raw IRC client."""
    client = BareClient()
    await client.connect(ircserver.address, ircserver.port)
    yield client
    client.close()


async def test_premature_close(clientsock: BareClient) -> None:
    """Test the handling of a premature close, right after connecting."""
    clientsock.close()


async def test_ping_timeout(ircserver_short_timeout: IRCServer, clientsock: BareClient) -> None:
    """Test a PING timeout condition."""
    # wait at least until the ping timeout interval
    await asyncio.sleep(ircserver_short_timeout.client_timeout)

    # try another 5 times for a total of another interval
    ping_timedout = False
    for _ in range(5):
        data = await clientsock.readline()
        if not data:
            continue
        elif b"ERROR :Closing Link: (Ping timeout)" in data:
            ping_timedout = True
            break
        else:
            raise AssertionError  # another unexpected message

    assert ping_timedout


async def test_preregister_command(clientsock: BareClient) -> None:
    """Test sending a command that is not valid before registration."""
    clientsock.write(b"WHOIS noone\n")
    data = await clientsock.readlines()
    assert len(data) == 1
    assert b"451 * :You have not registered" in data[0]


async def test_erroneous(clientsock: BareClient) -> None:
    """Test erroneous parameters."""
    clientsock.write(b"USER one two three four\n")

    clientsock.write(b"NICK /invalid\n")
    data = await clientsock.readlines()
    assert any(b"432 *" in response for response in data)

    clientsock.write(b"NICK " + b"a" * 100 + b"\n")
    data = await clientsock.readlines()
    assert any(b"432 *" in response for response in data)

    clientsock.write(b":NOCOMMAND\n")
    data = await clientsock.readlines()
    assert data == []

    clientsock.write(b":" + b"X" * (512 * 4) + b"\n")
    data = await clientsock.readlines()
    assert data == []


async def test_unicodeerror(ircserver: IRCServer, clientsock: BareClient) -> None:
    """Test for UnicodeError handling in both directions."""
    clientsock.write(b"USER one two three four\n")
    clientsock.write(b"NICK nick\n")
    data = await clientsock.readlines()
    assert any(b"001 nick" in response for response in data)

    clientsock.write(b"WHOIS \x80\n")  # 0x80 is invalid unicode
    data = await clientsock.readlines()
    assert data == []

    await ircserver.broadcast("#channel", "create the channel")
    clientsock.write(b"JOIN #channel\n")
    data = await clientsock.readlines()
    assert any(b"JOIN #channel" in response for response in data)

    # this creates a string that will fail .encode("utf8")
    unencodeable_utf8 = "unencodeable " + b"\x80".decode("utf8", "surrogateescape")
    await ircserver.broadcast("#channel", unencodeable_utf8)
    data = await clientsock.readlines()
    assert data == []


async def test_broadcast_failure(clientsock: BareClient, ircserver: IRCServer) -> None:
    """Test that exceptions in the broadcast() method are handled."""
    # login to the client (normal)
    clientsock.write(b"USER one two three four\n")
    clientsock.write(b"NICK nick\n")
    data = await clientsock.readlines()
    assert any(b"001 nick" in response for response in data)

    # create and join a channel (also normal)
    await ircserver.broadcast("#channel", "create the channel")
    clientsock.write(b"JOIN #channel\n")
    data = await clientsock.readlines()
    assert any(b"JOIN #channel" in response for response in data)

    # ...and now actually test
    with patch.object(IRCClient, "send", side_effect=OSError("dummy")):
        await ircserver.broadcast("#channel", "should fail silently")


async def test_redundant(clientsock: BareClient) -> None:
    """Test redundant parameters in commands that allow it."""
    # five arguments for USER
    clientsock.write(b"PASS password\n")
    clientsock.write(b"USER one two three four redundant\n")
    clientsock.write(b"NICK nick\n")
    data = await clientsock.readlines()
    assert any(b"001 nick" in response for response in data)

    clientsock.write(b"PASS password\n")
    data = await clientsock.readlines()
    assert any(b"462 nick :You may not reregister" in response for response in data)

    # two arguments for WHOIS
    clientsock.write(b"WHOIS nick second\n")
    data = await clientsock.readlines()
    assert any(b"401 nick second :No such nick/channel" in response for response in data)


async def test_exception(clientsock: BareClient) -> None:
    """Test whether our injected EXCEPTION handler works."""
    # register
    clientsock.write(b"USER one two three four\n")
    clientsock.write(b"NICK nick\n")
    data = await clientsock.readlines()
    assert any(b"001 nick" in response for response in data)

    # needs registration
    clientsock.write(b"RAISEEXC\n")
    data = await clientsock.readlines()
    assert data
    assert b"Internal server error" in data[-1]
