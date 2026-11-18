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
        self.assertEqual(witness["candidate_root_coverage"], 2)
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
            "candidate_root_coverage": 1,
            "reachable_from_source_less_root": True,
            "root_to_importer_path": ["real-workspace@0.0.0", "sqlx-sqlite@0.9.0"],
        }])

    def test_external_coverage_overlaps_and_does_not_sum_to_total(self):
        lock = b'''version = 4
[[package]]
name = "chrono"
version = "0.4.43"
source = "registry+https://example.test"
[[package]]
name = "external-a"
version = "1.0.0"
source = "registry+https://example.test"
dependencies = ["chrono"]
[[package]]
name = "external-b"
version = "1.0.0"
source = "registry+https://example.test"
dependencies = ["chrono"]
[[package]]
name = "root"
version = "0.0.0"
dependencies = ["external-a", "external-b"]
'''
        report = analyze_paths(lock, self.workspace)
        self.assertEqual(report["affected_candidate_roots"], 1)
        witnesses = report["external_direct_importer_witnesses"]
        self.assertEqual([w["candidate_root_coverage"] for w in witnesses], [1, 1])

    def test_exact_pinned_cargo_lock_external_impact_when_present(self):
        root = Path(__file__).resolve().parents[2]
        lock_path = root / "codex-rs" / "Cargo.lock"
        workspace_path = root / "codex-rs" / "Cargo.toml"
        if not lock_path.is_file() or not workspace_path.is_file():
            self.skipTest("source-only packet has no full Codex checkout")
        report = analyze_paths(lock_path.read_bytes(), workspace_path.read_bytes())
        if report["lock_git_blob"] != "e1fdaf3fde907d24fec7ea787d49c0e29b3eb4bd":
            self.skipTest("historical pinned lock has been replaced")
        self.assertEqual(report["package_count"], 1530)
        self.assertEqual(report["source_less_candidate_roots"], 193)
        self.assertEqual(report["affected_candidate_roots"], 121)
        self.assertEqual(report["direct_candidate_roots"], 28)
        self.assertEqual(report["indirect_only_candidate_roots"], 93)
        self.assertEqual({
            item["importer"].split("@", 1)[0]: item["candidate_root_coverage"]
            for item in report["external_direct_importer_witnesses"]
        }, {
            "schemars": 120,
            "serde_with": 120,
            "sqlx-core": 87,
            "sqlx-mysql": 87,
            "sqlx-postgres": 87,
            "sqlx-sqlite": 87,
            "oauth2": 69,
            "rmcp": 68,
        })

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
