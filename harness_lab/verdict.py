"""verdict(): can this data tell two variants apart, and does that survive the exclusions?

The pass/fail outcomes of two variants are paired by (task_id, repeat). The
verdict is one of:

* ``distinguishable``: both exact tests (pairs and tasks) reject equality;
* ``bounded_null``: no difference detected and the confidence interval of the
  pass-rate difference lies inside +-margin, so a larger effect is ruled out;
* ``underpowered``: the data cannot tell; the report says how many tasks are
  needed when that can be estimated;
* ``no_pairs``: nothing to compare.

Time and token counters get a paired ratio per metric: an exact sign test over
tasks, adjusted for the number of metrics with Holm's method, and a
distribution-free interval for the median ratio.

It is then computed again with every excluded run counted as a failure. If the
two verdicts differ, the conclusion depends on the exclusion policy and says so.
No ranking across variants is produced.

Methods: exact McNemar test on discordant pairs (binomial, p = 0.5); exact sign
test on tasks, which stays valid when repeats of one task are correlated;
Newcombe (1998) method 10 for the paired difference in proportions; the number
of units needed starts from Connor (1987) and is raised until the exact power
reaches the target.
"""

from __future__ import annotations

import math
from statistics import NormalDist

from .compare import CompareError, compare
from .model import Run

_SCHEMA = "harness-lab/verdict/1"
_MAX_K = 10
_METRICS = ("wall_s", "tokens_input", "tokens_prompt_total", "tokens_output")


def exact_two_sided_p(only_left: int, only_right: int) -> float:
    """Two-sided exact binomial p-value on discordant counts under p = 0.5."""
    discordant = only_left + only_right
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(min(only_left, only_right) + 1))
    return min(1.0, 2 * tail / 2**discordant)


def _wilson(successes: int, n: int, z: float) -> tuple[float, float]:
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe_paired_ci(both: int, left: int, right: int, neither: int, z: float):
    """Newcombe (1998) method 10: CI for p_left - p_right from paired counts."""
    n = both + left + right + neither
    p1, p2 = (both + left) / n, (both + right) / n
    l1, u1 = _wilson(both + left, n, z)
    l2, u2 = _wilson(both + right, n, z)
    scale = (both + left) * (right + neither) * (both + right) * (left + neither)
    phi = 0.0
    if scale:
        s = both * neither - left * right
        if s > n / 2:
            s -= n / 2
        elif s >= 0:
            s = 0.0
        phi = s / math.sqrt(scale)
    lower = (p1 - p2) - math.sqrt(
        max(0.0, (p1 - l1) ** 2 + (u2 - p2) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2))
    )
    upper = (p1 - p2) + math.sqrt(
        max(0.0, (u1 - p1) ** 2 + (p2 - l2) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2))
    )
    return max(-1.0, lower), min(1.0, upper)


def _pmf(k: int, n: int, p: float) -> float:
    if p <= 0 or p >= 1:
        return float(k == (n if p >= 1 else 0))
    log = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    return math.exp(log + k * math.log(p) + (n - k) * math.log1p(-p))


