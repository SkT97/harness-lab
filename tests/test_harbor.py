"""Offline tests for importing Harbor's per-trial JSON."""

import json
import tempfile
import unittest
from pathlib import Path

from harness_lab.harbor import harbor_report


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
