"""Offline, synthetic-byte snapshot integrity contracts; NO real model weights."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import snapshot_attestation as census
from jina_v5 import FrozenJinaV5, MODELS


REV = "b" * 40


class JinaSnapshotCensusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.model = "jina-v5-text-nano"
        self.root = Path(self.temporary.name) / (
            "models--" + MODELS[self.model].repository.replace("/", "--"))
        self.snap = self.root / "snapshots" / REV
        self.snap.mkdir(parents=True)
        self.write("config.json", '{"model_type":"test-only"}')
        self.write("modules.json", "[]")
        self.write("tokenizer.json", '{"version":"synthetic-tokenizer"}')
        self.write("model.safetensors", b"synthetic tensor fixture only")
        self.write("custom_st.py", "class TestOnly: pass\n")
        self.write("adapters/classification/adapter_config.json", "{}")
        self.write("adapters/classification/adapter_model.safetensors",
                   b"synthetic adapter bytes")

    def write(self, name, value):
        file = self.snap / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(value.encode("utf-8") if isinstance(value, str) else value)

    def census(self, *, expected=None, **values):
        options = {
            "store_root": self.root,
            "snapshot_dir": self.snap,
            "expected_digest": expected,
        }
        options.update(values)
        return census.attest_snapshot(self.model, REV, "classification", **options)

    def test_model_tokenizer_adapter_and_custom_code_are_all_counted(self):
        first = self.census()
        self.assertEqual(first["status"], "observed_unapproved_shadow_only")
        self.assertFalse(first["matches_precommitted_digest"])
        self.assertFalse(first["signed_artifact_cas_verified"])
        self.assertFalse(first["production_load_receipt_verified"])
        self.assertFalse(first["production_promotion_permitted"])
        names = {file["path"] for file in first["files"]}
        self.assertIn("model.safetensors", names)
        self.assertIn("tokenizer.json", names)
        self.assertIn("custom_st.py", names)
        self.assertIn("adapters/classification/adapter_model.safetensors", names)
        self.assertEqual(len(first["manifest_sha256"]), 64)
        approved = self.census(expected=first["manifest_sha256"])
        self.assertTrue(approved["matches_precommitted_digest"])
        self.assertEqual(approved["manifest_sha256"], first["manifest_sha256"])
        self.assertFalse(approved["actual_encoder_forward_verified"])

    def test_precommitted_digest_blocks_model_or_adapter_mutation(self):
        before = self.census()["manifest_sha256"]
        self.write("adapters/classification/adapter_model.safetensors", b"tampered")
        with self.assertRaisesRegex(ValueError, "differs"):
            self.census(expected=before)
        self.write("adapters/classification/adapter_model.safetensors",
                   b"synthetic adapter bytes")
        self.write("custom_st.py", "class Tampered: pass\n")
        with self.assertRaisesRegex(ValueError, "differs"):
            self.census(expected=before)

    def test_task_adapter_not_interchangeable_and_missing_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            census.attest_snapshot(
                self.model, REV, "retrieval",
                store_root=self.root, snapshot_dir=self.snap,
            )
        (self.snap / "adapters/classification/adapter_model.safetensors").unlink()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.census()

    def test_hf_cache_blob_symlink_allowed_but_external_symlink_rejected(self):
        source = self.snap / "model.safetensors"
        source.unlink()
        blob = self.root / "blobs" / "model-test"
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(b"real bytes from an approved local blob fixture")
        source.symlink_to(blob)
        self.assertTrue(self.census()["file_count"] >= 6)
        external = Path(self.temporary.name) / "external-weights"
        external.write_bytes(b"outside approved root")
        source.unlink()
        source.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.census()

    def test_snapshot_location_and_repository_identity_immutable(self):
        with self.assertRaisesRegex(ValueError, "exact pinned"):
            self.census(snapshot_dir=self.root)
        with self.assertRaisesRegex(ValueError, "repository"):
            self.census(store_root=Path(self.temporary.name))
        with self.assertRaisesRegex(ValueError, "exact 40"):
            census.attest_snapshot(self.model, "main", "classification",
                                   store_root=self.root, snapshot_dir=self.snap)
        with self.assertRaisesRegex(ValueError, "expected snapshot digest"):
            self.census(expected="master")

    def test_git_lfs_pointer_is_not_real_checkpoint(self):
        self.write("model.safetensors",
                   "version https://git-lfs.github.com/spec/v1\n"
                   "oid sha256:" + "a" * 64 + "\nsize 12345\n")
        with self.assertRaisesRegex(ValueError, "LFS pointer"):
            self.census()

    def test_hidden_mutable_content_and_symlinked_directories_refused(self):
        self.write(".git/config", "[core]\n")
        with self.assertRaisesRegex(ValueError, "unreviewed mutable"):
            self.census()
        (self.snap / ".git/config").unlink()
        (self.snap / ".git").rmdir()
        directory = self.snap / "external-directory"
        directory.symlink_to(self.root / "blobs", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "directory symlinks"):
            self.census()

    def test_capacity_limit_and_missing_trust_not_silent(self):
        with patch.object(census, "MAX_FILES", 5):
            with self.assertRaisesRegex(ValueError, "file count"):
                self.census()
        with self.assertRaisesRegex(ValueError, "expected snapshot digest"):
            self.census(expected="0" * 64)

    @unittest.skipUnless(os.name == "posix", "FIFO fixture only on POSIX")
    def test_nonregular_fifo_rejected_without_opening_it(self):
        pipe = self.snap / "special"
        os.mkfifo(pipe)
        with self.assertRaisesRegex(ValueError, "nonregular"):
            self.census()


if __name__ == "__main__":
    unittest.main()
