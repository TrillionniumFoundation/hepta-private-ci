"""Regression tests for the tracked advisory no-suppression policy."""

import tempfile
import tomllib
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
    def test_all_nineteen_tracked_advisories_are_caught_as_cargo_deny_ignores(self):
        self.assertEqual(len(TRACKED_RUSTSEC), 19)
        self.assertIn("RUSTSEC-2026-0374", TRACKED_RUSTSEC)
        for advisory_id in sorted(TRACKED_RUSTSEC):
            with self.subTest(advisory_id=advisory_id):
                policy = (
                    "[advisories]\n"
                    "ignore = ["
                    f'{{ id = "{advisory_id}", reason = "temporary" }}'
                    "]\n"
                )
                self.assertEqual(ignored_tracked_advisories(policy), [advisory_id])

    def test_audit_plain_string_ignores_are_not_a_bypass(self):
        for advisory_id in sorted(TRACKED_RUSTSEC):
            with self.subTest(advisory_id=advisory_id):
                policy = f'[advisories]\nignore = ["{advisory_id}"]\n'
                self.assertEqual(ignored_tracked_advisories(policy), [advisory_id])

    def test_emsign_tls_trust_dependency_pins_cannot_regress(self):
        """An installed vulnerable TLS verifier or trust-root bundle must fail."""
        lock_path = Path(__file__).resolve().parents[2] / "codex-rs" / "Cargo.lock"
        packages = tomllib.loads(lock_path.read_text(encoding="utf-8"))["package"]
        minimum = {
            "rustls-webpki": (0, 103, 16),  # RUSTSEC-2026-0382
            "webpki-roots": (1, 0, 10),  # RUSTSEC-2026-0381
            "webpki-root-certs": (1, 0, 10),  # RUSTSEC-2026-0383
        }
        for package in packages:
            name = package["name"]
            if name not in minimum:
                continue  # Removing the vulnerable dependency entirely is safe.
            with self.subTest(package=name, version=package["version"]):
                version = tuple(int(piece) for piece in package["version"].split("."))
                self.assertGreaterEqual(version, minimum[name])

    def test_ctutils_advisory_0385_pin_cannot_regress(self):
        """Any installed ctutils must have the constant-time advisory fix."""
        lock_path = Path(__file__).resolve().parents[2] / "codex-rs" / "Cargo.lock"
        packages = tomllib.loads(lock_path.read_text(encoding="utf-8"))["package"]
        for package in packages:
            if package["name"] != "ctutils":
                continue  # Full removal of the affected package is permitted.
            with self.subTest(version=package["version"]):
                version = tuple(int(piece) for piece in package["version"].split("."))
                self.assertGreaterEqual(version, (0, 4, 4))

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
