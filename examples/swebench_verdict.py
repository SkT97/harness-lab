"""Pairwise verdicts on public SWE-bench Verified results.

Downloads the per-instance results of the submissions listed in
``benchmarks/swebench-verified/submissions.txt`` from the public
SWE-bench/experiments repository at a pinned commit, then asks ``verdict``
whether adjacent entries of the leaderboard, and the first entry against lower
ones, can be told apart. Nothing from that repository is stored here: the
repository declares no license, so the files are fetched, not redistributed.

An instance a submission does not resolve counts as unresolved, as on the
leaderboard. The data has one attempt per instance and no timings, so only the
pass/fail verdict is used.

    uv run --locked python -m examples.swebench_verdict --out results.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from harness_lab.model import Run
from harness_lab.verdict import holm_adjust, verdict

COMMIT = "40f164d5b8f1d249bf95a6df8b74b577fd8e519d"
INSTANCES = 500
_BASE = f"https://raw.githubusercontent.com/SWE-bench/experiments/{COMMIT}/evaluation/verified/"
_MAX_BYTES = 2_000_000
_MAX_IDS = 2_000
_NAME = re.compile(r"[A-Za-z0-9._+-]+")
_MANIFEST = Path(__file__).resolve().parents[1] / "benchmarks/swebench-verified/submissions.txt"


def parse_results(document: object, name: str) -> tuple[set[str], set[str]]:
    """The resolved instance ids and every instance id the file mentions."""
    if not isinstance(document, dict) or not isinstance(document.get("resolved"), list):
        raise ValueError(f"{name}: not a results document with a resolved list")
    seen: set[str] = set()
    resolved: set[str] = set()
    for key, value in document.items():
        if not isinstance(value, list):
            continue
        if len(value) > _MAX_IDS or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{name}: {key} is not a plausible list of instance ids")
        seen.update(value)
        if key == "resolved":
            resolved.update(value)
    return resolved, seen


def _runs(first: str, second: str, resolved: dict[str, set[str]], universe: list[str]) -> list[Run]:
    rows, entry = [], 0
    for name in (first, second):
        for instance in universe:
            entry += 1
            rows.append(
                Run(entry, instance, "Python", name, 1, instance in resolved[name], 0.0,
                    None, None, None, False, False, False)
            )  # fmt: skip
    return rows


def _pair(left: str, right: str, resolved, universe) -> dict:
    result = verdict(_runs(left, right, resolved, universe), left, right)
    primary = result["primary"]
    return {
        "left": left,
        "right": right,
        "resolved_left": len(resolved[left]),
        "resolved_right": len(resolved[right]),
        "only_left": primary["counts"]["only_left_passed"],
        "only_right": primary["counts"]["only_right_passed"],
        "p": primary["p_value"],
        "difference": primary["difference_left_minus_right"],
        "interval": primary["confidence_interval"],
        "verdict": result["verdict"],
    }


def analyze(
    results: dict[str, tuple[set[str], set[str]]],
    top: int = 30,
    scan: int = 60,
    alpha: float = 0.05,
    instances: int | None = None,
) -> dict:
    universe = sorted(set().union(*(seen for _, seen in results.values())))
    if instances is not None and len(universe) != instances:
        raise ValueError(f"expected {instances} instances, found {len(universe)}")
    resolved = {name: found for name, (found, _) in results.items()}
    order = sorted(resolved, key=lambda name: (-len(resolved[name]), name))
    top_names = order[:top]
    adjacent = [
        _pair(a, b, resolved, universe) for a, b in zip(top_names, top_names[1:], strict=False)
    ]
    summary = {"pairs": len(adjacent)}
    for kind in ("distinguishable", "bounded_null", "underpowered"):
        summary[kind] = sum(1 for row in adjacent if row["verdict"] == kind)

    versus = []
    for rank, name in enumerate(order[1:scan], start=2):
        row = _pair(order[0], name, resolved, universe)
        row["rank"] = rank
        versus.append(row)
    for row, adjusted in zip(versus, holm_adjust([r["p"] for r in versus]), strict=True):
        row["p_holm"] = adjusted
        row["distinguishable_after_holm"] = row["verdict"] == "distinguishable" and adjusted < alpha
    first = next((r["rank"] for r in versus if r["distinguishable_after_holm"]), None)
    from_rank_on = None
    for row in reversed(versus):
        if not row["distinguishable_after_holm"]:
            break
        from_rank_on = row["rank"]
    return {
        "source": {
            "repository": "SWE-bench/experiments",
            "commit": COMMIT,
            "split": "evaluation/verified",
        },
        "instances": len(universe),
        "submissions": len(order),
        "alpha": alpha,
        "policy": "an instance not resolved counts as unresolved; one attempt per instance",
        "top": [
            {"rank": i + 1, "name": n, "resolved": len(resolved[n])}
            for i, n in enumerate(top_names)
        ],
        "adjacent": adjacent,
        "adjacent_summary": summary,
        "versus_first": versus,
        "first_distinguishable_rank": first,
        "distinguishable_from_rank_on": from_rank_on,
    }


def _fetch(name: str, cache: Path | None) -> object:
    if not _NAME.fullmatch(name) or name in (".", ".."):
        raise ValueError(f"unexpected submission name {name!r}")
    cached = cache / f"{name}.json" if cache else None
    if cached and cached.is_file():
        return json.loads(cached.read_text(encoding="utf-8"))
    url = f"{_BASE}{urllib.parse.quote(name, safe='+')}/results/results.json"
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed https host
        body = response.read(_MAX_BYTES + 1)
    if len(body) > _MAX_BYTES:
        raise ValueError(f"{name}: response too large")
    if cached:
        cache.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(body)
    return json.loads(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swebench_verdict")
    parser.add_argument("--manifest", type=Path, default=_MANIFEST)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--scan", type=int, default=60)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    names = [n for n in args.manifest.read_text(encoding="utf-8").split() if n]
    results = {name: parse_results(_fetch(name, args.cache_dir), name) for name in names}
    report = analyze(results, args.top, args.scan, instances=INSTANCES)
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.write(text if not args.out else f"wrote {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
