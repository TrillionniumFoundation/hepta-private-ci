"""Negative tests for supervisor CI receipt validation, not Rust qualification."""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.hepta_supervisor_ci import CONTEXT_ENV
from scripts.hepta_supervisor_ci import CONTEXT_FIELDS
from scripts.hepta_supervisor_ci import PLANS
from scripts.hepta_supervisor_ci import REQUIRED_BINARY_TESTS
from scripts.hepta_supervisor_ci import REQUIRED_TESTS
from scripts.hepta_supervisor_ci import context_from_env
from scripts.hepta_supervisor_ci import read_regular
from scripts.hepta_supervisor_ci import validate_record
from scripts.test_hepta_supervisor_evidence import transcript


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.context = dict(
            zip(
                CONTEXT_FIELDS,
                (
                    "a" * 40,
                    "b" * 40,
                    "a" * 40,
                    "source-head",
                    "17",
                    "1",
                ),
                strict=True,
            )
        )
        self.identity = {
            "commit": "a" * 40,
            "tree": "c" * 40,
            "parents": ["b" * 40],
            "dirty": False,
        }
        self.log = transcript(REQUIRED_BINARY_TESTS["products"])
        self.count = len(REQUIRED_TESTS["products"])
        self.record = {
            "schema_version": 1,
            "status": "passed",
            **self.context,
            "command": PLANS["products"][1].copy(),
            "minimum_tests": PLANS["products"][0],
            "before": copy.deepcopy(self.identity),
            "after": copy.deepcopy(self.identity),
            "returncode": 0,
            "command_exit_code": 0,
            "exit_code": 0,
            "timed_out": False,
            "output_limit_exceeded": False,
            "observed_passed_tests": self.count,
            "observed_failed_tests": 0,
            "log_bytes": len(self.log),
            "log_sha256": hashlib.sha256(self.log).hexdigest(),
        }

    def validate(self, data=None, counts=None, log=None, identity=None):
        # Summary parser is stubbed here; exact transcript parsing is NOT stubbed.
        return validate_record(
            "products",
            self.record if data is None else data,
            self.context,
            self.identity if identity is None else identity,
            self.log if log is None else log,
            lambda _text: (self.count, 0) if counts is None else counts,
        )

    def test_accepts_exact_record(self):
        self.assertEqual(self.validate()["required_tests"], self.count)

    def test_rejects_nonterminal_failed_and_skipped_records(self):
        for status in (None, "running", "failed", "skipped", "rejected"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.validate({**self.record, "status": status})

    def test_rejects_missing_and_noninteger_exit_fields(self):
        for field in (
            "returncode",
            "command_exit_code",
            "exit_code",
            "observed_failed_tests",
        ):
            for value in (None, False, True, "0", 1, -1):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(ValueError),
                ):
                    self.validate({**self.record, field: value})

    def test_rejects_timeout_and_output_overflow(self):
        for field in ("timed_out", "output_limit_exceeded"):
            for value in (True, None, 0, "false"):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(ValueError),
                ):
                    self.validate({**self.record, field: value})

    def test_rejects_cross_head_lane_run_and_attempt_substitution(self):
        for field in CONTEXT_FIELDS:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate({**self.record, field: "different"})

    def test_rejects_weaker_command_and_test_minimum(self):
        for update in (
            {"command": ["true"]},
            {"command": None},
            {"minimum_tests": 0},
            {"minimum_tests": True},
        ):
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.validate({**self.record, **update})

    def test_rejects_mutated_and_dirty_source_identity(self):
        for field in ("before", "after"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(
                    {**self.record, field: {**self.identity, "tree": "d" * 40}}
                )
        dirty = {**self.identity, "dirty": True}
        with self.assertRaises(ValueError):
            self.validate(
                {**self.record, "before": dirty, "after": dirty}, identity=dirty
            )

    def test_integer_zero_cannot_impersonate_a_clean_snapshot_boolean(self):
        for phase in ("before", "after"):
            record = copy.deepcopy(self.record)
            record[phase]["dirty"] = 0
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                self.validate(record)

    def test_rejects_truncated_or_substituted_log(self):
        for log in (self.log[:-1], b"different runner bytes"):
            with self.subTest(log=log), self.assertRaises(ValueError):
                self.validate(log=log)

    def test_rejects_fabricated_test_counts(self):
        with self.assertRaises(ValueError):
            self.validate(counts=(self.count - 1, 0))
        with self.assertRaises(ValueError):
            self.validate({**self.record, "observed_passed_tests": 0}, counts=(0, 0))
        with self.assertRaises(ValueError):
            self.validate(counts=(self.count, 1))

    def test_rejects_missing_schema_and_boolean_schema(self):
        for value in (None, True, 2, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate({**self.record, "schema_version": value})

    def test_exact_context_requires_run_identity(self):
        env = dict(zip(CONTEXT_ENV, self.context.values(), strict=True))
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(context_from_env(), self.context)
        for field in CONTEXT_ENV:
            with (
                self.subTest(field=field),
                patch.dict(os.environ, {**env, field: ""}, clear=True),
            ):
                with self.assertRaises(ValueError):
                    context_from_env()

    def test_rejects_invalid_sha_and_attempt_shapes(self):
        env = dict(zip(CONTEXT_ENV, self.context.values(), strict=True))
        for field, value in (
            ("SOURCE_SHA", "A" * 40),
            ("TESTED_SHA", "a" * 39),
            ("BASE_SHA", "main"),
            ("GITHUB_RUN_ATTEMPT", "0"),
            ("GITHUB_RUN_ID", "-1"),
            ("HEPTA_CI_LANE", "skipped"),
            ("SOURCE_SHA", "0" * 40),
        ):
            with self.subTest(field=field, value=value):
                with patch.dict(os.environ, {**env, field: value}, clear=True):
                    with self.assertRaises(ValueError):
                        context_from_env()

    def test_read_regular_is_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "log"
            path.write_bytes(b"abcd")
            self.assertEqual(read_regular(path, 4), b"abcd")
            with self.assertRaises(ValueError):
                read_regular(path, 3)
            with self.assertRaises(ValueError):
                read_regular(Path(root), 4)
            with self.assertRaises((OSError, ValueError)):
                read_regular(Path(root) / "missing", 4)

    @unittest.skipUnless(os.name == "posix", "POSIX symlink fixture")
    def test_read_regular_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "log"
            path.write_bytes(b"abcd")
            link = Path(root) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                read_regular(link, 4)

    def test_library_lanes_require_every_owner_and_cancellation_case(self):
        for lane in ("default", "production", "default-products"):
            log = transcript(REQUIRED_BINARY_TESTS[lane])
            count = len(REQUIRED_TESTS[lane])
            record = {
                **self.record,
                "command": PLANS[lane][1].copy(),
                "minimum_tests": PLANS[lane][0],
                "log_bytes": len(log),
                "observed_passed_tests": count,
                "log_sha256": hashlib.sha256(log).hexdigest(),
            }
            validate_record(
                lane, record, self.context, self.identity, log, lambda _: (count, 0)
            )
            for name in REQUIRED_TESTS[lane]:
                missing = log.replace(name.encode(), b"unrelated")
                changed = {
                    **record,
                    "log_bytes": len(missing),
                    "log_sha256": hashlib.sha256(missing).hexdigest(),
                }
                with self.subTest(lane=lane, name=name), self.assertRaises(ValueError):
                    validate_record(
                        lane,
                        changed,
                        self.context,
                        self.identity,
                        missing,
                        lambda _: (count, 0),
                    )

    def test_parent_command_without_binary_tests_cannot_be_reused(self):
        command = self.record["command"].copy()
        index = command.index("--bin")
        del command[index : index + 2]
        with self.assertRaises(ValueError):
            self.validate({**self.record, "command": command})

    def test_total_pass_count_cannot_hide_a_missing_mandatory_test(self):
        for name in REQUIRED_TESTS["products"]:
            log = self.log.replace(name.encode(), b"unrelated_test")
            record = {
                **self.record,
                "log_bytes": len(log),
                "log_sha256": hashlib.sha256(log).hexdigest(),
            }
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(record, log=log)

    def test_nonpass_or_substring_is_not_a_named_success(self):
        target = REQUIRED_TESTS["products"][0].encode()
        for log in (
            self.log.replace(b"PASS", b"SKIP", 1),
            self.log.replace(b"PASS", b"FAIL", 1),
            self.log.replace(target, target + b"_different"),
        ):
            record = {
                **self.record,
                "log_bytes": len(log),
                "log_sha256": hashlib.sha256(log).hexdigest(),
            }
            with self.subTest(log=log), self.assertRaises(ValueError):
                self.validate(record, log=log)

    def test_ansi_runner_successes_keep_exact_names(self):
        log = self.log.replace(b"PASS", b"\x1b[32mPASS\x1b[0m")
        record = {
            **self.record,
            "log_bytes": len(log),
            "log_sha256": hashlib.sha256(log).hexdigest(),
        }
        self.validate(record, log=log)

    def test_plans_preserve_default_and_production_lanes_without_retries(self):
        self.assertEqual(
            set(PLANS),
            {
                "format",
                "default",
                "default-products",
                "production",
                "qualification-lib",
                "hol-256",
                "sigkill",
                "authority-distribution",
                "products",
                "lint-default",
                "lint",
            },
        )
        self.assertNotIn("--features", PLANS["default"][1])
        self.assertNotIn("--features", PLANS["default-products"][1])
        self.assertNotIn("--features", PLANS["lint-default"][1])
        for name in REQUIRED_BINARY_TESTS:
            command = PLANS[name][1]
            self.assertIn("--locked", command)
            self.assertEqual(command[command.index("--retries") + 1], "0")
            self.assertEqual(command[command.index("--status-level") + 1], "all")
            self.assertEqual(command[command.index("--final-status-level") + 1], "none")
            self.assertEqual(command[command.index("--success-output") + 1], "never")
            self.assertIn("--no-fail-fast", command)
            self.assertGreaterEqual(PLANS[name][0], len(REQUIRED_TESTS[name]))
        self.assertIn("production-authority", PLANS["production"][1])
        self.assertIn("authority_recovery", PLANS["products"][1])

    def test_non_test_plans_require_exact_success_not_invented_tests(self):
        for name in ("format", "lint-default", "lint"):
            log = b"command completed\n"
            record = {
                **self.record,
                "command": PLANS[name][1].copy(),
                "minimum_tests": 0,
                "observed_passed_tests": 0,
                "log_bytes": len(log),
                "log_sha256": hashlib.sha256(log).hexdigest(),
            }
            validate_record(
                name, record, self.context, self.identity, log, lambda _: (0, 0)
            )
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_record(
                    name,
                    {**record, "observed_passed_tests": 1},
                    self.context,
                    self.identity,
                    log,
                    lambda _: (1, 0),
                )

    def test_every_product_scenario_has_its_own_binary_binding(self):
        self.assertEqual(len(REQUIRED_TESTS["products"]), 19)
        self.assertEqual(len(REQUIRED_TESTS["default-products"]), 9)
        for binary, tests in REQUIRED_BINARY_TESTS["products"].items():
            for test in tests:
                log = self.log.replace(
                    f"{binary} {test}".encode(), f"{binary}::other {test}".encode()
                )
                data = {
                    **self.record,
                    "log_bytes": len(log),
                    "log_sha256": hashlib.sha256(log).hexdigest(),
                }
                with (
                    self.subTest(binary=binary, test=test),
                    self.assertRaises(ValueError),
                ):
                    self.validate(data, log=log)


if __name__ == "__main__":
    unittest.main()
