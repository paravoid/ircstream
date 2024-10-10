"""Test as much of the functionality as possible at a high-level."""

from __future__ import annotations

import http.client
import multiprocessing
import multiprocessing.synchronize
import pathlib
import socket
import time
from typing import Any

import irc.client  # type: ignore
import irc.connection  # type: ignore
import pytest

import ircstream

SERVER_IP = "127.0.0.1"
PORTS = {
    "irc": 6667,
    "rc2udp": 9390,
    "prometheus": 9200,
}


class IRCMessageCounter(irc.client.SimpleIRCClient):  # type: ignore
    """Basic IRC Client, used for counting received messages.

    This connects, identifies, joins a channel, and then counts incoming events
    into a multiprocessing Value. It's used for testing, and verifying the
    right number of messages were received.
    """

    def __init__(self, channel: str, received: Any, ready: multiprocessing.synchronize.Event) -> None:
        self.channel = channel
        self.ready = ready
        self.received = received
        super().__init__()

    def connect(self, *args: Any, **kwargs: Any) -> None:
        """Override the method to add transparent IPv6 support."""
        if args and ":" in args[0]:
            kwargs["connect_factory"] = irc.connection.Factory(ipv6=True)
        super().connect(*args, **kwargs)

    def on_welcome(self, connection: irc.connection.Factory, _: irc.client.Event) -> None:
        """Join the channel immediately after identifying."""
        connection.join(self.channel)

    def on_join(self, _: irc.connection.Factory, __: irc.client.Event) -> None:
        """Set the ready event after a channel was joined."""
        self.ready.set()

    def on_pubmsg(self, _: irc.connection.Factory, __: irc.client.Event) -> None:
        """Increase the received counter after a message was received."""
        with self.received.get_lock():
            self.received.value += 1


@pytest.fixture(name="main")
def fixture_main(tmp_path: pathlib.Path) -> multiprocessing.Process:
    """Fixture for ircstream main(), running it in a Process."""
    # test a semi-stock config, with default ports etc.
    tmp_config = tmp_path / "ircstream-integration.conf"
    tmp_config.write_text(
        """
        [irc]
        servername = irc.example.org
        network = Example
        botname = rc-bot
        topic_tmpl = Test topic for {channel}
        welcome_msg =
          *******************************************************
          This is a test IRC instance
          *******************************************************
          Sending messages to channels is not allowed.

        [rc2udp]

        [prometheus]
        """
    )
    args = ("--config", str(tmp_config))

    main = multiprocessing.Process(target=ircstream.run, args=(args,), daemon=True)
    main.start()
    time.sleep(0.1)
    if not main.is_alive():
        pytest.skip("Main thread died, likely cannot bind to default ports; skipping test")
    return main


def prometheus_metric(metric: str) -> float:
    """Fetch a Prometheus metrics from the wire.

    This fetches from Prometheus on every call!
    """
    conn = http.client.HTTPConnection(SERVER_IP, PORTS["prometheus"])
    conn.request("GET", "/metrics")
    response = conn.getresponse()
    assert response.status == 200

    content = response.read().decode().splitlines()
    for line in content:
        if line.startswith("#"):
            continue
        key, value = line.split(" ", maxsplit=1)
        if key == metric:
            return float(value)
    return 0.0


def spawn_client_process(channel: str, counter: Any) -> multiprocessing.Process:
    """Spawn an IRC message counter client into a separate process."""
    ready_to_receive = multiprocessing.Event()

    def spawn_client() -> None:
        ircclient = IRCMessageCounter(channel, counter, ready_to_receive)
        ircclient.connect(SERVER_IP, PORTS["irc"], "rc-bot")
        ircclient.start()

    ircclient_process = multiprocessing.Process(target=spawn_client)
    ircclient_process.start()
    ready_to_receive.wait()
    return ircclient_process


def send_to_rc2udp(channel: str, count: int, message: str = "message") -> None:
    """Send one or multiple messages RC2UDP.

    Runs into a separate process just in case, but waits until the process is
    finished before returning.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rawdata = f"{channel}\t{message}".encode()

    def send_in_process() -> None:
        for _ in range(count):
            sock.sendto(rawdata, (SERVER_IP, PORTS["rc2udp"]))

    proc = multiprocessing.Process(target=send_in_process)
    proc.start()
    proc.join()


@pytest.mark.usefixtures("main")
def test_out_of_the_box() -> None:
    """Tests the out-of-the-box experience of the server.

    Tests the server with multiple clients and multiple messages being passed
    to all of them, verifying that they were received, and with the right
    metrics recorded in Prometheus.
    """
    client_count = 10
    message_count = 50
    received_counter = multiprocessing.Value("h")

    # send one message, to create the channel
    assert prometheus_metric("ircstream_channels") == 0
    send_to_rc2udp("#channel", 1)
    assert prometheus_metric("ircstream_channels") == 1

    # connect a number of different clients
    assert prometheus_metric("ircstream_clients") == 0
    ircclients = []
    for _ in range(client_count):
        ircclient = spawn_client_process("#channel", received_counter)
        ircclients.append(ircclient)
    assert prometheus_metric("ircstream_clients") == float(client_count)
    assert prometheus_metric('ircstream_clients_per_channel{channel="#channel"}') == float(client_count)

    # send a burst of RC2UDP messages and wait a bit to make sure they're processed
    send_to_rc2udp("#channel", message_count)
    time.sleep(message_count * 0.01)  # 10ms per message ought to be enough

    # verify whether they were sent by the server
    messages_total = message_count + 1  # +1 for the channel creation
    assert prometheus_metric("ircstream_messages_total") == float(messages_total)

    # verify whether they were received by the clients
    assert received_counter.value == client_count * message_count

    # check again to verify no new channels were created and no clients were dropped
    assert prometheus_metric("ircstream_clients") == float(client_count)
    assert prometheus_metric('ircstream_clients_per_channel{channel="#channel"}') == float(client_count)
    assert prometheus_metric("ircstream_channels") == 1

    # terminate all the clients (abruptly)
    for ircclient in ircclients:
        ircclient.terminate()
    time.sleep(0.1)

    # verify a) client count dropped to zero b) the channel did not disappear
    assert prometheus_metric("ircstream_clients") == 0
    assert prometheus_metric('ircstream_clients_per_channel{channel="#channel"}') == 0
    assert prometheus_metric("ircstream_channels") == 1