def _critical(discordant: int, alpha: float) -> int:
    """Largest min(b, c) that the exact test still rejects with ``discordant`` pairs."""
    cumulative, critical = 0.0, -1
    for k in range(discordant // 2 + 1):
        cumulative += _pmf(k, discordant, 0.5)
        if 2 * cumulative >= alpha:
            break
        critical = k
    return critical


def exact_power(units: int, discordant_rate: float, margin: float, alpha: float) -> float:
    """Power of the exact McNemar test when p10 - p01 = margin and p10 + p01 = rate."""
    left_share = (discordant_rate + margin) / (2 * discordant_rate)
    spread = 8 * math.sqrt(units * discordant_rate * (1 - discordant_rate)) + 1
    centre = units * discordant_rate
    total = 0.0
    for m in range(max(0, int(centre - spread)), min(units, int(centre + spread)) + 1):
        critical = _critical(m, alpha)
        if critical < 0:
            continue
        reject = sum(_pmf(b, m, left_share) for b in range(critical + 1))
        reject += sum(_pmf(b, m, left_share) for b in range(m - critical, m + 1))
        total += _pmf(m, units, discordant_rate) * reject
    return total


MAX_PLANNED_UNITS = 3000


def units_needed(discordant_rate: float, margin: float, alpha: float, power: float) -> int | None:
    """Number of units for which the exact test reaches ``power``, or ``None``.

    Starts from Connor's (1987) normal approximation, which falls a little short,
    then gallops upward and bisects until the exact power reaches the target and
    one unit fewer does not. Returns ``None`` when the disagreement rate is below
    the margin (such an effect cannot exist) or when more than
    ``MAX_PLANNED_UNITS`` would be needed: the search is not attempted.
    """
    if discordant_rate < margin:
        return None
    z = NormalDist().inv_cdf
    root = z(1 - alpha / 2) * math.sqrt(discordant_rate) + z(power) * math.sqrt(
        discordant_rate - margin**2
    )
    low = math.ceil((root / margin) ** 2)
    if low > MAX_PLANNED_UNITS:
        return None

    def reaches(units: int) -> bool:
        return exact_power(units, discordant_rate, margin, alpha) >= power

    if reaches(low):
        return low
    step = 1
    while True:
        high = low + step
        if high > MAX_PLANNED_UNITS:
            return None
        if reaches(high):
            break
        low, step = high, step * 2
    while high - low > 1:
        middle = (low + high) // 2
        if reaches(middle):
            high = middle
        else:
            low = middle
    return high


def _task_counts(cells: list[tuple[str, int, bool, bool]]) -> dict:
    tasks: dict[str, list[tuple[bool, bool]]] = {}
    for task, _repeat, left, right in cells:
        tasks.setdefault(task, []).append((left, right))
    better = {"left": 0, "right": 0, "tied": 0}
    for outcomes in tasks.values():
        gap = sum(left - right for left, right in outcomes)
        better["left" if gap > 0 else "right" if gap < 0 else "tied"] += 1
    return {
        "tasks": len(tasks),
        "max_repeats_per_task": max((len(v) for v in tasks.values()), default=0),
        "left_better": better["left"],
        "right_better": better["right"],
        "tied": better["tied"],
    }


def _scenario(cells: list[tuple[str, int, bool, bool]], alpha: float, margin: float, power: float):
    n = len(cells)
    if n == 0:
        return {"pairs": 0, "class": "no_pairs", "direction": None, "reasons": ["no pairs"]}
    both = sum(1 for _, _, left, right in cells if left and right)
    only_left = sum(1 for _, _, left, right in cells if left and not right)
    only_right = sum(1 for _, _, left, right in cells if right and not left)
    neither = n - both - only_left - only_right
    tasks = _task_counts(cells)
    independent = tasks["max_repeats_per_task"] == 1
    z = NormalDist().inv_cdf(1 - alpha / 2)
    lower, upper = newcombe_paired_ci(both, only_left, only_right, neither, z)
    p_pairs = exact_two_sided_p(only_left, only_right)
    p_tasks = exact_two_sided_p(tasks["left_better"], tasks["right_better"])
    p_primary = max(p_pairs, p_tasks)
    pair_direction = (only_left > only_right) - (only_left < only_right)
    task_direction = (tasks["left_better"] > tasks["right_better"]) - (
        tasks["left_better"] < tasks["right_better"]
    )

    reasons: list[str] = []
    verdict, direction = "underpowered", None
    if p_primary < alpha and pair_direction == task_direction != 0:
        verdict = "distinguishable"
        direction = "left_better" if pair_direction > 0 else "right_better"
    elif p_primary < alpha:
        reasons.append("pair-level and task-level tests point in different directions")
    elif independent and lower > -margin and upper < margin:
        verdict = "bounded_null"
    elif not independent:
        reasons.append(
            "repeats of one task are correlated: a bounded null needs one repeat per task"
        )

    needed = None
    if verdict == "underpowered":
        discordant = tasks["left_better"] + tasks["right_better"]
        if discordant == 0:
            reasons.append("no task separates the variants: cannot estimate the units needed")
        else:
            rate = discordant / tasks["tasks"]
            needed = units_needed(rate, margin, alpha, power)
            if needed is None and rate < margin:
                reasons.append("the observed disagreement rate is below the margin")
            elif needed is None:
                reasons.append(f"more than {MAX_PLANNED_UNITS} tasks would be needed")

    return {
        "pairs": n,
        "counts": {
            "both_passed": both,
            "only_left_passed": only_left,
            "only_right_passed": only_right,
            "neither_passed": neither,
        },
        "informative_pairs": only_left + only_right,
        "saturated_pairs": both + neither,
        "tasks": tasks,
        "p_pairs_mcnemar_exact": p_pairs,
        "p_tasks_sign_exact": p_tasks,
        "p_value": p_primary,
        "difference_left_minus_right": (only_left - only_right) / n,
        "confidence_interval": [lower, upper],
        "interval_assumes_independent_pairs": independent,
        "class": verdict,
        "direction": direction,
        "units_needed_tasks": needed,
        "reasons": reasons,
    }


def _metric(pairs: list[dict], name: str, alpha: float) -> dict:
    """Paired ratio of one metric: exact sign test and a median interval over tasks.

    Repeats of a task are averaged on the log scale first, so the task is the
    unit. The interval comes from order statistics and assumes no distribution;
    it needs a minimum number of tasks to reach the requested level.
    """
    per_task: dict[str, list[float]] = {}
    available = set()
    for pair in pairs:
        available.add(pair["task_id"])
        left, right = pair["left"][name], pair["right"][name]
        if left is not None and right is not None and left > 0 and right > 0:
            per_task.setdefault(pair["task_id"], []).append(math.log(left / right))
    logs = sorted(sum(v) / len(v) for v in per_task.values())
    n = len(logs)
    result = {
        "tasks_available": len(available),
        "tasks_used": n,
        "tasks_without_ratio": len(available) - n,
        "pairs_used": sum(len(v) for v in per_task.values()),
        "min_tasks_for_interval": math.ceil(math.log2(2 / alpha)),
        "class": "no_data",
        "direction": None,
    }
    if n == 0:
        return result
    lower_left = sum(1 for x in logs if x < 0)
    lower_right = sum(1 for x in logs if x > 0)
    middle = n // 2
    median = logs[middle] if n % 2 else (logs[middle - 1] + logs[middle]) / 2
    cut, cumulative = 0, 0.0
    for index in range(n):
        cumulative += math.comb(n, index) / 2**n
        if cumulative > alpha / 2:
            break
        cut = index + 1
    result.update(
        {
            "left_lower": lower_left,
            "right_lower": lower_right,
            "ties": n - lower_left - lower_right,
            "p_sign_exact": exact_two_sided_p(lower_left, lower_right),
            "median_ratio_left_over_right": math.exp(median),
            "ratio_interval": [math.exp(logs[cut - 1]), math.exp(logs[n - cut])] if cut else None,
        }
    )
    return result


def holm_adjust(p_values: list[float]) -> list[float]:
    """Holm (1979) step-down adjustment, returned in the order given."""
    order = sorted(range(len(p_values)), key=lambda i: p_values[i])
    adjusted = [0.0] * len(p_values)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(p_values) - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


def _finish_metrics(metrics: dict[str, dict], alpha: float) -> None:
    """Holm step-down over the metrics that have data, then each class and statement.

    The metrics are tested together, so the p-value used for the class is
    adjusted for that number of tests (Holm 1979).
    """
    tested = [name for name, m in metrics.items() if m["tasks_used"]]
    for name, adjusted in zip(
        tested, holm_adjust([metrics[name]["p_sign_exact"] for name in tested]), strict=True
    ):
        metrics[name]["p_holm"] = adjusted
    for name, metric in metrics.items():
        if not metric["tasks_used"]:
            metric["statement"] = f"{name}: no task has a usable value on both sides."
            continue
        interval = metric["ratio_interval"]
        kind = "underpowered"
        if interval and metric["p_holm"] < alpha and (interval[0] > 1 or interval[1] < 1):
            kind = "distinguishable"
            metric["direction"] = "left_lower" if interval[1] < 1 else "right_lower"
        metric["class"] = kind
        span = (
            f"{(1 - alpha) * 100:g}% interval [{interval[0]:.3f}, {interval[1]:.3f}]"
            if interval
            else f"no interval below {metric['min_tasks_for_interval']} tasks"
        )
        metric["statement"] = (
            f"{name}: median ratio {metric['median_ratio_left_over_right']:.3f} over "
            f"{metric['tasks_used']} tasks ({metric['left_lower']} lower on the left, "
            f"{metric['right_lower']} on the right), exact p = {metric['p_sign_exact']:.3g}, "
            f"Holm-adjusted {metric['p_holm']:.3g} over {len(tested)} metrics, {span}; {kind}."
        )


def _reliability(rows: list[Run], variant: str) -> dict[str, dict]:
    """Unbiased pass^k per task, averaged over the tasks with at least k completed runs.

    For a task with s passes in n runs, pass^k is C(s, k) / C(n, k): the chance
    that k runs drawn without replacement all pass (the tau-bench estimator).
    """
    tasks: dict[str, list[bool]] = {}
    for run in rows:
        if run.variant == variant and not run.excluded:
            tasks.setdefault(run.task_id, []).append(run.passed)
    longest = min(max((len(v) for v in tasks.values()), default=0), _MAX_K)
    result = {}
    for k in range(1, longest + 1):
        values = [
            math.comb(sum(v), k) / math.comb(len(v), k) for v in tasks.values() if len(v) >= k
        ]
        result[str(k)] = {"tasks_used": len(values), "value": sum(values) / len(values)}
    return result


def _statement(result: dict, left: str, right: str, alpha: float, margin: float) -> str:
    kind = result["class"]
    if kind == "no_pairs":
        return "No shared completed (task, repeat) cell: nothing to compare."
    lower, upper = result["confidence_interval"]
    interval = f"{(1 - alpha) * 100:g}% CI [{lower:+.3f}, {upper:+.3f}]"
    if kind == "distinguishable":
        winner, other = (left, right) if result["direction"] == "left_better" else (right, left)
        return (
            f"{winner} passes more tasks than {other}: exact p = {result['p_value']:.3g} "
            f"(alpha {alpha:g}), difference {result['difference_left_minus_right']:+.3f}, {interval}."
        )
    if kind == "bounded_null":
        return f"No difference detected, and one larger than {margin:g} is ruled out: {interval}."
    needed = result["units_needed_tasks"]
    plan = f" About {needed} tasks would be needed." if needed else ""
    return (
        f"The data cannot tell {left} and {right} apart "
        f"({result['informative_pairs']} of {result['pairs']} pairs differ).{plan}"
    )


def verdict(
    rows: list[Run],
    left_variant: str,
    right_variant: str,
    alpha: float = 0.05,
    margin: float = 0.10,
    power: float = 0.80,
) -> dict:
    for name, value in (("alpha", alpha), ("margin", margin), ("power", power)):
        if not 0 < value < 1:
            raise CompareError(f"{name} must be between 0 and 1")
    base = compare(rows, left_variant, right_variant)
    completed = [
        (p["task_id"], p["repeat"], p["left"]["passed"], p["right"]["passed"])
        for p in base["pairs"]
    ]
    by_cell: dict[tuple[str, int], dict[str, list[Run]]] = {}
    for run in rows:
        if run.variant in (left_variant, right_variant):
            by_cell.setdefault(run.cell, {}).setdefault(run.variant, []).append(run)
    strict, ambiguous = [], 0
    for (task, repeat), sides in sorted(by_cell.items()):
        left, right = sides.get(left_variant, []), sides.get(right_variant, [])
        if not left or not right:
            continue
        if len(left) > 1 or len(right) > 1:
            ambiguous += 1
            continue
        strict.append(
            (
                task,
                repeat,
                left[0].passed and not left[0].excluded,
                right[0].passed and not right[0].excluded,
            )
        )
    metrics = {name: _metric(base["pairs"], name, alpha) for name in _METRICS}
    _finish_metrics(metrics, alpha)
    primary = _scenario(completed, alpha, margin, power)
    sensitivity = _scenario(strict, alpha, margin, power)
    excluded = base["rows"]["left"]["rows_excluded"] + base["rows"]["right"]["rows_excluded"]
    robust = (primary["class"], primary["direction"]) == (
        sensitivity["class"],
        sensitivity["direction"],
    )
    statement = _statement(primary, left_variant, right_variant, alpha, margin)
    if excluded and not robust:
        statement += " This depends on how excluded runs are treated: see sensitivity."
    return {
        "schema": _SCHEMA,
        "left": left_variant,
        "right": right_variant,
        "alpha": alpha,
        "margin": margin,
        "power": power,
        "verdict": primary["class"],
        "statement": statement,
        "primary": primary,
        "sensitivity": {
            "policy": "excluded runs count as failures",
            "ambiguous_cells_skipped": ambiguous,
            **sensitivity,
        },
        "excluded_rows": excluded,
        "robust_to_exclusions": robust,
        "metrics": metrics,
        "reliability": {
            "left": _reliability(rows, left_variant),
            "right": _reliability(rows, right_variant),
        },
        "notes": [
            "Primary policy: completed runs only, as in compare.",
            "No ranking: this compares one pair of variants on the tasks they share.",
            "Metrics use completed pairs only; a run excluded for infrastructure has no usable time.",
            "Public tasks may be familiar to a model; this measures these tasks, not a population.",
        ],
    }
