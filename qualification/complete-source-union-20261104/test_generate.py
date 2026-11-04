"""Strict controls for the composed-lock adoption boundary."""
import copy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("union_generate", Path(__file__).with_name("generate.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SOURCE = "registry+https://github.com/rust-lang/crates.io-index"
OLD_UNICODE = {"name": "unicode-normalization", "version": "0.1.25",
               "source": SOURCE, "checksum": "old", "dependencies": ["tinyvec"]}
NEW_UNICODE = {"name": "unicode-normalization", "version": "0.1.26",
               "source": SOURCE, "checksum": "new", "dependencies": ["tinyvec"]}
CONTROL = {"name": "hepta-control-core", "version": "0.1.0", "dependencies": ["unicode-normalization"]}
TINYVEC = {"name": "tinyvec", "version": "1.10.0", "source": SOURCE, "checksum": "unchanged"}
LOCAL = {"name": "owner", "version": "0.1.0", "dependencies": ["tinyvec"]}
CONFIG = {"unicode_before": OLD_UNICODE, "unicode_after": NEW_UNICODE,
          "new_local_package": CONTROL, "allowed_local_dependency_packages": ["owner"]}


def encode(rows, version=4):
    import json
    result = [f"version = {version}"]
    for row in rows:
        result.append("[[package]]")
        result.extend(f"{key} = {json.dumps(value)}" for key, value in row.items())
    return ("\n".join(result) + "\n").encode()


class LockBoundaryControls(unittest.TestCase):
    def setUp(self):
        self.before = encode([OLD_UNICODE, TINYVEC, LOCAL])
        self.rows = [copy.deepcopy(NEW_UNICODE), copy.deepcopy(TINYVEC),
                     copy.deepcopy(LOCAL), copy.deepcopy(CONTROL)]
        self.rows[2]["dependencies"].append("hepta-control-core")

    def check(self, rows=None, config=None):
        return MODULE.compare_cargo(self.before, encode(rows or self.rows), config or CONFIG)

    def test_exact_reviewed_identity_and_manifest_edges(self):
        result = self.check()
        self.assertEqual(result["generated_packages"], 4)
        self.assertTrue(result["all_other_versions_sources_checksums_unchanged"])
        self.assertEqual(len(result["local_dependency_changes"]), 1)

    def test_unknown_registry_version_rejected(self):
        self.rows[1]["version"] = "1.11.0"
        with self.assertRaisesRegex(RuntimeError, "unreviewed"):
            self.check()

    def test_unchanged_identity_checksum_mutation_rejected(self):
        self.rows[1]["checksum"] = "mutated"
        with self.assertRaisesRegex(RuntimeError, "unrelated"):
            self.check()

    def test_wrong_new_unicode_checksum_rejected(self):
        self.rows[0]["checksum"] = "mutated"
        with self.assertRaisesRegex(RuntimeError, "Unicode"):
            self.check()

    def test_external_substitution_of_local_package_rejected(self):
        self.rows[3]["source"] = SOURCE
        with self.assertRaisesRegex(RuntimeError, "unreviewed"):
            self.check()

    def test_missing_prior_package_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "unreviewed"):
            self.check(self.rows[:1] + self.rows[2:])

    def test_duplicate_package_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            self.check(self.rows + [copy.deepcopy(self.rows[0])])

    def test_undeclared_local_dependency_change_rejected(self):
        config = {**CONFIG, "allowed_local_dependency_packages": []}
        with self.assertRaisesRegex(RuntimeError, "unrelated"):
            self.check(config=config)

    def test_changed_lock_header_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "header"):
            MODULE.compare_cargo(self.before, encode(self.rows, version=3), CONFIG)

    def test_git_and_sha256_bind_actual_byte_sequence(self):
        self.assertEqual(MODULE.identity(b"hello\n"), {
            "bytes": 6, "sha256": "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03",
            "git_blob": "ce013625030ba8dba906f756967f9e9ca394464a",
        })


if __name__ == "__main__":
    unittest.main()
