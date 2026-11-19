"""verdict(): exact tests, intervals, planning and robustness to exclusions."""

from __future__ import annotations

import contextlib
import io
import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from statistics import NormalDist

from harness_lab.cli import main
from harness_lab.compare import CompareError
from harness_lab.model import load_csv
from harness_lab.verdict import (
    MAX_PLANNED_UNITS,
    _finish_metrics,
    exact_power,
    exact_two_sided_p,
    holm_adjust,
    newcombe_paired_ci,
    units_needed,
    verdict,
)
from tests.support import csv_text, row

Z = NormalDist().inv_cdf(0.975)
PILOT = Path(__file__).resolve().parents[1] / "benchmarks/qwen-flash-next-pilot/trials.csv"


def runs(outcomes, repeats=1, excluded_left=(), excluded_right=()):
    """outcomes: {task: (left_passed, right_passed)}, same outcome for every repeat."""
    rows, entry = [], 0
    for task, (left, right) in outcomes.items():
        for repeat in range(1, repeats + 1):
            for variant, passed, excluded in (
                ("A", left, task in excluded_left),
                ("B", right, task in excluded_right),
            ):
                entry += 1
                rows.append(
                    row(entry, task, "Python", variant, repeat, passed=passed, timed_out=excluded)
                )
    return rows


def split(both=0, only_left=0, only_right=0, neither=0):
    outcomes = {}
    for kind, count, pair in (
        ("both", both, (True, True)),
        ("left", only_left, (True, False)),
        ("right", only_right, (False, True)),
        ("none", neither, (False, False)),
    ):
        for index in range(count):
            outcomes[f"{kind}{index}"] = pair
    return outcomes


class TestExactTest(unittest.TestCase):
    def test_hand_computed_values(self):
        self.assertEqual(exact_two_sided_p(0, 0), 1.0)
        self.assertEqual(exact_two_sided_p(3, 3), 1.0)
        self.assertAlmostEqual(exact_two_sided_p(0, 5), 2 / 32)
        self.assertAlmostEqual(exact_two_sided_p(1, 5), 2 * 7 / 64)
        self.assertEqual(exact_two_sided_p(2, 7), exact_two_sided_p(7, 2))


class TestInterval(unittest.TestCase):
    def test_all_concordant_small_sample_is_wide(self):
        lower, upper = newcombe_paired_ci(3, 0, 0, 0, Z)
        half = 1 - 3 / (3 + Z * Z)  # Wilson lower bound of 3 out of 3
        self.assertAlmostEqual(upper, half, places=6)
        self.assertAlmostEqual(lower, -half, places=6)

    def test_swapping_sides_negates_the_interval(self):
        lower, upper = newcombe_paired_ci(20, 9, 3, 8, Z)
        flipped_lower, flipped_upper = newcombe_paired_ci(20, 3, 9, 8, Z)
        self.assertAlmostEqual(lower, -flipped_upper)
        self.assertAlmostEqual(upper, -flipped_lower)

    def test_interval_contains_the_estimate(self):
        lower, upper = newcombe_paired_ci(20, 9, 3, 8, Z)
        self.assertLess(lower, 6 / 40)
        self.assertGreater(upper, 6 / 40)

    def test_coverage_is_nominal_by_enumeration(self):
        n, p11, p10, p01 = 20, 0.3, 0.2, 0.2
        p00 = 1 - p11 - p10 - p01
        covered = 0.0
        for a in range(n + 1):
            for b in range(n + 1 - a):
                for c in range(n + 1 - a - b):
                    d = n - a - b - c
                    weight = (
                        math.factorial(n)
                        / (
                            math.factorial(a)
                            * math.factorial(b)
                            * math.factorial(c)
                            * math.factorial(d)
                        )
                        * p11**a
                        * p10**b
                        * p01**c
                        * p00**d
                    )
                    lower, upper = newcombe_paired_ci(a, b, c, d, Z)
                    if lower - 1e-12 <= p10 - p01 <= upper + 1e-12:
                        covered += weight
        self.assertGreaterEqual(covered, 0.94)


