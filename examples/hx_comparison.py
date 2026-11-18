"""Compare a deterministic agent session with and without hx on three languages."""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from harness_lab.cli import main
from harness_lab.model import REQUIRED_COLUMNS

CASES = {
    "Python": (
        "check.py",
        "def score(value: int) -> int:\n    return value + 1\n\nassert score(2) == 4\n",
    ),
    "Java": (
        "Check.java",
        "class Check { public static void main(String[] args) {\n"
        "    if (2 + 1 != 4) throw new AssertionError();\n"
        "} }\n",
    ),
    "TypeScript": (
        "check.ts",
        "function score(value: number): number { return value + 1; }\n"
        "if (score(2) !== 4) throw new Error('wrong result');\n",
    ),
}
AGENT = (
    "import sys; from pathlib import Path; "
    "p = Path(sys.argv[1]); data = p.read_bytes(); "
    "assert data.count(b'+ 1') == 1; p.write_bytes(data.replace(b'+ 1', b'+ 2'))"
)


def _verifier(language: str, filename: str) -> list[str]:
    if language == "Python":
        return [sys.executable, filename]
    program = "java" if language == "Java" else "node"
    executable = shutil.which(program)
    if language == "Java":
        # Use the launcher adjacent to the JDK compiler, rather than an older JRE on PATH.
        compiler = shutil.which("javac")
        executable = (
            str(Path(compiler).with_name(Path(executable).name))
            if compiler and executable
            else None
        )
    if executable is None:
        raise RuntimeError(f"{language} runtime is required")
    return [executable, filename]


def _call(argv: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, timeout=60, check=check)


def _initialize(path: Path, filename: str, source: str) -> None:
    path.mkdir()
    (path / filename).write_bytes(source.encode("utf-8"))
    _call(["git", "init", "--quiet", "-b", "main"], path)
    _call(["git", "add", "--", filename], path)
    _call(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Synthetic baseline",
        ],
        path,
    )


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hx-src", type=Path, required=True, help="src directory of an hx checkout"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if not (args.hx_src / "hx" / "__init__.py").is_file():
        parser.error("--hx-src must contain the hx package")

    sys.path.insert(0, str(args.hx_src.resolve()))
    import hx

    with TemporaryDirectory() as temporary:
        scratch = Path(temporary)
        rows = []
        for language, (filename, source) in CASES.items():
            verifier = _verifier(language, filename)
            agent = [sys.executable, "-c", AGENT, filename]
            for repeat in range(args.repeats):
                variants = ("direct", "hx") if repeat % 2 == 0 else ("hx", "direct")
                for variant in variants:
                    checkout = scratch / f"{language}-{repeat}-{variant}"
                    _initialize(checkout, filename, source)
                    if repeat == 0 and _call(verifier, checkout, check=False).returncode == 0:
                        raise RuntimeError(f"{language} baseline must fail")
                    start = time.perf_counter()
                    if variant == "hx":
                        result = hx.run(
                            checkout, agent, verifier, runs_root=scratch / "runs", timeout=60
                        )
                        if not result.passed:
                            raise RuntimeError(f"{language} hx fixture failed: {result.status}")
                        hx.accept(result.run_id, runs_root=scratch / "runs")
                    else:
                        _call(agent, checkout)
                        _call(verifier, checkout)
                    wall = time.perf_counter() - start
                    if b"+ 2" not in (checkout / filename).read_bytes():
                        raise RuntimeError(f"{language} final source is not fixed")
                    rows.append(
                        {
                            "entry_id": len(rows) + 1,
                            "task_id": f"{language.lower()}-score",
                            "language": language,
                            "variant": variant,
                            "repeat": repeat,
                            "passed": "true",
                            "wall_s": f"{wall:.6f}",
                            "network_error": "false",
                            "infra_error": "false",
                            "timed_out": "false",
                        }
                    )

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / "runs.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return main(
        [
            "compare",
            "--input",
            str(csv_path),
            "--left",
            "direct",
            "--right",
            "hx",
            "--json-out",
            str(args.out / "comparison.json"),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(run())
