"""Quantiles with one fixed, stated method: R type 7, linear interpolation.

Missing values (None) are counted and excluded from the observations;
they are never imputed as zero.
"""

from __future__ import annotations

PERCENTILE_METHOD = "R type 7 (linear interpolation)"


def percentile(values: list[float], p: float) -> float | None:
    """The p-th percentile of non-missing values, or None when there are none."""
    if not 0 <= p <= 100:
        raise ValueError(f"percentile must be in [0, 100], got {p}")
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    if n == 1:
        return ordered[0]
    h = (n - 1) * p / 100.0
    lo = int(h)
    hi = min(lo + 1, n - 1)
    return ordered[lo] + (h - lo) * (ordered[hi] - ordered[lo])


def distribution(values: list[float | None]) -> dict:
    """n, missing count, and p50/p95 for a possibly sparse list of values."""
    present = [v for v in values if v is not None]
    missing = len(values) - len(present)
    return {
        "n": len(present),
        "missing": missing,
        "p50": percentile(present, 50),
        "p95": percentile(present, 95),
    }
