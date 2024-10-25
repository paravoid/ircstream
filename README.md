# IRCStream

![build](https://github.com/paravoid/ircstream/workflows/build/badge.svg)

**IRCStream** is a simple gateway to the [MediaWiki](https://www.mediawiki.org/) recent changes feed, from the IRC
protocol. It was written mainly for compatibility reasons, as there are a number of legacy clients in the wild relying
on this interface.

It presents itself as an IRC server with a restricted command set. Sending messages to channels or other
clients is not allowed. Each client is within a private namespace, unable to view messages and interact with other
connected clients, create channels, or speak on them.

Other clients are not visible on channel lists, /who etc. The sole exception is a (fake) bot user, that emits the recent
changes feed, and which is also embedded in the server (i.e. it's not a real client).

It is **not recommended** to use this gateway in new projects. Instead, Wikimedia's [EventStreams
service](https://wikitech.wikimedia.org/wiki/EventStreams) can be used, which streams recent changes in JSON using a
well defined schema and over the SSE protocol.

# Usage

The software requires a configuration file, `ircstream.conf`. An example file is provided with this distribution and
should be self-explanatory.

The server has been designed to be as cloud-native as an IRC server can be. It exposes metrics over the
[Prometheus](https://prometheus.io/) protocol, logs to `stdout`, and can optionally log in JSON as well, using a
structured format to allow easy ingestion into modern log pipelines.

It currently requires messages to be broadcast over UDP to a specified port using the so-called `RC2UDP` protocol: each
UDP message is expected to be a channel name, followed by a tab character, followed by the message to be sent to all
clients.

Future versions will support ingesting over the EventStream service using SSE.

# History

The idea for this project was originally conceived in November 2016 internally at the Wikimedia Foundation, as a
response to ongoing difficulties with the deprecation of the `irc.wikimedia.org` gateway. It was developed on and off
for a few years, and saw its first release in May 2020, as part of a renewed effort to [migrate the internal
architecture to EventStreams' backend](https://phabricator.wikimedia.org/T234234).

As of October 2024, `ircstream` is the software powering the `irc.wikimedia.org` service.

# Requirements

Python 3.11+, plus the following modules from PyPI or your distribution:

* `prometheus_client`
* `structlog`

You can use `pip install .` to install the package into the standard location of your system, which will install
an executable in a standard binary location, such as /usr/bin or /bin. Alternatively, provided the necessary libraries
above have already been installed, one can execute `python3 -m ircstream` to run directly from the cloned source tree.

# Copyright and license

Copyright © Faidon Liambotis  
Copyright © Wikimedia Foundation, Inc.

This software is licensed under the Apache License, Version 2.0. See the LICENSE file for the full license text.
