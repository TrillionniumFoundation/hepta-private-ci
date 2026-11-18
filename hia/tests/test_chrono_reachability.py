"""Static lock-path tests; deliberately no Cargo/Rust/native execution."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chrono_reachability import analyze_paths, load_graph


class ChronoReachabilityTests(unittest.TestCase):
    def setUp(self):
        self.workspace = b'[workspace]\nmembers = ["root"]\n'

    def test_direct_and_transitive_external_witness(self):
        lock = b'''version = 4
[[package]]
name = "chrono"
version = "0.4.43"
source = "registry+https://example.test"
[[package]]
name = "oauth2"
version = "5.0.0"
source = "registry+https://example.test"
dependencies = ["chrono"]
[[package]]
name = "root"
version = "0.0.0"
dependencies = ["oauth2", "chrono"]
[[package]]
name = "other"
version = "0.0.0"
dependencies = ["oauth2"]
[[package]]
name = "unrelated"
version = "0.0.0"
'''
        r = analyze_paths(lock, self.workspace)
        self.assertEqual(r["package_count"], 5)
        self.assertEqual(r["source_less_candidate_roots"], 3)
        self.assertEqual(r["affected_candidate_roots"], 2)
        self.assertEqual(r["direct_candidate_roots"], 1)
        self.assertEqual(r["indirect_only_candidate_roots"], 1)
        witness = r["external_direct_importer_witnesses"][0]
        self.assertEqual(witness["root_to_importer_path"], ["other@0.0.0", "oauth2@5.0.0"])
        self.assertEqual(r["root_witnesses"][1]["path"], ["root@0.0.0", "chrono@0.4.43"])
        self.assertFalse(r["no_chrono_package_or_edge"])

    def test_vendor_cannot_be_mislabelled_as_workspace_root(self):
        manifest = b'[patch.crates-io]\nsqlx-sqlite = { path = "third_party/sqlx-sqlite" }\n'
        lock = b'''version = 4
[[package]]
name = "chrono"
version = "0.4.43"
source = "registry+https://example.test"
[[package]]
name = "sqlx-sqlite"
version = "0.9.0"
dependencies = ["chrono"]
[[package]]
name = "real-workspace"
version = "0.0.0"
dependencies = ["sqlx-sqlite"]
'''
        r = analyze_paths(lock, manifest)
        self.assertEqual(r["source_less_candidate_roots"], 1)
        self.assertEqual(r["direct_candidate_roots"], 0)
        self.assertEqual(r["indirect_only_candidate_roots"], 1)
        self.assertEqual(r["external_direct_importer_witnesses"], [{
            "importer": "sqlx-sqlite@0.9.0", "kind": "vendored_external",
            "reachable_from_source_less_root": True,
            "root_to_importer_path": ["real-workspace@0.0.0", "sqlx-sqlite@0.9.0"],
        }])

    def test_explicit_duplicate_dependency_version_is_exact(self):
        lock = b'''version = 4
[[package]]
name = "chrono"
version = "0.4.43"
[[package]]
name = "dup"
version = "1.0.0"
[[package]]
name = "dup"
version = "2.0.0"
dependencies = ["chrono"]
[[package]]
name = "root"
version = "0.0.0"
dependencies = ["dup 2.0.0"]
'''
        r = analyze_paths(lock, self.workspace)
        self.assertEqual(r["root_witnesses"][-1]["path"],
                         ["root@0.0.0", "dup@2.0.0", "chrono@0.4.43"])

    def test_ambiguous_dependency_fails_closed(self):
        lock = b'''version = 4
[[package]]
name = "dup"
version = "1.0.0"
[[package]]
name = "dup"
version = "2.0.0"
[[package]]
name = "root"
version = "0.0.0"
dependencies = ["dup"]
'''
        with self.assertRaisesRegex(ValueError, "resolves to 2"):
            load_graph(lock)

    def test_missing_package_and_invalid_edge_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "nonempty package"):
            load_graph(b'version = 4\n')
        with self.assertRaisesRegex(ValueError, "resolves to 0"):
            load_graph(b'[[package]]\nname = "a"\nversion = "1"\ndependencies = ["missing"]\n')

    def test_cycles_are_bounded_and_no_chrono_is_an_absence(self):
        lock = b'''version = 4
[[package]]
name = "a"
version = "1"
dependencies = ["b"]
[[package]]
name = "b"
version = "1"
dependencies = ["a"]
'''
        r = analyze_paths(lock, self.workspace)
        self.assertTrue(r["no_chrono_package_or_edge"])
        self.assertEqual(r["affected_candidate_roots"], 0)

    def test_dependency_with_source_or_invalid_package_rejected(self):
        with self.assertRaises(ValueError):
            load_graph(b'[[package]]\nname = "x"\nversion = "1"\nsource = 5\n')
        with self.assertRaises(ValueError):
            load_graph(b'[[package]]\nname = "x"\nversion = "1"\ndependencies = ["y 1 source"]\n')


if __name__ == "__main__":
    unittest.main()
