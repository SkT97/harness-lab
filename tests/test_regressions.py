"""Reject contradictory metadata instead of producing plausible comparisons."""

import unittest

from harness_lab.compare import CompareError, compare
from harness_lab.model import ValidationError, parse_csv_text
from tests.support import csv_text, row


class MetadataTest(unittest.TestCase):
    def test_parser_rejects_conflicting_task_languages(self):
        rows = [row(1, "T01", "Python", "a", 0), row(2, "T01", "Java", "b", 0)]
        with self.assertRaisesRegex(ValidationError, "inconsistent language"):
            parse_csv_text(csv_text(rows))

    def test_compare_rejects_conflicting_languages_even_for_direct_runs(self):
        rows = [row(1, "T01", "Python", "a", 0), row(2, "T01", "Java", "b", 0)]
        with self.assertRaisesRegex(CompareError, "inconsistent language"):
            compare(rows, "a", "b")

    def test_zero_based_repeat_is_valid(self):
        self.assertEqual(parse_csv_text(csv_text([row(1, "T01", "Java", "a", 0)]))[0].repeat, 0)

    def test_reordered_header_preserves_fields(self):
        text = csv_text([row(1, "T01", "Java", "a", 0)])
        header, record = text.strip().splitlines()
        reordered = (
            ",".join(reversed(header.split(","))) + "\n" + ",".join(reversed(record.split(",")))
        )
        self.assertEqual(parse_csv_text(reordered)[0].task_id, "T01")
