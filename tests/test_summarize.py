"""summarize(): auditable aggregation over completed runs only."""

from __future__ import annotations

import unittest

from harness_lab.summarize import summarize
from tests.support import row


def summary_rows():
    """Ten hand-written rows: 7 completed, 3 excluded by raw flags."""
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
            wall_s=100.0,
            tokens_input=500,
            tokens_prompt_total=1000,
            tokens_output=250,
            timed_out=True,
        ),
        row(
            6,
            "T02",
            "Java",
            "agent-a",
            2,
            passed=True,
            wall_s=12.0,
            tokens_input=60,
            tokens_prompt_total=120,
            tokens_output=30,
            infra_error=True,
        ),
        row(
            7,
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
            8,
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
            9,
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
            10,
            "T05",
            "Python",
            "agent-b",
            1,
            passed=True,
            wall_s=5.0,
            tokens_input=40,
            tokens_prompt_total=80,
            tokens_output=20,
            network_error=True,
            timed_out=True,
        ),
    ]


class TestCountsAndFilter(unittest.TestCase):
    def setUp(self):
        self.report = summarize(summary_rows())

    def test_schema_and_percentile_method_are_declared(self):
        self.assertEqual(self.report["schema"], "harness-lab/summarize/1")
        self.assertIn("R type 7", self.report["percentile_method"])

    def test_filter_is_documented_as_completed_runs_only(self):
        self.assertEqual(
            self.report["filter"]["excludes"],
            ["network_error", "infra_error", "timed_out"],
        )
        self.assertIn("completed runs", self.report["filter"]["measures"])
        self.assertIn("not reliability", self.report["filter"]["measures"])

    def test_row_counts(self):
        counts = self.report["counts"]
        self.assertEqual(counts["rows_total"], 10)
        self.assertEqual(counts["rows_completed"], 7)
        self.assertEqual(counts["rows_excluded"], 3)

    def test_task_and_variant_counts(self):
        counts = self.report["counts"]
        self.assertEqual(counts["tasks_total"], 5)
        self.assertEqual(counts["tasks_completed"], 4)
        self.assertEqual(counts["variants_total"], 2)

    def test_exclusion_breakdown_counts_every_flag_type(self):
        breakdown = self.report["counts"]["exclusions"]
        self.assertEqual(breakdown["network_error"], 1)
        self.assertEqual(breakdown["infra_error"], 1)
        self.assertEqual(breakdown["timed_out"], 2)
        self.assertEqual(breakdown["any_flag"], 3)

    def test_overlapping_flags_are_counted_once_in_any_flag(self):
        report = summarize(
            [
                row(1, "T01", "Python", "v", 1, network_error=True, timed_out=True),
                row(2, "T01", "Python", "v", 2, infra_error=True, timed_out=True),
                row(3, "T01", "Python", "v", 3, network_error=True),
            ]
        )
        breakdown = report["counts"]["exclusions"]
        self.assertEqual(breakdown["any_flag"], 3)
        self.assertEqual(breakdown["multiple_flags"], 2)
        self.assertEqual(report["counts"]["rows_completed"], 0)

    def test_filter_is_identical_for_every_variant(self):
        # Every excluded row carries a raw flag; no variant-specific rule exists.
        for variant, stats in self.report["variants"].items():
            self.assertEqual(
                stats["rows_total"] - stats["rows_completed"],
                stats["rows_excluded"],
                variant,
            )


class TestPassAccounting(unittest.TestCase):
    def test_success_and_failure_are_preserved_for_completed_runs(self):
        report = summarize(summary_rows())
        a = report["variants"]["agent-a"]
        self.assertEqual(a["passed"], 3)
        self.assertEqual(a["failed"], 1)
        self.assertAlmostEqual(a["pass_fraction"], 0.75, places=9)

    def test_excluded_rows_do_not_move_pass_fraction(self):
        # Row 6 is a *pass* but carries infra_error: it must not be counted.
        only = summarize(
            [
                row(1, "T01", "Python", "v", 1, passed=True),
                row(2, "T01", "Python", "v", 2, passed=True, infra_error=True),
            ]
        )
        self.assertEqual(only["variants"]["v"]["passed"], 1)
        self.assertEqual(only["variants"]["v"]["failed"], 0)
        self.assertAlmostEqual(only["variants"]["v"]["pass_fraction"], 1.0, places=9)

    def test_excluded_failure_does_not_appear_as_a_failure(self):
        only = summarize([row(1, "T01", "Python", "v", 1, passed=False, timed_out=True)])
        self.assertEqual(only["variants"]["v"]["passed"], 0)
        self.assertEqual(only["variants"]["v"]["failed"], 0)
        self.assertIsNone(only["variants"]["v"]["pass_fraction"])

    def test_no_relaxed_or_corrected_score_anywhere(self):
        report = summarize(summary_rows())
        self.assertIsNone(report["variants"]["agent-a"]["relaxed_score"])
        self.assertIn("raw pass", " ".join(report["notes"]).lower())


