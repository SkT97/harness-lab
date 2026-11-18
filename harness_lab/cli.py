"""Report and compare CSV observations; run an offline synthetic example."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .compare import CompareError, compare
from .demo import DEMO_CSV_TEXT, demo_report, self_check
from .model import ValidationError, load_csv
from .summarize import summarize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-lab")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("report", "compare"):
        command = commands.add_parser(name)
        command.add_argument("--input", required=True)
        command.add_argument("--json-out")
        if name == "compare":
            command.add_argument("--left", required=True)
            command.add_argument("--right", required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--csv-out")
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
        else:
            rows = load_csv(args.input)
            payload = (
                summarize(rows)
                if args.command == "report"
                else compare(rows, args.left, args.right)
            )
            if args.command == "compare" and not payload["comparable"]:
                print(f"not comparable: {args.left} versus {args.right}", file=sys.stderr)
        output = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if getattr(args, "json_out", None):
            Path(args.json_out).write_text(output, encoding="utf-8")
        sys.stdout.write(output)
        return 0
    except (OSError, ValidationError, CompareError, RuntimeError) as exc:
        print(f"harness-lab: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
