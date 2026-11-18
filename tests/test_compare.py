"""compare(): exact (task_id, repeat) pairing, honest denominators."""

from __future__ import annotations

import unittest

from harness_lab.compare import AmbiguousPairingError, CompareError, compare
from tests.support import fixture_rows, row


class TestExactPairing(unittest.TestCase):
    def setUp(self):
        self.report = compare(fixture_rows(), "agent-a", "agent-b")

    def test_schema_and_variants(self):
        self.assertEqual(self.report["schema"], "harness-lab/compare/1")
        self.assertEqual(self.report["left"], "agent-a")
        self.assertEqual(self.report["right"], "agent-b")

    def test_only_matching_task_and_repeat_are_paired(self):
        cells = [(p["task_id"], p["repeat"]) for p in self.report["pairs"]]
        self.assertEqual(cells, [("T01", 1), ("T02", 1), ("T03", 1)])
        self.assertEqual(self.report["pairing"]["pairs"], 3)
        self.assertIn("task_id", self.report["pairing"]["method"])

    def test_unpaired_completed_rows_on_both_sides(self):
        # T04/r2 only on the left; T05/r2 only on the right.
        self.assertEqual(self.report["pairing"]["left_unpaired_completed"], 1)
        self.assertEqual(self.report["pairing"]["right_unpaired_completed"], 1)

    def test_excluded_rows_are_never_paired(self):
        cells = [(p["task_id"], p["repeat"]) for p in self.report["pairs"]]
        self.assertNotIn(("T01", 2), cells)  # left row is timed_out
        self.assertNotIn(("T05", 1), cells)  # right row is infra_error
        self.assertEqual(self.report["rows"]["left"]["rows_excluded"], 1)
        self.assertEqual(self.report["rows"]["right"]["rows_excluded"], 1)
        self.assertEqual(self.report["rows"]["left"]["rows_completed"], 4)
        self.assertEqual(self.report["rows"]["right"]["rows_completed"], 4)

    def test_task_coverage_is_reported(self):
        coverage = self.report["task_coverage"]
        self.assertEqual(coverage["shared_tasks_completed"], ["T01", "T02", "T03"])
        self.assertEqual(coverage["left_only_tasks_completed"], ["T04"])
        self.assertEqual(coverage["right_only_tasks_completed"], ["T05"])
        self.assertFalse(coverage["identical_task_sets"])

    def test_pair_detail_carries_both_sides(self):
        first = self.report["pairs"][0]
        self.assertEqual(first["language"], "Python")
        self.assertEqual(first["left"]["passed"], True)
        self.assertEqual(first["left"]["wall_s"], 10.0)
        self.assertEqual(first["right"]["passed"], True)
        self.assertEqual(first["right"]["wall_s"], 20.0)
        self.assertEqual(first["left"]["tokens_input"], 100)
        self.assertIsNone(self.report["pairs"][2]["right"]["tokens_input"])


class TestPairedSuccess(unittest.TestCase):
    def setUp(self):
        self.success = compare(fixture_rows(), "agent-a", "agent-b")["paired_success"]

    def test_raw_paired_success_counts(self):
        self.assertEqual(self.success["pairs"], 3)
        self.assertEqual(self.success["left_passed"], 2)
        self.assertEqual(self.success["right_passed"], 2)
        self.assertEqual(self.success["both_passed"], 1)
        self.assertEqual(self.success["only_left_passed"], 1)
        self.assertEqual(self.success["only_right_passed"], 1)
        self.assertEqual(self.success["neither_passed"], 0)

    def test_failures_are_counted_among_completed_runs(self):
        self.assertEqual(self.success["left_failed"], 1)
        self.assertEqual(self.success["right_failed"], 1)
        self.assertAlmostEqual(self.success["left_pass_fraction"], 2 / 3, places=9)
        self.assertAlmostEqual(self.success["right_pass_fraction"], 2 / 3, places=9)