class TestSampleAndTaskCounts(unittest.TestCase):
    def test_variant_sample_and_unique_task_counts(self):
        a = summarize(summary_rows())["variants"]["agent-a"]
        self.assertEqual(a["samples_completed"], 4)
        self.assertEqual(a["unique_tasks_completed"], 4)
        self.assertEqual(a["tasks_completed"], ["T01", "T02", "T03", "T04"])
        b = summarize(summary_rows())["variants"]["agent-b"]
        self.assertEqual(b["samples_completed"], 3)
        self.assertEqual(b["unique_tasks_completed"], 3)

    def test_repeats_do_not_inflate_unique_task_count(self):
        report = summarize(
            [
                row(1, "T01", "Python", "v", 1),
                row(2, "T01", "Python", "v", 2),
                row(3, "T01", "Python", "v", 3),
            ]
        )
        v = report["variants"]["v"]
        self.assertEqual(v["samples_completed"], 3)
        self.assertEqual(v["unique_tasks_completed"], 1)

    def test_duplicate_cells_are_reported_not_hidden(self):
        report = summarize(
            [
                row(1, "T01", "Python", "v", 1, wall_s=1.0),
                row(2, "T01", "Python", "v", 1, wall_s=3.0),
                row(3, "T01", "Python", "v", 2, wall_s=2.0),
            ]
        )
        self.assertEqual(report["variants"]["v"]["duplicate_cells"], 1)
        self.assertTrue(any("duplicate" in w.lower() for w in report["warnings"]))

    def test_language_coverage(self):
        languages = summarize(summary_rows())["languages"]
        self.assertEqual(sorted(languages), ["Java", "Python", "TypeScript"])
        self.assertEqual(languages["Python"]["rows_total"], 5)
        self.assertEqual(languages["Python"]["rows_completed"], 3)
        self.assertEqual(languages["Python"]["tasks_completed"], 2)
        self.assertEqual(languages["Python"]["variants"], ["agent-a", "agent-b"])
        self.assertEqual(languages["TypeScript"]["rows_completed"], 2)


class TestDistributionFields(unittest.TestCase):
    def test_exact_percentiles_for_a_variant(self):
        a = summarize(summary_rows())["variants"]["agent-a"]
        self.assertEqual(a["wall_s"]["n"], 4)
        self.assertEqual(a["wall_s"]["missing"], 0)
        self.assertAlmostEqual(a["wall_s"]["p50"], 25.0, places=9)
        self.assertAlmostEqual(a["wall_s"]["p95"], 38.5, places=9)
        self.assertAlmostEqual(a["tokens_input"]["p50"], 200.0, places=9)
        self.assertAlmostEqual(a["tokens_input"]["p95"], 290.0, places=9)
        self.assertAlmostEqual(a["tokens_prompt_total"]["p95"], 580.0, places=9)
        self.assertAlmostEqual(a["tokens_output"]["p95"], 145.0, places=9)

    def test_missing_tokens_are_counted_never_imputed(self):
        a = summarize(summary_rows())["variants"]["agent-a"]
        self.assertEqual(a["tokens_input"]["n"], 3)
        self.assertEqual(a["tokens_input"]["missing"], 1)
        b = summarize(summary_rows())["variants"]["agent-b"]
        self.assertEqual(b["tokens_input"]["n"], 2)
        self.assertEqual(b["tokens_input"]["missing"], 1)
        self.assertAlmostEqual(b["tokens_input"]["p50"], 110.0, places=9)
        self.assertAlmostEqual(b["tokens_input"]["p95"], 119.0, places=9)

    def test_variant_with_no_token_observations_reports_none(self):
        report = summarize(
            [
                row(
                    1,
                    "T01",
                    "Python",
                    "v",
                    1,
                    tokens_input=None,
                    tokens_prompt_total=None,
                    tokens_output=None,
                ),
            ]
        )
        for metric in ("tokens_input", "tokens_prompt_total", "tokens_output"):
            stats = report["variants"]["v"][metric]
            self.assertEqual(stats["n"], 0, metric)
            self.assertIsNone(stats["p50"], metric)
            self.assertIsNone(stats["p95"], metric)

    def test_overall_distribution_uses_completed_rows_only(self):
        overall = summarize(summary_rows())["overall"]
        self.assertEqual(overall["wall_s"]["n"], 7)
        self.assertAlmostEqual(overall["wall_s"]["p50"], 20.0, places=9)
        self.assertAlmostEqual(overall["wall_s"]["p95"], 54.0, places=9)


class TestNoRanking(unittest.TestCase):
    def test_unequal_task_sets_block_ranking(self):
        report = summarize(summary_rows())
        self.assertFalse(report["task_sets"]["identical_across_variants"])
        self.assertIsNone(report["ranking"]["ranking"])
        self.assertFalse(report["ranking"]["allowed"])
        self.assertIn("unequal task sets", report["ranking"]["reason"])
        self.assertTrue(any("unequal task sets" in w for w in report["warnings"]))

    def test_ranking_is_withheld_even_for_identical_task_sets(self):
        report = summarize(
            [
                row(1, "T01", "Python", "a", 1, wall_s=1.0),
                row(2, "T02", "Java", "a", 1, wall_s=2.0),
                row(3, "T01", "Python", "b", 1, wall_s=9.0),
                row(4, "T02", "Java", "b", 1, wall_s=8.0),
            ]
        )
        self.assertTrue(report["task_sets"]["identical_across_variants"])
        self.assertIsNone(report["ranking"]["ranking"])
        self.assertEqual(report["task_sets"]["common_tasks_completed"], ["T01", "T02"])


class TestEmptyInput(unittest.TestCase):
    def test_no_rows_produces_zero_counts_and_no_numbers(self):
        report = summarize([])
        self.assertEqual(report["counts"]["rows_total"], 0)
        self.assertEqual(report["variants"], {})
        self.assertIsNone(report["overall"]["pass_fraction"])
        self.assertIsNone(report["overall"]["wall_s"]["p50"])
        self.assertTrue(any("no rows" in w.lower() for w in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
