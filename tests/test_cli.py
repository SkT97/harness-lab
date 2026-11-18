"""CLI: report/compare on a supplied CSV, self-checking synthetic demo."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest

from harness_lab.cli import main
from tests.support import csv_text, fixture_rows, row


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.csv_path = os.path.join(self._tmp.name, "runs.csv")
        with open(self.csv_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(csv_text(fixture_rows()))


class TestReport(CliTestCase):
    def test_report_writes_json_to_stdout(self):
        code, out, err = run_cli(["report", "--input", self.csv_path])
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(report["schema"], "harness-lab/summarize/1")
        self.assertEqual(report["counts"]["rows_total"], 10)
        self.assertEqual(report["counts"]["rows_completed"], 8)

    def test_report_can_write_a_file_too(self):
        target = os.path.join(self._tmp.name, "report.json")
        code, out, _ = run_cli(["report", "--input", self.csv_path, "--json-out", target])
        self.assertEqual(code, 0)
        with open(target, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), json.loads(out))


class TestCompareCommand(CliTestCase):
    def test_compare_writes_json_to_stdout(self):
        code, out, err = run_cli(
            [
                "compare",
                "--input",
                self.csv_path,
                "--left",
                "agent-a",
                "--right",
                "agent-b",
            ]
        )
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(report["schema"], "harness-lab/compare/1")
        self.assertEqual(report["pairing"]["pairs"], 3)
        self.assertTrue(report["comparable"])

    def test_compare_can_write_a_file_too(self):
        target = os.path.join(self._tmp.name, "compare.json")
        code, out, _ = run_cli(
            [
                "compare",
                "--input",
                self.csv_path,
                "--left",
                "agent-a",
                "--right",
                "agent-b",
                "--json-out",
                target,
            ]
        )
        self.assertEqual(code, 0)
        with open(target, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), json.loads(out))

    def test_unknown_variant_is_not_comparable_but_not_a_crash(self):
        code, out, err = run_cli(
            [
                "compare",
                "--input",
                self.csv_path,
                "--left",
                "agent-a",
                "--right",
                "ghost",
            ]
        )
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["comparable"])
        self.assertIn("ghost", err)

    def test_same_variant_twice_is_a_usage_error(self):
        code, out, err = run_cli(
            [
                "compare",
                "--input",
                self.csv_path,
                "--left",
                "agent-a",
                "--right",
                "agent-a",
            ]
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("differ", err)


class TestFailureModes(CliTestCase):
    def test_missing_input_file_fails_cleanly(self):
        code, out, err = run_cli(["report", "--input", os.path.join(self._tmp.name, "nope.csv")])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("nope.csv", err)

    def test_malformed_values_fail_loudly(self):
        path = os.path.join(self._tmp.name, "bad.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(csv_text(fixture_rows()).replace("20.0", "nan", 1))
        code, out, err = run_cli(["report", "--input", path])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("wall_s", err)
        self.assertIn("line", err)

    def test_ambiguous_pairing_fails_loudly(self):
        rows = fixture_rows() + [row(11, "T01", "Python", "agent-b", 1, wall_s=25.0)]
        path = os.path.join(self._tmp.name, "dup.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(csv_text(rows))
        code, out, err = run_cli(
            ["compare", "--input", path, "--left", "agent-a", "--right", "agent-b"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("ambiguous", err.lower())

    def test_no_subcommand_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            run_cli([])
        self.assertEqual(ctx.exception.code, 2)


class TestDemoCommand(unittest.TestCase):
    def test_self_check_failure_is_a_clean_cli_error(self):
        from unittest.mock import patch

        with patch("harness_lab.cli.self_check", return_value=["mismatch"]):
            code, out, err = run_cli(["demo"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("harness-lab: mismatch", err)

    def test_demo_runs_and_self_checks(self):
        code, out, err = run_cli(["demo"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["synthetic"])
        self.assertEqual(payload["summarize"]["counts"]["rows_total"], 11)
        self.assertEqual(payload["compare"]["pairing"]["pairs"], 3)
        self.assertIn("self-check: OK", err)

    def test_demo_can_emit_its_own_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "synthetic.csv")
            code, _, _ = run_cli(["demo", "--csv-out", target])
            self.assertEqual(code, 0)
            with open(target, encoding="utf-8") as handle:
                self.assertIn("entry_id,task_id,language", handle.read())


if __name__ == "__main__":
    unittest.main()
