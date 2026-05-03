"""Tests for harness/metrics.py: Wilson 95% CI computation."""

from __future__ import annotations

import math

from harness.metrics import Proportion, latency_summary


def test_wilson_ci_zero_n():
    p = Proportion(0, 0)
    assert p.wilson_ci() == (0.0, 0.0)


def test_wilson_ci_all_success():
    # 10/10 should have a non-trivial lower bound, not collapse to (1.0, 1.0).
    p = Proportion(10, 10)
    lo, hi = p.wilson_ci()
    assert math.isclose(hi, 1.0, abs_tol=1e-9)
    assert lo > 0.69 and lo < 0.73  # ~0.7225


def test_wilson_ci_half():
    # 5/10 ~ (0.237, 0.763)
    p = Proportion(5, 10)
    lo, hi = p.wilson_ci()
    assert math.isclose(lo, 0.237, abs_tol=0.005)
    assert math.isclose(hi, 0.763, abs_tol=0.005)


def test_latency_summary_basic():
    s = latency_summary([10, 20, 30, 40, 50])
    assert s["n"] == 5
    assert s["median_ms"] == 30
    assert s["mean_ms"] == 30
    # nearest-rank p95 of 5 values = ceil(0.95*5)-1 = 5-1 = idx 4 (value 50)
    assert s["p95_ms"] == 50


def test_latency_summary_empty():
    s = latency_summary([])
    assert s["n"] == 0
    assert math.isnan(s["median_ms"])
