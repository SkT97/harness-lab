"""Report and compare CSV observations; run an offline synthetic example."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .compare import CompareError, compare
from .demo import DEMO_CSV_TEXT, demo_report, self_check
from .harbor import HarborError, harbor_report
from .inspect_logs import InspectError, inspect_to_csv
from .model import ValidationError, load_csv
from .summarize import summarize
from .verdict import verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-lab")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("report", "compare", "verdict"):
        command = commands.add_parser(name)
        command.add_argument("--input", required=True)
        command.add_argument("--json-out")
        if name in ("compare", "verdict"):
            command.add_argument("--left", required=True)
            command.add_argument("--right", required=True)
        if name == "verdict":
            command.add_argument("--alpha", type=float, default=0.05)
            command.add_argument("--margin", type=float, default=0.10)
            command.add_argument("--power", type=float, default=0.80)
    demo = commands.add_parser("demo")
    demo.add_argument("--csv-out")
    inspect = commands.add_parser("inspect-csv")
    inspect.add_argument("logs", nargs="+", metavar="[LABEL=]LOG.json")
    inspect.add_argument("--language", required=True)
    inspect.add_argument("--score")
    inspect.add_argument("--allow-incomplete", action="store_true")
    inspect.add_argument("--out")
    harbor = commands.add_parser("harbor-report")
    harbor.add_argument("--job-dir", type=Path, required=True)
    harbor.add_argument("--manifest", type=Path)
    harbor.add_argument("--reward-key", default="reward")
    harbor.add_argument("--json-out")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            text = DEMO_CSV_TEXT
            payload = demo_report()
            errors = self_check(payload)
            if errors:
                raise RuntimeError("; ".join(errors))
            if args.csv_out:
                Path(args.csv_out).write_text(text, encoding="utf-8")
            print("self-check: OK (synthetic data)", file=sys.stderr)
        elif args.command == "inspect-csv":
            text = inspect_to_csv(args.logs, args.language, args.score, args.allow_incomplete)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8", newline="")
            else:
                sys.stdout.write(text)
            return 0
        elif args.command == "harbor-report":
            payload = harbor_report(args.job_dir, args.manifest, args.reward_key)
        else:
            rows = load_csv(args.input)
            if args.command == "report":
                payload = summarize(rows)
            elif args.command == "compare":
                payload = compare(rows, args.left, args.right)
            else:
                payload = verdict(rows, args.left, args.right, args.alpha, args.margin, args.power)
                print(payload["statement"], file=sys.stderr)
                for metric in payload["metrics"].values():
                    print(metric["statement"], file=sys.stderr)
            if args.command == "compare" and not payload["comparable"]:
                print(f"not comparable: {args.left} versus {args.right}", file=sys.stderr)
        output = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if getattr(args, "json_out", None):
            Path(args.json_out).write_text(output, encoding="utf-8")
        sys.stdout.write(output)
        return 0
    except (OSError, ValidationError, CompareError, HarborError, InspectError, RuntimeError) as exc:
        print(f"harness-lab: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
