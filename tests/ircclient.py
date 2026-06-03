"""Basic IRC Client implementation, used for testing."""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import irc.client
import irc.client_aio
import irc.connection


class IRCClientAio(irc.client_aio.AioSimpleIRCClient):  # type: ignore[misc]
    """Basic IRC Client, used for testing.

    The IRC implementation is third-party, but as far as this client goes,
    it's pretty dummy: it just shoves incoming events into a queue, and
    provides a method to consume from the queue.
    """

    def __init__(self) -> None:
        super().__init__()
        self.events: asyncio.Queue[irc.client.Event] = asyncio.Queue()

    async def connect_async(self, *args: Any, **kwargs: Any) -> None:
        """Override the method as the original runs a new loop."""
        if args and ":" in args[0]:  # is IPv6 (heuristic)
            kwargs["connect_factory"] = irc.connection.AioFactory(family=socket.AF_INET6)
        await self.connection.connect(*args, **kwargs)

    def _dispatcher(self, _: irc.connection.Factory, event: irc.client.Event) -> None:
        """Handle callbacks for all events.

        Just shoves incoming events into a simple queue.
        """
        self.events.put_nowait(event)

    async def expect(self, typ: str, timeout: float = 2, **kwargs: str | list[str]) -> irc.client.Event | None:
        """Groks events until the expect one is found.

        If the matching event is not found within a timeout, returns None.
        otherwise, the matching event.
        """
        found = None
        while True:  # grok events until the queue is empty
            try:
                # break if no messages have been received for a given timeout
                event = await asyncio.wait_for(self.events.get(), timeout)
            except TimeoutError:
                break

            # match the given type + other criteria (source, target, arguments)
            matched = event.type == typ
            for name, value in kwargs.items():
                matched &= getattr(event, name) == value

            if matched:
                found = event
                break
        return found
