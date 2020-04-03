"""Argument parse tests."""

import json

import ircstream

import pytest  # type: ignore

import structlog  # type: ignore


def test_parse_args_help(capsys):
    """Test whether --help returns usage and exits."""
    with pytest.raises(SystemExit) as exc:
        ircstream.parse_args(["--help"])

    assert exc.value.code == 0
    out, _ = capsys.readouterr()
    assert "usage: " in out


def test_config_nonexistent(capsys):
    """Test with non-existing configuration directories."""
    not_a_file = "/nonexistent"
    with pytest.raises(SystemExit) as exc:
        ircstream.parse_args(["--config-file", not_a_file])

    assert exc.value.code != 0
    _, err = capsys.readouterr()
    assert "No such file or directory" in err


def test_configure_logging_plain(caplog):
    """Test that logging configuration works."""
    ircstream.configure_logging("DEBUG", "plain")
    log = structlog.get_logger("testlogger")
    caplog.clear()
    log.warn("this is a test log")
    assert ["this is a test log"] == [rec.message for rec in caplog.records]

    ircstream.configure_logging("DEBUG", "json")
    log = structlog.get_logger("testlogger")
    caplog.clear()
    log.warn("this is a json log", key="value")

    parsed_logs = [json.loads(rec.message) for rec in caplog.records]
    assert ["this is a json log"] == [rec["event"] for rec in parsed_logs]
    assert ["value"] == [rec["key"] for rec in parsed_logs]