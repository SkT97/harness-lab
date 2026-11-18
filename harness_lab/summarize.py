"""summarize(): auditable aggregation over completed runs only.

Excluded rows (network_error / infra_error / timed_out) are counted and
broken down, but never enter any distribution, pass fraction, or ranking.
No global ranking is ever computed, and no relaxed/corrected score exists.
"""

from __future__ import annotations

from . import stats
from .model import Run

_SCHEMA = "harness-lab/summarize/1"
_FLAG_COLUMNS = ("network_error", "infra_error", "timed_out")
_METRIC_COLUMNS = ("wall_s", "tokens_input", "tokens_prompt_total", "tokens_output")

NOTES = [
    "Scores are raw pass/fail on completed runs; no relaxed or corrected score is computed.",
    "Missing token values stay missing: they are counted, never imputed as zero.",
]


def _metrics_block(rows: list[Run]) -> dict[str, dict]:
    return {m: stats.distribution([getattr(r, m) for r in rows]) for m in _METRIC_COLUMNS}


def summarize(rows: list[Run]) -> dict:
    rows = list(rows)
    completed = [r for r in rows if not r.excluded]
    warnings: list[str] = []

    exclusions = {flag: sum(1 for r in rows if getattr(r, flag)) for flag in _FLAG_COLUMNS}
    exclusions["any_flag"] = sum(1 for r in rows if r.excluded)
    exclusions["multiple_flags"] = sum(1 for r in rows if len(r.exclusion_flags) > 1)

    variants: dict[str, dict] = {}
    per_variant_tasks: dict[str, set[str]] = {}
    for name in sorted({r.variant for r in rows}):
        vrows = [r for r in rows if r.variant == name]
        vdone = [r for r in vrows if not r.excluded]
        passed = sum(1 for r in vdone if r.passed)
        tasks = sorted({r.task_id for r in vdone})
        per_variant_tasks[name] = set(tasks)

        cells: dict[tuple[str, int], int] = {}
        for r in vdone:
            cells[r.cell] = cells.get(r.cell, 0) + 1
        duplicates = sum(1 for count in cells.values() if count > 1)
        if duplicates:
            warnings.append(
                f"duplicate (task_id, repeat) cells for variant '{name}': "
                f"{duplicates} (reported, not resolved by picking fastest/best)"
            )

        block: dict = {
            "rows_total": len(vrows),
            "rows_completed": len(vdone),
            "rows_excluded": len(vrows) - len(vdone),
            "passed": passed,
            "failed": len(vdone) - passed,
            "pass_fraction": passed / len(vdone) if vdone else None,
            "samples_completed": len(vdone),
            "unique_tasks_completed": len(tasks),
            "tasks_completed": tasks,
            "duplicate_cells": duplicates,
            "relaxed_score": None,
        }
        block.update(_metrics_block(vdone))
        variants[name] = block

    languages: dict[str, dict] = {}
    for language in sorted({r.language for r in rows}):
        lrows = [r for r in rows if r.language == language]
        ldone = [r for r in lrows if not r.excluded]
        languages[language] = {
            "rows_total": len(lrows),
            "rows_completed": len(ldone),
            "tasks_completed": len({r.task_id for r in ldone}),
            "variants": sorted({r.variant for r in lrows}),
        }

    overall_passed = sum(1 for r in completed if r.passed)
    overall: dict = {
        "passed": overall_passed,
        "failed": len(completed) - overall_passed,
        "pass_fraction": overall_passed / len(completed) if completed else None,
    }
    overall.update(_metrics_block(completed))

    if not per_variant_tasks:
        identical = False
        common: list[str] = []
        reason = "no rows supplied; no ranking is possible"
    else:
        task_sets = [per_variant_tasks[n] for n in sorted(per_variant_tasks)]
        identical = all(s == task_sets[0] for s in task_sets[1:])
        common = sorted(set.intersection(*task_sets))
        if identical:
            reason = "no global ranking is ever computed by this tool"
        else:
            reason = "unequal task sets across variants; no global ranking is computed"

    if not rows:
        warnings.append("no rows supplied; all numbers are empty")
    elif not identical:
        warnings.append("unequal task sets across variants; no global ranking is computed")

    return {
        "schema": _SCHEMA,
        "percentile_method": stats.PERCENTILE_METHOD,
        "filter": {
            "measures": "completed runs only (not reliability, not retry quality)",
            "excludes": list(_FLAG_COLUMNS),
        },
        "counts": {
            "rows_total": len(rows),
            "rows_completed": len(completed),
            "rows_excluded": len(rows) - len(completed),
            "tasks_total": len({r.task_id for r in rows}),
            "tasks_completed": len({r.task_id for r in completed}),
            "variants_total": len(per_variant_tasks),
            "exclusions": exclusions,
        },
        "variants": variants,
        "languages": languages,
        "overall": overall,
        "task_sets": {
            "identical_across_variants": identical,
            "common_tasks_completed": common,
        },
        "ranking": {"ranking": None, "allowed": False, "reason": reason},
        "warnings": warnings,
        "notes": list(NOTES),
    }
