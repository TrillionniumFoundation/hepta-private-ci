"""Local evidence-policy regressions. Fixtures are not native execution receipts."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.hepta_supervisor_evidence import (
    read_regular,
    strict_json,
    validate_transcript,
)

RUN = (
    "Nextest run ID 11111111-1111-4111-8111-111111111111 with nextest profile: local\n"
)


def transcript(expected, *, skipped=0):
    tests = [(binary, name) for binary, names in expected.items() for name in names]
    return (
        RUN
        + "".join(f"PASS [ 0.01s] {b} {n}\n" for b, n in tests)
        + f"Summary [ 0.1s] {len(tests)} tests run: {len(tests)} passed, {skipped} skipped\n"
    ).encode()


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.expected = {"owner": ("fence",), "owner::process": ("restart",)}
        self.log = transcript(self.expected)

    def test_exact_binary_pairs(self):
        result = validate_transcript(self.log, self.expected, 2)
        self.assertEqual(result["required_tests"], 2)
        self.assertEqual(
            result["passed_binary_tests"],
            [["owner", "fence"], ["owner::process", "restart"]],
        )

    def test_foreign_binary_cannot_supply_same_named_test(self):
        with self.assertRaises(ValueError):
            validate_transcript(
                self.log.replace(b"owner::process restart", b"other restart"),
                self.expected,
                2,
            )

    def test_wrong_in_package_binary_cannot_supply_same_name(self):
        with self.assertRaises(ValueError):
            validate_transcript(
                self.log.replace(b"owner::process restart", b"owner restart"),
                self.expected,
                2,
            )

    def test_malformed_run_identifier_rejects(self):
        invalid = self.log.replace(b"11111111-1111-4111-8111-111111111111", b"-" * 36)
        with self.assertRaises(ValueError):
            validate_transcript(invalid, self.expected, 2)

    def test_summary_alone_is_not_execution(self):
        with self.assertRaises(ValueError):
            validate_transcript(
                RUN.encode() + self.log.splitlines(keepends=True)[-1], self.expected, 2
            )

    def test_duplicate_terminal_success_rejects(self):
        duplicate = self.log.replace(b"Summary", b"PASS [ 0.01s] owner fence\nSummary")
        with self.assertRaises(ValueError):
            validate_transcript(duplicate, self.expected, 2)

    def test_repeated_run_and_repeated_summary_reject(self):
        for data in (
            self.log + self.log,
            RUN.encode() + self.log,
            self.log + self.log.splitlines(keepends=True)[-1],
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_transcript(data, self.expected, 2)

    def test_truncated_run_rejects(self):
        with self.assertRaises(ValueError):
            validate_transcript(
                b"\n".join(self.log.splitlines()[:-1]), self.expected, 2
            )

    def test_outside_run_passes_reject(self):
        line = b"PASS [ 0.01s] owner other\n"
        for data in (line + self.log, self.log + line):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_transcript(data, self.expected, 2)

    def test_failure_retry_timeout_leak_and_flaky_reject(self):
        for status in (
            "FAIL",
            "FLAKY",
            "TIMEOUT",
            "LEAK",
            "FL+LK",
            "ABORT",
            "SIGSEGV",
            "TMPASS",
            "TRY 2 PASS",
        ):
            data = self.log.replace(
                b"Summary", f"{status} [ 0.01s] owner retry\nSummary".encode()
            )
            with self.subTest(status=status), self.assertRaises(ValueError):
                validate_transcript(data, self.expected, 2)

    def test_failed_summary_cannot_be_hidden_by_later_success(self):
        failed = b"Summary [ 0.1s] 2 tests run: 1 passed, 1 failed, 0 skipped\n"
        with self.assertRaises(ValueError):
            validate_transcript(failed + self.log, self.expected, 2)

    def test_summary_count_cannot_inflate_observed_passes(self):
        data = self.log.replace(b"2 tests run: 2 passed", b"3 tests run: 3 passed")
        with self.assertRaises(ValueError):
            validate_transcript(data, self.expected, 3)

    def test_skip_never_satisfies_mandatory_case(self):
        with self.assertRaises(ValueError):
            validate_transcript(self.log.replace(b"PASS", b"SKIP", 1), self.expected, 2)

    def test_documented_fixture_skips_are_counted_separately(self):
        result = validate_transcript(
            transcript(self.expected, skipped=1), self.expected, 2
        )
        self.assertEqual((result["passed_tests"], result["skipped_tests"]), (2, 1))

    def test_slow_success_is_not_flaky_or_leaky_success(self):
        slow = self.log.replace(b"2 passed,", b"2 passed (1 slow),")
        self.assertEqual(
            validate_transcript(slow, self.expected, 2)["slow_passed_tests"], 1
        )
        for suffix in (b"3 slow", b"1 flaky", b"1 leaky", b"1 slow, 1 flaky"):
            data = self.log.replace(b"2 passed,", b"2 passed (" + suffix + b"),")
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                validate_transcript(data, self.expected, 2)

    def test_nonfinite_or_boolean_counts_and_empty_requirements_reject(self):
        for count in (True, 0, -1, 2.0, "2"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                validate_transcript(self.log, self.expected, count)
        with self.assertRaises(ValueError):
            validate_transcript(self.log, {}, 2)

    def test_ansi_reporter_format_and_invalid_utf8(self):
        colored = self.log.replace(b"PASS", b"\x1b[32mPASS\x1b[0m")
        validate_transcript(colored, self.expected, 2)
        with self.assertRaises(ValueError):
            validate_transcript(b"\xff" + self.log, self.expected, 2)


class JsonTests(unittest.TestCase):
    def test_accepts_strict_json(self):
        self.assertEqual(strict_json(b'{"a": {"b": false}}'), {"a": {"b": False}})

    def test_rejects_duplicate_fields_recursively(self):
        for value in (
            '{"status":"failed","status":"passed"}',
            '{"before":{"dirty":true,"dirty":false}}',
            '{"rows":[{"x":1,"x":2}]}',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                strict_json(value)

    def test_nonfinite_extensions_reject(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                strict_json('{"duration":' + value + "}")


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "evidence"
        self.path.write_bytes(b"abcd")

    def test_exact_limit_and_empty_file(self):
        self.assertEqual(read_regular(self.path, 4), b"abcd")
        self.path.write_bytes(b"")
        self.assertEqual(read_regular(self.path, 0), b"")

    def test_invalid_limit_rejects_before_open(self):
        for limit in (-1, True, "4", 4.0):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                read_regular(self.path, limit)

    def test_missing_directory_and_oversized_files_reject(self):
        for path, maximum in (
            (self.path, 3),
            (self.root, 4),
            (self.root / "missing", 4),
        ):
            with self.subTest(path=path), self.assertRaises((OSError, ValueError)):
                read_regular(path, maximum)

    @unittest.skipUnless(os.name == "posix", "POSIX fixtures")
    def test_links_fifo_and_sparse_inputs_reject(self):
        link, hard, fifo = (self.root / n for n in ("link", "hard", "fifo"))
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            read_regular(link, 4)
        os.link(self.path, hard)
        with self.assertRaises(ValueError):
            read_regular(self.path, 4)
        hard.unlink()
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            read_regular(fifo, 4)
        with self.path.open("wb") as f:
            f.truncate(2**32)
        with self.assertRaises(ValueError):
            read_regular(self.path, 128)

    def test_replacement_between_lstat_and_open_rejects(self):
        real_open = os.open

        def replaced(path, flags):
            self.path.rename(self.root / "original")
            self.path.write_bytes(b"evil")
            return real_open(path, flags)

        with patch("scripts.hepta_supervisor_evidence.os.open", side_effect=replaced):
            with self.assertRaises(ValueError):
                read_regular(self.path, 4)

    def test_mutation_during_read_rejects(self):
        real_read = os.read

        def mutate(fd, maximum):
            data = real_read(fd, maximum)
            if data:
                with self.path.open("ab") as f:
                    f.write(b"changed")
            return data

        with patch("scripts.hepta_supervisor_evidence.os.read", side_effect=mutate):
            with self.assertRaises(ValueError):
                read_regular(self.path, 64)


class CompanionRequirementTests(unittest.TestCase):
    def test_new_rust_cases_are_required_in_both_library_profiles(self):
        import re
        from scripts.hepta_supervisor_ci import PACKAGE, PLANS, REQUIRED_BINARY_TESTS

        root = Path(__file__).resolve().parents[1] / "codex-rs/hepta-supervisor/src"
        names = set()
        for filename, prefix in (
            ("restart_state_tests.rs", "restart_state::tests::"),
            ("matrix_tick_tests.rs", "matrix::tick::tests::"),
        ):
            text = (root / filename).read_text()
            names.update(
                prefix + name for name in re.findall(r"#\[test\]\s+fn (\w+)", text)
            )
        self.assertEqual(len(names), 14)
        for profile in ("default", "production"):
            required = set(REQUIRED_BINARY_TESTS[profile][PACKAGE])
            self.assertTrue(names <= required, names - required)
            self.assertGreaterEqual(PLANS[profile][0], len(required))

    def test_missing_companion_case_cannot_hide_behind_unchanged_total(self):
        from scripts.hepta_supervisor_ci import PACKAGE, REQUIRED_BINARY_TESTS

        for profile in ("default", "production"):
            required = REQUIRED_BINARY_TESTS[profile]
            log = transcript(required)
            count = len(required[PACKAGE])
            for name in required[PACKAGE]:
                if name.startswith(("restart_state::", "matrix::tick::")):
                    altered = log.replace(name.encode(), (name + "_unrelated").encode())
                    with (
                        self.subTest(profile=profile, name=name),
                        self.assertRaises(ValueError),
                    ):
                        validate_transcript(altered, required, count)

    def test_new_companion_cases_must_come_from_the_library_binary(self):
        from scripts.hepta_supervisor_ci import PACKAGE, REQUIRED_BINARY_TESTS

        required = REQUIRED_BINARY_TESTS["default"]
        log = transcript(required)
        count = len(required[PACKAGE])
        for name in required[PACKAGE]:
            if name.startswith(("restart_state::", "matrix::tick::")):
                altered = log.replace(
                    f"{PACKAGE} {name}".encode(), f"{PACKAGE}::fixture {name}".encode()
                )
                with self.subTest(name=name), self.assertRaises(ValueError):
                    validate_transcript(altered, required, count)


if __name__ == "__main__":
    unittest.main()