class TestPairedMetrics(unittest.TestCase):
    def setUp(self):
        self.metrics = compare(fixture_rows(), "agent-a", "agent-b")["paired_metrics"]

    def test_wall_ratio_with_denominator(self):
        wall = self.metrics["wall_s"]
        self.assertEqual(wall["pairs_available"], 3)
        self.assertEqual(wall["pairs_used"], 3)
        self.assertEqual(wall["denominator"], 3)
        self.assertEqual(wall["pairs_missing_observation"], 0)
        self.assertEqual(wall["sum_left"], 60.0)
        self.assertEqual(wall["sum_right"], 90.0)
        self.assertAlmostEqual(wall["mean_left"], 20.0, places=9)
        self.assertAlmostEqual(wall["mean_right"], 30.0, places=9)
        self.assertAlmostEqual(wall["ratio_left_over_right"], 2 / 3, places=9)
        self.assertTrue(wall["comparable"])
        self.assertIsNone(wall["reason"])

    def test_token_ratio_uses_only_common_observations(self):
        tokens = self.metrics["tokens_input"]
        self.assertEqual(tokens["pairs_used"], 2)  # T03/r1 is null on the right
        self.assertEqual(tokens["pairs_missing_observation"], 1)
        self.assertEqual(tokens["sum_left"], 300.0)
        self.assertEqual(tokens["sum_right"], 220.0)
        self.assertAlmostEqual(tokens["mean_left"], 150.0, places=9)
        self.assertAlmostEqual(tokens["mean_right"], 110.0, places=9)
        self.assertAlmostEqual(tokens["ratio_left_over_right"], 300 / 220, places=9)

    def test_metrics_with_full_common_coverage(self):
        prompt = self.metrics["tokens_prompt_total"]
        self.assertEqual(prompt["pairs_used"], 3)
        self.assertEqual(prompt["sum_left"], 1200.0)
        self.assertEqual(prompt["sum_right"], 940.0)
        self.assertAlmostEqual(prompt["ratio_left_over_right"], 1200 / 940, places=9)
        output = self.metrics["tokens_output"]
        self.assertAlmostEqual(output["ratio_left_over_right"], 300 / 310, places=9)

    def test_metric_without_any_common_observation_is_not_comparable(self):
        rows = [
            row(
                1,
                "T01",
                "Python",
                "a",
                1,
                wall_s=2.0,
                tokens_input=None,
                tokens_prompt_total=None,
                tokens_output=None,
            ),
            row(
                2,
                "T02",
                "Java",
                "a",
                1,
                wall_s=4.0,
                tokens_input=None,
                tokens_prompt_total=None,
                tokens_output=None,
            ),
            row(
                3,
                "T01",
                "Python",
                "b",
                1,
                wall_s=6.0,
                tokens_input=None,
                tokens_prompt_total=None,
                tokens_output=None,
            ),
            row(
                4,
                "T02",
                "Java",
                "b",
                1,
                wall_s=8.0,
                tokens_input=None,
                tokens_prompt_total=None,
                tokens_output=None,
            ),
        ]
        metrics = compare(rows, "a", "b")["paired_metrics"]
        self.assertTrue(metrics["wall_s"]["comparable"])
        for metric in ("tokens_input", "tokens_prompt_total", "tokens_output"):
            self.assertFalse(metrics[metric]["comparable"], metric)
            self.assertEqual(metrics[metric]["pairs_used"], 0, metric)
            self.assertEqual(metrics[metric]["pairs_missing_observation"], 2, metric)
            self.assertIsNone(metrics[metric]["ratio_left_over_right"], metric)
            self.assertIsNone(metrics[metric]["mean_left"], metric)

    def test_zero_denominator_is_not_comparable_and_not_infinity(self):
        rows = [
            row(1, "T01", "Python", "a", 1, wall_s=0.0),
            row(2, "T01", "Python", "b", 1, wall_s=0.0),
        ]
        wall = compare(rows, "a", "b")["paired_metrics"]["wall_s"]
        self.assertFalse(wall["comparable"])
        self.assertIsNone(wall["ratio_left_over_right"])
        self.assertEqual(wall["mean_left"], 0.0)
        self.assertIn("denominator", wall["reason"])


