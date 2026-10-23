#!/usr/bin/env python3
"""Regression tests for required-job scope and exact-needs admission."""

from __future__ import annotations

import unittest

from hepta_blocking_ci_fanin import EXPECTED_JOBS, allowed_skipped, check


def needs_with_skips(skips: set[str]) -> dict[str, dict[str, str]]:
    return {
        name: {"result": "skipped" if name in skips else "success"}
        for name in EXPECTED_JOBS
    }


class BlockingCiFanInTests(unittest.TestCase):
    def test_valid_scope_combinations_accept_only_inapplicable_skips(self):
        for native, full in (("false", "false"), ("true", "false"), ("true", "true")):
            with self.subTest(native=native, full=full):
                allowed = allowed_skipped(native, full)
                self.assertNotIn("scope", allowed)
                self.assertNotIn("blob-size-policy", allowed)
                self.assertNotIn("codespell", allowed)
                check(needs_with_skips(allowed), native, full)

    def test_missing_or_noncanonical_scope_is_never_static(self):
        for native, full in (
            (None, "false"),
            ("false", None),
            ("", "false"),
            ("false", ""),
            ("TRUE", "false"),
            ("false", "False"),
            ("0", "false"),
            ("false", "1"),
        ):
            with self.subTest(native=native, full=full):
                with self.assertRaisesRegex(ValueError, "explicit lowercase"):
                    check(needs_with_skips(set()), native, full)

    def test_full_repo_cannot_disable_native(self):
        with self.assertRaisesRegex(ValueError, "requires native"):
            check(needs_with_skips(set()), "false", "true")

    def test_missing_or_extra_required_job_rejected(self):
        for native, full in (("false", "false"), ("true", "false"), ("true", "true")):
            required = needs_with_skips(allowed_skipped(native, full))
            with self.subTest(native=native, full=full):
                for job in EXPECTED_JOBS:
                    with self.subTest(removed=job):
                        reduced = dict(required)
                        del reduced[job]
                        with self.assertRaisesRegex(ValueError, "dependency set"):
                            check(reduced, native, full)
                expanded = dict(required)
                expanded["unreviewed-job"] = {"result": "success"}
                with self.assertRaisesRegex(ValueError, "dependency set"):
                    check(expanded, native, full)

    def test_skipping_applicable_job_is_rejected(self):
        for native, full in (("false", "false"), ("true", "false"), ("true", "true")):
            allowed = allowed_skipped(native, full)
            for job in EXPECTED_JOBS - allowed:
                with self.subTest(native=native, full=full, skipped=job):
                    with self.assertRaisesRegex(ValueError, "did not succeed"):
                        check(needs_with_skips(allowed | {job}), native, full)

    def test_failure_and_cancellation_never_count_as_skipped(self):
        for outcome in ("failure", "cancelled"):
            for native, full in (("false", "false"), ("true", "false"), ("true", "true")):
                allowed = allowed_skipped(native, full)
                job = next(iter(sorted(allowed)))
                needs = needs_with_skips(allowed)
                needs[job]["result"] = outcome
                with self.subTest(outcome=outcome, native=native, full=full):
                    with self.assertRaisesRegex(ValueError, "did not succeed"):
                        check(needs, native, full)


if __name__ == "__main__":
    unittest.main()