class TestPlanning(unittest.TestCase):
    def test_values_match_a_brute_force_power_calculation(self):
        self.assertEqual(units_needed(0.3, 0.1, 0.05, 0.8), 249)
        self.assertEqual(units_needed(0.4, 0.2, 0.05, 0.8), 84)
        self.assertEqual(units_needed(0.1, 0.1, 0.05, 0.8), 78)

    def test_reaches_the_target_and_one_fewer_does_not(self):
        needed = units_needed(0.3, 0.1, 0.05, 0.8)
        self.assertGreaterEqual(exact_power(needed, 0.3, 0.1, 0.05), 0.8)
        self.assertLess(exact_power(needed - 1, 0.3, 0.1, 0.05), 0.8)

    def test_a_huge_requirement_is_refused_quickly_instead_of_searched(self):
        for rate, margin in ((0.6, 0.02), (0.9, 0.01), (0.5, 0.001)):
            started = time.monotonic()
            self.assertIsNone(units_needed(rate, margin, 0.05, 0.8))
            self.assertLess(time.monotonic() - started, 2.0, (rate, margin))

    def test_the_search_within_the_cap_is_bounded_in_time_and_minimal(self):
        started = time.monotonic()
        needed = units_needed(0.3, 0.05, 0.05, 0.8)
        self.assertLess(time.monotonic() - started, 5.0)
        started = time.monotonic()
        self.assertIsInstance(units_needed(0.5, 0.05, 0.05, 0.8), int)  # about 1600 tasks
        self.assertLess(time.monotonic() - started, 10.0)
        self.assertLessEqual(needed, MAX_PLANNED_UNITS)
        self.assertGreaterEqual(exact_power(needed, 0.3, 0.05, 0.05), 0.8)
        self.assertLess(exact_power(needed - 1, 0.3, 0.05, 0.05), 0.8)

    def test_the_report_says_when_more_than_the_cap_would_be_needed(self):
        result = verdict(
            runs(split(both=4, only_left=3, only_right=1, neither=2)), "A", "B", margin=0.01
        )
        primary = result["primary"]
        self.assertIsNone(primary["units_needed_tasks"])
        self.assertTrue(any(str(MAX_PLANNED_UNITS) in r for r in primary["reasons"]))
        self.assertFalse(any("below the margin" in r for r in primary["reasons"]))

    def test_effect_larger_than_disagreement_cannot_exist(self):
        self.assertIsNone(units_needed(0.05, 0.1, 0.05, 0.8))


