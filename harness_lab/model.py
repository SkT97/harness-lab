"""Input contract: the public CSV columns, per-cell validation, and Run."""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from pathlib import Path

REQUIRED_COLUMNS = (
    "entry_id",
    "task_id",
    "language",
    "variant",
    "repeat",
    "passed",
    "wall_s",
    "tokens_input",
    "tokens_prompt_total",
    "tokens_output",
    "network_error",
    "infra_error",
    "timed_out",
)

ALLOWED_LANGUAGES = ("Java", "Python", "TypeScript")

_TRUTHY = {"true", "1", "yes", "y"}
_FALSY = {"false", "0", "no", "n"}


class ValidationError(Exception):
    """The input CSV violates the documented contract.

    Carries every individual error in :attr:`errors` and names the source.
    """

    def __init__(self, errors: list[str], source: str) -> None:
        self.errors = list(errors)
        self.source = source
        super().__init__(f"invalid input for {source}: " + "; ".join(self.errors))


@dataclass(frozen=True)
class Run:
    """One completed-or-excluded execution of one task repeat."""

    entry_id: int
    task_id: str
    language: str
    variant: str
    repeat: int
    passed: bool
    wall_s: float
    tokens_input: int | None
    tokens_prompt_total: int | None
    tokens_output: int | None
    network_error: bool
    infra_error: bool
    timed_out: bool

    @property
    def exclusion_flags(self) -> tuple[str, ...]:
        flags = []
        if self.network_error:
            flags.append("network_error")
        if self.infra_error:
            flags.append("infra_error")
        if self.timed_out:
            flags.append("timed_out")
        return tuple(flags)

    @property
    def excluded(self) -> bool:
        return bool(self.exclusion_flags)

    @property
    def cell(self) -> tuple[str, int]:
        """The pairing identity: exact (task_id, repeat)."""
        return (self.task_id, self.repeat)


def _parse_bool(value: str) -> bool:
    key = value.strip().lower()
    if key in _TRUTHY:
        return True
    if key in _FALSY:
        return False
    raise ValueError(f"not a boolean: {value!r}")


def _parse_int(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"not an integer: {value!r}") from exc


def _parse_wall(value: str) -> float:
    try:
        number = float(value.strip())
    except ValueError as exc:
        raise ValueError(f"not a number: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"not finite: {value!r}")
    if number < 0:
        raise ValueError(f"negative: {value!r}")
    return number


def _parse_tokens(value: str) -> int | None:
    key = value.strip()
    if key == "":
        return None
    number = _parse_int(key)
    if number < 0:
        raise ValueError(f"negative: {value!r}")
    return number


def _parse_row(raw: list[str], line: int, seen_entry_ids: dict[int, int]) -> Run:
    errors: list[str] = []

    def bad(field: str, message: str) -> None:
        errors.append(f"line {line}: {field}: {message}")

    values = dict(zip(REQUIRED_COLUMNS, raw, strict=True))

    try:
        entry_id = _parse_int(values["entry_id"])
        if entry_id < 1:
            errors.append(f"line {line}: entry_id: must be >= 1, got {entry_id}")
        elif entry_id in seen_entry_ids:
            errors.append(
                f"duplicate entry_id {entry_id} at line {seen_entry_ids[entry_id]} and line {line}"
            )
        else:
            seen_entry_ids[entry_id] = line
    except ValueError as exc:
        bad("entry_id", str(exc))

    task_id = values["task_id"].strip()
    if not task_id:
        bad("task_id", "missing")

    language = values["language"].strip()
    if language not in ALLOWED_LANGUAGES:
        allowed = ", ".join(ALLOWED_LANGUAGES)
        bad("language", f"must be one of {allowed} (got {language!r})")

    variant = values["variant"].strip()
    if not variant:
        bad("variant", "missing")

    try:
        repeat = _parse_int(values["repeat"])
        if repeat < 0:
            errors.append(f"line {line}: repeat: must be >= 0, got {repeat}")
    except ValueError as exc:
        bad("repeat", str(exc))

    try:
        passed = _parse_bool(values["passed"])
    except ValueError as exc:
        bad("passed", str(exc))

    try:
        wall_s = _parse_wall(values["wall_s"])
    except ValueError as exc:
        bad("wall_s", str(exc))

    tokens: dict[str, int | None] = {}
    for column in ("tokens_input", "tokens_prompt_total", "tokens_output"):
        try:
            tokens[column] = _parse_tokens(values[column])
        except ValueError as exc:
            bad(column, str(exc))

    flags: dict[str, bool] = {}
    for column in ("network_error", "infra_error", "timed_out"):
        try:
            flags[column] = _parse_bool(values[column])
        except ValueError as exc:
            bad(column, str(exc))

    if errors:
        raise _RowRejected(errors)

    return Run(
        entry_id=entry_id,
        task_id=task_id,
        language=language,
        variant=variant,
        repeat=repeat,
        passed=passed,
        wall_s=wall_s,
        tokens_input=tokens["tokens_input"],
        tokens_prompt_total=tokens["tokens_prompt_total"],
        tokens_output=tokens["tokens_output"],
        network_error=flags["network_error"],
        infra_error=flags["infra_error"],
        timed_out=flags["timed_out"],
    )


class _RowRejected(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("row rejected")
        self.errors = errors


def parse_csv_text(text: str, source: str = "<text>") -> list[Run]:
    """Parse the public CSV shape into Run objects, reporting every bad cell."""
    if not text.strip():
        raise ValidationError(["input is empty (no header)"], source)

    reader = csv.reader(io.StringIO(text))
    lines = [row for row in reader]
    header = [cell.strip() for cell in lines[0]]

    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    unknown = [c for c in header if c not in REQUIRED_COLUMNS]
    duplicate = len(header) != len(set(header))
    if missing or unknown or duplicate:
        errors = []
        if duplicate:
            errors.append("duplicate column names")
        if missing:
            errors.append("missing column(s): " + ", ".join(missing))
        if unknown:
            errors.append("unknown column(s): " + ", ".join(unknown))
        raise ValidationError(errors, source)

    errors: list[str] = []
    seen_entry_ids: dict[int, int] = {}
    runs: list[Run] = []
    for offset, raw in enumerate(lines[1:], start=2):
        if not any(cell.strip() for cell in raw):
            continue  # blank line
        if len(raw) != len(REQUIRED_COLUMNS):
            errors.append(f"line {offset}: expected {len(REQUIRED_COLUMNS)} fields, got {len(raw)}")
            continue
        try:
            ordered = [raw[header.index(column)] for column in REQUIRED_COLUMNS]
            runs.append(_parse_row(ordered, offset, seen_entry_ids))
        except _RowRejected as rejected:
            errors.extend(rejected.errors)

    languages = {}
    for run in runs:
        previous = languages.setdefault(run.task_id, run.language)
        if previous != run.language:
            errors.append(
                f"task {run.task_id}: inconsistent language {previous} versus {run.language}"
            )
    if errors:
        raise ValidationError(errors, source)
    return runs


def load_csv(path: str) -> list[Run]:
    """Read a CSV file (utf-8, optional BOM) and validate it."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ValidationError([f"cannot read file: {exc}"], path) from exc
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError([f"file is not valid utf-8: {exc}"], path) from exc
    return parse_csv_text(text, source=path)
