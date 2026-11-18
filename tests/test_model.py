"""Input contract: types, ranges, duplicates, missing IDs, clear failures."""

from __future__ import annotations

import unittest

from harness_lab.model import (
    ALLOWED_LANGUAGES,
    REQUIRED_COLUMNS,
    ValidationError,
    load_csv,
    parse_csv_text,
)
from tests.support import HEADER, row


def one_line_csv(**overrides) -> str:
    """A single valid data row with the given cells replaced."""
    cells = {
        "entry_id": "1",
        "task_id": "T01",
        "language": "Python",
        "variant": "agent-a",
        "repeat": "1",
        "passed": "true",
        "wall_s": "1.5",
        "tokens_input": "10",
        "tokens_prompt_total": "20",
        "tokens_output": "5",
        "network_error": "false",
        "infra_error": "false",
        "timed_out": "false",
    }
    cells.update(overrides)
    return HEADER + "\n" + ",".join(cells[c] for c in HEADER.split(",")) + "\n"


class TestColumns(unittest.TestCase):
    def test_required_columns_match_the_documented_header(self):
        self.assertEqual(tuple(HEADER.split(",")), REQUIRED_COLUMNS)

    def test_missing_column_is_rejected_with_name(self):
        header = HEADER.replace(",timed_out", "")
        body = "1,T01,Python,agent-a,1,true,1.5,10,20,5,false,false\n"
        with self.assertRaises(ValidationError) as ctx:
            parse_csv_text(header + "\n" + body)
        self.assertIn("timed_out", str(ctx.exception))

    def test_unknown_column_is_rejected_with_name(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_csv_text(HEADER + ",secret_note\n1,T01,Python,a,1,true,1,1,1,1,f,f,f,x\n")
        self.assertIn("secret_note", str(ctx.exception))

    def test_empty_input_is_rejected(self):
        with self.assertRaises(ValidationError):
            parse_csv_text("")

    def test_header_only_is_valid_and_empty(self):
        self.assertEqual(parse_csv_text(HEADER + "\n"), [])


class TestFieldValidation(unittest.TestCase):
    def test_valid_row_round_trips_into_a_run(self):
        (run_,) = parse_csv_text(one_line_csv())
        self.assertEqual(
            run_,
            row(
                1,
                "T01",
                "Python",
                "agent-a",
                1,
                passed=True,
                wall_s=1.5,
                tokens_input=10,
                tokens_prompt_total=20,
                tokens_output=5,
            ),
        )

    def test_missing_entry_id_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_csv_text(one_line_csv(entry_id=""))
        self.assertIn("entry_id", str(ctx.exception))

    def test_non_integer_entry_id_is_rejected(self):
        with self.assertRaises(ValidationError):
            parse_csv_text(one_line_csv(entry_id="1x"))

    def test_zero_entry_id_is_rejected(self):
        with self.assertRaises(ValidationError):
            parse_csv_text(one_line_csv(entry_id="0"))

    def test_duplicate_entry_id_is_rejected_with_both_lines(self):
        text = (
            HEADER + "\n"
            "1,T01,Python,agent-a,1,true,1,1,1,1,false,false,false\n"
            "1,T02,Java,agent-a,1,true,1,1,1,1,false,false,false\n"
        )
        with self.assertRaises(ValidationError) as ctx:
            parse_csv_text(text)
        message = str(ctx.exception)
        self.assertIn("duplicate entry_id", message)
        self.assertIn("line 2", message)
        self.assertIn("line 3", message)

    def test_missing_task_id_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_csv_text(one_line_csv(task_id="   "))
        self.assertIn("task_id", str(ctx.exception))

    def test_unknown_language_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_csv_text(one_line_csv(language="React"))
        self.assertIn("language", str(ctx.exception))
        self.assertIn("TypeScript", str(ctx.exception))

    def test_allowed_languages_are_the_three_documented_ones(self):
        self.assertEqual(ALLOWED_LANGUAGES, ("Java", "Python", "TypeScript"))

    def test_missing_variant_is_rejected(self):
        with self.assertRaises(ValidationError):
            parse_csv_text(one_line_csv(variant=""))

    def test_repeat_must_be_a_nonnegative_integer(self):
        for bad in ("", "-1", "1.5", "many"):
            with self.subTest(repeat=bad):
                with self.assertRaises(ValidationError):
                    parse_csv_text(one_line_csv(repeat=bad))

    def test_bool_fields_accept_the_documented_spellings(self):
        for truthy in ("true", "TRUE", "1", "yes", "y"):
            with self.subTest(truthy=truthy):
                (run_,) = parse_csv_text(one_line_csv(passed=truthy))
                self.assertIs(run_.passed, True)
        for falsy in ("false", "FALSE", "0", "no", "n"):
            with self.subTest(falsy=falsy):
                (run_,) = parse_csv_text(one_line_csv(passed=falsy))
                self.assertIs(run_.passed, False)

    def test_unparsable_bool_is_rejected(self):
        for bad in ("maybe", "2", ""):
            with self.subTest(value=bad):
                with self.assertRaises(ValidationError):
                    parse_csv_text(one_line_csv(passed=bad))

    def test_wall_s_must_be_finite_and_non_negative(self):
        for bad in ("nan", "NaN", "inf", "-inf", "-0.5", "", "abc"):
            with self.subTest(wall_s=bad):
                with self.assertRaises(ValidationError):
                    parse_csv_text(one_line_csv(wall_s=bad))

    def test_wall_s_zero_is_allowed(self):
        (run_,) = parse_csv_text(one_line_csv(wall_s="0"))
        self.assertEqual(run_.wall_s, 0.0)

    def test_negative_tokens_are_rejected(self):
        for column in ("tokens_input", "tokens_prompt_total", "tokens_output"):
            with self.subTest(column=column):
                with self.assertRaises(ValidationError) as ctx:
                    parse_csv_text(one_line_csv(**{column: "-1"}))
                self.assertIn(column, str(ctx.exception))

    def test_fractional_tokens_are_rejected(self):
        with self.assertRaises(ValidationError):
            parse_csv_text(one_line_csv(tokens_output="1.5"))

    def test_nan_tokens_are_rejected(self):
        with self.assertRaises(ValidationError):
            parse_csv_text(one_line_csv(tokens_input="nan"))

    def test_empty_tokens_are_none_not_zero(self):
        (run_,) = parse_csv_text(
            one_line_csv(tokens_input="", tokens_prompt_total="  ", tokens_output="")
        )
        self.assertIsNone(run_.tokens_input)
        self.assertIsNone(run_.tokens_prompt_total)
        self.assertIsNone(run_.tokens_output)

    def test_short_row_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_csv_text(HEADER + "\n1,T01,Python,agent-a,1,true,1\n")
        self.assertIn("fields", str(ctx.exception))

    def test_long_row_is_rejected(self):
        with self.assertRaises(ValidationError):
            parse_csv_text(HEADER + "\n" + "1," * 13 + "\n")

    def test_every_bad_cell_is_reported_not_only_the_first(self):
        text = (
            HEADER + "\n"
            "1,T01,Python,agent-a,1,true,nan,10,20,5,false,false,false\n"
            "2,T02,Java,agent-b,1,true,2.0,-1,20,5,false,false,false\n"
        )
        with self.assertRaises(ValidationError) as ctx:
            parse_csv_text(text)
        message = str(ctx.exception)
        self.assertIn("line 2", message)
        self.assertIn("line 3", message)
        self.assertGreaterEqual(len(ctx.exception.errors), 2)

    def test_error_message_names_the_source(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_csv_text(one_line_csv(wall_s="nan"), source="runs.csv")
        self.assertIn("runs.csv", str(ctx.exception))


class TestRunModel(unittest.TestCase):
    def test_excluded_is_true_for_any_single_flag(self):
        for flag in ("network_error", "infra_error", "timed_out"):
            with self.subTest(flag=flag):
                self.assertTrue(row(1, "T01", "Python", "a", 1, **{flag: True}).excluded)

    def test_overlapping_flags_list_every_reason(self):
        run_ = row(1, "T01", "Python", "a", 1, network_error=True, timed_out=True)
        self.assertTrue(run_.excluded)
        self.assertEqual(run_.exclusion_flags, ("network_error", "timed_out"))

    def test_clean_run_is_not_excluded(self):
        clean = row(1, "T01", "Python", "a", 1)
        self.assertFalse(clean.excluded)
        self.assertEqual(clean.exclusion_flags, ())

    def test_cell_key_is_task_and_repeat(self):
        self.assertEqual(row(1, "T07", "Java", "a", 3).cell, ("T07", 3))


class TestLoadCsv(unittest.TestCase):
    def test_load_csv_reads_utf8_bom(self):
        import os
        import tempfile

        text = one_line_csv()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runs.csv")
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                handle.write(text)
            rows = load_csv(path)
        self.assertEqual(len(rows), 1)

    def test_missing_file_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            load_csv("no-such-file-anywhere.csv")

    def test_undecodable_file_raises_validation_error(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runs.csv")
            with open(path, "wb") as handle:
                handle.write(b"\xff\xfe\x00garbage")
            with self.assertRaises(ValidationError) as ctx:
                load_csv(path)
            self.assertIn("utf-8", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
