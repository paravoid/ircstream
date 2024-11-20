"""Testing initialization."""

from __future__ import annotations

import asyncio
import configparser
import logging
from collections.abc import AsyncGenerator

import pytest
import structlog

from ircstream.ircserver import IRCClient, IRCServer

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(autouse=True)
def _fixture_configure_structlog() -> None:
    """Fixture to configure structlog. Currently just silences it entirely."""

    def dummy_processor(
        logger: logging.Logger, name: str, event_dict: structlog.typing.EventDict
    ) -> structlog.typing.EventDict:
        raise structlog.DropEvent

    structlog.configure(processors=[dummy_processor])


@pytest.fixture(name="config", scope="module", params=["127.0.0.1", "::1"])
def fixture_config(request: pytest.FixtureRequest) -> configparser.ConfigParser:
    """Fixture representing an example configuration."""
    listen_address = request.param
    config = configparser.ConfigParser()
    config.read_string(
        f"""
        [irc]
        listen_address = {listen_address}
        # pick a random free port (not 6667!)
        listen_port = 0
        servername = irc.example.org
        network = Example
        botname = rc-bot
        topic_tmpl = Test topic for {{channel}}
        welcome_msg =
          *******************************************************
          This is a test IRC instance
          *******************************************************
          Sending messages to channels is not allowed.

        [rc2udp]
        listen_address = {listen_address}
        listen_port = 0

        [prometheus]
        listen_address = {listen_address}
        listen_port = 0
        """
    )
    return config


@pytest.fixture(name="ircserver", scope="module")
async def fixture_ircserver(config: configparser.ConfigParser) -> AsyncGenerator[IRCServer, None]:
    """Fixture for an instance of an IRCServer.

    This spawns a task to run the server. It yields the IRCServer instance,
    *not* the task, however.
    """

    # set up a fake EXCEPTION command handler, that raises an exception
    # useful to test whether exceptions are actually being caught!
    async def handle_raiseexc(self: IRCClient, _: list[str]) -> None:
        raise NotImplementedError("Purposefully triggered exception")

    IRCClient.handle_raiseexc = handle_raiseexc  # type: ignore

    ircserver = IRCServer(config["irc"])
    irc_task = asyncio.create_task(ircserver.serve())
    yield ircserver
    irc_task.cancel()
    try:
        await irc_task
    except asyncio.CancelledError:
        pass


@pytest.fixture(name="ircserver_short_timeout")
async def fixture_ircserver_short_timeout(ircserver: IRCServer) -> AsyncGenerator[IRCServer, None]:
    """Return an IRCServer modified to run with a very short timeout.

    This is a separate fixture to make sure that the default value is restored
    e.g. if the test fails.
    """
    # save the old timeout
    default_timeout = ircserver.client_timeout
    # set timeout to a (much) smaller value, to avoid long waits while testing
    ircserver.client_timeout = 2
    yield ircserver
    # restore it to the default value
    ircserver.client_timeout = default_timeout
