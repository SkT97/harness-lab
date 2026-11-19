"""Convert Inspect AI JSON eval logs (EvalLog version 2) to the harness-lab CSV.

Fields follow the Inspect definitions: ``EvalSample.id`` and ``epoch``, the score
``value`` (``"C"`` correct, ``"I"`` incorrect), ``total_time`` and
``working_time``, ``model_usage`` and ``limit.type``. Inspect advises reading
logs through its own API; this reads the documented JSON text form so the
package needs no Inspect install. Binary ``.eval`` logs are not read: convert
them with ``inspect log convert --to json``.

Nothing is guessed. A score that is not plainly pass or fail, a log that did not
finish, or a completed sample without a time stops the conversion with every
offending sample named.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
from collections.abc import Sequence
from pathlib import Path

from .model import ALLOWED_LANGUAGES, REQUIRED_COLUMNS, parse_csv_text

_TIMEOUT_LIMITS = frozenset({"time", "working"})
_REPORTED_PROBLEMS = 5


class InspectError(ValueError):
    """A log cannot be converted without guessing."""


def _split_label(source: str) -> tuple[str | None, str]:
    label, separator, path = source.partition("=")
    if separator and label and not any(c in label for c in (os.sep, "/", ".")):
        return label, path
    return None, source


def _read_log(path: str) -> dict:
    name = Path(path).name
    if path.lower().endswith(".eval"):
        raise InspectError(
            f"{name}: binary .eval logs are not read; run: inspect log convert --to json {name}"
        )
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InspectError(f"{name}: cannot read a JSON log ({type(exc).__name__})") from exc
    if not isinstance(document, dict) or document.get("version") != 2:
        raise InspectError(f"{name}: not an Inspect EvalLog with version 2")
    spec = document.get("eval")
    if not isinstance(spec, dict) or not all(
        isinstance(spec.get(k), str) for k in ("task", "model")
    ):
        raise InspectError(f"{name}: the eval header has no task and model")
    if not isinstance(document.get("samples"), list) or not document["samples"]:
        raise InspectError(f"{name}: the log has no samples (header-only logs cannot be used)")
    return document


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _binary(value: object) -> bool | None:
    """True for "C", True and 1; False for "I", False and 0; None for anything else."""
    if isinstance(value, bool):
        return value
    if value == "C" or (_number(value) and value == 1):
        return True
    if value == "I" or (_number(value) and value == 0):
        return False
    return None


def _passed(sample: dict, score: str | None, excluded: bool) -> bool:
    scores = sample.get("scores")
    if not isinstance(scores, dict) or not scores:
        if excluded:
            return False
        raise InspectError("the sample has no scores")
    if score is None:
        if len(scores) > 1:
            raise InspectError(f"several scores ({', '.join(sorted(scores))}): choose with --score")
        score = next(iter(scores))
    if score not in scores:
        raise InspectError(f"no score named {score!r}")
    entry = scores[score]
    outcome = _binary(entry.get("value") if isinstance(entry, dict) else None)
    if outcome is None:
        if excluded:
            return False
        shown = entry.get("value") if isinstance(entry, dict) else entry
        raise InspectError(f"score {score!r} is {shown!r}, not plainly pass or fail")
    return outcome


def _seconds(sample: dict, excluded: bool) -> float:
    for key in ("total_time", "working_time"):
        value = sample.get(key)
        if _number(value) and math.isfinite(value) and value >= 0:
            return float(value)
    if excluded:
        return 0.0
    raise InspectError("no total_time or working_time on a completed sample")


def _tokens(sample: dict) -> tuple[int | None, int | None, int | None]:
    usage = sample.get("model_usage")
    if not isinstance(usage, dict) or not usage:
        return None, None, None
    fresh = cached = output = 0
    for entry in usage.values():
        if not isinstance(entry, dict):
            raise InspectError("model_usage entries must be objects")
        for key in ("input_tokens", "output_tokens"):
            if not _is_int(entry.get(key, 0)) or entry.get(key, 0) < 0:
                raise InspectError(f"model_usage {key} must be a non-negative integer")
        fresh += entry.get("input_tokens", 0)
        output += entry.get("output_tokens", 0)
        for key in ("input_tokens_cache_read", "input_tokens_cache_write"):
            extra = entry.get(key)
            if extra is not None:
                if not _is_int(extra) or extra < 0:
                    raise InspectError(f"model_usage {key} must be a non-negative integer")
                cached += extra
    return fresh, fresh + cached, output


def _row(entry_id: int, task: str, variant: str, language: str, sample: dict, score: str | None):
    sample_id, epoch = sample.get("id"), sample.get("epoch")
    if not (_is_int(sample_id) or isinstance(sample_id, str)):
        raise InspectError("the sample has no usable id")
    if not _is_int(epoch) or epoch < 0:
        raise InspectError("the sample has no usable epoch")
    limit = sample.get("limit")
    limit_type = limit.get("type") if isinstance(limit, dict) else None
    timed_out = limit_type in _TIMEOUT_LIMITS
    infra = sample.get("error") is not None or limit_type == "operator"
    excluded = timed_out or infra
    fresh, prompt_total, output = _tokens(sample)
    return [
        entry_id,
        f"{task}/{sample_id}",
        language,
        variant,
        epoch,
        str(_passed(sample, score, excluded)).lower(),
        repr(_seconds(sample, excluded)),
        "" if fresh is None else fresh,
        "" if prompt_total is None else prompt_total,
        "" if output is None else output,
        "false",
        str(infra).lower(),
        str(timed_out).lower(),
    ]


def inspect_to_csv(
    sources: Sequence[str],
    language: str,
    score: str | None = None,
    allow_incomplete: bool = False,
) -> str:
    """CSV text in the harness-lab contract for the given Inspect JSON logs.

    A source is ``PATH`` or ``LABEL=PATH``. The label becomes the variant; without
    one the variant is the model of the log.
    """
    if language not in ALLOWED_LANGUAGES:
        raise InspectError(f"language must be one of {', '.join(ALLOWED_LANGUAGES)}")
    rows, problems = [], []
    cells: set[tuple] = set()
    for source in sources:
        label, path = _split_label(source)
        document = _read_log(path)
        name = Path(path).name
        status = document.get("status")
        if status != "success" and not allow_incomplete:
            raise InspectError(f"{name}: status is {status!r}; use --allow-incomplete to read it")
        spec = document["eval"]
        variant = label or spec["model"]
        for sample in document["samples"]:
            if not isinstance(sample, dict):
                problems.append(f"{name}: a sample is not an object")
                continue
            where = f"{name} sample {sample.get('id')!r} epoch {sample.get('epoch')!r}"
            try:
                row = _row(len(rows) + 1, spec["task"], variant, language, sample, score)
            except InspectError as exc:
                problems.append(f"{where}: {exc}")
                continue
            cell = (row[1], row[3], row[4])  # task_id, variant, repeat
            if cell in cells:
                problems.append(
                    f"{where}: duplicate of an earlier sample for {cell[0]!r} / {cell[1]!r} / "
                    f"epoch {cell[2]} (label logs of the same model, ids 1 and '1' collide)"
                )
                continue
            cells.add(cell)
            rows.append(row)
    if problems:
        shown = "; ".join(problems[:_REPORTED_PROBLEMS])
        more = "; ..." if len(problems) > _REPORTED_PROBLEMS else ""
        raise InspectError(f"{len(problems)} sample(s) cannot be converted: {shown}{more}")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(REQUIRED_COLUMNS)
    writer.writerows(rows)
    text = buffer.getvalue()
    parse_csv_text(text, source="inspect conversion")  # never emit a file the contract rejects
    return text