class TestVerdict(unittest.TestCase):
    def test_clear_difference_is_distinguishable(self):
        result = verdict(runs(split(both=2, only_left=10)), "A", "B")
        self.assertEqual(result["verdict"], "distinguishable")
        self.assertEqual(result["primary"]["direction"], "left_better")
        self.assertAlmostEqual(result["primary"]["p_value"], 2 / 1024)
        self.assertTrue(result["robust_to_exclusions"])
        self.assertIn("A passes more tasks than B", result["statement"])

    def test_interval_level_follows_alpha(self):
        rows = runs(split(both=20, only_left=9, only_right=3, neither=8))
        default = verdict(rows, "A", "B")["primary"]["confidence_interval"]
        wide = verdict(rows, "A", "B", alpha=0.01)["primary"]["confidence_interval"]
        self.assertEqual(default, list(newcombe_paired_ci(20, 9, 3, 8, Z)))
        self.assertLess(wide[0], default[0])
        self.assertGreater(wide[1], default[1])

    def test_direction_follows_the_better_side(self):
        result = verdict(runs(split(only_right=10, neither=2)), "A", "B")
        self.assertEqual(result["primary"]["direction"], "right_better")

    def test_equal_large_samples_give_a_bounded_null(self):
        result = verdict(runs(split(both=100, only_left=2, only_right=2, neither=96)), "A", "B")
        self.assertEqual(result["verdict"], "bounded_null")
        lower, upper = result["primary"]["confidence_interval"]
        self.assertGreater(lower, -0.10)
        self.assertLess(upper, 0.10)

    def test_small_sample_is_underpowered_and_reports_units_needed(self):
        result = verdict(runs(split(both=4, only_left=3, only_right=1, neither=2)), "A", "B")
        self.assertEqual(result["verdict"], "underpowered")
        self.assertIsInstance(result["primary"]["units_needed_tasks"], int)
        self.assertGreater(result["primary"]["units_needed_tasks"], 10)

    def test_saturated_data_cannot_be_planned(self):
        result = verdict(runs(split(both=3)), "A", "B")
        self.assertEqual(result["verdict"], "underpowered")
        self.assertEqual(result["primary"]["informative_pairs"], 0)
        self.assertIsNone(result["primary"]["units_needed_tasks"])
        self.assertTrue(any("no task separates" in r for r in result["primary"]["reasons"]))

    def test_no_shared_cell(self):
        rows = [row(1, "T1", "Python", "A", 1), row(2, "T2", "Python", "B", 1)]
        result = verdict(rows, "A", "B")
        self.assertEqual(result["verdict"], "no_pairs")

    def test_repeats_of_one_task_do_not_fake_significance(self):
        outcomes = {"T1": (True, False), "T2": (True, False), "T3": (True, False)}
        result = verdict(runs(outcomes, repeats=5), "A", "B")
        primary = result["primary"]
        self.assertLess(primary["p_pairs_mcnemar_exact"], 0.001)
        self.assertAlmostEqual(primary["p_tasks_sign_exact"], 0.25)
        self.assertEqual(result["verdict"], "underpowered")
        self.assertFalse(primary["interval_assumes_independent_pairs"])

    def test_repeats_cannot_produce_a_bounded_null(self):
        outcomes = {f"T{i}": (i % 2 == 0, i % 2 == 0) for i in range(200)}
        result = verdict(runs(outcomes, repeats=2), "A", "B")
        self.assertEqual(result["verdict"], "underpowered")
        self.assertTrue(any("correlated" in r for r in result["primary"]["reasons"]))

    def test_conclusion_that_flips_with_exclusions_is_flagged(self):
        outcomes = split(only_left=8)
        for index in range(8):
            outcomes[f"cut{index}"] = (False, True)
        excluded = {f"cut{index}" for index in range(8)}
        result = verdict(runs(outcomes, excluded_left=excluded), "A", "B")
        self.assertEqual(result["verdict"], "distinguishable")
        self.assertEqual(result["sensitivity"]["class"], "underpowered")
        self.assertFalse(result["robust_to_exclusions"])
        self.assertEqual(result["excluded_rows"], 8)
        self.assertIn("depends on how excluded runs are treated", result["statement"])

    def test_without_exclusions_both_policies_agree(self):
        result = verdict(runs(split(both=2, only_left=10)), "A", "B")
        self.assertEqual(result["primary"]["counts"], {**result["sensitivity"]["counts"]})
        self.assertTrue(result["robust_to_exclusions"])

    def test_invalid_parameters_are_rejected(self):
        rows = runs(split(both=2, only_left=10))
        for kwargs in ({"alpha": 0}, {"margin": 1.5}, {"power": -0.1}):
            with self.assertRaises(CompareError):
                verdict(rows, "A", "B", **kwargs)
        with self.assertRaises(CompareError):
            verdict(rows, "A", "A")

    def test_output_is_strict_json(self):
        result = verdict(runs(split(both=3, only_left=2)), "A", "B")
        json.dumps(result, allow_nan=False)

    def test_notes_forbid_a_ranking(self):
        result = verdict(runs(split(both=2, only_left=10)), "A", "B")
        self.assertTrue(any(note.startswith("No ranking") for note in result["notes"]))


