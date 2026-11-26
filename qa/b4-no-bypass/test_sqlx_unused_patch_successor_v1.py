"""Exercise full lock records and metadata; no Cargo process is launched."""

import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import hepta_sqlx_unused_patch_successor_contract_v1 as contract


class UnusedPatchSuccessorControls(unittest.TestCase):
    prefix = (
        'version = 4\n\n[[package]]\nname = "fixture"\nversion = "0.0.0"\n'
        'dependencies = ["used"]\n\n[[package]]\nname = "used"\n'
        'version = "1.0.0"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n'
        'checksum = "' + "a" * 64 + '"\n'
    ).encode()
    first = b'name = "a"\nversion = "1.0.0"\n'
    repeated = (
        b'name = "z"\nversion = "2.0.0"\nsource = "git+https://example.invalid/z#123"\n'
    )

    def lock(self, records):
        return self.prefix + b"".join(b"\n[[patch.unused]]\n" + row for row in records)

    def pair(self):
        return (
            self.lock((self.repeated, self.first, self.repeated)),
            self.lock((self.first, self.repeated, self.repeated)),
        )

    def graph(self):
        return {
            "packages": [
                {
                    "id": "fixture",
                    "targets": [
                        {
                            "kind": ["bin"],
                            "name": "fixture",
                            "src_path": "/work/fixture.rs",
                        }
                    ],
                }
            ],
            "resolve": {
                "root": "fixture",
                "nodes": [
                    {
                        "id": "fixture",
                        "features": ["std"],
                        "deps": [
                            {
                                "name": "used",
                                "pkg": "used",
                                "dep_kinds": [{"kind": None, "target": "cfg(unix)"}],
                            }
                        ],
                    }
                ],
            },
            "workspace_members": ["fixture"],
            "version": 1,
        }

    def reject_lock(self, after, reason):
        before, _ = self.pair()
        with self.assertRaisesRegex(ValueError, "^" + reason + "$"):
            contract.order_only(before, after)

    def test_order_only_permutation_preserves_duplicate(self):
        before, after = self.pair()
        result = contract.order_only(before, after)
        self.assertEqual(result["records_including_duplicates"], 3)
        self.assertEqual(result["before"], contract.pin(before))
        self.assertEqual(result["successor"], contract.pin(after))

    def test_identical_lock_is_not_a_successor(self):
        before, _ = self.pair()
        self.reject_lock(before, "successor-must-differ")

    def test_dropped_duplicate_rejected(self):
        self.reject_lock(
            self.lock((self.first, self.repeated)), "unused-record-multiset-changed"
        )

    def test_changed_unused_version_rejected(self):
        _, after = self.pair()
        self.reject_lock(
            after.replace(b'version = "2.0.0"', b'version = "2.0.1"'),
            "unused-record-multiset-changed",
        )

    def test_changed_unused_source_rejected(self):
        _, after = self.pair()
        self.reject_lock(
            after.replace(b"z#123", b"z#456"), "unused-record-multiset-changed"
        )

    def test_changed_used_checksum_rejected(self):
        _, after = self.pair()
        self.reject_lock(
            after.replace(b"a" * 64, b"b" * 64), "non-unused-lock-bytes-changed"
        )

    def test_changed_used_edge_rejected(self):
        _, after = self.pair()
        self.reject_lock(
            after.replace(b'dependencies = ["used"]', b"dependencies = []"),
            "non-unused-lock-bytes-changed",
        )

    def test_added_package_rejected(self):
        _, after = self.pair()
        self.reject_lock(
            b'[[package]]\nname = "extra"\nversion = "1.0.0"\n' + after,
            "non-unused-lock-bytes-changed",
        )

    def reject_graph(self, change):
        before = self.graph()
        after = copy.deepcopy(before)
        change(after)
        with self.assertRaisesRegex(ValueError, "^full-metadata-graph-changed$"):
            contract.same_graph(before, after)

    def test_changed_graph_feature_rejected(self):
        self.reject_graph(
            lambda value: value["resolve"]["nodes"][0]["features"].append("chrono")
        )

    def test_changed_graph_target_rejected(self):
        self.reject_graph(
            lambda value: value["packages"][0]["targets"][0].update(kind=["lib"])
        )

    def test_changed_graph_dependency_kind_rejected(self):
        self.reject_graph(
            lambda value: value["resolve"]["nodes"][0]["deps"][0]["dep_kinds"][
                0
            ].update(kind="dev")
        )

    def test_identical_full_graph_accepted(self):
        value = self.graph()
        self.assertTrue(contract.same_graph(value, copy.deepcopy(value)))


if __name__ == "__main__":
    unittest.main()
