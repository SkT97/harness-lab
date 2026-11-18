"""Verify that the shipped demonstration labels synthetic measurements."""

import unittest
from pathlib import Path


class ExampleTest(unittest.TestCase):
    def test_shipped_example_is_labelled_synthetic(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "commands.md"
        self.assertIn("synthetic", path.read_text().lower())
