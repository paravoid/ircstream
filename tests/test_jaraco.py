"""Test an instance of our IRCServer, using a Python IRC client."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import pytest

from .ircclient import IRCClientAio

if TYPE_CHECKING:
    from ircstream.ircserver import IRCServer

BOTNAME = "testsuite-bot"

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(name="ircclient")
async def ircclient_instance(ircserver: IRCServer) -> AsyncGenerator[IRCClientAio, None]:
    """Fixture for an instance of an IRCClient."""
    ircclient = IRCClientAio()
    await ircclient.connect_async(ircserver.address, ircserver.port, BOTNAME)

    yield ircclient

    ircclient.connection.quit()
    assert await ircclient.expect("error")


@pytest.mark.usefixtures("ircserver")
async def test_ping(ircclient: IRCClientAio) -> None:
    """Test the PING command."""
    ircclient.connection.ping("there")
    assert await ircclient.expect("pong", arguments=["there"])
    ircclient.connection.ping("")
    assert await ircclient.expect("noorigin")


@pytest.mark.usefixtures("ircserver")
async def test_pong(ircserver_short_timeout: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the PONG command (a server-side ping)."""
    wait_for = (ircserver_short_timeout.client_timeout / 2) + 1
    assert await ircclient.expect("ping", timeout=wait_for)


@pytest.mark.usefixtures("ircserver")
async def test_who(ircclient: IRCClientAio) -> None:
    """Test the WHO command."""
    ircclient.connection.who(BOTNAME)
    assert await ircclient.expect("endofwho")

    ircclient.connection.who()
    assert await ircclient.expect("endofwho")


