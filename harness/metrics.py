"""Metrics: ASR, FPR, Wilson 95% CIs, latency aggregates (CLAUDE.md Section 9).

ASR (attack success rate) is the proportion of k repeats in which an
attack scored as success. FPR (false positive rate) is the proportion
of benign workload items CapGuard incorrectly blocked. Both are reported
with Wilson 95% confidence intervals.

Latency: per-tool-call wall time, summarized as median + p95.

This module is pure-stdlib + math; no scipy dependency required for the
Wilson interval (it's a closed-form expression).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# 95% two-sided z-score.
Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Proportion:
    successes: int
    n: int

    @property
    def rate(self) -> float:
        return self.successes / self.n if self.n else float("nan")

    def wilson_ci(self, z: float = Z_95) -> tuple[float, float]:
        """Two-sided Wilson score interval for a binomial proportion.
        Returns (lo, hi) at the given z. Falls back to (0, 0) when n=0.
        """
        n = self.n
        if n == 0:
            return (0.0, 0.0)
        p = self.successes / n
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
        return (max(0.0, center - half), min(1.0, center + half))

    def fmt(self) -> str:
        lo, hi = self.wilson_ci()
        return f"{self.rate:.3f} ({lo:.3f}–{hi:.3f}) [n={self.n}]"


def aggregate_runs(summary_paths: Iterable[Path]) -> dict[str, Proportion]:
    """Read run summary.jsonl files and group ASR by (scenario, attack_id, config).

    The summary records emitted by harness.run_attack.run_k carry
    attack_success per run. Group key here is `path stem`-based and
    cell-tagged at a higher level; this helper just rolls up by the
    grouping key supplied by callers.
    """
    rolled: dict[str, list[bool]] = {}
    for p in summary_paths:
        for line in Path(p).read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            key = rec.get("group_key", "default")
            rolled.setdefault(key, []).append(bool(rec.get("attack_success")))
    return {k: Proportion(successes=sum(v), n=len(v)) for k, v in rolled.items()}


def latency_summary(latencies_ms: list[float]) -> dict[str, float]:
    if not latencies_ms:
        return {"n": 0, "median_ms": float("nan"), "p95_ms": float("nan"),
                "mean_ms": float("nan")}
    sl = sorted(latencies_ms)
    n = len(sl)

    def quantile(q: float) -> float:
        if n == 1:
            return sl[0]
        # nearest-rank
        idx = int(math.ceil(q * n)) - 1
        return sl[max(0, min(n - 1, idx))]

    return {
        "n": n,
        "median_ms": quantile(0.50),
        "p95_ms": quantile(0.95),
        "mean_ms": sum(sl) / n,
    }
