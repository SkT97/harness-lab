"""The SWE-bench Verified example: parsing hostile files and pairwise verdicts. No network."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import examples.swebench_verdict as module
from examples.swebench_verdict import _fetch, analyze, main, parse_results


def doc(resolved, extra=()):
    ids = [f"i{n}" for n in resolved]
    return {"resolved": ids, "applied": ids + [f"i{n}" for n in extra], "no_generation": []}


class TestNames(unittest.TestCase):
    def test_names_that_could_leave_the_directory_are_refused_before_any_request(self):
        for bad in ("", ".", "..", "../x", "a/b", "a\b", "x y", "a?b", "a#b", "%2e%2e"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                _fetch(bad, None)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestFetch(unittest.TestCase):
    def test_a_download_is_parsed_cached_and_not_repeated(self):
        body = b'{"resolved": ["i1"]}'
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "examples.swebench_verdict.urllib.request.urlopen", return_value=FakeResponse(body)
            ) as opened,
        ):
            first = _fetch("a+b_1", Path(tmp))
            second = _fetch("a+b_1", Path(tmp))
            self.assertEqual(first, {"resolved": ["i1"]})
            self.assertEqual(second, first)
            self.assertEqual(opened.call_count, 1)
            url = opened.call_args.args[0]
            self.assertTrue(
                url.startswith("https://raw.githubusercontent.com/SWE-bench/experiments/")
            )
            self.assertIn("/evaluation/verified/a+b_1/results/results.json", url)

    def test_an_oversized_response_is_refused_and_not_cached(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "examples.swebench_verdict.urllib.request.urlopen",
                return_value=FakeResponse(b"x" * 3_000_000),
            ),
        ):
            with self.assertRaises(ValueError):
                _fetch("big", Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])


class TestMain(unittest.TestCase):
    def test_a_cached_run_writes_lf_json_without_any_download(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cache = tmp / "cache"
            cache.mkdir()
            ids = [f"i{n}" for n in range(60)]
            for name, count in (("one", 50), ("two", 49), ("three", 10)):
                document = {"resolved": ids[:count], "applied": ids}
                (cache / f"{name}.json").write_text(json.dumps(document), encoding="utf-8")
            manifest = tmp / "m.txt"
            manifest.write_text("one\ntwo\nthree\n", encoding="utf-8")
            out = tmp / "out.json"
            with (
                patch.object(module, "INSTANCES", 60),
                patch(
                    "examples.swebench_verdict.urllib.request.urlopen", side_effect=AssertionError
                ),
            ):
                code = main(
                    [
                        "--manifest",
                        str(manifest),
                        "--cache-dir",
                        str(cache),
                        "--out",
                        str(out),
                        "--top",
                        "3",
                        "--scan",
                        "3",
                    ]
                )
            raw = out.read_bytes()
        self.assertEqual(code, 0)
        self.assertNotIn(b"\r", raw)
        self.assertEqual(json.loads(raw)["submissions"], 3)


class TestParse(unittest.TestCase):
    def test_a_valid_document(self):
        resolved, seen = parse_results(doc([1, 2], extra=[3]), "x")
        self.assertEqual(resolved, {"i1", "i2"})
        self.assertEqual(seen, {"i1", "i2", "i3"})

    def test_hostile_documents_are_refused(self):
        for bad in (
            [],
            {},
            {"resolved": "i1"},
            {"resolved": [1, 2]},
            {"resolved": ["i1", {"a": 1}]},
            {"resolved": ["i" + str(n) for n in range(5000)]},
            {"resolved": ["i1"], "applied": [1]},
        ):
            with self.assertRaises(ValueError, msg=repr(bad)[:40]):
                parse_results(bad, "x")


def results(counts, total=60):
    """Submission name -> (resolved, seen): each resolves the first `count` instances."""
    universe = {f"i{n}" for n in range(total)}
    return {name: ({f"i{n}" for n in range(count)}, universe) for name, count in counts.items()}


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.report = analyze(results({"a": 50, "b": 49, "c": 10, "d": 9}), top=4, scan=4)

    def test_ranking_is_by_resolved_count_then_name(self):
        self.assertEqual([r["name"] for r in self.report["top"]], ["a", "b", "c", "d"])
        self.assertEqual([r["resolved"] for r in self.report["top"]], [50, 49, 10, 9])
        tied = analyze(results({"y": 5, "x": 5}), top=2, scan=2)
        self.assertEqual([r["name"] for r in tied["top"]], ["x", "y"])

    def test_adjacent_pairs_and_the_summary(self):
        verdicts = [row["verdict"] for row in self.report["adjacent"]]
        self.assertEqual(len(verdicts), 3)
        self.assertNotEqual(verdicts[0], "distinguishable")  # 50 against 49 of 60
        self.assertEqual(verdicts[1], "distinguishable")  # 49 against 10 of 60
        summary = self.report["adjacent_summary"]
        self.assertEqual(summary["pairs"], 3)
        self.assertEqual(
            sum(summary[k] for k in ("distinguishable", "bounded_null", "underpowered")), 3
        )

    def test_counts_of_disagreement_are_exact(self):
        first = self.report["adjacent"][0]
        self.assertEqual((first["only_left"], first["only_right"]), (1, 0))

    def test_versus_first_is_holm_adjusted_over_the_scan(self):
        rows = self.report["versus_first"]
        self.assertEqual([r["rank"] for r in rows], [2, 3, 4])
        self.assertTrue(all(r["p_holm"] >= r["p"] for r in rows))
        self.assertFalse(rows[0]["distinguishable_after_holm"])
        self.assertTrue(rows[1]["distinguishable_after_holm"])
        self.assertEqual(self.report["first_distinguishable_rank"], 3)
        self.assertEqual(self.report["distinguishable_from_rank_on"], 3)

    def test_holm_can_overturn_a_raw_significant_difference(self):
        report = analyze(results({"a": 50, "b": 44, "c": 47, "d": 48}), top=4, scan=4)
        by_name = {r["right"]: r for r in report["versus_first"]}
        self.assertEqual(by_name["b"]["verdict"], "distinguishable")
        self.assertAlmostEqual(by_name["b"]["p"], 2 / 64)
        self.assertAlmostEqual(by_name["b"]["p_holm"], 3 * 2 / 64)
        self.assertFalse(by_name["b"]["distinguishable_after_holm"])
        self.assertIsNone(report["first_distinguishable_rank"])

    def test_the_instance_count_is_checked(self):
        with self.assertRaises(ValueError):
            analyze(results({"a": 5, "b": 4}), instances=500)
        analyze(results({"a": 5, "b": 4}), instances=60)

    def test_an_instance_a_submission_does_not_list_counts_as_unresolved(self):
        data = results({"a": 5, "b": 4})
        data["b"] = (data["b"][0], {"i0", "i1", "i2", "i3"})  # lists far fewer instances
        report = analyze(data, instances=60, top=2, scan=2)
        self.assertEqual(report["instances"], 60)
        row = report["adjacent"][0]
        self.assertEqual((row["only_left"], row["only_right"]), (1, 0))

    def test_output_is_strict_json(self):
        import json

        json.dumps(self.report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
