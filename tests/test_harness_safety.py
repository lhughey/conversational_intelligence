"""The test harness's own safety properties."""

import pathlib
import socket

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def test_network_is_blocked_in_ordinary_tests():
    with pytest.raises(RuntimeError, match="Network access attempted"):
        socket.socket().connect(("1.1.1.1", 80))


def test_costly_markers_are_deselected_by_default():
    """`live` and `e2e` must be excluded by addopts, so a bare `pytest` never
    spends money or binds a port."""
    config = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    addopts = next(l for l in config.splitlines() if l.startswith("addopts"))
    assert "not live" in addopts and "not e2e" in addopts