class TestAmbiguousPairing(unittest.TestCase):
    def test_duplicates_on_both_sides_are_rejected(self):
        rows = fixture_rows() + [
            row(11, "T01", "Python", "agent-b", 1, wall_s=25.0),
        ]
        with self.assertRaises(AmbiguousPairingError) as ctx:
            compare(rows, "agent-a", "agent-b")
        self.assertIn("T01", str(ctx.exception))
        self.assertIn("r1", str(ctx.exception))

    def test_duplicates_on_one_side_with_counterpart_are_rejected(self):
        rows = fixture_rows() + [
            row(11, "T02", "Java", "agent-a", 1, wall_s=21.0),
        ]
        with self.assertRaises(AmbiguousPairingError):
            compare(rows, "agent-a", "agent-b")

    def test_duplicates_without_counterpart_are_not_ambiguous(self):
        rows = fixture_rows() + [
            row(11, "T04", "Python", "agent-a", 2, wall_s=45.0),
        ]
        report = compare(rows, "agent-a", "agent-b")
        self.assertEqual(report["pairing"]["pairs"], 3)
        self.assertEqual(report["pairing"]["left_unpaired_completed"], 2)

    def test_no_fastest_or_best_row_is_quietly_chosen(self):
        # Same cell duplicated with wildly different times: no result at all.
        rows = [
            row(1, "T01", "Python", "a", 1, wall_s=1.0),
            row(2, "T01", "Python", "a", 1, wall_s=99.0),
            row(3, "T01", "Python", "b", 1, wall_s=5.0),
        ]
        with self.assertRaises(AmbiguousPairingError):
            compare(rows, "a", "b")


class TestNotComparable(unittest.TestCase):
    def test_no_pairs_is_reported_as_not_comparable_not_zero(self):
        rows = [
            row(1, "T01", "Python", "a", 1, wall_s=1.0),
            row(2, "T09", "Python", "b", 7, wall_s=3.0),
        ]
        report = compare(rows, "a", "b")
        self.assertFalse(report["comparable"])
        self.assertEqual(report["pairing"]["pairs"], 0)
        self.assertIsNone(report["paired_success"]["left_pass_fraction"])
        self.assertEqual(report["pairs"], [])
        for metric in report["paired_metrics"].values():
            self.assertFalse(metric["comparable"])
            self.assertIsNone(metric["mean_left"])
            self.assertIsNone(metric["ratio_left_over_right"])
        self.assertTrue(any("no pairs" in w.lower() for w in report["warnings"]))

    def test_unknown_variant_is_not_comparable_and_is_flagged(self):
        report = compare(fixture_rows(), "agent-a", "agent-ghost")
        self.assertFalse(report["comparable"])
        self.assertTrue(any("agent-ghost" in w for w in report["warnings"]))

    def test_self_comparison_is_rejected(self):
        with self.assertRaises(CompareError):
            compare(fixture_rows(), "agent-a", "agent-a")


class TestWarnings(unittest.TestCase):
    def test_small_sample_and_no_universal_winner_warnings(self):
        report = compare(fixture_rows(), "agent-a", "agent-b")
        text = " ".join(report["warnings"])
        self.assertIn("Small sample", text)
        self.assertIn("No universal winner", text)

    def test_unshared_tasks_warning(self):
        report = compare(fixture_rows(), "agent-a", "agent-b")
        self.assertTrue(any("only on both" in w or "shared" in w for w in report["warnings"]))

    def test_notes_declare_scope_and_no_imputation(self):
        notes = " ".join(compare(fixture_rows(), "agent-a", "agent-b")["notes"]).lower()
        self.assertIn("completed runs", notes)
        self.assertIn("imput", notes)


if __name__ == "__main__":
    unittest.main()
