"""Create a small Harbor-shaped job and its plan in a temporary directory."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from harness_lab.cli import main


def run() -> int:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        job = root / "job"
        manifest_file = root / "manifest.json"

        plan = []
        for repeat, (name, reward) in enumerate(
            (("pass", 1), ("fail", 0), ("connection", None), ("missing", None))
        ):
            identity = {"trial_name": name, "task_name": "parse-widget", "task_checksum": "v1"}
            plan.append({**identity, "configuration": "sample-agent", "repeat": repeat})
            if name == "missing":
                continue
            trial = job / name
            trial.mkdir(parents=True)
            outcome = {
                **identity,
                "schema_version": 1,
                "agent_info": {"name": "sample-agent", "version": "1"},
                "verifier_result": None if reward is None else {"rewards": {"reward": reward}},
                "reward_valid": reward is not None,
                "exception_info": None
                if reward is not None
                else {"exception_type": "ConnectionError"},
            }
            (trial / "result.json").write_text(json.dumps(outcome), encoding="utf-8")

        manifest_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "harbor_version": "0.26.0",
                    "campaign": "synthetic-offline",
                    "benchmark": "parse-widget",
                    "benchmark_revision": "1",
                    "limits": {"timeout_seconds": 30},
                    "trials": plan,
                }
            ),
            encoding="utf-8",
        )
        return main(
            [
                "harbor-report",
                "--job-dir",
                str(job),
                "--manifest",
                str(manifest_file),
                *sys.argv[1:],
            ]
        )


if __name__ == "__main__":
    raise SystemExit(run())
