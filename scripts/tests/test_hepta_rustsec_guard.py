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
    def test_all_thirteen_tracked_advisories_are_caught_as_cargo_deny_ignores(self):
        self.assertEqual(len(TRACKED_RUSTSEC), 13)
        for advisory_id in sorted(TRACKED_RUSTSEC):
            with self.subTest(advisory_id=advisory_id):
                self.assertEqual(
                    ignored_tracked_advisories(
                        "[advisories]\nignore = ["
                        f'{{ id = "{advisory_id}", reason = "temporary" }}'
                        "]\n"
                    ),
                    [advisory_id],
                )

    def test_audit_plain_string_ignores_are_not_a_bypass(self):
        for advisory_id in sorted(TRACKED_RUSTSEC):
            with self.subTest(advisory_id=advisory_id):
                self.assertEqual(
                    ignored_tracked_advisories(
                        f'[advisories]\nignore = ["{advisory_id}"]\n'
                    ),
                    [advisory_id],
                )

    def test_unrelated_existing_exceptions_are_not_silently_rewritten(self):
        self.assertEqual(
            ignored_tracked_advisories(
                "[advisories]\nignore = ["
                '{ id = "RUSTSEC-2024-0388", reason = "tracked separately" }'
                "]\n"
            ),
            [],
        )

    def test_real_paths_are_checked_and_bad_entries_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in POLICIES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('[advisories]\nignore = []\n', encoding="utf-8")
            self.assertEqual(violations(root), {})
            (root / POLICIES[1]).write_text(
                '[advisories]\nignore = ["RUSTSEC-2026-0370"]\n', encoding="utf-8"
            )
            self.assertEqual(
                violations(root), {str(POLICIES[1]): ["RUSTSEC-2026-0370"]}
            )
            self.assertEqual(main(["--repo-root", str(root)]), 1)
            (root / POLICIES[1]).write_text(
                "[advisories]\nignore = [42]\n", encoding="utf-8"
            )
            self.assertEqual(main(["--repo-root", str(root)]), 1)


if __name__ == "__main__":
    unittest.main()
