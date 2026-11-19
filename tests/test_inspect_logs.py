"""Inspect AI JSON logs to the CSV contract. Logs are synthetic, in the EvalLog v2 shape."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from harness_lab.cli import main
from harness_lab.compare import compare
from harness_lab.inspect_logs import InspectError, inspect_to_csv
from harness_lab.model import ValidationError, parse_csv_text
from harness_lab.verdict import verdict


def sample(sid, epoch=1, value="C", **extra):
    base = {
        "id": sid,
        "epoch": epoch,
        "scores": {"match": {"value": value}},
        "total_time": 10.0,
        "working_time": 8.0,
        "model_usage": {
            "provider/model": {
                "input_tokens": 100,
                "output_tokens": 40,
                "total_tokens": 190,
                "input_tokens_cache_read": 50,
                "input_tokens_cache_write": None,
            }
        },
        "error": None,
        "limit": None,
    }
    base.update(extra)
    return base


def log(samples, model="provider/model", task="mytask", status="success", version=2):
    return {
        "version": version,
        "status": status,
        "eval": {"task": task, "model": model},
        "samples": samples,
    }


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name: str, document) -> str:
        path = self.dir / name
        path.write_text(
            document if isinstance(document, str) else json.dumps(document), encoding="utf-8"
        )
        return str(path)

    def convert(self, *documents, labels=None, **options):
        paths = [self.write(f"log{i}.json", d) for i, d in enumerate(documents)]
        if labels:
            paths = [f"{label}={path}" for label, path in zip(labels, paths, strict=True)]
        options.setdefault("language", "Python")
        return parse_csv_text(inspect_to_csv(paths, **options))


class TestMapping(Case):
    def test_fields_follow_the_inspect_definitions(self) -> None:
        (run,) = self.convert(log([sample("s1", epoch=2)]))
        self.assertEqual(
            (run.task_id, run.variant, run.repeat, run.language),
            ("mytask/s1", "provider/model", 2, "Python"),
        )
        self.assertTrue(run.passed)
        self.assertEqual(run.wall_s, 10.0)
        # input_tokens is the full-rate input in Inspect, so it is the fresh input here
        self.assertEqual(run.tokens_input, 100)
        self.assertEqual(run.tokens_prompt_total, 150)
        self.assertEqual(run.tokens_output, 40)
        self.assertFalse(run.excluded)

    def test_integer_ids_and_tokens_summed_over_models(self) -> None:
        usage = {
            "a": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            "b": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        }
        (run,) = self.convert(log([sample(7, model_usage=usage)]))
        self.assertEqual(run.task_id, "mytask/7")
        self.assertEqual(
            (run.tokens_input, run.tokens_prompt_total, run.tokens_output), (11, 11, 22)
        )

    def test_missing_usage_stays_blank_not_zero(self) -> None:
        (run,) = self.convert(log([sample("s1", model_usage={})]))
        self.assertEqual(
            (run.tokens_input, run.tokens_prompt_total, run.tokens_output), (None,) * 3
        )

    def test_variant_label_overrides_the_model_name(self) -> None:
        path = self.write("l.json", log([sample("s1")]))
        text = inspect_to_csv([f"harness-b={path}"], language="Python")
        self.assertEqual(parse_csv_text(text)[0].variant, "harness-b")

    def test_a_path_with_an_equals_sign_in_the_directory_is_a_path(self) -> None:
        directory = self.dir / "run=1"
        directory.mkdir()
        path = directory / "l.json"
        path.write_text(json.dumps(log([sample("s1")])), encoding="utf-8")
        self.assertEqual(
            parse_csv_text(inspect_to_csv([str(path)], language="Python"))[0].variant,
            "provider/model",
        )


class TestScores(Case):
    def test_strict_binary_values(self) -> None:
        runs = self.convert(
            log(
                [
                    sample("a", value="C"),
                    sample("b", value="I"),
                    sample("c", value=True),
                    sample("d", value=False),
                    sample("e", value=1),
                    sample("f", value=0.0),
                ]
            )
        )
        self.assertEqual([r.passed for r in runs], [True, False, True, False, True, False])

    def test_partial_and_fractional_values_are_refused_not_guessed(self) -> None:
        for value in ("P", "N", 0.5, ["C"], {"a": 1}):
            with self.assertRaises(InspectError, msg=repr(value)):
                self.convert(log([sample("a", value=value)]))

    def test_several_scores_need_a_choice(self) -> None:
        both = {"scores": {"match": {"value": "C"}, "other": {"value": "I"}}}
        with self.assertRaisesRegex(InspectError, "--score"):
            self.convert(log([sample("a", **both)]))
        (run,) = self.convert(log([sample("a", **both)]), score="other")
        self.assertFalse(run.passed)

    def test_an_unknown_score_name_is_refused(self) -> None:
        with self.assertRaisesRegex(InspectError, "nope"):
            self.convert(log([sample("a")]), score="nope")

    def test_a_sample_without_scores_is_refused(self) -> None:
        with self.assertRaisesRegex(InspectError, "no scores"):
            self.convert(log([sample("a", scores=None)]))


class TestExclusions(Case):
    def test_an_error_is_an_infrastructure_exclusion(self) -> None:
        (run,) = self.convert(log([sample("a", value="I", error={"message": "boom"})]))
        self.assertTrue(run.infra_error)
        self.assertTrue(run.excluded)

    def test_time_limits_are_timeouts(self) -> None:
        for kind in ("time", "working"):
            (run,) = self.convert(log([sample("a", value="I", limit={"type": kind, "limit": 5})]))
            self.assertTrue(run.timed_out, kind)

    def test_budget_limits_are_failed_runs_not_exclusions(self) -> None:
        for kind in ("token", "message", "turn", "cost", "context", "custom"):
            (run,) = self.convert(log([sample("a", value="I", limit={"type": kind, "limit": 5})]))
            self.assertFalse(run.excluded, kind)
            self.assertFalse(run.passed)

    def test_an_operator_stop_is_not_a_quality_result(self) -> None:
        (run,) = self.convert(log([sample("a", value="I", limit={"type": "operator", "limit": 0})]))
        self.assertTrue(run.infra_error)

    def test_an_errored_sample_without_scores_or_times_is_kept_as_excluded(self) -> None:
        (run,) = self.convert(
            log(
                [
                    sample(
                        "a", scores=None, total_time=None, working_time=None, error={"message": "x"}
                    )
                ]
            )
        )
        self.assertTrue(run.excluded)
        self.assertEqual(run.wall_s, 0.0)
        self.assertFalse(run.passed)

    def test_working_time_is_the_fallback_for_wall_time(self) -> None:
        (run,) = self.convert(log([sample("a", total_time=None, working_time=3.5)]))
        self.assertEqual(run.wall_s, 3.5)

    def test_a_completed_sample_without_any_time_is_refused(self) -> None:
        with self.assertRaisesRegex(InspectError, "time"):
            self.convert(log([sample("a", total_time=None, working_time=None)]))


class TestLogs(Case):
    def test_unfinished_logs_are_refused_unless_allowed(self) -> None:
        for status in ("started", "error", "cancelled"):
            with self.assertRaisesRegex(InspectError, "allow-incomplete"):
                self.convert(log([sample("a")], status=status))
        (run,) = self.convert(log([sample("a")], status="error"), allow_incomplete=True)
        self.assertEqual(run.task_id, "mytask/a")

    def test_other_formats_and_versions_are_refused(self) -> None:
        with self.assertRaisesRegex(InspectError, "inspect log convert"):
            inspect_to_csv([self.write("l.eval", "binary")], language="Python")
        with self.assertRaisesRegex(InspectError, "version"):
            self.convert(log([sample("a")], version=3))
        with self.assertRaises(InspectError):
            self.convert("not json")
        with self.assertRaises(InspectError):
            self.convert({"version": 2})
        with self.assertRaisesRegex(InspectError, "no samples"):
            self.convert(log([]))
        with self.assertRaisesRegex(InspectError, "no samples"):
            self.convert(log(None))

    def test_an_empty_model_name_is_caught_by_the_csv_contract(self) -> None:
        path = self.write("l.json", log([sample("a")], model=""))
        with self.assertRaises(ValidationError):
            inspect_to_csv([path], language="Python")

    def test_two_logs_of_the_same_model_need_labels(self) -> None:
        with self.assertRaisesRegex(InspectError, "duplicate"):
            self.convert(log([sample("a")]), log([sample("a")]))
        self.assertEqual(
            len(self.convert(log([sample("a")]), log([sample("a")]), labels=["x", "y"])), 2
        )

    def test_an_integer_id_and_its_string_form_collide(self) -> None:
        with self.assertRaisesRegex(InspectError, "duplicate"):
            self.convert(log([sample(1), sample("1")]))

    def test_the_language_must_be_one_the_contract_knows(self) -> None:
        with self.assertRaisesRegex(InspectError, "language"):
            self.convert(log([sample("a")]), language="Rust")

    def test_every_bad_sample_is_reported_with_its_identity(self) -> None:
        with self.assertRaises(InspectError) as ctx:
            self.convert(log([sample("x1", value="P"), sample("x2", value="N")]))
        message = str(ctx.exception)
        self.assertIn("2 sample(s)", message)
        self.assertIn("x1", message)
        self.assertIn("x2", message)


class TestEndToEnd(Case):
    def test_converted_logs_feed_compare_and_verdict(self) -> None:
        left = log([sample(i, value="C" if i < 10 else "I") for i in range(12)], model="m/left")
        right = log([sample(i, value="I" if i < 9 else "C") for i in range(12)], model="m/right")
        runs = self.convert(left, right)
        report = compare(runs, "m/left", "m/right")
        self.assertEqual(report["paired_success"]["pairs"], 12)
        result = verdict(runs, "m/left", "m/right")
        self.assertEqual(result["primary"]["counts"]["only_left_passed"], 9)
        self.assertEqual(result["primary"]["counts"]["only_right_passed"], 2)

    def test_cli_writes_the_csv(self) -> None:
        path = self.write("l.json", log([sample("a"), sample("b", value="I")]))
        out_file = self.dir / "runs.csv"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["inspect-csv", path, "--language", "Python", "--out", str(out_file)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(len(parse_csv_text(out_file.read_text(encoding="utf-8"))), 2)

    def test_cli_reports_a_refusal_without_a_traceback(self) -> None:
        path = self.write("l.json", log([sample("a", value="P")]))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["inspect-csv", path, "--language", "Python"])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err.getvalue())
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
