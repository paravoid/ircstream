"""RC2UDP component.

Responsible for spawning a server that listens on a UDP socket for messages
formatted using the RC2UDP protocol, as used by MediaWiki. The messages that
are received are broadcasted to the ircserver.IRCServer instance, which in turn
sends them to connected/subscribed clients.
"""

# SPDX-FileCopyrightText: Faidon Liambotis
# SPDX-FileCopyrightText: Wikimedia Foundation
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    import configparser

    from .ircserver import IRCServer

logger = structlog.get_logger()


class RC2UDPHandler(asyncio.Protocol):
    """A handler implementing the RC2UDP protocol, as used by MediaWiki."""

    def __init__(self, server: RC2UDPServer) -> None:
        self.server = server
        self.running_tasks: set[asyncio.Task[Any]] = set()
        self.log = logger.bind()

    def datagram_received(self, data: bytes, _: tuple[str, int]) -> None:
        """Receive a new RC2UDP message and broadcast to all clients."""
        try:
            decoded = data.decode("utf8")
            channel, text = decoded.split("\t", maxsplit=1)
            channel = channel.strip()
            text = text.lstrip().replace("\r", "").replace("\n", "")
        except Exception:
            self.server.ircserver.metrics["errors"].labels("rc2udp-parsing").inc()
            return

        self.log.debug("Broadcasting message", channel=channel, message=text)
        task = asyncio.create_task(self.server.ircserver.broadcast(channel, text))
        self.running_tasks.add(task)
        task.add_done_callback(self.running_tasks.discard)


class RC2UDPServer:
    """A server implementing the RC2UDP protocol, as used by MediaWiki."""

    def __init__(self, config: configparser.SectionProxy, ircserver: IRCServer) -> None:
        self.ircserver = ircserver
        self.address = config.get("listen_address", fallback="::")
        self.port = config.getint("listen_port", fallback=9390)
        self.log = logger.bind()

    async def serve(self) -> None:
        """Create a new socket, listen to it and serve requests."""
        loop = asyncio.get_running_loop()
        local_addr = (self.address, self.port)
        transport, _ = await loop.create_datagram_endpoint(lambda: RC2UDPHandler(self), local_addr=local_addr)
        local_addr = transport.get_extra_info("sockname")[:2]
        self.address, self.port = local_addr  # update address/port based on what bind() returned
        self.log.info("Listening for RC2UDP broadcast", listen_address=self.address, listen_port=self.port)
