"""Held-out sufficiency set: scored, never tuned against.

The 23-item seed set (`data/labels/sufficiency.seed.jsonl`) has been tuned
against - fixes were made after seeing results - so a number from it is a
floor, not an estimate. This set exists so a number CAN be read as an
estimate. It stays one only while nobody learns from it:

  * never used for tuning, prompt optimization (DSPy or otherwise), few-shot
    examples, or choosing between prompt variants by reading its misses;
  * read only by bench/eval code and by the labelling flow - pinned by
    `tests/test_heldout_leak.py`, which also checks no item text has leaked
    into the seed set, the turn-decision data, the persona banks or `src/`;
  * labels are the USER's (`labels.jsonl`). The author's intended rung lives
    in `intended.jsonl` and is read only to measure author/labeller agreement,
    never by the labelling flow.

Layout and the labelling workflow: `data/heldout/README.md`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import random
from collections import Counter

from pydantic import BaseModel, ConfigDict

from ..domain.enums import Ownership, Specificity
from .evaluate import Result, score
from .stats import format_ci, rate_summary

REPO = pathlib.Path(__file__).resolve().parents[3]
DIR = REPO / "data" / "heldout"
ITEMS = DIR / "items.jsonl"
LABELS = DIR / "labels.jsonl"
INTENDED = DIR / "intended.jsonl"
PERSONAS = DIR / "personas"

#: Below this many user labels no headline is printed and no model is called.
MIN_LABELLED = 20
#: Fixed so every labelling session (interactive or sheet) sees the same order.
ORDER_SEED = 20261016
CLUSTER_UNIT = "personas"
#: `--assessor all` = deterministic + llm/hybrid on each of these.
#: Mirrors MODELS in scripts/compare_assessors.py so the two splits compare.
MODELS = ["haiku-4-5", "haiku-5-5", "sonnet-5", "sonnet-5-5", "opus-5", "opus-5-5",
          "gpt-4.1-mini", "gpt-4.1"]


class InsufficientLabels(RuntimeError):
    """Too few user labels to print a headline."""


class HeldoutItem(BaseModel):
    """One unlabelled candidate: what the labeller sees, nothing more."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    persona: str
    topic: str
    question: str
    text: str

    @property
    def text_sha(self) -> str:
        return text_sha(self.text)


