"""Tier 5: cross-language proof.

Starts the real HTTP server and drives it with the Node client from
examples/. This is the test that demonstrates the component is genuinely
consumable by a TypeScript application sharing nothing but the contract.

Deselected by default (marker `e2e`) because it binds a port and shells out.
    make test-e2e
"""

from __future__ import annotations

import pathlib
import shutil
import socket
import subprocess
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
CLIENT = REPO / "examples" / "typescript-client" / "client.mjs"

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server() -> str:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory", "convint.api.http:build_app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if proc.poll() is not None:
                raise RuntimeError(f"server died:\n{proc.stdout.read().decode()}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not start in time")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_consumer_can_drive_the_component(server):
    result = subprocess.run(
        ["node", str(CLIENT), server],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "contract 1.0 OK" in out
    assert "decision   : follow_up / deepen" in out
    assert "rule_fired : floor_not_met" in out
    assert "followups  : 1" in out
    assert out.strip().endswith("OK")
