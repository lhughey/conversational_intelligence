"""The run recorder: files written, history appended exactly once, never rewritten."""

from __future__ import annotations

import json
import re

from convint.bench import record

PROV = {
    "run_at": "2026-10-16T12:00:00+00:00",
    "git": {"commit": "abcdef1234567890", "branch": "main", "dirty": True, "dirty_files": []},
    "platform": {"python": "3.12.0", "os": "test"},
    "packages": {},
    "dataset_hashes": {},
}


def _run(tmp_path, note="smoke", **kw):
    return record.record_run(
        "gate-synth", note, {"acc": 1.0}, "body text\n",
        models=["haiku-4-5 (claude-haiku-4-5, effort n/a)"],
        headline={"synth gate": "acc 100% [100–100]"},
        command="convint bench --gate", prov=kw.pop("prov", PROV),
        directory=tmp_path, **kw,
    )


def _rows(path):
    return [l for l in path.read_text().splitlines() if l.startswith("| 20")]


def test_writes_json_md_and_one_history_row(tmp_path):
    paths = _run(tmp_path)
    assert paths["json"].name == "gate-synth-2026-10-16T120000Z.json"
    payload = json.loads(paths["json"].read_text())
    assert payload["note"] == "smoke"
    assert payload["results"] == {"acc": 1.0}
    assert payload["provenance"]["git"]["commit"] == "abcdef1234567890"

    md = paths["md"].read_text()
    assert "**What this run tested:** smoke" in md
    assert "convint bench --gate" in md
    assert "DIRTY TREE" in md
    assert "haiku-4-5" in md
    assert md.rstrip().endswith("body text")

    rows = _rows(paths["history"])
    assert len(rows) == 1
    assert "`abcdef1` +dirty" in rows[0]
    assert "acc 100% [100–100]" in rows[0]
    assert f"({paths['md'].name})" in rows[0]


def test_history_created_with_header_when_missing(tmp_path):
    assert not (tmp_path / "HISTORY.md").exists()
    paths = _run(tmp_path)
    text = paths["history"].read_text()
    assert text.startswith("# Benchmark history")
    assert "How to read" in text
    assert "| date (UTC) | kind | note |" in text


def test_existing_rows_untouched_and_append_only(tmp_path):
    history = tmp_path / "HISTORY.md"
    prior = record.HISTORY_HEADER + "| 2026-09-03 23:04 | testbed | backfilled | x | y | z | — | r |"
    history.write_text(prior)  # no trailing newline on purpose
    _run(tmp_path)
    later = dict(PROV, run_at="2026-10-16T13:00:00+00:00")
    _run(tmp_path, note="second", prov=later)
    text = history.read_text()
    assert text.startswith(prior + "\n")
    rows = _rows(history)
    assert len(rows) == 3
    assert "smoke" in rows[1] and "second" in rows[2]


def test_note_defaults_and_env(tmp_path, monkeypatch):
    assert record.resolve_note(None) == record.NO_NOTE
    assert record.resolve_note("   ") == record.NO_NOTE
    monkeypatch.setenv("NOTE", "from env")
    assert record.resolve_note("") == "from env"
    assert record.resolve_note("flag wins") == "flag wins"
    monkeypatch.delenv("NOTE")
    paths = _run(tmp_path, note=None)
    assert "(no note)" in _rows(paths["history"])[0]


def test_pipes_in_cells_do_not_break_the_table(tmp_path):
    paths = _run(tmp_path, note="a | b")
    row = _rows(paths["history"])[0]
    assert "a \\| b" in row
    assert len(re.findall(r"(?<!\\)\|", row)) == 9  # eight cells


def test_cli_gate_bench_records_to_isolated_dir(tmp_path, capsys):
    """conftest points CONVINT_BENCH_RESULTS at tmp; real history is untouched."""
    from convint.api.cli import main as cli_main

    assert cli_main(["bench", "--gate", "--split", "synth", "--e2e",
                     "--note", "cli test"]) == 0
    out_dir = record.out_dir()
    assert str(out_dir).startswith(str(tmp_path))
    rows = _rows(out_dir / "HISTORY.md")
    assert len(rows) == 1
    assert "gate-synth-e2e" in rows[0] and "cli test" in rows[0]
    assert "synth gate (e2e: deterministic)" in rows[0]


def test_runs_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    from convint.bench.record import provenance, record_run

    prov = provenance()
    a = record_run("gate-synth-e2e", "a", {}, "body a", [], {}, prov=prov, directory=tmp_path)
    b = record_run("gate-synth-e2e", "b", {}, "body b", [], {}, prov=prov, directory=tmp_path)
    assert a["md"] != b["md"]
    assert "body a" in a["md"].read_text() and "body b" in b["md"].read_text()