class HeldoutLabel(BaseModel):
    """One user judgement. `text_sha` pins the label to the text it judged."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    specificity: Specificity
    ownership: Ownership
    text_sha: str
    note: str = ""
    source: str = "human"
    via: str = "interactive"
    labelled_at: str = ""


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# -- loading -----------------------------------------------------------------

def load_items(path: pathlib.Path | None = None) -> list[HeldoutItem]:
    items = [HeldoutItem.model_validate(r) for r in _read_jsonl(path or ITEMS)]
    dupes = [i for i, c in Counter(it.id for it in items).items() if c > 1]
    if dupes:
        raise ValueError(f"duplicate held-out item ids: {dupes}")
    return items


def load_labels(path: pathlib.Path | None = None,
                items: list[HeldoutItem] | None = None) -> dict[str, HeldoutLabel]:
    """User labels by item id. The file is append-only; the LAST line for an
    id wins, so a correction is made by appending (or editing the line).

    Raises on a label for an unknown item, or one whose text changed after it
    was labelled - re-label rather than silently re-score."""
    items = load_items() if items is None else items
    by_id = {i.id: i for i in items}
    out: dict[str, HeldoutLabel] = {}
    for row in _read_jsonl(path or LABELS):
        label = HeldoutLabel.model_validate(row)
        item = by_id.get(label.item_id)
        if item is None:
            raise ValueError(f"label for unknown held-out item {label.item_id!r}")
        if label.text_sha != item.text_sha:
            raise ValueError(
                f"held-out drift: {label.item_id} changed after it was labelled. "
                "Re-label rather than silently re-scoring."
            )
        out[label.item_id] = label
    return out


def make_label(item: HeldoutItem, specificity: Specificity | str,
               ownership: Ownership | str, *, note: str = "", via: str = "interactive",
               now: dt.datetime | None = None) -> HeldoutLabel:
    now = now or dt.datetime.now(dt.timezone.utc)
    return HeldoutLabel(
        item_id=item.id, specificity=Specificity(specificity),
        ownership=Ownership(ownership), text_sha=item.text_sha, note=note.strip(),
        via=via, labelled_at=now.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
    )


def append_label(label: HeldoutLabel, path: pathlib.Path | None = None) -> None:
    path = path or LABELS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(label.model_dump(mode="json"), ensure_ascii=False) + "\n")


def load_intended(path: pathlib.Path | None = None) -> dict[str, dict]:
    """The author's intended rung. ANALYSIS ONLY: never call this from the
    labelling flow - showing it would anchor the labeller."""
    return {r["id"]: r for r in _read_jsonl(path or INTENDED)}


# -- labelling queue ---------------------------------------------------------

def presentation_order(items: list[HeldoutItem], seed: int = ORDER_SEED) -> list[HeldoutItem]:
    """Seeded shuffle, so persona and authored-rung order cannot cue answers.
    Independent of file order: sorted by id first, then shuffled."""
    ordered = sorted(items, key=lambda i: i.id)
    random.Random(seed).shuffle(ordered)
    return ordered


def queue(items: list[HeldoutItem] | None = None,
          labels: dict[str, HeldoutLabel] | None = None) -> list[HeldoutItem]:
    """Unlabelled items in presentation order - what a session resumes with."""
    items = load_items() if items is None else items
    labels = load_labels(items=items) if labels is None else labels
    return [i for i in presentation_order(items) if i.id not in labels]


def status(items: list[HeldoutItem] | None = None,
           labels: dict[str, HeldoutLabel] | None = None) -> dict:
    items = load_items() if items is None else items
    labels = load_labels(items=items) if labels is None else labels
    by_persona: dict[str, list[int]] = {}
    for item in items:
        done_total = by_persona.setdefault(item.persona, [0, 0])
        done_total[1] += 1
        done_total[0] += item.id in labels
    return {"n_labelled": sum(1 for i in items if i.id in labels),
            "n_items": len(items), "min_labelled": MIN_LABELLED,
            "by_persona": {p: {"labelled": d, "items": t}
                           for p, (d, t) in sorted(by_persona.items())}}


def format_status(st: dict) -> str:
    parts = ", ".join(f"{p} {v['labelled']}/{v['items']}" for p, v in st["by_persona"].items())
    return (f"held-out: {st['n_labelled']} labelled of {st['n_items']} "
            f"(a headline needs >= {st['min_labelled']}) - {parts}")


# -- scoring -----------------------------------------------------------------

def labelled_cases(items: list[HeldoutItem] | None = None,
                   labels: dict[str, HeldoutLabel] | None = None,
                   *, min_labelled: int = MIN_LABELLED) -> list[dict]:
    """Cases for `evaluate.score`: user-labelled items only, cluster = persona.

    Raises InsufficientLabels below `min_labelled`, before any assessor runs."""
    items = load_items() if items is None else items
    labels = load_labels(items=items) if labels is None else labels
    cases = [{"id": i.id, "text": i.text,
              "specificity": labels[i.id].specificity.value,
              "ownership": labels[i.id].ownership.value,
              "cluster": i.persona, "note": ""}
             for i in sorted(items, key=lambda i: i.id) if i.id in labels]
    if len(cases) < min_labelled:
        raise InsufficientLabels(
            f"only {len(cases)} of {len(items)} held-out items are labelled; "
            f"need >= {min_labelled} before a headline is printed. Run `make label-heldout`."
        )
    return cases


def evaluate_heldout(assessor, *, items: list[HeldoutItem] | None = None,
                     labels: dict[str, HeldoutLabel] | None = None,
                     min_labelled: int = MIN_LABELLED,
                     seed: int = 0, n_boot: int = 2000) -> Result:
    """Agreement with the user's labels, with persona-level cluster-bootstrap CIs."""
    items = load_items() if items is None else items
    cases = labelled_cases(items, labels, min_labelled=min_labelled)
    result = score(assessor, cases, cluster_unit=CLUSTER_UNIT, seed=seed, n_boot=n_boot)
    result["split"] = "heldout"
    result["n_items"] = len(items)
    return result


def author_agreement(items: list[HeldoutItem] | None = None,
                     labels: dict[str, HeldoutLabel] | None = None,
                     intended: dict[str, dict] | None = None,
                     *, seed: int = 0, n_boot: int = 2000) -> dict:
    """How often the author's intended rung matches the user's label.

    Not an assessor score: it says how far the set's design matches the
    labeller's reading, and on which kind of item (boundary vs clear) they
    part ways. Persona-level cluster bootstrap, like everything else here."""
    items = load_items() if items is None else items
    labels = load_labels(items=items) if labels is None else labels
    intended = load_intended() if intended is None else intended

    flags: dict[str, list[bool]] = {"specificity": [], "ownership": [], "both": []}
    clusters: list[str] = []
    boundary_flags: list[bool] = []
    boundary_clusters: list[str] = []
    for item in sorted(items, key=lambda i: i.id):
        label, want = labels.get(item.id), intended.get(item.id)
        if label is None or want is None:
            continue
        s_ok = label.specificity.value == want["specificity"]
        o_ok = label.ownership.value == want["ownership"]
        flags["specificity"].append(s_ok)
        flags["ownership"].append(o_ok)
        flags["both"].append(s_ok and o_ok)
        clusters.append(item.persona)
        if want.get("boundary"):
            boundary_flags.append(s_ok and o_ok)
            boundary_clusters.append(item.persona)

    out: dict = {"n": len(clusters)}
    for name, values in flags.items():
        out[name] = rate_summary(values, clusters, seed=seed, n_boot=n_boot)
    out["both_on_boundary_items"] = rate_summary(
        boundary_flags, boundary_clusters, seed=seed, n_boot=n_boot)
    return out


