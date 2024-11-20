"""Tests for the RC2UDP protocol server."""

from __future__ import annotations

import asyncio
import configparser

import prometheus_client
import pytest

from ircstream.rc2udp import RC2UDPServer

pytestmark = pytest.mark.asyncio(loop_scope="module")


class MockIRCServer:
    """Mocks the IRCServer object.

    Provide only a few functions that the RC2UDPServer expects.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()  # set when a broadcast event has been sent
        self.data: list[tuple[str, str]] = []  # accumulates parsed broadcast messages received
        self.metrics = {  # emulates the prometheus interface
            "errors": prometheus_client.Counter("mock_errors", "Count of mocked errors", ["type"]),
        }

    async def broadcast(self, target: str, msg: str) -> None:
        """Mock IRCServer's broadcast method."""
        self.data.append((target, msg))
        self._event.set()

    async def wait(self, timeout: float = 0.2) -> bool:
        """Wait until the event triggers."""
        try:
            await asyncio.wait_for(self._event.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        else:
            return True

    def clear(self) -> None:
        """Clear accumulated messages and the associated event."""
        self.data.clear()
        self._event.clear()


@pytest.fixture(name="mock_ircserver", scope="module")
def fixture_mock_ircserver() -> MockIRCServer:
    """Fixture for an instance of MockIRCServer."""
    return MockIRCServer()


@pytest.fixture(name="rc2udp_server", scope="module")
async def fixture_rc2udp_server(config: configparser.ConfigParser, mock_ircserver: MockIRCServer) -> RC2UDPServer:
    """Fixture for an instance of an RC2UDPServer."""
    rc2udpserver = RC2UDPServer(config["rc2udp"], mock_ircserver)  # type: ignore
    await rc2udpserver.serve()
    return rc2udpserver


async def send_datagram(address: str, port: int, data: bytes) -> None:
    """Small helper to send UDP datagrams."""

    class DummyProtocol(asyncio.DatagramProtocol):
        """Simple datagram protocol that just sends the given data."""

        def __init__(self, data: bytes) -> None:
            self.data = data

        def connection_made(self, transport: asyncio.transports.DatagramTransport) -> None:  # type: ignore[override]
            transport.sendto(self.data)

    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(lambda: DummyProtocol(data), remote_addr=(address, port))


@pytest.mark.parametrize("message", ["my message", "#lookslikeachannel", "onetab\tsecond tab"])
async def test_rc2udp_valid(mock_ircserver: MockIRCServer, rc2udp_server: RC2UDPServer, message: str) -> None:
    """Test that valid RC2UDP messages are received and parsed correctly."""
    mock_ircserver.clear()
    data = ("#channel", message)
    rawdata = "\t".join(data).encode()
    await send_datagram(rc2udp_server.address, rc2udp_server.port, rawdata)
    assert await mock_ircserver.wait()
    assert mock_ircserver.data == [data]


@pytest.mark.parametrize("data", [b"#nomessage", b"#channel\tinvalid utf8\x80"])
async def test_rc2udp_invalid(mock_ircserver: MockIRCServer, rc2udp_server: RC2UDPServer, data: bytes) -> None:
    """Test that invalid RC2UDP are dropped gracefully."""
    mock_ircserver.clear()
    await send_datagram(rc2udp_server.address, rc2udp_server.port, data)
    assert not await mock_ircserver.wait()
    assert len(mock_ircserver.data) == 0
