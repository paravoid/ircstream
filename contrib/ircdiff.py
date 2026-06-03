#!/usr/bin/env python3

"""MediaWiki RecentChanges IRC server differ."""

# SPDX-FileCopyrightText: Faidon Liambotis
# SPDX-License-Identifier: Apache-2.0
#
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "irc",
# ]
# ///

from __future__ import annotations

import argparse
import logging
import threading
import time
from collections.abc import Sequence
from typing import Any, Literal

import irc.client
import irc.connection

messages: tuple[dict[str, float], dict[str, float]] = ({}, {})
message_count = [0, 0]
timedout_message_count = [0, 0]
online = [False, False]
lock = threading.Lock()
shutdown = threading.Event()

# ruff: noqa: D101 D102  # docstrings

logger = logging.getLogger()


class IRCClient(irc.client.SimpleIRCClient):  # type: ignore[misc]
    def __init__(self, channel: str, side: Literal[0, 1]):
        irc.client.SimpleIRCClient.__init__(self)
        self.channel = channel
        self.this_side = side

    @property
    def other_side(self) -> Literal[0, 1]:
        return 1 if self.this_side == 0 else 0

    def on_welcome(self, connection: irc.client.ServerConnection, _: irc.client.Event) -> None:
        connection.join(self.channel)

    def on_pubmsg(self, _: irc.client.ServerConnection, event: irc.client.Event) -> None:
        if not event.source.startswith("rc-pmtpa"):
            return
        message = event.arguments[0]

        if not online[self.this_side]:
            logger.info(f"Server {self.this_side} is online")

        online[self.this_side] = True
        if not online[self.other_side]:
            return

        with lock:
            message_count[self.this_side] += 1
            try:
                del messages[self.other_side][message]
            except KeyError:
                messages[self.this_side][message] = time.time()

    def on_disconnect(self, _: irc.client.ServerConnection, event: irc.client.Event) -> None:
        logger.critical(f"Server {self.this_side} disconnected {event.arguments}")
        shutdown.set()


class IRCThread(threading.Thread):
    daemon_threads = True

    def __init__(self, server: str, channel: str, side: Literal[0, 1], *args: Any, **kwargs: Any):
        self.server = server
        self.port = 6667
        self.nickname = "ircstream-diff-bot"
        self.channel = channel
        self.client = IRCClient(self.channel, side)
        super().__init__(*args, **kwargs)

    def run(self) -> None:
        try:
            self.client.connect(self.server, self.port, self.nickname)
        except irc.client.ServerConnectionError as exc:
            logger.critical(f"Error connecting to {self.server}:", exc)
            shutdown.set()
        self.client.start()


class IRCReporter(threading.Thread):
    daemon_threads = True

    def gc(self) -> None:
        for idx in (0, 1):
            with lock:
                for msg, timestamp in list(messages[idx].items()):
                    if time.time() - timestamp > 5:
                        del messages[idx][msg]
                        timedout_message_count[idx] += 1
                        logger.warning(f"Dropping[{idx}]: {msg}")

    def run(self) -> None:
        while True:
            self.gc()
            output = [
                f"{len(messages[0])}/{len(messages[1])} queued",
                f"{timedout_message_count[0]}/{timedout_message_count[1]} timed-out",
                f"{message_count[0]}/{message_count[1]} processed",
            ]
            logger.info("; ".join(output))

            # sleep(1), but with the ability to be interrupted by a shutdown signal
            if shutdown.wait(1):
                break


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse and return the parsed command line arguments."""
    parser = argparse.ArgumentParser(
        prog="ircdiff",
        description="MediaWiki RecentChanges IRC server differ",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--server-0", type=str, default="localhost", help="Hostname for server 0")
    parser.add_argument("--server-1", type=str, default="irc.wikimedia.org", help="Hostname for server 1")
    parser.add_argument("--channel", "-c", type=str, default="#en.wikipedia", help="Channel to join")

    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> None:
    """Entry point."""
    options = parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    logger.info(f"Server 0: {options.server_0}, Server 1: {options.server_1}, Channel: {options.channel}")
    try:
        c0 = IRCThread(server=options.server_0, channel=options.channel, side=0, daemon=True)
        c0.start()
        c1 = IRCThread(server=options.server_1, channel=options.channel, side=1, daemon=True)
        c1.start()
        reporter = IRCReporter()
        reporter.start()

        # sleep indefinitely, until one of the thread errors-out
        while not shutdown.wait():
            pass
    except KeyboardInterrupt:
        pass
    finally:
        shutdown.set()
        reporter.join()


if __name__ == "__main__":
    run()
