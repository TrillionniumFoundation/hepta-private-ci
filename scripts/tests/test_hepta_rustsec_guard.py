"""Regression tests for the tracked advisory no-suppression policy."""

import tempfile
import unittest
from pathlib import Path

from scripts.check_hepta_rustsec_advisories import (
    POLICIES,
    TRACKED_RUSTSEC,
    ignored_tracked_advisories,
    main,
    violations,
)


class TrackedRustSecGuardTests(unittest.TestCase):
    def test_all_fifteen_tracked_advisories_are_caught_as_cargo_deny_ignores(self):
        self.assertEqual(len(TRACKED_RUSTSEC), 15)
        for advisory_id in sorted(TRACKED_RUSTSEC):
            with self.subTest(advisory_id=advisory_id):
                policy = (
                    "[advisories]\n"
                    "ignore = ["
                    f'{{ id = "{advisory_id}", reason = "temporary" }}'
                    "]\n"
                )
                self.assertEqual(ignored_tracked_advisories(policy), [advisory_id])

    def test_ctutils_rustsec_0385_is_rejected_in_both_policy_encodings(self):
        advisory = "RUSTSEC-2026-0385"
        self.assertIn(advisory, TRACKED_RUSTSEC)
        for entry in (
            f'"{advisory}"',
            f'{{ id = "{advisory}", reason = "temporary" }}',
        ):
            with self.subTest(entry=entry):
                self.assertEqual(
                    ignored_tracked_advisories(f"[advisories]\nignore = [{entry}]\n"),
                    [advisory],
                )

    def test_crypto_bigint_rustsec_0387_is_rejected_in_both_policy_encodings(self):
        advisory = "RUSTSEC-2026-0387"
        self.assertIn(advisory, TRACKED_RUSTSEC)
        for entry in (
            f'"{advisory}"',
            f'{{ id = "{advisory}", reason = "temporary" }}',
        ):
            with self.subTest(entry=entry):
                self.assertEqual(
                    ignored_tracked_advisories(f"[advisories]\\nignore = [{entry}]\\n"),
                    [advisory],
                )

    def test_audit_plain_string_ignores_are_not_a_bypass(self):
        for advisory_id in sorted(TRACKED_RUSTSEC):
            with self.subTest(advisory_id=advisory_id):
                policy = f'[advisories]\nignore = ["{advisory_id}"]\n'
                self.assertEqual(ignored_tracked_advisories(policy), [advisory_id])

    def test_unrelated_existing_exceptions_are_not_silently_rewritten(self):
        policy = (
            "[advisories]\n"
            "ignore = ["
            '{ id = "RUSTSEC-2024-0388", reason = "tracked separately" }'
            "]\n"
        )
        self.assertEqual(ignored_tracked_advisories(policy), [])

    def test_real_paths_are_checked_and_bad_entries_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in POLICIES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[advisories]\nignore = []\n", encoding="utf-8")
            self.assertEqual(violations(root), {})
            (root / POLICIES[1]).write_text(
                '[advisories]\nignore = ["RUSTSEC-2026-0370"]\n', encoding="utf-8"
            )
            expected = {str(POLICIES[1]): ["RUSTSEC-2026-0370"]}
            self.assertEqual(violations(root), expected)
            self.assertEqual(main(["--repo-root", str(root)]), 1)
            (root / POLICIES[1]).write_text(
                "[advisories]\nignore = [42]\n", encoding="utf-8"
            )
            self.assertEqual(main(["--repo-root", str(root)]), 1)


if __name__ == "__main__":
    unittest.main()
