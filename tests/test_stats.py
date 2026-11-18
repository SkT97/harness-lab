"""Quantiles: fixed method, hand-computed literals, missing values respected."""

from __future__ import annotations

import statistics
import unittest

from harness_lab.stats import PERCENTILE_METHOD, distribution, percentile


class TestPercentile(unittest.TestCase):
    def test_method_is_stated(self):
        self.assertIn("linear interpolation", PERCENTILE_METHOD)
        self.assertIn("R type 7", PERCENTILE_METHOD)

    def test_no_observations_is_none_not_zero(self):
        self.assertIsNone(percentile([], 50))
        self.assertIsNone(percentile([], 95))

    def test_single_observation(self):
        self.assertEqual(percentile([7.5], 50), 7.5)
        self.assertEqual(percentile([7.5], 95), 7.5)

    def test_ten_values_hand_computed_literals(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        self.assertAlmostEqual(percentile(values, 50), 5.5, places=9)
        self.assertAlmostEqual(percentile(values, 95), 9.55, places=9)

    def test_four_values_hand_computed_literals(self):
        values = [4.0, 1.0, 2.0, 3.0]  # unsorted on purpose
        self.assertAlmostEqual(percentile(values, 50), 2.5, places=9)
        self.assertAlmostEqual(percentile(values, 95), 3.85, places=9)

    def test_min_and_max_endpoints(self):
        self.assertEqual(percentile([2.0, 8.0], 0), 2.0)
        self.assertEqual(percentile([2.0, 8.0], 100), 8.0)

    def test_agrees_with_statistics_quantiles_inclusive(self):
        values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
        q = statistics.quantiles(values, n=100, method="inclusive")
        self.assertAlmostEqual(percentile(values, 25), q[24], places=9)
        self.assertAlmostEqual(percentile(values, 50), q[49], places=9)
        self.assertAlmostEqual(percentile(values, 95), q[94], places=9)

    def test_out_of_range_percentile_is_rejected(self):
        for bad in (-1, 101):
            with self.subTest(p=bad), self.assertRaises(ValueError):
                percentile([1.0], bad)


class TestDistribution(unittest.TestCase):
    def test_counts_and_missing(self):
        stats = distribution([1.0, None, 3.0, 2.0])
        self.assertEqual(stats["n"], 3)
        self.assertEqual(stats["missing"], 1)
        self.assertAlmostEqual(stats["p50"], 2.0, places=9)
        self.assertAlmostEqual(stats["p95"], 2.9, places=9)

    def test_all_missing_has_no_number_at_all(self):
        stats = distribution([None, None])
        self.assertEqual(stats["n"], 0)
        self.assertEqual(stats["missing"], 2)
        self.assertIsNone(stats["p50"])
        self.assertIsNone(stats["p95"])

    def test_empty_input(self):
        stats = distribution([])
        self.assertEqual(stats, {"n": 0, "missing": 0, "p50": None, "p95": None})


if __name__ == "__main__":
    unittest.main()
