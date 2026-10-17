"""Record a benchmark run so it can be read later, next to every other run.

A benchmark number without provenance is a rumour. Each run writes

    bench-results/<kind>-<UTC stamp>.json   results + provenance
    bench-results/<kind>-<UTC stamp>.md     what was tested, then the report

and appends ONE row to bench-results/HISTORY.md, the index. History is
append-only: existing rows are never rewritten.

The "note" says what the run was for. It comes from `--note`, else the `NOTE`
environment variable (the Makefile passes `NOTE="..."` through), else
"(no note)" - a missing note never blocks a run.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import platform
import shlex
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
#: Overridable so tests (and anyone experimenting) never touch real history.
OUT_ENV = "CONVINT_BENCH_RESULTS"
NO_NOTE = "(no note)"
HISTORY = "HISTORY.md"

HISTORY_HEADER = """# Benchmark history

One row per recorded run, oldest first. Rows are appended by
`convint.bench.record` (`make testbed`, `make bench-assessors`,
`make bench-gate*`) and are never rewritten; to correct a row, append a new
one that says so.

**How to read.** *note* is what the run was meant to test (pass `NOTE="..."`
to make, or `--note`). *commit* is the HEAD the run measured; `+dirty` means
uncommitted changes were present, so the numbers are not reproducible from the
commit alone. Rates are `rate [95% CI]` (cluster bootstrap over transcripts or
topics); `[—]` means no interval was computed, either because too few clusters
existed or because the run predates intervals. *est. cost* is `—` when it was
not measured (cached model calls cost nothing to re-run). Rows marked
**backfilled** were reconstructed from result files written before this index
existed. Follow *report* for the full numbers.

| date (UTC) | kind | note | commit | models | headline | est. cost | report |
|---|---|---|---|---|---|---|---|
"""


def out_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get(OUT_ENV) or REPO / "bench-results")


def resolve_note(note: str | None = None) -> str:
    """`--note` wins, then `$NOTE`, then the placeholder. Never blocks."""
    for candidate in (note, os.environ.get("NOTE")):
        if candidate and candidate.strip():
            return " ".join(candidate.split())
    return NO_NOTE


def _sh(*cmd: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    except OSError as exc:  # pragma: no cover - git missing
        return 1, str(exc)
    return proc.returncode, proc.stdout


def git_provenance() -> dict:
    _, sha = _sh("git", "rev-parse", "HEAD")
    _, branch = _sh("git", "rev-parse", "--abbrev-ref", "HEAD")
    _, status = _sh("git", "status", "--porcelain")
    dirty = bool(status.strip())
    return {
        "commit": sha.strip(),
        "branch": branch.strip(),
        "dirty": dirty,
        "dirty_files": [l[3:] for l in status.splitlines()][:20] if dirty else [],
    }


def file_hash(path: pathlib.Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def package_versions() -> dict:
    out = {}
    for name in ("pydantic", "anthropic", "openai", "fastapi", "pytest"):
        try:
            mod = __import__(name)
            out[name] = getattr(mod, "__version__", getattr(mod, "VERSION", "?"))
        except Exception:
            out[name] = "not installed"
    try:
        from importlib.metadata import version

        out["convint"] = version("convint")
    except Exception:
        out["convint"] = "?"
    return out


def provenance(now: dt.datetime | None = None) -> dict:
    """Everything needed to trace a number back to what produced it."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return {
        "run_at": now.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
        "git": git_provenance(),
        "platform": {"python": platform.python_version(), "os": platform.platform()},
        "packages": package_versions(),
        "dataset_hashes": {
            str(p.relative_to(REPO / "data")): file_hash(p)
            for p in sorted((REPO / "data").rglob("*.jsonl"))
        },
    }


def command_line() -> str:
    argv = list(sys.argv)
    if argv and argv[0].endswith(("cli.py", "__main__.py")):
        argv[0] = "python -m convint.api.cli"
    elif argv:
        try:
            argv[0] = str(pathlib.Path(argv[0]).resolve().relative_to(REPO))
        except ValueError:
            pass
    return " ".join([argv[0], *(shlex.quote(a) for a in argv[1:])]) if argv else ""


def assessor_model_label(key: str, effort: str = "low") -> str:
    """`haiku-4-5 (claude-haiku-4-5, effort n/a)` - the system under test is a
    model AND an effort tier. LLMAssessor sends effort=low where supported."""
    try:
        from ..adapters.models import REGISTRY

        s = REGISTRY[key]
    except Exception:
        return key
    return f"{key} ({s.model_id}, effort {effort if s.supports_effort else 'n/a'})"


def _cell(text: str) -> str:
    return " ".join(str(text).replace("|", "\\|").split()) or "—"


def _commit_cell(git: dict) -> str:
    sha = (git.get("commit") or "?")[:7]
    return f"`{sha}`" + (" +dirty" if git.get("dirty") else "")


