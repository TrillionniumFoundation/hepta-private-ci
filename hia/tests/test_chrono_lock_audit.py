"""Pure-source tests; no Cargo build, repository mutation or native execution."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chrono_lock_audit import analyze_lock, comparison


class ChronoLockAuditTests(unittest.TestCase):
    def test_workspace_and_external_dependency_paths(self):
        data = b'''version = 3
[[package]]
name = "chrono"
version = "0.4.43"
source = "registry+https://github.com/rust-lang/crates.io-index"
[[package]]
name = "codex-core"
version = "0.0.0"
dependencies = ["chrono"]
[[package]]
name = "oauth2"
version = "5.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = ["chrono 0.4.43"]
'''
        result = analyze_lock(data)
        self.assertEqual(result["workspace_local_count"], 1)
        self.assertEqual(result["registry_external_count"], 1)
        self.assertEqual(result["vendored_external_count"], 0)
        self.assertEqual(result["chrono_versions"], ["0.4.43"])
        self.assertFalse(result["closure_ready"])

    def test_vendored_patched_dependency_is_not_first_party(self):
        patch = b'[patch.crates-io]\nsqlx-sqlite = { path = "third_party/sqlx-sqlite-0.9.0" }\n'
        lock = b'version = 4\n[[package]]\nname = "sqlx-sqlite"\nversion = "0.9.0"\ndependencies = ["chrono"]\n'
        result = analyze_lock(lock, patch)
        self.assertEqual(result["vendored_external_count"], 1)
        self.assertEqual(result["workspace_local_count"], 0)
        self.assertEqual(result["registry_external_count"], 0)

    def test_invalid_vendor_manifest_fails_closed(self):
        lock = b'version = 4\n[[package]]\nname = "sqlx-sqlite"\n'
        with self.assertRaises(ValueError):
            analyze_lock(lock, b'[patch.crates-io]\nsqlx-sqlite = { path = 5 }\n')

    def test_complete_removal_required(self):
        empty = b'version = 3\n[[package]]\nname = "other"\nversion = "1.0.0"\n'
        result = analyze_lock(empty)
        self.assertTrue(result["closure_ready"])
        self.assertEqual(result["importers"], [])

    def test_retirement_and_growth_are_distinct(self):
        before = analyze_lock(b'version = 3\n[[package]]\nname = "codex-core"\nversion = "0.0.0"\ndependencies = ["chrono"]\n')
        after = analyze_lock(b'version = 3\n[[package]]\nname = "some-new-crate"\nversion = "0.0.0"\ndependencies = ["chrono"]\n')
        delta = comparison(after, before)
        self.assertEqual(len(delta["new_edges"]), 1)
        self.assertEqual(len(delta["retired_edges"]), 1)

    def test_invalid_dependency_arrays_fail_closed(self):
        broken = b'version = 3\n[[package]]\nname = "a"\ndependencies = [5]\n'
        with self.assertRaises(ValueError):
            analyze_lock(broken)

    def test_no_package_array_is_not_false_success(self):
        with self.assertRaises(ValueError):
            analyze_lock(b'version = 3\n')


if __name__ == "__main__":
    unittest.main()
