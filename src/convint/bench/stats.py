"""Cluster-bootstrap confidence intervals for benchmark rates.

Why cluster, not item: items drawn from one transcript (or one bank topic)
share a persona, a voice and often literally the same text, so they are not
independent draws. Resampling items would treat 92 correlated turns as 92
independent observations and print intervals that are far too narrow. The
honest unit is the cluster - the transcript - so the bootstrap resamples whole
clusters with replacement and recomputes the statistic over the pooled items
of the resample. The effective n is then close to the number of clusters, and
the interval width says so.

Stdlib only (no numpy dependency), and deterministic: every call builds its own
`random.Random(seed)`, so the same inputs and seed give the same interval.

The interval is the plain percentile interval of the bootstrap distribution.
With few clusters (k < ~10) it is known to be too narrow; it is reported
anyway because a too-narrow interval next to `k` is still far more honest than
a bare point estimate, and `k` is always printed beside it.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Hashable, Mapping, Sequence

Number = float | int | bool
Stat = Callable[[Sequence[float]], float]


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _group(values: Sequence[Number], cluster_ids: Sequence[Hashable]) -> dict:
    if len(values) != len(cluster_ids):
        raise ValueError(
            f"values and cluster_ids differ in length ({len(values)} vs {len(cluster_ids)})"
        )
    grouped: dict = {}
    for value, cid in zip(values, cluster_ids):
        grouped.setdefault(cid, []).append(float(value))
    return grouped


def _quantile(sorted_xs: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile of an already sorted, non-empty list."""
    pos = q * (len(sorted_xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_xs) - 1)
    frac = pos - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def cluster_bootstrap_ci(
    values: Mapping[Hashable, Sequence[Number]] | Sequence[Number],
    cluster_ids: Sequence[Hashable] | None = None,
    *,
    stat: Stat | None = None,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float | None, float | None, float | None]:
    """Return `(point, lo, hi)` for `stat` under a cluster bootstrap.

    Input is either a mapping `{cluster_id: [values...]}` or a flat sequence
    of values with a parallel `cluster_ids` sequence. Values are typically
    0/1 hit flags, so the default statistic (the pooled mean) is a rate.

    Only clusters that contribute at least one value take part. For a rate
    with a restricted denominator (e.g. premature advance, counted only on
    must-follow-up items) that is the right population: a transcript with no
    eligible items carries no information about that rate.

    Edge cases, all without raising:
      - no values at all (a rate whose denominator is 0): `(None, None, None)`
      - a single cluster: `(point, None, None)`. Resampling one cluster always
        returns that cluster, so the bootstrap would print a zero-width
        interval - a false claim of certainty. No interval is the honest answer.
    """
    if cluster_ids is None:
        if not isinstance(values, Mapping):
            raise TypeError("pass a {cluster: values} mapping, or values with cluster_ids")
        grouped = {k: [float(v) for v in vs] for k, vs in values.items()}
    else:
        grouped = _group(values, cluster_ids)  # type: ignore[arg-type]

    clusters = [vs for vs in grouped.values() if vs]
    if not clusters:
        return None, None, None

    pooled = [v for vs in clusters for v in vs]
    point = mean(pooled) if stat is None else stat(pooled)
    if len(clusters) < 2:
        return point, None, None

    rng = random.Random(seed)
    k = len(clusters)
    boot: list[float] = []

    if stat is None:
        # Fast path for the pooled mean: a ratio of summed cluster totals,
        # which avoids rebuilding the pooled list on every resample.
        sums = [sum(vs) for vs in clusters]
        counts = [len(vs) for vs in clusters]
        for _ in range(n_boot):
            draw = [rng.randrange(k) for _ in range(k)]
            boot.append(sum(sums[i] for i in draw) / sum(counts[i] for i in draw))
    else:
        for _ in range(n_boot):
            draw = [rng.randrange(k) for _ in range(k)]
            boot.append(stat([v for i in draw for v in clusters[i]]))

    boot.sort()
    return point, _quantile(boot, alpha / 2), _quantile(boot, 1 - alpha / 2)


def rate_summary(
    flags: Sequence[Number], cluster_ids: Sequence[Hashable], **kwargs,
) -> dict:
    """A rate with everything needed to read it: point, CI, n and k.

    `ci` is `[lo, hi]`, or `None` when no interval can be computed (n = 0 or
    a single cluster). `rate` is `None` when the denominator is 0.
    """
    point, lo, hi = cluster_bootstrap_ci(flags, cluster_ids, **kwargs)
    return {
        "rate": point,
        "ci": None if lo is None else [lo, hi],
        "n": len(flags),
        "k": len(set(cluster_ids)),
    }


def format_ci(rate: float | None, ci: Sequence[float] | None = None,
              n: int | None = None, k: int | None = None,
              unit: str = "transcripts") -> str:
    """Render e.g. `77% [68–85] n=92 (k=11 transcripts)`.

    Pass only `rate` and `ci` for a compact table cell (`77% [68–85]`); the
    n/k suffix is appended only when given. A missing interval renders as
    `[—]` so it cannot be mistaken for a zero-width one.
    """
    if rate is None:
        out = "n/a"
    else:
        out = f"{rate:.0%}"
        out += f" [{ci[0]*100:.0f}–{ci[1]*100:.0f}]" if ci else " [—]"
    if n is not None:
        out += f" n={n}"
    if k is not None:
        out += f" (k={k} {unit})" if n is not None else f" k={k}"
    return out
