"""Synthetic lockfile contracts: no advisory suppressions or false security pass."""

import unittest

from matrix_sdk_security_probe import compare, inventory


def fixture(sdk="0.18.0", *, legacy=True, yaml=True):
    rows = [
        ("matrix-sdk", sdk),
        ("matrix-sdk-crypto", sdk),
        ("matrix-sdk-sqlite", sdk),
        ("codex-hepta-matrix-sdk", "0.0.0"),
    ]
    if legacy:
        rows.append(("anymap2", "0.13.0"))
    if yaml:
        rows.append(("unsafe-libyaml", "0.2.11"))
    return (
        "version = 4\n\n"
        + "".join(
            f'[[package]]\nname = "{name}"\nversion = "{ver}"\n\n'
            for name, ver in rows
        )
    ).encode()


class SecurityCandidateTests(unittest.TestCase):
    def test_baseline_has_real_security_and_maintenance_obligations(self):
        inventory0 = inventory(fixture())
        self.assertEqual(
            inventory0["known_relevant_advisories"],
            ["RUSTSEC-2024-0449", "RUSTSEC-2026-0318", "RUSTSEC-2026-0319"],
        )

    def test_new_matrix_sdk_can_clear_one_vulnerability_not_all_debt(self):
        result = compare(
            fixture(), fixture("0.19.0", legacy=False, yaml=True),
        )
        self.assertEqual(
            result["removed_known_advisories"],
            ["RUSTSEC-2026-0318", "RUSTSEC-2026-0319"],
        )
        self.assertEqual(
            result["remaining_known_advisories"], ["RUSTSEC-2024-0449"]
        )
        self.assertFalse(result["full_cargo_deny_qualified"])
        self.assertFalse(result["production_accepted"])

    def test_candidate_must_not_disappear_the_crypto_dependency(self):
        raw = fixture().replace(
            b'name = "matrix-sdk-crypto"\nversion = "0.18.0"\n\n', b"",
        )
        with self.assertRaisesRegex(ValueError, "critical"):
            inventory(raw)

    def test_divergent_sdk_versions_are_a_hard_error(self):
        raw = fixture().replace(
            b'name = "matrix-sdk-crypto"\nversion = "0.18.0"',
            b'name = "matrix-sdk-crypto"\nversion = "0.19.0"',
        )
        with self.assertRaisesRegex(ValueError, "diverged"):
            inventory(raw)

    def test_duplicated_or_invalid_cargo_packages_fail_closed(self):
        raw = fixture()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            inventory(raw + b'[[package]]\nname = "anymap2"\nversion = "0.13.0"\n')
        with self.assertRaisesRegex(ValueError, "noncanonical"):
            inventory(raw.replace(b'version = "0.18.0"', b'version = "0.18"', 1))

    def test_downgrade_not_accepted_as_maintenance(self):
        with self.assertRaisesRegex(ValueError, "downgrades"):
            compare(fixture("0.19.0", legacy=False), fixture("0.18.0"))

    def test_invalid_lockfile_and_false_safety_claim_rejected(self):
        with self.assertRaises(ValueError):
            inventory(b"[[package]\ninvalid")
        result = compare(fixture(), fixture())
        self.assertFalse(result["candidate_independently_safe"])
        self.assertFalse(result["code_compilation_verified_here"])


if __name__ == "__main__":
    unittest.main()
