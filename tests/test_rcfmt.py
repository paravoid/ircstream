"""Test the validity of our RecentChanges IRC Formatter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ircstream.rcfmt import RecentChangeIRCFormatter

TEST_DATA_DIR = Path("tests") / Path("rcfmt")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Generate test data fixtures from {name}.json / {name}.out files."""

    rc_fixtures: list[dict[str, Any]] = []
    for json_file in TEST_DATA_DIR.glob("*.json"):
        parsed_input = json.loads(json_file.read_text())

        rc_fixture: dict[str, Any] = {
            "input": parsed_input,
        }

        # xfail = expected failures (parse errors)
        # xempty = expected non-failures, i.e. parses OK, but is not for IRC consumption
        for flag in ("xfail", "xempty"):
            if json_file.with_suffix("." + flag).exists():
                rc_fixture[flag] = True

        out = json_file.with_suffix(".out")
        if out.exists():
            text = out.read_text().rstrip("\n")
            rc_fixture["expected_channel"], rc_fixture["expected_output"] = text.split("\t ")[:2]

        rc_fixtures.append(rc_fixture)

    if "rc_fixture" in metafunc.fixturenames:
        metafunc.parametrize("rc_fixture", rc_fixtures)


def test_rcfmt_valid(rc_fixture: dict[str, Any]) -> None:
    """Test the output of a fixture."""
    if rc_fixture.get("xfail", False):
        pytest.xfail("Marked as xfail")

    fmt = RecentChangeIRCFormatter(rc_fixture["input"])
    if rc_fixture.get("xempty", False):
        assert fmt.should_skip is True
        assert fmt.channel is None
        assert fmt.ircstr is None
    else:
        assert fmt.channel == rc_fixture["expected_channel"]
        assert fmt.ircstr == rc_fixture["expected_output"]
