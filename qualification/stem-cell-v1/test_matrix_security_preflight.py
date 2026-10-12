import json
from pathlib import Path
import tempfile
import unittest

from matrix_security_preflight import audit, main, parse_version, packages


def fixture(crypto="0.18.0", sdk="0.18.0", anymap=True, roots=True):
    rows = []
    if roots:
        rows += [("codex-hepta-matrix-sdk", "0.0.0", ["matrix-sdk"]),
                 ("codex-hepta-matrixd", "0.0.0", ["codex-hepta-matrix-sdk"])]
    rows += [("matrix-sdk", sdk, ["matrix-sdk-base"] + (["anymap2"] if anymap else [])),
             ("matrix-sdk-base", sdk, ["matrix-sdk-crypto"]),
             ("matrix-sdk-crypto", crypto, [])]
    if anymap:
        rows += [("anymap2", "0.13.0", [])]
    text = "version = 4\n"
    for name, version, dependencies in rows:
        text += f'\n[[package]]\nname = "{name}"\nversion = "{version}"\n'
        if dependencies:
            text += "dependencies = [\n" + "".join(f' "{d}",\n' for d in dependencies) + "]\n"
    return text


class MatrixGateTests(unittest.TestCase):
    def test_current_018_locked_graph_is_blocked_for_both_advisories(self):
        result = audit(fixture(), '[toolchain]\nchannel = "1.95.0"\n')
        self.assertTrue(result["blocked"])
        self.assertEqual({x["code"] for x in result["blockers"]}, {"RUSTSEC-2026-0318", "RUSTSEC-2026-0319"})
        self.assertEqual(result["provenance_paths_unverified_until_cargo_tree"]["anymap2"],
                         ["codex-hepta-matrix-sdk", "matrix-sdk", "anymap2"])
        self.assertFalse(result["production_authorized"])

    def test_sdk_0191_still_bad_with_anymap_and_older_rust(self):
        result = audit(fixture(sdk="0.19.1", crypto="0.19.1", anymap=True),
                       '[toolchain]\nchannel = "1.95.0"\n')
        self.assertEqual({x["code"] for x in result["blockers"]},
                         {"RUSTSEC-2026-0319", "matrix_sdk_msrv"})

    def test_isolated_migration_candidate_does_not_issue_release(self):
        result = audit(fixture(sdk="0.19.1", crypto="0.19.1", anymap=False),
                       '[toolchain]\nchannel = "1.96.0"\n')
        self.assertFalse(result["blocked"])
        self.assertFalse(result["cargo_deny_passed"])
        self.assertFalse(result["production_authorized"])

    def test_missing_crypto_fails_closed(self):
        lock = fixture().replace('[[package]]\nname = "matrix-sdk-crypto"\nversion = "0.18.0"\n', '')
        lock = lock.replace(' "matrix-sdk-crypto",\n', '')
        self.assertIn("e2ee_crypto_missing", [x["code"] for x in audit(lock, '[toolchain]\nchannel = "1.95.0"\n')["blockers"]])

    def test_missing_owner_fails_closed(self):
        result = audit(fixture(roots=False), '[toolchain]\nchannel = "1.95.0"\n')
        self.assertTrue(any(x["code"] == "matrix_owner_missing" for x in result["blockers"]))

    def test_pretend_patched_prerelease_is_not_accepted(self):
        result = audit(fixture(sdk="0.19.1", crypto="0.19.0-rc.1", anymap=False),
                       '[toolchain]\nchannel = "1.96.0"\n')
        codes = {x["code"] for x in result["blockers"]}
        self.assertIn("RUSTSEC-2026-0318", codes)
        self.assertIn("matrix_sdk_family_alignment_unverified", codes)

    def test_unknown_newer_sdk_version_requires_reviewed_msrv(self):
        result = audit(fixture(sdk="0.20.0", crypto="0.20.0", anymap=False),
                       '[toolchain]\nchannel = "1.96.0"\n')
        self.assertIn("matrix_sdk_msrv_unknown", {x["code"] for x in result["blockers"]})

    def test_mixed_family_is_not_a_qualifiable_shortcut(self):
        result = audit(fixture(sdk="0.18.0", crypto="0.19.1", anymap=False),
                       '[toolchain]\nchannel = "1.95.0"\n')
        self.assertIn("matrix_sdk_family_alignment_unverified", [x["code"] for x in result["blockers"]])

    def test_version_and_lock_parser_are_strict(self):
        with self.assertRaises(ValueError):
            parse_version("0.19")
        with self.assertRaises(ValueError):
            packages('version = 4\n')
        self.assertEqual(parse_version("1.96.0"), (1, 96, 0))

    def test_create_only_report_and_enforce(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "Cargo.lock").write_text(fixture(), encoding="utf-8")
            (root / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "1.95.0"\n', encoding="utf-8")
            argv = ["--lock", str(root/"Cargo.lock"), "--toolchain", str(root/"rust-toolchain.toml"),
                    "--output", str(root/"report.json"), "--enforce"]
            self.assertEqual(main(argv), 2)
            report = json.loads((root/"report.json").read_text())
            self.assertTrue(report["blocked"])
            with self.assertRaises(FileExistsError):
                main(argv)


if __name__ == "__main__":
    unittest.main()
