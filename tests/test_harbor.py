"""Offline tests for importing Harbor's per-trial JSON."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from harness_lab.cli import main
from harness_lab.harbor import HarborError, harbor_report


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI without letting its output reach the test console."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def symlinks_are_usable() -> bool:
    """Whether this OS and account let the test process create a symlink."""
    with tempfile.TemporaryDirectory() as probe:
        target = Path(probe) / "target"
        link = Path(probe) / "link"
        try:
            target.mkdir()
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
    return True


SYMLINKS_USABLE = symlinks_are_usable()


class HarborReportTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = self.root / "job"
        self.job.mkdir()
        self.manifest = self.root / "manifest.json"

    def trial(self, trial_name, reward, **fields):
        directory = self.job / trial_name
        directory.mkdir()
        result = directory / "result.json"
        result.write_text(
            json.dumps(
                {
                    "trial_name": trial_name,
                    "task_name": "slugify",
                    "task_checksum": "fixture-checksum",
                    "agent_info": {"name": "test-agent", "version": "1"},
                    "verifier_result": {"rewards": {"reward": reward}},
                    "exception_info": None,
                    **fields,
                }
            ),
            encoding="utf-8",
        )
        return result

    def write_manifest(self):
        payload = {
            "schema_version": 1,
            "harbor_version": "0.26.0",
            "campaign": "offline-example",
            "benchmark": "synthetic",
            "benchmark_revision": "v1",
            "limits": {"timeout_seconds": 30},
            "trials": [
                {
                    "trial_name": name,
                    "task_name": "slugify",
                    "task_checksum": "fixture-checksum",
                    "configuration": "baseline",
                    "repeat": index,
                }
                for index, name in enumerate(("pass", "fail", "network", "partial", "missing"))
            ],
        }
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")

    def test_quality_denominator_differs_from_planned_denominator(self):
        self.write_manifest()
        self.trial("pass", 1, schema_version=1)
        self.trial("fail", 0)
        self.trial(
            "network", 0, reward_valid=False, exception_info={"exception_type": "NetworkError"}
        )
        self.trial("partial", 0.5, reward_valid=True)
        report = harbor_report(self.job, self.manifest, "reward")
        self.assertEqual(report["counts"]["planned"], 5)
        self.assertEqual(report["counts"]["observed"], 4)
        self.assertEqual(report["counts"]["evaluable_binary"], 2)
        self.assertEqual(report["counts"]["missing_planned"], 1)
        self.assertEqual(report["counts"]["exceptions"], 1)
        self.assertEqual(report["counts"]["non_binary"], 1)
        self.assertEqual(report["rates"]["success_per_planned"], 0.2)
        self.assertEqual(report["rates"]["success_per_evaluable"], 0.5)
        self.assertEqual(report["rates"]["observed_per_planned"], 0.8)
        self.assertEqual(report["campaign"]["benchmark_revision"], "v1")
        self.assertEqual(
            {row["trial_name"]: row["reward"] for row in report["trials"]}["partial"], 0.5
        )

    def test_unknown_plan_and_missing_score_are_kept_unknown(self):
        self.trial("trial", None, verifier_result=None)
        report = harbor_report(self.job, None, "reward")
        self.assertIsNone(report["counts"]["planned"])
        self.assertIsNone(report["rates"]["success_per_planned"])
        self.assertIsNone(report["rates"]["success_per_evaluable"])
        self.assertEqual(report["counts"]["missing_reward"], 1)

    def test_unknown_schema_and_duplicate_keys_fail(self):
        result = self.trial("trial", 1, schema_version=2)
        with self.assertRaisesRegex(ValueError, "unsupported trial schema"):
            harbor_report(self.job, None, "reward")
        result.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            harbor_report(self.job, None, "reward")

    def test_trial_revision_must_match_plan(self):
        self.write_manifest()
        self.trial("pass", 1, task_checksum="different-revision")
        with self.assertRaisesRegex(ValueError, "does not match manifest"):
            harbor_report(self.job, self.manifest, "reward")

    def test_exception_with_missing_reward_is_counted_in_both_dimensions(self):
        self.trial("trial", None, exception_info={"exception_type": "ProviderError"})
        report = harbor_report(self.job, None, "reward")
        self.assertEqual(report["counts"]["exceptions"], 1)
        self.assertEqual(report["counts"]["missing_reward"], 1)

    def clear_job(self):
        """Empty the job directory so that a check imports exactly one trial."""
        for entry in sorted(self.job.iterdir()):
            if entry.is_dir() and not entry.is_symlink() and not entry.is_junction():
                shutil.rmtree(entry)
            else:
                entry.unlink()

    def write_document(self, text, name="trial"):
        directory = self.job / name
        directory.mkdir()
        path = directory / "result.json"
        path.write_text(text, encoding="utf-8")
        return path

    def test_non_numeric_and_non_finite_rewards_are_rejected(self):
        for label, reward in (
            ("string", "1"),
            ("boolean", True),
            ("NaN", float("nan")),
            ("Infinity", float("inf")),
        ):
            with self.subTest(reward=label):
                self.clear_job()
                self.trial("trial", reward)
                with self.assertRaisesRegex(HarborError, "reward must be a finite number"):
                    harbor_report(self.job, None, "reward")

    def test_non_boolean_reward_valid_is_rejected(self):
        for label, value in (("string", "true"), ("integer", 1), ("null", None)):
            with self.subTest(reward_valid=label):
                self.clear_job()
                self.trial("trial", 1, reward_valid=value)
                with self.assertRaisesRegex(HarborError, "reward_valid must be a boolean"):
                    harbor_report(self.job, None, "reward")

    def test_non_object_document_is_rejected(self):
        for label, text in (("array", "[]"), ("string", '"pass"'), ("number", "1")):
            with self.subTest(document=label):
                self.clear_job()
                self.write_document(text)
                with self.assertRaisesRegex(HarborError, "document must be an object"):
                    harbor_report(self.job, None, "reward")

    def test_invalid_reward_flag_is_counted_on_its_own(self):
        self.trial("valid", 1)
        self.trial("invalid", 0, reward_valid=False)
        report = harbor_report(self.job, None, "reward")
        self.assertEqual(report["counts"]["invalid_reward"], 1)
        self.assertEqual(report["counts"]["missing_reward"], 0)
        self.assertEqual(report["counts"]["non_binary"], 0)
        self.assertEqual(report["counts"]["evaluable_binary"], 1)
        self.assertEqual(report["counts"]["passed"], 1)

    def test_fractional_reward_is_counted_as_non_binary(self):
        self.trial("half", 0.5)
        self.trial("whole", 1)
        report = harbor_report(self.job, None, "reward")
        self.assertEqual(report["counts"]["non_binary"], 1)
        self.assertEqual(report["counts"]["invalid_reward"], 0)
        self.assertEqual(report["counts"]["evaluable_binary"], 1)
        self.assertEqual([row["outcome"] for row in report["trials"]], ["unevaluable", "pass"])

    def test_counts_expose_exactly_the_documented_fields(self):
        self.write_manifest()
        self.trial("pass", 1)
        report = harbor_report(self.job, self.manifest, "reward")
        self.assertEqual(
            set(report["counts"]),
            {
                "planned",
                "observed",
                "missing_planned",
                "evaluable_binary",
                "passed",
                "failed",
                "exceptions",
                "missing_reward",
                "invalid_reward",
                "non_binary",
                "skipped_links",
            },
        )
        self.assertEqual(report["counts"]["skipped_links"], 0)

    def test_a_plain_file_in_the_job_directory_is_not_a_skipped_link(self):
        self.trial("trial", 1)
        (self.job / "notes.txt").write_text("not a trial", encoding="utf-8")
        report = harbor_report(self.job, None, "reward")
        self.assertEqual(report["counts"]["observed"], 1)
        self.assertEqual(report["counts"]["skipped_links"], 0)

    @unittest.skipUnless(SYMLINKS_USABLE, "this OS or account cannot create symlinks")
    def test_symlinked_trials_are_skipped_and_counted_without_leaking_names(self):
        self.trial("real", 1)
        outside = self.root / "outside-job"
        outside.mkdir()
        (outside / "result.json").write_text(
            json.dumps(
                {
                    "trial_name": "linked-dir",
                    "task_name": "slugify",
                    "task_checksum": "fixture-checksum",
                    "agent_info": {"name": "test-agent", "version": "1"},
                    "verifier_result": {"rewards": {"reward": 1}},
                    "exception_info": None,
                }
            ),
            encoding="utf-8",
        )
        (self.job / "linked-dir").symlink_to(outside, target_is_directory=True)
        mirror = self.job / "mirrored-result"
        mirror.mkdir()
        (mirror / "result.json").symlink_to(self.job / "real" / "result.json")
        (self.job / "gone-dir").symlink_to(self.root / "absent", target_is_directory=True)

        report = harbor_report(self.job, None, "reward")
        self.assertEqual(report["counts"]["observed"], 1)
        self.assertEqual(report["counts"]["evaluable_binary"], 1)
        self.assertEqual(report["counts"]["skipped_links"], 3)
        self.assertEqual([row["trial_name"] for row in report["trials"]], ["real"])
        text = json.dumps(report)
        self.assertNotIn("linked-dir", text)
        self.assertNotIn("mirrored-result", text)
        self.assertNotIn("gone-dir", text)
        self.assertNotIn(self.root.name, text)
        self.assertNotIn(str(self.root), text)


class HarborCliTest(unittest.TestCase):
    def test_missing_job_dir_is_a_clean_error_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            absent = Path(temporary) / "no-such-job"
            code, out, err = run_cli(["harbor-report", "--job-dir", str(absent)])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("harness-lab:"))
        self.assertNotIn("Traceback", err)
        self.assertIn("no-such-job", err)