# -- running a comparison ----------------------------------------------------

def expand_assessor_specs(spec: str) -> list[str]:
    """`all`, or a comma-separated list of `deterministic` / `llm:<key>` / `hybrid:<key>`."""
    if spec.strip() == "all":
        return ["deterministic"] + [f"{kind}:{m}" for m in MODELS for kind in ("llm", "hybrid")]
    specs = [s.strip() for s in spec.split(",") if s.strip()]
    if not specs:
        raise ValueError("no assessor given")
    return specs


def model_keys(specs: list[str]) -> list[str]:
    keys = []
    for s in specs:
        key = s.partition(":")[2]
        if key and key not in keys:
            keys.append(key)
    return keys


def run(specs: list[str], *, make=None, items: list[HeldoutItem] | None = None,
        labels: dict[str, HeldoutLabel] | None = None,
        min_labelled: int = MIN_LABELLED) -> dict:
    """Score every assessor spec. Refuses (InsufficientLabels) before building
    any assessor when too few items are labelled, so a refusal costs nothing.
    A failing assessor becomes an `error` row rather than aborting the run."""
    if make is None:
        from .gate_eval import make_assessor as make
    items = load_items() if items is None else items
    labels = load_labels(items=items) if labels is None else labels
    labelled_cases(items, labels, min_labelled=min_labelled)  # gate first

    rows: dict = {}
    for spec in specs:
        name = spec.replace(":", "/")
        try:
            assessor = make(spec)
            name = getattr(assessor, "name", name)
            rows[name] = evaluate_heldout(assessor, items=items, labels=labels,
                                          min_labelled=min_labelled)
        except InsufficientLabels:
            raise
        except Exception as exc:  # a missing key or API error must not sink the others
            rows[name] = {"error": str(exc)[:160]}
    return rows


def headline(rows: dict, st: dict) -> dict:
    out = {"heldout labelled": f"{st['n_labelled']}/{st['n_items']}"}
    for name, m in rows.items():
        if "error" in m:
            out[f"{name} both"] = "error"
        else:
            out[f"{name} both"] = format_ci(m["both_exact"], m.get("both_exact_ci"))
    return out


def render(rows: dict, st: dict, agreement: dict | None = None) -> str:
    """Markdown report. Deliberately prints NO item text and NO per-item
    misses: reading the misses and adjusting a prompt is tuning, and spends
    the set. Per-item rows (ids only) are kept in the recorded JSON for audit."""
    lines = [
        "## Held-out sufficiency set - scored, never tuned against",
        "",
        f"**Labelled: {st['n_labelled']} of {st['n_items']} items** "
        f"(a headline needs >= {st['min_labelled']}). By persona: "
        + ", ".join(f"{p} {v['labelled']}/{v['items']}" for p, v in st["by_persona"].items())
        + ".",
        "",
        "Labels: `data/heldout/labels.jsonl` (the user's). Cells are `rate [95% CI]`, a "
        f"cluster bootstrap over **{len(st['by_persona'])} personas**; with so few clusters "
        "the percentile interval is too narrow, so read every number as directional. "
        "Per-item misses are deliberately not printed.",
        "",
        "| assessor | n (k) | specificity | within 1 | ownership | both |",
        "|---|---|---|---|---|---|",
    ]
    for name, m in rows.items():
        if "error" in m:
            lines.append(f"| {name} | - | FAILED: {m['error']} | | | |")
            continue
        cell = lambda k: format_ci(m.get(k), m.get(f"{k}_ci"))  # noqa: E731
        lines.append(f"| {name} | {m.get('n', '?')} (k={m.get('clusters', '?')}) | "
                     f"{cell('specificity_exact')} | {cell('specificity_within_1')} | "
                     f"{cell('ownership_exact')} | {cell('both_exact')} |")
    if agreement and agreement.get("n"):
        a = agreement
        fmt = lambda s: format_ci(s["rate"], s["ci"], s["n"])  # noqa: E731
        lines += [
            "",
            "**Author-intended rung vs the user's labels** (how far the set's design "
            "matches the labeller's reading; not an assessor score): "
            f"specificity {fmt(a['specificity'])}, ownership {fmt(a['ownership'])}, "
            f"both {fmt(a['both'])}; on items authored as boundary cases, both "
            f"{fmt(a['both_on_boundary_items'])}.",
        ]
    return "\n".join(lines) + "\n"
