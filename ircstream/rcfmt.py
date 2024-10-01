"""Helpers to format RecentChanges for IRC consumption."""

import html
import re
from typing import Any

# Canonical location: operations/mediawiki-config wmf-config/InitialiseSettings.php
LEGACY_CHANNEL_MAP = {
    # Do NOT add any more wikis here; this is a list of legacy exceptions
    "advisorywiki": "#advisory.wikipedia",
    "arbcom_dewiki": "#arbcom-de.wikipedia",
    "arbcom_enwiki": "#arbcom-en.wikipedia",
    "arbcom_fiwiki": "#arbcom-fi.wikipedia",
    "arbcom_nlwiki": "#arbcom-nl.wikipedia",
    "auditcomwiki": "#auditcom.wikipedia",
    "boardgovcomwiki": "#boardgovcom.wikipedia",
    "boardwiki": "#board.wikipedia",
    "chairwiki": "#chair.wikipedia",
    "chapcomwiki": "#chapcom.wikipedia",
    "checkuserwiki": "#checkuser.wikipedia",
    "collabwiki": "#collab.wikipedia",
    "donatewiki": "#donate.wikimedia.org",
    "execwiki": "#exec.wikipedia",
    "fdcwiki": "#fdc.wikipedia",
    "foundationwiki": "#wikimediafoundation.org",
    "iegcomwiki": "#iegcom.wikipedia",
    "internalwiki": "#internal.wikipedia",
    "legalteamwiki": "#legalteam.wikipedia",
    "loginwiki": "#login.wikipedia",
    "mediawikiwiki": "#mediawiki.wikipedia",
    "movementroleswiki": "#movementroles.wikipedia",
    "noboard_chapterswikimedia": "#noboard-chapters.wikimedia",
    "officewiki": "#office.wikipedia",
    "ombudsmenwiki": "#ombudsmen.wikipedia",
    "otrs_wikiwiki": "#otrs-wiki.wikipedia",
    "outreachwiki": "#outreach.wikipedia",
    "qualitywiki": "#quality.wikipedia",
    "searchcomwiki": "#searchcom.wikipedia",
    "spcomwiki": "#spcom.wikipedia",
    "stewardwiki": "#steward.wikipedia",
    "testwikidatawiki": "#testwikidata.wikipedia",
    "transitionteamwiki": "#transitionteam.wikipedia",
    "votewiki": "#vote.wikipedia",
    "wg_enwiki": "#wg-en.wikipedia",
    "wikidatawiki": "#wikidata.wikipedia",
    "wikimania2005wiki": "#wikimania.wikimedia",
    "wikimania2010wiki": "#wikimania2010.wikipedia",
    "wikimania2011wiki": "#wikimania2011.wikipedia",
    "wikimania2012wiki": "#wikimania2012.wikipedia",
    "wikimania2013wiki": "#wikimania2013.wikipedia",
    "wikimania2014wiki": "#wikimania2014.wikipedia",
    "wikimaniateamwiki": "#wikimaniateam.wikipedia",
    # Do NOT add any more wikis here; this is a list of legacy exceptions
}


def _html_cleanup(msg: str) -> str:
    """Remove HTML tags and newlines."""
    return html.unescape(msg).replace("\n", " ").replace("\r", "")


