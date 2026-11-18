"""The synthetic demo and its hand-written expected numbers."""

from __future__ import annotations

import os
import unittest

from harness_lab.demo import (
    DEMO_CSV_TEXT,
    DEMO_EXPECTED,
    demo_report,
    demo_rows,
    self_check,
)

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestDemoDataset(unittest.TestCase):
    def test_row_and_exclusion_counts_are_as_documented(self):
        rows = demo_rows()
        self.assertEqual(len(rows), 11)
        self.assertEqual(sum(1 for r in rows if r.excluded), 3)
        self.assertEqual([r.entry_id for r in rows], list(range(1, 12)))

    def test_csv_is_the_single_source_of_truth(self):
        # The shipped example file must be identical (modulo line endings).
        example = os.path.join(PACKAGE_ROOT, "examples", "synthetic_runs.csv")
        with open(example, encoding="utf-8", newline="") as handle:
            self.assertEqual(handle.read().replace("\r\n", "\n"), DEMO_CSV_TEXT)


class TestDemoSelfCheck(unittest.TestCase):
    def test_expected_table_is_substantial(self):
        self.assertGreaterEqual(len(DEMO_EXPECTED), 30)

    def test_every_expected_value_matches_the_computed_report(self):
        self.assertEqual(self_check(), [])

    def test_report_is_marked_synthetic(self):
        report = demo_report()
        self.assertTrue(report["synthetic"])
        self.assertIn("synthetic", report["notice"].lower())

    def test_self_check_detects_a_tampered_report(self):
        report = demo_report()
        report["summarize"]["counts"]["rows_completed"] = 999
        mismatches = self_check(report)
        self.assertTrue(any("rows_completed" in m for m in mismatches))


if __name__ == "__main__":
    unittest.main()
