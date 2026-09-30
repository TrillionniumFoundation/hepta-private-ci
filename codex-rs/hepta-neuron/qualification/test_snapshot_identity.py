"""No model dependency or network is required by source-identity regressions."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from snapshot_identity import canonical, snapshot_supply_chain_admission, verify_snapshot_files


class SnapshotIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = b'{"model_type":"qualified-fixture"}\n'
        (self.root / "config.json").write_bytes(self.data)
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.revision = "a" * 40
        self.rows = [{"path": "config.json", "bytes": len(self.data), "sha256": self.sha}]
        self.manifest = {"revision": self.revision, "files": [
            {"path": "config.json", "bytes": len(self.data), "lfs_sha256": None,
             "git_blob": hashlib.sha1(f"blob {len(self.data)}\0".encode() + self.data).hexdigest()}]}

    def verify(self, rows=None, manifest=None):
        return verify_snapshot_files(self.root, self.revision,
                                     self.rows if rows is None else rows,
                                     self.manifest if manifest is None else manifest)

    def test_git_blob_and_lfs_are_both_bound(self):
        self.assertTrue(self.verify()["snapshot_matches_pinned_revision"])
        self.manifest["files"][0]["lfs_sha256"] = self.sha
        self.assertEqual(self.verify()["verified_file_count"], 1)
        self.assertFalse(self.verify()["selection_authority"])

    def test_correct_revision_string_with_wrong_content_is_rejected(self):
        self.manifest["files"][0]["git_blob"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "Git blob mismatch"):
            self.verify()

    def test_lfs_corruption_is_not_hidden_by_recomputed_local_hash(self):
        self.manifest["files"][0]["lfs_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "LFS digest mismatch"):
            self.verify()

    def test_source_changed_after_initial_hash_is_rejected(self):
        (self.root / "config.json").write_bytes(b"x" * len(self.data))
        with self.assertRaisesRegex(ValueError, "changed since hashing"):
            self.verify()

    def test_missing_upstream_entry_rejects_extra_consumed_code(self):
        manifest = {"revision": self.revision, "files": []}
        with self.assertRaisesRegex(ValueError, "absent from pinned"):
            self.verify(manifest=manifest)

    def test_duplicate_paths_and_wrong_revision_reject(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.verify(rows=self.rows * 2)
        manifest = copy.deepcopy(self.manifest)
        manifest["files"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.verify(manifest=manifest)
        manifest = copy.deepcopy(self.manifest)
        manifest["revision"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "revision mismatch"):
            self.verify(manifest=manifest)

    def test_missing_size_cannot_self_attest(self):
        self.manifest["files"][0]["bytes"] = None
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            self.verify()

    def test_path_escape_and_symlink_reject(self):
        for name in ("../config.json", "/config.json", "a/../config.json"):
            with self.assertRaisesRegex(ValueError, "unsafe consumed path"):
                self.verify(rows=[{**self.rows[0], "path": name}])
        target = self.root / "real.json"
        (self.root / "config.json").rename(target)
        (self.root / "config.json").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "immutable root"):
            self.verify()

    def test_empty_or_unbounded_manifests_reject(self):
        with self.assertRaisesRegex(ValueError, "file count"):
            self.verify(rows=[])
        with self.assertRaisesRegex(ValueError, "file count"):
            self.verify(rows=self.rows * 1025)
        with self.assertRaisesRegex(ValueError, "file count"):
            self.verify(manifest={"revision": self.revision, "files": self.manifest["files"] * 1025})


    def test_equal_revision_strings_without_byte_proof_are_not_admission(self):
        base = {"revision": self.revision, "observed_hub_sha": self.revision,
                "snapshot_digest": "d" * 64, "license_profile": "mit", "trust_remote_code": False}
        self.assertFalse(snapshot_supply_chain_admission(base)["exact_revision_bound"])
        base.update({"snapshot_matches_pinned_revision": True,
                     "upstream_identity": {"revision": self.revision,
                        "verified_files_sha256": "d" * 64, "snapshot_matches_pinned_revision": True}})
        # Equal arbitrary digest strings alone are still not a byte manifest.
        self.assertFalse(snapshot_supply_chain_admission(base)["exact_revision_bound"])
        base.update({"files": self.rows, "upstream_identity": self.verify(),
                     "snapshot_digest": hashlib.sha256(canonical(self.rows) + b"\n").hexdigest()})
        self.assertTrue(all(snapshot_supply_chain_admission(base).values()))
        base["upstream_identity"]["verified_files_sha256"] = "e" * 64
        self.assertFalse(snapshot_supply_chain_admission(base)["exact_revision_bound"])

    def test_actual_producer_hash_domains_bind_the_same_consumed_bytes(self):
        base = {"revision": self.revision, "observed_hub_sha": self.revision,
                "snapshot_matches_pinned_revision": True, "files": self.rows,
                "snapshot_digest": hashlib.sha256(canonical(self.rows) + b"\n").hexdigest(),
                "upstream_identity": self.verify()}
        self.assertTrue(snapshot_supply_chain_admission(base)["exact_revision_bound"])
        changed = copy.deepcopy(base)
        changed["files"][0]["sha256"] = "d" * 64
        self.assertFalse(snapshot_supply_chain_admission(changed)["exact_revision_bound"])
        changed = copy.deepcopy(base)
        changed["upstream_identity"]["verified_file_count"] = 2
        self.assertFalse(snapshot_supply_chain_admission(changed)["exact_revision_bound"])

    def test_missing_code_review_or_custom_license_does_not_pass_distribution(self):
        base = {"revision": self.revision, "observed_hub_sha": None,
                "snapshot_digest": "d" * 64, "license_profile": "lfm1.0", "trust_remote_code": True}
        gates = snapshot_supply_chain_admission(base)
        self.assertFalse(gates["no_unreviewed_remote_code"])
        self.assertFalse(gates["permissive_distribution_license"])
        base.pop("trust_remote_code")
        self.assertFalse(snapshot_supply_chain_admission(base)["no_unreviewed_remote_code"])


if __name__ == "__main__":
    unittest.main()
