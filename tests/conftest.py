"""Tests are network-blocked by default.

A test that accidentally reaches a model API fails loudly instead of quietly
costing money. Live tests opt back in with @pytest.mark.live (deselected by
default via addopts in pyproject.toml).
"""

from __future__ import annotations

import json
import pathlib
import socket

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GOLDENS = REPO / "docs" / "golden-transcripts"


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return

    def _blocked(*args, **kwargs):  # pragma: no cover - only fires on a bug
        raise RuntimeError(
            "Network access attempted in a non-live test. "
            "Mark it @pytest.mark.live or inject a fake adapter."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)


@pytest.fixture(autouse=True)
def _isolated_bench_results(tmp_path, monkeypatch):
    """Recorded runs (convint.bench.record) go to a temp dir, never to the
    real bench-results/HISTORY.md; and a stray $NOTE cannot leak in."""
    monkeypatch.setenv("CONVINT_BENCH_RESULTS", str(tmp_path / "bench-results"))
    monkeypatch.delenv("NOTE", raising=False)


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def golden_files() -> list[pathlib.Path]:
    files = sorted(GOLDENS.rglob("*.json"))
    assert files, f"no golden transcripts found under {GOLDENS}"
    return files


@pytest.fixture(scope="session")
def goldens(golden_files) -> dict[str, dict]:
    return {p.stem: _load(p) for p in golden_files}