def history_row(*, date: str, kind: str, note: str, git: dict, models: list[str],
                headline: dict, cost: str | None, report: str) -> str:
    head = "; ".join(f"{k}: {v}" for k, v in headline.items())
    cells = [date, kind, note, _commit_cell(git), ", ".join(models) or "—",
             head, cost or "—", f"[{pathlib.Path(report).name}]({report})"]
    return "| " + " | ".join(_cell(c) if i != 3 else c for i, c in enumerate(cells)) + " |"


def append_history(row: str, directory: pathlib.Path | None = None) -> pathlib.Path:
    """Append one row; create the file with its header first if absent."""
    directory = directory or out_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / HISTORY
    if not path.exists():
        path.write_text(HISTORY_HEADER, encoding="utf-8")
    existing = path.read_text(encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write(row + "\n")
    return path


def render_header(*, kind: str, note: str, command: str, prov: dict,
                  models: list[str], headline: dict, cost: str | None) -> str:
    g = prov["git"]
    lines = [
        f"# {kind} run — {prov['run_at']}",
        "",
        f"> **What this run tested:** {note}",
        "",
        f"- **command** `{command}`",
        f"- **commit** `{g.get('commit', '?')[:12]}` on `{g.get('branch', '?')}`"
        + ("  ⚠️ **DIRTY TREE — not reproducible from the commit alone**"
           if g.get("dirty") else " (clean tree)"),
        f"- **python** {prov['platform']['python']}",
        "- **models / effort** " + (", ".join(models) if models else "none (offline)"),
    ]
    if cost:
        lines.append(f"- **est. cost** {cost}")
    lines += ["", "**Headline**", ""]
    lines += [f"- {k}: {v}" for k, v in headline.items()] or ["- (none)"]
    lines += ["", "---", ""]
    return "\n".join(lines)


def record_run(kind: str, note: str | None, results: dict, markdown: str,
               models: list[str], headline: dict, *, command: str | None = None,
               cost: str | None = None, prov: dict | None = None,
               suffix: str = "", directory: pathlib.Path | None = None) -> dict:
    """Write `<kind>-<stamp>{suffix}.json` + `.md` and append a HISTORY row.

    Returns {"json", "md", "history", "markdown"} - paths plus the full
    markdown text (header + body), so callers can mirror it (LATEST.md)."""
    directory = directory or out_dir()
    directory.mkdir(parents=True, exist_ok=True)
    note = resolve_note(note)
    command = command or command_line()
    prov = prov or provenance()
    run_at = dt.datetime.fromisoformat(prov["run_at"]).astimezone(dt.timezone.utc)
    base = f"{kind}-{run_at.strftime('%Y-%m-%dT%H%M%SZ')}{suffix}"
    # Two runs started in the same second must not overwrite each other's report.
    stem, n = base, 1
    while (directory / f"{stem}.json").exists() or (directory / f"{stem}.md").exists():
        n += 1
        stem = f"{base}-{n}"

    json_path = directory / f"{stem}.json"
    md_path = directory / f"{stem}.md"
    payload = {"kind": kind, "note": note, "command": command, "models": models,
               "headline": headline, "est_cost": cost, "provenance": prov,
               "results": results}
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")

    text = render_header(kind=kind, note=note, command=command, prov=prov,
                         models=models, headline=headline, cost=cost) + markdown
    if not text.endswith("\n"):
        text += "\n"
    md_path.write_text(text, encoding="utf-8")

    row = history_row(date=run_at.strftime("%Y-%m-%d %H:%M"), kind=kind, note=note,
                      git=prov["git"], models=models, headline=headline, cost=cost,
                      report=md_path.name)
    history = append_history(row, directory)
    return {"json": json_path, "md": md_path, "history": history, "markdown": text}


# -- headline helpers shared by the callers ---------------------------------

def gate_headline(result: dict, split: str) -> dict:
    """acc / premature / stall (+CI) for the gate row(s) of one split."""
    from .stats import format_ci

    out = {}
    for name, m in result.items():
        if not name.startswith("gate") or "error" in m:
            continue
        label = f"{split} {name}" if name != "gate" else f"{split} gate"
        out[label] = ", ".join(
            f"{short} {format_ci(m.get(key), m.get(f'{key}_ci'))}"
            for key, short in (("accuracy_strict", "acc"),
                               ("premature_advance_rate", "premature"),
                               ("stall_rate", "stall"))
        )
    return out


def best_assessor(rows: dict) -> tuple[str, str] | None:
    """(name, `both [CI]`) of the assessor with the highest both_exact."""
    from .stats import format_ci

    scored = [(n, m) for n, m in rows.items()
              if isinstance(m, dict) and m.get("both_exact") is not None]
    if not scored:
        return None
    name, m = max(scored, key=lambda nm: nm[1]["both_exact"])
    return name, format_ci(m["both_exact"], m.get("both_exact_ci"))
