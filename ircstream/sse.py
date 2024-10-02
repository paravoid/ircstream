"""SSE component.

Responsible for spawning our custom HTTP SSE client, that connects to the
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
from typing import TYPE_CHECKING, Any

import aiohttp
import structlog

from . import sse_client
from .rcfmt import RecentChangeIRCFormatter

if TYPE_CHECKING:
    import configparser

    from .ircserver import IRCServer

logger = structlog.get_logger()


class SSEBroadcaster:
    """Broadcaster consuming events from SSE and broadcasting them over to IRC."""

    log = structlog.get_logger("ircstream.sse.broadcaster")

    def __init__(self, config: configparser.SectionProxy, ircserver: IRCServer) -> None:
        self.ircserver = ircserver
        self.url = config.get("url", "https://stream.wikimedia.org/v2/stream/recentchange")
        self.log.info("Listening for SSE Events", sse_url=self.url)
        self.last_event_id = ""

    async def run(self) -> None:
        """Entry point, run in a while True loop to make sure we never stop consuming events."""
        while True:
            await self.connect_and_consume()
            await asyncio.sleep(1)

    async def connect_and_consume(self) -> None:
        """Connect and continuously consume events from the event feed.

        Does *not* handle reconnects. Callers are expected to reconnect by
        reinitializing as necessary.
        """
        events = sse_client.EventSource(self.url, last_event_id=self.last_event_id)
        try:
            await events.connect()
            async for event in events:
                try:
                    data = await self.parse_event(event)
                    if not data:
                        continue
                    await self.format_and_emit(data)
                except Exception:
                    self.log.warn("Could not parse event:", rc=event, exc_info=True)
                    continue
        except ConnectionError as exc:
            self.log.warning("SSE client connection error", exc=str(exc))
        except aiohttp.http_exceptions.TransferEncodingError:
            # "Not enough data for satisfy transfer length header."
            self.log.debug("Connection lost")
        except aiohttp.client_exceptions.ClientPayloadError as exc:
            if "TransferEncodingError" in str(exc):
                # <ClientPayloadError: Response payload is not completed: <TransferEncodingError: 400,
                # message='Not enough data for satisfy transfer length header.'>>
                self.log.debug("Connection lost (payload error)")
            else:
                self.log.warning("HTTP client payload error", exc=str(exc))
        except aiohttp.client_exceptions.ClientError as exc:
            # needs to be after more-specific errors, like ClientPayloadError
            self.log.warning("HTTP client error", exc=str(exc))
        except asyncio.TimeoutError:
            # this is raised internally in EventSource via aiohttp.streams
            # (self._response.content -> self.read_func() -> self.readuntil() -> ...)
            #
            # We handle by ignoring the exception, returning, and expecting to reconnect
            self.log.debug("SSE timeout")
        except asyncio.CancelledError:
            # handle cancellations e.g. due to a KeyboardInterrupt. Raise to break the loop.
            raise
        except Exception:
            self.log.warning("Unknown SSE error", exc_info=True)
        finally:
            await events.close()

    async def parse_event(self, event: sse_client.MessageEvent) -> Any | None:
        """Parse a single SSE event."""
        if not event or event.type != "message":
            return None

        log = logger.bind(message=event)
        try:
            data = json.loads(event.data)
        except json.decoder.JSONDecodeError as exc:
            log.warning("Could not parse JSON for message", err=str(exc))
            return None

        # Reconstruct our own version of Last-Connect-Id, from the messages' "meta":
        #    data: { ..., meta: { ..., "topic":"...", "partition":0, "offset": NNNN } }
        # ...as that is offset-based rather than timestamp-based (like the regular id is)
        try:
            meta = data["meta"]
            last_event_id = [{key: meta[key] for key in ("topic", "partition", "offset")}]
        except KeyError:
            log.warn("Could not parse the message metadata")
        else:
            # store this for subsequent connections
            self.last_event_id = json.dumps(last_event_id, separators=(",", ":"))

        return data

    async def format_and_emit(self, data: Any) -> None:
        """Format RecentChange with IRC, and broadcast."""
        rc = RecentChangeIRCFormatter(data)
        channel, text = rc.channel, rc.ircstr
        if not channel or not text:
            # e.g. not a message type that is emitted
            return
        self.log.debug("Broadcasting message", channel=channel, message=str(rc))
        await self.ircserver.broadcast(channel, text)