class RecentChangeIRCFormatter:
    """Format a RecentChange for IRC consumption.

    Initialized with a dict (usually parsed from JSON); emits IRC strings.
    """

    def __init__(self, msg: dict[str, Any]) -> None:
        self.msg = msg

    def __repr__(self) -> str:
        """Return a user-readable description of the message."""
        return f"<{self.__class__.__name__}: {self.msg['type']}>"

    def __str__(self) -> str:
        """Return an unformatted version of the string, suitable for printing."""
        parsed_msg = self.ircstr
        if parsed_msg:
            return re.sub(r"\003((?P<fg>\d{1,2})(,(?P<bg>\d{1,2}))?)?", "", parsed_msg)
        else:
            return ""

    @property
    def should_skip(self) -> bool:
        """Return True if this message should be skipped."""
        if "type" not in self.msg:
            return True
        if self.msg["type"] not in ("edit", "new", "log", "external"):
            return True
        return False

    @property
    def ircstr(self) -> str | None:
        """Return an formatted version, suitable for emitting over IRC."""
        if self.should_skip:
            return None

        comment = self.msg["comment"]

        if self.msg["type"] == "log":
            # FIXME: this is localized in MediaWiki (NS_SPECIAL)
            # e.g. on ruwiki, it's Служебная:Log, not Special:Log
            title = "Special:Log/" + self.msg["log_type"]
        else:
            title = self.msg["title"]
        title = _html_cleanup(title)

        if self.msg["type"] == "log":
            url = ""
        else:
            url = self.msg["server_url"] + self.msg["server_script_path"] + "/index.php"
            if self.msg["type"] == "new":
                query = "?oldid=" + str(self.msg["revision"]["new"])
            else:
                query = "?diff=" + str(self.msg["revision"]["new"]) + "&oldid=" + str(self.msg["revision"]["old"])

            # show rcid= when patrolled merely exists (even if false)
            if "patrolled" in self.msg:
                query += "&rcid=" + str(self.msg["id"])

            # FIXME: hooks can add more URLs; e.g. see Flow
            #   extensions/Flow/includes/Formatter/IRCLineUrlFormatter.php
            # also check what wikidata does?
            # Hooks::run( 'IRCLineURL', [ &$url, &$query, $rc ] );

            url += query

        try:
            new_len = self.msg["length"]["new"]
            old_len = self.msg["length"].get("old", 0)  # this can be missing e.g. on new pages
            szdiff_i = new_len - old_len
            szdiff = str(szdiff_i)
            if szdiff_i < -500:
                szdiff = "\002" + szdiff + "\002"
            elif szdiff_i >= 0:
                szdiff = "+" + szdiff
            szdiff = "(" + szdiff + ")"
        except KeyError:
            szdiff = ""

        user = _html_cleanup(self.msg["user"])

        if self.msg["type"] == "log":
            target = self.msg["title"]
            comment = self.msg["log_action_comment"].replace("[[" + target + "]]", "[[\00302" + target + "\00310]]")
            flag = self.msg["log_action"]
        else:
            comment = self.msg["comment"]
            flag = ""
            if "patrolled" in self.msg and not self.msg["patrolled"]:
                flag += "!"

            if self.msg["type"] == "new":
                flag += "N"
            if self.msg["minor"]:
                flag += "M"
            if self.msg["bot"]:
                flag += "B"
        comment = _html_cleanup(comment)

        # NOTE: the interwiki prefix logic from the original implementation is
        # not present here, as it is unused in Wikimedia production

        # see http://www.irssi.org/documentation/formats for some colour codes. prefix is \003,
        # no colour (\003) switches back to the term default
        titlestring = "\00314[[\00307" + title + "\00314]]"
        fullstring = f"{titlestring}\0034 {flag}\00310 \00302{url}\003 \0035*\003 \00303{user}\003 \0035*\003 {szdiff} \00310{comment}\003"  # noqa

        return fullstring

    @property
    def channel(self) -> str | None:
        """Return the IRC channel this message should be emitted to."""
        if self.should_skip:
            return None

        domain, wiki = self.msg["meta"]["domain"], self.msg["wiki"]
        try:
            channel = LEGACY_CHANNEL_MAP[wiki]
        except KeyError:
            try:
                channel = "#" + re.findall(r"^(.+)\.org$", domain)[0]
            except IndexError:
                channel = None

        return channel


if __name__ == "__main__":
    """Accept JSON input on stdin, emit formatted message on stdout.

    Accepts either a single message, with a JSON potentially spanning multiple
    lines, or a JSONL with each message being its own line.

    Can be used to generate .out test files.
    """

    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", action="store_true", help="Consume JSON Lines")
    options = parser.parse_args()

    try:
        messages = sys.stdin if options.jsonl else (sys.stdin.read(),)
        for message_raw in messages:
            message = json.loads(message_raw)
            rc = RecentChangeIRCFormatter(message)
            channel, ircstr = rc.channel, rc.ircstr
            if not channel or not ircstr:
                continue

            # this is the same format as rc2udp
            sys.stdout.write(f"{channel}\t {ircstr}\n")
    except KeyboardInterrupt:
        pass
