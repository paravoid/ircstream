"""SSE component.

Responsible for spawning an aiohttp client, that connects to the
stream.wikimedia.org SSE server, parse the JSON messages, and formats them
according to the RecentChanges-to-IRC formatter.

The messages are subsequently broadcasted to the ircserver.IRCServer instance,
which in turn sends them to connected/subscribed clients.
"""

# SPDX-FileCopyrightText: Faidon Liambotis
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING

import aiohttp
import aiohttp_sse_client.client  # type: ignore
import attr
import structlog

from .rcfmt import RecentChangeIRCFormatter

if TYPE_CHECKING:
    import configparser

    from .ircserver import IRCServer

logger = structlog.get_logger()


class RecentChangeSource(aiohttp_sse_client.client.EventSource):  # type: ignore
    """API to the Wikimedia RecentChange stream.

    This inherits the default EventSource and overloads it.
    """

    log = structlog.get_logger("ircstream.sse.source")

    # store a last_event_id across all instances of RecentChangeSource
    static_last_event_id = ""

    async def connect(self, retry: int = 0) -> None:
        """Overload connect, to provide more immediate reconnects."""
        # restore last_event_id from the class variable, common across all instances
        self._last_event_id = type(self).static_last_event_id
        # replace exponential backoff with a fixed reconnection time
        self._reconnection_time = timedelta(seconds=0.5)
        # Always retry, i.e. never run out of retries
        await super().connect(1)

    def _dispatch_event(self) -> aiohttp_sse_client.client.MessageEvent | None:
        """Parse the event with appropriate error handling, and dispatch it.

        This is overloaded to:
          * Skip non-message events, that we're not interested in
          * Decode the JSON transparently, and provide a Pythonic API
          * Update last_event_id to be the content of
              data: { ..., meta: { ..., "topic":"...", "partition":0, "offset": NNNN } }
            as that is offset-based rather than timestamp-based (like the main id is)
        """
        message: aiohttp_sse_client.client.MessageEvent = super()._dispatch_event()
        if not message or message.type != "message":
            return None

        log = self.log.bind(message=message)
        try:
            # replace message.data from a str, to its JSON-decoded version (usually a dict)
            # do so here rather than in the consumer, as we need to parse the JSON for metadata extraction anyway
            # and it'd be quite inefficient and error prone to have to parse the json twice
            data = json.loads(message.data)
            message = attr.evolve(message, data=data)
        except json.decoder.JSONDecodeError as exc:
            log.warn("Could not parse JSON for message", err=str(exc))
            return None
        except Exception as exc:
            log.warn("Unknown error while parsing", err=str(exc))
            return None

        try:
            meta = message.data["meta"]
            last_event_id = [{key: meta[key] for key in ("topic", "partition", "offset")}]
        except KeyError:
            log.warn("Could not parse the message metadata")
        else:
            self._last_event_id = json.dumps(last_event_id, separators=(",", ":"))
            type(self).static_last_event_id = self._last_event_id

        return message


class SSEBroadcaster:
    """Broadcaster consuming events from SSE and broadcasting them over to IRC."""

    log = structlog.get_logger("ircstream.sse.broadcaster")

    def __init__(self, config: configparser.SectionProxy, ircserver: IRCServer) -> None:
        self.ircserver = ircserver
        self.url = config.get("url", "https://stream.wikimedia.org/v2/stream/recentchange")
        self.log.info("Listening for SSE Events", sse_url=self.url)

    async def run(self) -> None:
        """Entry point, run in a while True loop to make sure we never stop consuming events."""
        while True:
            await self.loop()

    async def loop(self) -> None:
        """Connect and continuously consume events from the event feed."""
        try:
            async with RecentChangeSource(self.url) as events:
                async for event in events:
                    try:
                        await self.parse_event(event)
                    except Exception:
                        self.log.warn("Could not parse event:", rc=event, exc_info=True)
                        continue
        except aiohttp.client_exceptions.ClientError as exc:
            self.log.critical("SSE client connection error", exc=str(exc))
        except aiohttp.http_exceptions.TransferEncodingError:
            # "Not enough data for satisfy transfer length header."
            self.log.debug("SSE in-flight disconnect, reconnecting")
        except asyncio.TimeoutError:
            # this is raised internally in RecentChangeSource's __anext__ through a
            # aiohttp_sse_client.client -> aiohttp.streams chain
            # (self._response.content -> self.read_func() -> self.readuntil() -> ...)
            #
            # We handle by ignoring the exception, returning, and expecting to reconnect
            self.log.debug("SSE timeout, reconnecting")
        except asyncio.CancelledError:
            # handle cancellations e.g. due to a KeyboardInterrupt. Raise to break the loop.
            raise
        except Exception:
            self.log.critical("Unknown SSE error", exc_info=True)
            # ignore the error, so that the loop restarts

    async def parse_event(self, event: aiohttp_sse_client.client.MessageEvent) -> None:
        """Parse a single SSE event."""
        rc = RecentChangeIRCFormatter(event.data)
        channel, text = rc.channel, rc.ircstr
        if not channel or not text:
            # e.g. not a message type that is emitted
            return
        self.log.debug("Broadcasting message", channel=channel, message=str(rc))
        await self.ircserver.broadcast(channel, text)
