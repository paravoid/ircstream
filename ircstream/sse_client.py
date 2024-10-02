"""SSE Client component.

A custom HTTP SSE client implementation based on aiohttp. Implements minimal
exception handling, expecting the underlying client to handle most of it and
respawn the client on errors.
"""

# SPDX-FileCopyrightText: Faidon Liambotis
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import collections.abc
import copy
import dataclasses
from typing import Any

import aiohttp
import multidict
import structlog

logger = structlog.get_logger()


@dataclasses.dataclass(slots=True)
class MessageEvent:
    """Represent DOM MessageEvent Interface.

    https://www.w3.org/TR/eventsource/#dispatchMessage section 4
    https://developer.mozilla.org/en-US/docs/Web/API/MessageEvent
    """

    type: str | None
    data: str
    origin: str | None
    id: str


class EventSource(collections.abc.AsyncIterator[MessageEvent]):
    """Represent EventSource interface as an async iterator.

    Loosely based on aiohttp-sse-client v0.2.1, by Jason Hu, licensed
    under the Apache-2.0 license.
    """

    def __init__(self, url: str, last_event_id: str = "", **kwargs: Any) -> None:
        """Construct EventSource instance."""
        self._url = url
        self.last_event_id = last_event_id

        self._session = aiohttp.ClientSession()
        self._response: aiohttp.ClientResponse | None = None
        self._kwargs = kwargs
        if "headers" not in self._kwargs:
            self._kwargs["headers"] = multidict.MultiDict()

        self._event = MessageEvent(
            type="",
            data="",
            origin=None,
            id=self.last_event_id,
        )

    async def connect(self) -> None:
        """Connect to stream."""
        headers = self._kwargs["headers"]
        headers[aiohttp.hdrs.ACCEPT] = "text/event-stream"
        headers[aiohttp.hdrs.CACHE_CONTROL] = "no-cache"
        if self.last_event_id != "":
            headers["Last-Event-Id"] = self.last_event_id

        logger.debug("Connecting to stream", url=self._url, last_event_id=self.last_event_id)
        response = await self._session.request("GET", self._url, **self._kwargs)

        if response.status >= 400 or response.status == 305:
            error_message = f"Fetch {self._url} failed: {response.status}"
            if response.status in [305, 401, 407]:
                raise ConnectionRefusedError(error_message)
            raise ConnectionError(error_message)

        if response.status != 200:
            error_message = f"Fetch {self._url} failed with wrong response status: {response.status}"
            raise ConnectionAbortedError(error_message)

        if response.content_type != "text/event-stream":
            content_type = response.headers.get(aiohttp.hdrs.CONTENT_TYPE)
            error_message = f"Fetch {self._url} failed with wrong Content-Type: {content_type}"
            raise ConnectionAbortedError(error_message)

        # only status == 200 and content_type == 'text/event-stream'
        self._response = response
        self._event.origin = str(response.real_url.origin())

    async def close(self) -> None:
        """Close connection."""
        logger.debug("Closing connection")
        if self._response is not None:
            self._response.close()
            self._response = None
        await self._session.close()

    def __aiter__(self) -> EventSource:
        """Return self, an async iterator."""
        return self

    async def __anext__(self) -> MessageEvent:
        """Emit MessageEvents one by one."""
        if not self._response:
            raise ValueError

        while self._response.status != 204:
            async for line_in_bytes in self._response.content:
                line = line_in_bytes.decode("utf8")
                line = line.rstrip("\n").rstrip("\r")

                if line == "":
                    # empty line, end of event
                    event = await self._dispatch_event()
                    if event is not None:
                        return event
                elif line[0] == ":":
                    # comment line, ignore
                    pass
                elif ":" in line:
                    # key/value
                    key, value = line.split(":", 1)
                    value = value.lstrip(" ")
                    self._process_field(key, value)
                else:
                    self._process_field(line, "")
        logger.debug("Exiting iterator")
        raise StopAsyncIteration

    async def _dispatch_event(self) -> MessageEvent | None:
        """Dispatch event."""
        if self._event.data == "":
            self._event.type = ""
            return None

        self._event.data = self._event.data.rstrip("\n")

        event = copy.copy(self._event)
        self.last_event_id = self._event.id

        # reset event
        self._event.type = ""
        self._event.data = ""

        return event

    def _process_field(self, field_name: str, field_value: str) -> None:
        """Process field."""
        if field_name == "event":
            self._event.type = field_value
        elif field_name == "data":
            self._event.data += field_value
            self._event.data += "\n"
        elif field_name == "id" and field_value not in ("\u0000", "\x00\x00"):
            self._event.id = field_value
        elif field_name == "retry":
            # currently ignored
            pass
