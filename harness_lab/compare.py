"""compare(): exact (task_id, repeat) pairing between two variants.

Duplicate cells that have a counterpart are a hard error: no fastest or
best row is ever quietly chosen. Each metric keeps its own denominator of
pairs with a common observation; missing values are counted, not imputed.
"""

from __future__ import annotations

from .model import Run

_SCHEMA = "harness-lab/compare/1"
_METRIC_COLUMNS = ("wall_s", "tokens_input", "tokens_prompt_total", "tokens_output")
_SMALL_SAMPLE = 30

NOTES = [
    "Measures completed runs only; excluded rows never enter pairing or denominators.",
    "Missing token values stay missing: each metric keeps its own denominator; nothing is imputed.",
]


class CompareError(Exception):
    """The comparison cannot be run as requested."""


class AmbiguousPairingError(CompareError):
    """A (task_id, repeat) cell is duplicated on a side that has a counterpart."""


def _side(run: Run) -> dict:
    return {
        "passed": run.passed,
        "wall_s": run.wall_s,
        "tokens_input": run.tokens_input,
        "tokens_prompt_total": run.tokens_prompt_total,
        "tokens_output": run.tokens_output,
    }


def _cell_map(rows: list[Run]) -> dict[tuple[str, int], list[Run]]:
    cells: dict[tuple[str, int], list[Run]] = {}
    for r in rows:
        cells.setdefault(r.cell, []).append(r)
    return cells


def _paired_metric(pairs: list[dict], metric: str) -> dict:
    values = [(p["left"][metric], p["right"][metric]) for p in pairs]
    usable = [(x, y) for x, y in values if x is not None and y is not None]
    used = len(usable)
    sum_left = sum(x for x, _ in usable)
    sum_right = sum(y for _, y in usable)
    mean_left = sum_left / used if used else None
    mean_right = sum_right / used if used else None

    if used == 0:
        comparable = False
        reason = "no pairs" if not values else "no common observation for this metric"
    elif sum_right <= 0:
        comparable = False
        reason = "zero denominator on the right side; a ratio would be infinite"
    else:
        comparable = True
        reason = None

    return {
        "pairs_available": len(values),
        "pairs_used": used,
        "denominator": used,
        "pairs_missing_observation": len(values) - used,
        "sum_left": float(sum_left),
        "sum_right": float(sum_right),
        "mean_left": mean_left,
        "mean_right": mean_right,
        "ratio_left_over_right": (sum_left / sum_right) if comparable else None,
        "comparable": comparable,
        "reason": reason,
    }


def compare(rows: list[Run], left_variant: str, right_variant: str) -> dict:
    if left_variant == right_variant:
        raise CompareError("left and right variants must differ")

    left_rows = [r for r in rows if r.variant == left_variant]
    right_rows = [r for r in rows if r.variant == right_variant]
    languages = {}
    for run in left_rows + right_rows:
        previous = languages.setdefault(run.task_id, run.language)
        if previous != run.language:
            raise CompareError(f"task {run.task_id}: inconsistent language")
    left_done = [r for r in left_rows if not r.excluded]
    right_done = [r for r in right_rows if not r.excluded]
    left_cells = _cell_map(left_done)
    right_cells = _cell_map(right_done)

    for task, repeat in sorted(set(left_cells) & set(right_cells)):
        cell = (task, repeat)
        if len(left_cells[cell]) > 1 or len(right_cells[cell]) > 1:
            raise AmbiguousPairingError(
                f"ambiguous pairing at {task}/r{repeat}: duplicate (task_id, repeat) "
                "cells on at least one side; refusing to pick the fastest or best row"
            )

    pairs: list[dict] = []
    for task, repeat in sorted(set(left_cells) & set(right_cells)):
        left, right = left_cells[(task, repeat)][0], right_cells[(task, repeat)][0]
        pairs.append(
            {
                "task_id": left.task_id,
                "repeat": left.repeat,
                "language": left.language,
                "left": _side(left),
                "right": _side(right),
            }
        )

    left_unpaired = sum(len(v) for c, v in left_cells.items() if c not in right_cells)
    right_unpaired = sum(len(v) for c, v in right_cells.items() if c not in left_cells)

    left_tasks = sorted({r.task_id for r in left_done})
    right_tasks = sorted({r.task_id for r in right_done})
    left_only = sorted(set(left_tasks) - set(right_tasks))
    right_only = sorted(set(right_tasks) - set(left_tasks))
    shared_tasks = sorted(set(left_tasks) & set(right_tasks))
    identical_task_sets = bool(left_tasks) and left_tasks == right_tasks

    n = len(pairs)
    left_passed = sum(1 for p in pairs if p["left"]["passed"])
    right_passed = sum(1 for p in pairs if p["right"]["passed"])
    paired_success = {
        "pairs": n,
        "left_passed": left_passed,
        "left_failed": n - left_passed,
        "right_passed": right_passed,
        "right_failed": n - right_passed,
        "both_passed": sum(1 for p in pairs if p["left"]["passed"] and p["right"]["passed"]),
        "only_left_passed": sum(
            1 for p in pairs if p["left"]["passed"] and not p["right"]["passed"]
        ),
        "only_right_passed": sum(
            1 for p in pairs if not p["left"]["passed"] and p["right"]["passed"]
        ),
        "neither_passed": sum(
            1 for p in pairs if not p["left"]["passed"] and not p["right"]["passed"]
        ),
        "left_pass_fraction": left_passed / n if n else None,
        "right_pass_fraction": right_passed / n if n else None,
    }

    warnings: list[str] = []
    if not left_rows:
        warnings.append(f"variant '{left_variant}' has no rows in the input")
    if not right_rows:
        warnings.append(f"variant '{right_variant}' has no rows in the input")
    if not pairs:
        warnings.append("no pairs: the two variants share no completed (task_id, repeat) cell")
    elif n < _SMALL_SAMPLE:
        warnings.append(f"Small sample: only {n} paired cells; treat the numbers as unstable")
    if left_only or right_only:
        warnings.append(
            "unshared completed tasks "
            f"(left-only: {left_only or 'none'}, right-only: {right_only or 'none'}); "
            "pairing covers shared cells only"
        )
    warnings.append("No universal winner: no aggregate score or global ranking is computed")

    return {
        "schema": _SCHEMA,
        "left": left_variant,
        "right": right_variant,
        "comparable": bool(pairs),
        "pairs": pairs,
        "pairing": {
            "method": "exact (task_id, repeat) pairing; duplicates with a "
            "counterpart are rejected, never resolved by fastest/best",
            "pairs": n,
            "left_unpaired_completed": left_unpaired,
            "right_unpaired_completed": right_unpaired,
        },
        "task_coverage": {
            "shared_tasks_completed": shared_tasks,
            "left_only_tasks_completed": left_only,
            "right_only_tasks_completed": right_only,
            "identical_task_sets": identical_task_sets,
        },
        "rows": {
            "left": {
                "rows_total": len(left_rows),
                "rows_completed": len(left_done),
                "rows_excluded": len(left_rows) - len(left_done),
            },
            "right": {
                "rows_total": len(right_rows),
                "rows_completed": len(right_done),
                "rows_excluded": len(right_rows) - len(right_done),
            },
        },
        "paired_success": paired_success,
        "paired_metrics": {m: _paired_metric(pairs, m) for m in _METRIC_COLUMNS},
        "warnings": warnings,
        "notes": list(NOTES),
    }