@pytest.mark.usefixtures("ircserver")
async def test_mode(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the MODE command."""
    # channel modes
    ircclient.connection.mode("", "")
    assert await ircclient.expect("needmoreparams")

    ircclient.connection.mode("#one-channel", "")
    assert await ircclient.expect("channelmodeis")

    ircclient.connection.mode("#one-channel", "b")
    assert await ircclient.expect("endofbanlist")

    ircclient.connection.mode("#one-channel", "o")
    assert await ircclient.expect("chanoprivsneeded")

    # user modes
    ircclient.connection.mode(BOTNAME, "")
    assert await ircclient.expect("umodeis")

    ircclient.connection.mode(BOTNAME, "+r")
    # (no response expected)

    ircclient.connection.mode(ircserver.botname, "")
    assert await ircclient.expect("usersdontmatch")

    ircclient.connection.mode("nonexistent", "")
    assert await ircclient.expect("nosuchnick")


@pytest.mark.usefixtures("ircserver")
async def test_whois(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the WHOIS command."""
    ircclient.connection.whois([ircserver.botname])
    assert await ircclient.expect("whoisuser")
    assert await ircclient.expect("whoisserver")
    assert await ircclient.expect("whoisidle")

    ircclient.connection.whois([BOTNAME])
    assert await ircclient.expect("whoisuser")
    assert await ircclient.expect("whoisserver")
    assert await ircclient.expect("whoisidle")

    ircclient.connection.whois(["nonexistent"])
    assert await ircclient.expect("nosuchnick")

    ircclient.connection.whois("")
    assert await ircclient.expect("nonicknamegiven")


@pytest.mark.usefixtures("ircserver")
async def test_whowas(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the WHOWAS command."""
    ircclient.connection.whowas(ircserver.botname)
    assert await ircclient.expect("wasnosuchnick")
    assert await ircclient.expect("endofwhowas")

    ircclient.connection.whowas(BOTNAME)
    assert await ircclient.expect("wasnosuchnick")
    assert await ircclient.expect("endofwhowas")

    ircclient.connection.whowas("")
    assert await ircclient.expect("nonicknamegiven")


@pytest.mark.usefixtures("ircserver")
async def test_userhost(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the USERHOST command."""
    ircclient.connection.userhost([])
    assert await ircclient.expect("needmoreparams")

    ircclient.connection.userhost(["nonexistent"])
    assert await ircclient.expect("userhost", arguments=[""])

    bot_userhost = f"{ircserver.botname}*=+{ircserver.botname}@{ircserver.servername}"
    ircclient.connection.userhost([ircserver.botname])
    assert await ircclient.expect("userhost", arguments=[bot_userhost])

    client_userhost = f"{BOTNAME}=+{BOTNAME}@{ircserver.address}"  # address is 127.0.0.1 or ::1
    ircclient.connection.userhost([BOTNAME])
    assert await ircclient.expect("userhost", arguments=[client_userhost])

    # most advanced check: both nicknames, in opposite order, one of them twice, nonexistent in the middle
    # ircclient joins with comma with is not spec-compliant; join with spaces here manually
    ircclient.connection.userhost([" ".join([BOTNAME, "nonexistent", ircserver.botname, BOTNAME])])
    assert await ircclient.expect("userhost", arguments=[" ".join([client_userhost, bot_userhost, client_userhost])])


@pytest.mark.usefixtures("ircserver")
async def test_nick(ircclient: IRCClientAio) -> None:
    """Test the NICK command."""
    ircclient.connection.nick("")
    assert await ircclient.expect("nonicknamegiven")

    ircclient.connection.nick("i")
    assert await ircclient.expect("erroneusnickname")

    # change our nickname
    ircclient.connection.nick("new-nick")
    assert await ircclient.expect("nick", target="new-nick")

    # make sure the internal state of the server has also changed
    ircclient.connection.whois([BOTNAME])
    assert await ircclient.expect("nosuchnick")

    # change our nickname back (be nice to other tests)
    ircclient.connection.nick(BOTNAME)
    assert await ircclient.expect("nick", target=BOTNAME)


@pytest.mark.usefixtures("ircserver")
async def test_user(ircclient: IRCClientAio) -> None:
    """Test the USER command."""
    ircclient.connection.user("", "")
    assert await ircclient.expect("needmoreparams")

    ircclient.connection.user("new-nick", "new-realname")
    assert await ircclient.expect("alreadyregistered")


@pytest.mark.usefixtures("ircserver")
async def test_join(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the JOIN command."""
    ircclient.connection.join("")
    assert await ircclient.expect("needmoreparams")

    ircclient.connection.join("invalid")
    assert await ircclient.expect("nosuchchannel")

    ircclient.connection.join("#nonexistent")
    assert await ircclient.expect("nosuchchannel")

    # join a valid channel
    await ircserver.broadcast("#one-channel", "create the channel")
    ircclient.connection.join("#one-channel")
    assert await ircclient.expect("join", target="#one-channel")

    # also part the channel, to reset state and be nice to other tests
    ircclient.connection.part("#one-channel")
    assert await ircclient.expect("part", target="#one-channel")


@pytest.mark.usefixtures("ircserver")
async def test_part(ircclient: IRCClientAio) -> None:
    """Test the PART command."""
    ircclient.connection.part("")
    assert await ircclient.expect("needmoreparams")

    ircclient.connection.part("#nonexistent")
    assert await ircclient.expect("notonchannel")

    ircclient.connection.part("#one-channel")
    assert await ircclient.expect("notonchannel")

    # actual part tested in the JOIN test


@pytest.mark.usefixtures("ircserver")
async def test_topic(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the TOPIC command."""
    ircclient.connection.topic("")
    assert await ircclient.expect("needmoreparams")

    ircclient.connection.topic("#nonexistent", "new topic")
    assert await ircclient.expect("notonchannel")

    await ircserver.broadcast("#one-channel", "create the channel")
    ircclient.connection.join("#one-channel")
    assert await ircclient.expect("join", target="#one-channel")

    ircclient.connection.topic("#one-channel")
    assert await ircclient.expect("currenttopic", arguments=["#one-channel", "Test topic for #one-channel"])
    assert await ircclient.expect("topicinfo")

    ircclient.connection.topic("#one-channel", "new topic")
    assert await ircclient.expect("chanoprivsneeded")

    # also part the channel, to reset state and be nice to other tests
    ircclient.connection.part("#one-channel")
    assert await ircclient.expect("part", target="#one-channel")


@pytest.mark.usefixtures("ircserver")
async def test_names(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the NAMES command."""
    ircclient.connection.names("")
    assert await ircclient.expect("endofnames")

    await ircserver.broadcast("#another-channel", "create another channel")
    ircclient.connection.names("#another-channel")
    assert await ircclient.expect("endofnames")


@pytest.mark.usefixtures("ircserver")
async def test_privmsg(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the PRIVMSG command."""
    ircclient.connection.privmsg("", "")
    assert await ircclient.expect("needmoreparams")

    # channel messages
    ircclient.connection.privmsg("#one-channel", "message")
    assert await ircclient.expect("cannotsendtochan")

    # private messages
    ircclient.connection.privmsg(BOTNAME, "message")
    assert await ircclient.expect("privmsg")

    ircclient.connection.privmsg("nonexistent", "message")
    assert await ircclient.expect("nosuchnick")

    ircclient.connection.privmsg(ircserver.botname, "message")
    # (no response expected)


@pytest.mark.usefixtures("ircserver")
async def test_notice(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the NOTICE command."""
    ircclient.connection.notice("", "")
    assert await ircclient.expect("needmoreparams")

    # private messages
    ircclient.connection.notice(BOTNAME, "message")
    assert await ircclient.expect("privnotice")

    ircclient.connection.privmsg(ircserver.botname, "message")
    ircclient.connection.notice("nonexistent", "message")
    # (no response expected)


@pytest.mark.usefixtures("ircserver")
async def test_list(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test the LIST command."""
    ircclient.connection.list()
    assert await ircclient.expect("listend")

    await ircserver.broadcast("#one-channel", "create the channel")
    ircclient.connection.list()
    assert await ircclient.expect("listend")

    ircclient.connection.list(["#one-channel"])
    assert await ircclient.expect("list")
    assert await ircclient.expect("listend")


@pytest.mark.usefixtures("ircserver")
async def test_nonexistent(ircclient: IRCClientAio) -> None:
    """Test a non-existent command."""
    ircclient.connection.send_raw("NONEXISTENT :nonarg")
    assert await ircclient.expect("unknowncommand")


@pytest.mark.usefixtures("ircserver")
async def test_conversation(ircserver: IRCServer, ircclient: IRCClientAio) -> None:
    """Test a scenario of a hypothetic real client/conversation."""
    await ircserver.broadcast("#one-channel", "create the channel")

    ircclient.connection.join("#one-channel")
    assert await ircclient.expect("join", target="#one-channel")

    await ircserver.broadcast("#one-channel", "this is another message")
    assert await ircclient.expect("pubmsg", target="#one-channel", arguments=["this is another message"])
