"""Shared helpers for the test-suite. Everything here is synthetic data."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from harness_lab.model import Run

#: Written out by hand (not imported from the package) so that a change of the
#: public column contract cannot silently keep the tests green.
HEADER = (
    "entry_id,task_id,language,variant,repeat,passed,wall_s,tokens_input,"
    "tokens_prompt_total,tokens_output,network_error,infra_error,timed_out"
)


def row(
    entry_id: int,
    task_id: str,
    language: str,
    variant: str,
    repeat: int,
    *,
    passed: bool = True,
    wall_s: float = 1.0,
    tokens_input: int | None = 10,
    tokens_prompt_total: int | None = 20,
    tokens_output: int | None = 5,
    network_error: bool = False,
    infra_error: bool = False,
    timed_out: bool = False,
) -> Run:
    return Run(
        entry_id=entry_id,
        task_id=task_id,
        language=language,
        variant=variant,
        repeat=repeat,
        passed=passed,
        wall_s=wall_s,
        tokens_input=tokens_input,
        tokens_prompt_total=tokens_prompt_total,
        tokens_output=tokens_output,
        network_error=network_error,
        infra_error=infra_error,
        timed_out=timed_out,
    )


def csv_text(rows: Iterable[Run]) -> str:
    """Render runs back into the public CSV shape."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADER.split(","))
    for r in rows:
        writer.writerow(
            [
                r.entry_id,
                r.task_id,
                r.language,
                r.variant,
                r.repeat,
                "true" if r.passed else "false",
                repr(float(r.wall_s)),
                "" if r.tokens_input is None else r.tokens_input,
                "" if r.tokens_prompt_total is None else r.tokens_prompt_total,
                "" if r.tokens_output is None else r.tokens_output,
                "true" if r.network_error else "false",
                "true" if r.infra_error else "false",
                "true" if r.timed_out else "false",
            ]
        )
    return buf.getvalue()


def fixture_rows() -> list[Run]:
    """The comparison fixture used by test_compare / test_cli.

    Hand-designed so every expected number is computable on paper:
      agent-a completed: T01/r1 (pass, 10s), T02/r1 (fail, 20s),
                         T03/r1 (pass, 30s), T04/r2 (pass, 40s, no tokens)
      agent-a excluded:  T01/r2 (timed_out)
      agent-b completed: T01/r1 (pass, 20s), T02/r1 (pass, 10s),
                         T03/r1 (fail, 60s, no tokens_input), T05/r2 (pass, 5s)
      agent-b excluded:  T05/r1 (infra_error)
    """
    return [
        row(
            1,
            "T01",
            "Python",
            "agent-a",
            1,
            passed=True,
            wall_s=10.0,
            tokens_input=100,
            tokens_prompt_total=200,
            tokens_output=50,
        ),
        row(
            2,
            "T02",
            "Java",
            "agent-a",
            1,
            passed=False,
            wall_s=20.0,
            tokens_input=200,
            tokens_prompt_total=400,
            tokens_output=100,
        ),
        row(
            3,
            "T03",
            "TypeScript",
            "agent-a",
            1,
            passed=True,
            wall_s=30.0,
            tokens_input=300,
            tokens_prompt_total=600,
            tokens_output=150,
        ),
        row(
            4,
            "T04",
            "Python",
            "agent-a",
            2,
            passed=True,
            wall_s=40.0,
            tokens_input=None,
            tokens_prompt_total=None,
            tokens_output=None,
        ),
        row(
            5,
            "T01",
            "Python",
            "agent-a",
            2,
            passed=False,
            wall_s=99.0,
            tokens_input=900,
            tokens_prompt_total=900,
            tokens_output=900,
            timed_out=True,
        ),
        row(
            6,
            "T01",
            "Python",
            "agent-b",
            1,
            passed=True,
            wall_s=20.0,
            tokens_input=120,
            tokens_prompt_total=240,
            tokens_output=60,
        ),
        row(
            7,
            "T02",
            "Java",
            "agent-b",
            1,
            passed=True,
            wall_s=10.0,
            tokens_input=100,
            tokens_prompt_total=200,
            tokens_output=50,
        ),
        row(
            8,
            "T03",
            "TypeScript",
            "agent-b",
            1,
            passed=False,
            wall_s=60.0,
            tokens_input=None,
            tokens_prompt_total=500,
            tokens_output=200,
        ),
        row(
            9,
            "T05",
            "Python",
            "agent-b",
            2,
            passed=True,
            wall_s=5.0,
            tokens_input=30,
            tokens_prompt_total=60,
            tokens_output=15,
        ),
        row(
            10,
            "T05",
            "Python",
            "agent-b",
            1,
            passed=True,
            wall_s=8.0,
            tokens_input=40,
            tokens_prompt_total=80,
            tokens_output=20,
            infra_error=True,
        ),
    ]
