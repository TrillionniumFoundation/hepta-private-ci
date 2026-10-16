"""Pure-stdlib security experiment tests; numbers are test fixtures, not audits."""
from pathlib import Path
import tempfile
import unittest

from matrix_sdk_0191_trial import CANDIDATE, PINNED_OLD, assess_lock, prepare

SHA = "b" * 40
FAMILY = ("matrix-sdk", "matrix-sdk-base", "matrix-sdk-crypto", "matrix-sdk-sqlite")


def lock(matrix_version="0.19.1", anymap2=True, unsafe_yaml=True):
    rows = [{"name": name, "version": matrix_version} for name in FAMILY]
    if anymap2:
        rows.append({"name": "anymap2", "version": "0.13.0"})
    if unsafe_yaml:
        rows.append({"name": "unsafe-libyaml", "version": "0.2.11"})
    return {"version": 4, "package": rows}


class SecurityTrialTests(unittest.TestCase):
    def test_scrap_manifest_only_exact_018_is_editable(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "Cargo.toml"
            p.write_text("[workspace.dependencies]\n" + PINNED_OLD + "\n", encoding="utf-8")
            prepare(p)
            self.assertIn(CANDIDATE, p.read_text(encoding="utf-8"))
            self.assertNotIn(PINNED_OLD, p.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ValueError, "approved trial baseline"):
                prepare(p)

    def test_019_crypto_patch_does_not_hide_unmaintained_dependencies(self):
        report = assess_lock(lock(), SHA, "1.96.0")
        self.assertTrue(report["candidate_0318_crypto_fix_resolved"])
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("RUSTSEC-2026-0319", report["unresolved_advisories"])
        self.assertIn("RUSTSEC-2024-0449", report["unresolved_advisories"])
        self.assertFalse(report["production_promotion_permitted"])
        self.assertTrue(report["no_advisory_ignored"])

    def test_missing_crypto_fix_stays_blocked(self):
        result = assess_lock(lock(matrix_version="0.18.0"), SHA, "1.96.0")
        self.assertIn("RUSTSEC-2026-0318", result["unresolved_advisories"])
        self.assertFalse(result["candidate_0318_crypto_fix_resolved"])

    def test_independent_clean_lock_cannot_self_authorize(self):
        report = assess_lock(lock(anymap2=False, unsafe_yaml=False), SHA, "1.96.0")
        self.assertEqual(report["status"], "dependency_lock_candidate_only")
        self.assertFalse(report["production_promotion_permitted"])
        self.assertTrue(report["non_matrix_advisories_still_require_independent_cargo_deny"])
        self.assertFalse(report["package_upgrade_committed"])

    def test_wrong_rust_toolchain_and_unpinned_version_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Rust 1.96"):
            assess_lock(lock(), SHA, "1.95.0")
        with self.assertRaisesRegex(ValueError, "40-character"):
            assess_lock(lock(), "main", "1.96.0")
        with self.assertRaisesRegex(ValueError, "one version"):
            assess_lock({"version": 4, "package": [{"name": "matrix-sdk", "version": "0.19.1"}]},
                        SHA, "1.96.0")
        x = lock()
        x["package"].append({"name": "matrix-sdk", "version": "0.18.0"})
        with self.assertRaisesRegex(ValueError, "one version"):
            assess_lock(x, SHA, "1.96.0")

    def test_only_checked_lock_version_can_clear_crypto_advisory(self):
        x = lock()
        x["package"] = [row for row in x["package"] if row["name"] != "matrix-sdk-crypto"]
        x["package"].append({"name": "matrix-sdk-crypto", "version": "0.18.0"})
        r = assess_lock(x, SHA, "1.96.0")
        self.assertFalse(r["candidate_0318_crypto_fix_resolved"])
        self.assertIn("RUSTSEC-2026-0318", r["unresolved_advisories"])


if __name__ == "__main__":
    unittest.main()
