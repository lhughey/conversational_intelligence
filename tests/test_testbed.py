"""scripts/testbed.py must not report a suite that proved nothing as PASS."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def testbed():
    spec = importlib.util.spec_from_file_location("testbed", REPO / "scripts" / "testbed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("exit_code", "passed", "expected"), [
    (0, 12, "PASS"),
    (0, 0, "SKIPPED"),   # every test skipped, e.g. e2e without node
    (5, 0, "SKIPPED"),   # pytest collected nothing
    (1, 3, "FAIL"),
    (2, 0, "FAIL"),      # interrupted / usage error
])
def test_suite_status(testbed, exit_code, passed, expected):
    assert testbed.suite_status(exit_code, passed) == expected


def test_headline_does_not_call_a_skipped_suite_a_pass(testbed):
    record = {
        "suites": [{"suite": "e2e", "status": "SKIPPED", "ok": False, "passed": 0}],
        "gate": {}, "assessors": {},
    }
    assert testbed.headline(record)["suites"] == "e2e SKIPPED (0 passed)"