class TestPilot(unittest.TestCase):
    def test_the_published_pilot_is_honestly_underpowered(self):
        result = verdict(load_csv(PILOT), "pi", "opencode")
        self.assertEqual(result["verdict"], "underpowered")
        self.assertEqual(result["primary"]["pairs"], 3)
        self.assertEqual(result["primary"]["informative_pairs"], 0)
        self.assertIsNone(result["primary"]["units_needed_tasks"])


class TestCli(unittest.TestCase):
    def test_verdict_command_prints_json_and_the_statement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.csv"
            path.write_text(csv_text(runs(split(both=2, only_left=10))), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["verdict", "--input", str(path), "--left", "A", "--right", "B"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["schema"], "harness-lab/verdict/1")
        self.assertIn("A passes more tasks than B", err.getvalue())

    def test_bad_alpha_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.csv"
            path.write_text(csv_text(runs(split(both=2, only_left=10))), encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = main(
                    ["verdict", "--input", str(path), "--left", "A", "--right", "B", "--alpha", "2"]
                )
        self.assertEqual(code, 1)
        self.assertIn("alpha", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()


def timed(ratios, repeats=1, metric="wall_s"):
    """One task per ratio: A takes `ratio` times as long as B (B takes 10)."""
    rows, entry = [], 0
    for index, ratio in enumerate(ratios):
        for repeat in range(1, repeats + 1):
            for variant, value in (("A", 10.0 * ratio), ("B", 10.0)):
                entry += 1
                rows.append(
                    row(
                        entry,
                        f"T{index}",
                        "Python",
                        variant,
                        repeat,
                        wall_s=value,
                        tokens_input=None,
                        tokens_prompt_total=None,
                        tokens_output=None,
                    )
                )
    return rows


class TestPairedMetrics(unittest.TestCase):
    def test_six_tasks_all_faster_on_one_side_are_distinguishable(self):
        result = verdict(timed([0.5, 0.6, 0.7, 0.8, 0.9, 0.4]), "A", "B")
        metric = result["metrics"]["wall_s"]
        self.assertEqual(metric["class"], "distinguishable")
        self.assertEqual(metric["direction"], "left_lower")
        self.assertAlmostEqual(metric["p_sign_exact"], 2 / 64)
        low, high = metric["ratio_interval"]
        self.assertAlmostEqual(low, 0.4)
        self.assertAlmostEqual(high, 0.9)
        self.assertAlmostEqual(metric["median_ratio_left_over_right"], math.sqrt(0.6 * 0.7))

    def test_interval_never_undercovers(self):
        # With 8 tasks the 95% interval is [x1, x8]: [x2, x7] would only reach 93%.
        ratios = [0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80]
        low, high = verdict(timed(ratios), "A", "B")["metrics"]["wall_s"]["ratio_interval"]
        self.assertAlmostEqual(low, 0.30)
        self.assertAlmostEqual(high, 0.80)

    def test_three_tasks_cannot_give_an_interval(self):
        metric = verdict(timed([0.5, 0.6, 0.7]), "A", "B")["metrics"]["wall_s"]
        self.assertEqual(metric["class"], "underpowered")
        self.assertAlmostEqual(metric["p_sign_exact"], 0.25)
        self.assertIsNone(metric["ratio_interval"])
        self.assertEqual(metric["min_tasks_for_interval"], 6)

    def test_ties_are_dropped_from_the_sign_test_only(self):
        metric = verdict(timed([1.0, 1.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]), "A", "B")["metrics"][
            "wall_s"
        ]
        self.assertEqual(metric["ties"], 2)
        self.assertEqual(metric["left_lower"], 6)
        self.assertAlmostEqual(metric["p_sign_exact"], 2 / 64)
        self.assertEqual(metric["tasks_used"], 8)

    def test_repeats_are_averaged_per_task_before_testing(self):
        metric = verdict(timed([0.5, 0.6, 0.7], repeats=4), "A", "B")["metrics"]["wall_s"]
        self.assertEqual(metric["tasks_used"], 3)
        self.assertEqual(metric["pairs_used"], 12)
        self.assertAlmostEqual(metric["p_sign_exact"], 0.25)

    def test_missing_and_zero_values_stay_out_with_their_own_denominator(self):
        rows = [
            row(1, "T1", "Python", "A", 1, tokens_output=100),
            row(2, "T1", "Python", "B", 1, tokens_output=200),
            row(3, "T2", "Python", "A", 1, tokens_output=None),
            row(4, "T2", "Python", "B", 1, tokens_output=200),
            row(5, "T3", "Python", "A", 1, tokens_output=0),
            row(6, "T3", "Python", "B", 1, tokens_output=200),
        ]
        metric = verdict(rows, "A", "B")["metrics"]["tokens_output"]
        self.assertEqual(metric["tasks_available"], 3)
        self.assertEqual(metric["tasks_used"], 1)
        self.assertEqual(metric["tasks_without_ratio"], 2)

    def test_no_usable_task(self):
        rows = [row(1, "T1", "Python", "A", 1, tokens_input=None), row(2, "T1", "Python", "B", 1)]
        metric = verdict(rows, "A", "B")["metrics"]["tokens_input"]
        self.assertEqual(metric["class"], "no_data")

    def test_the_pilot_timing_is_not_yet_conclusive(self):
        metrics = verdict(load_csv(PILOT), "pi", "opencode")["metrics"]
        wall = metrics["wall_s"]
        self.assertEqual(wall["direction"], None)
        self.assertEqual(wall["class"], "underpowered")
        self.assertEqual(wall["right_lower"], 3)
        self.assertAlmostEqual(wall["p_sign_exact"], 0.25)
        self.assertEqual(metrics["tokens_output"]["right_lower"], 3)


class TestHolm(unittest.TestCase):
    def test_a_lone_metric_keeps_its_p_value(self):
        metric = verdict(timed([0.5, 0.6, 0.7, 0.8, 0.9, 0.4]), "A", "B")["metrics"]["wall_s"]
        self.assertEqual(metric["p_holm"], metric["p_sign_exact"])
        self.assertEqual(metric["class"], "distinguishable")

    def test_four_metrics_raise_the_bar(self):
        rows = [
            row(i * 2 + k, f"T{i}", "Python", "AB"[k], 1, wall_s=(5.0 if k == 0 else 10.0))
            for i in range(6)
            for k in range(2)
        ]
        metrics = verdict(rows, "AB"[0], "AB"[1])["metrics"]
        wall = metrics["wall_s"]
        self.assertAlmostEqual(wall["p_sign_exact"], 2 / 64)
        self.assertAlmostEqual(wall["p_holm"], 4 * 2 / 64)
        self.assertEqual(wall["class"], "underpowered")
        self.assertEqual(metrics["tokens_output"]["p_holm"], 1.0)

    def test_holm_is_monotone_and_capped(self):
        rows = [
            row(i * 2 + k, f"T{i}", "Python", "AB"[k], 1, wall_s=(5.0 if k == 0 else 10.0))
            for i in range(6)
            for k in range(2)
        ]
        metrics = verdict(rows, "A", "B")["metrics"]
        adjusted = sorted(m["p_holm"] for m in metrics.values())
        self.assertEqual(adjusted, sorted(adjusted))
        self.assertTrue(all(0 <= value <= 1 for value in adjusted))

    def test_step_down_never_lowers_an_earlier_adjusted_value(self):
        def fake(p_value):
            return {
                "tasks_used": 8,
                "p_sign_exact": p_value,
                "ratio_interval": None,
                "median_ratio_left_over_right": 1.0,
                "left_lower": 1,
                "right_lower": 1,
                "min_tasks_for_interval": 6,
                "direction": None,
            }

        metrics = {"a": fake(0.01), "b": fake(0.012), "c": fake(0.4), "d": fake(0.9)}
        _finish_metrics(metrics, 0.05)
        self.assertAlmostEqual(metrics["a"]["p_holm"], 0.04)
        self.assertAlmostEqual(metrics["b"]["p_holm"], 0.04)  # 3 * 0.012 = 0.036 is raised
        self.assertAlmostEqual(metrics["c"]["p_holm"], 0.8)
        self.assertAlmostEqual(metrics["d"]["p_holm"], 0.9)


class TestReliability(unittest.TestCase):
    def runs_for(self, per_task):
        """per_task: {task: (successes, attempts)} for variant A; B mirrors A."""
        rows, entry = [], 0
        for task, (successes, attempts) in per_task.items():
            for repeat in range(1, attempts + 1):
                for variant in ("A", "B"):
                    entry += 1
                    rows.append(
                        row(entry, task, "Python", variant, repeat, passed=repeat <= successes)
                    )
        return rows

    def test_pass_hat_k_matches_the_hand_computation(self):
        # task one: 3 of 4 pass -> pass^1 = 3/4, pass^2 = C(3,2)/C(4,2) = 1/2
        # task two: 2 of 4 pass -> pass^1 = 1/2, pass^2 = C(2,2)/C(4,2) = 1/6
        result = verdict(self.runs_for({"t1": (3, 4), "t2": (2, 4)}), "A", "B")
        left = result["reliability"]["left"]
        self.assertAlmostEqual(left["1"]["value"], (3 / 4 + 1 / 2) / 2)
        self.assertAlmostEqual(left["2"]["value"], (1 / 2 + 1 / 6) / 2)
        self.assertEqual(left["3"]["tasks_used"], 2)
        self.assertAlmostEqual(left["3"]["value"], (1 / 4 + 0) / 2)
        self.assertAlmostEqual(left["4"]["value"], 0.0)

    def test_tasks_with_fewer_attempts_than_k_are_left_out_of_that_k(self):
        result = verdict(self.runs_for({"t1": (2, 2), "t2": (3, 4)}), "A", "B")
        left = result["reliability"]["left"]
        self.assertEqual(left["1"]["tasks_used"], 2)
        self.assertEqual(left["3"]["tasks_used"], 1)
        self.assertAlmostEqual(left["3"]["value"], 1 / 4)

    def test_a_single_attempt_per_task_gives_only_the_pass_rate(self):
        result = verdict(self.runs_for({"t1": (1, 1), "t2": (0, 1)}), "A", "B")
        self.assertEqual(list(result["reliability"]["left"]), ["1"])
        self.assertAlmostEqual(result["reliability"]["left"]["1"]["value"], 0.5)

    def test_excluded_runs_do_not_count_as_attempts(self):
        rows = self.runs_for({"t1": (4, 4)})
        rows = [
            r if r.repeat != 4 else row(r.entry_id, "t1", "Python", r.variant, 4, timed_out=True)
            for r in rows
        ]
        left = verdict(rows, "A", "B")["reliability"]["left"]
        self.assertEqual(sorted(left), ["1", "2", "3"])

    def test_k_stops_at_ten(self):
        left = verdict(self.runs_for({"t1": (12, 12)}), "A", "B")["reliability"]["left"]
        self.assertEqual(list(left), [str(k) for k in range(1, 11)])


class TestHolmAdjust(unittest.TestCase):
    def test_returns_adjusted_values_in_the_original_order(self):
        adjusted = holm_adjust([0.4, 0.01, 0.9, 0.012])
        self.assertEqual([round(v, 6) for v in adjusted], [0.8, 0.04, 0.9, 0.04])

    def test_single_value_and_empty_list(self):
        self.assertEqual(holm_adjust([0.03]), [0.03])
        self.assertEqual(holm_adjust([]), [])

    def test_values_are_capped_at_one(self):
        self.assertEqual(holm_adjust([0.5, 0.6, 0.7]), [1.0, 1.0, 1.0])

    def test_ties_are_adjusted_alike(self):
        adjusted = holm_adjust([0.02, 0.02, 0.5])
        self.assertEqual(adjusted[0], adjusted[1])
