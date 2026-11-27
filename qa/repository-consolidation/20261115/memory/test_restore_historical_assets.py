"""Temporary local Git fixtures; never fetch, extract, or execute archives."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import restore_historical_assets as storage


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Storage fixture")
        self.run_git("config", "user.email", "storage-fixture@example.invalid")
        self.raw = b"historical archive bytes\x00\xff\n"
        path = self.repo / "qa/evidence/archive.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(self.raw)
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "fixture source")
        self.source = self.run_git("rev-parse", "HEAD").strip()
        self.oid = self.run_git("rev-parse", "HEAD:qa/evidence/archive.bin").strip()
        self.row = {
            "original_path": "qa/evidence/archive.bin",
            "source_commit": self.source,
            "blob_oid": self.oid,
            "mode": "100644",
            "bytes": len(self.raw),
            "sha256": hashlib.sha256(self.raw).hexdigest(),
        }
        self.data = {
            "schema": storage.SCHEMA,
            "git_object_format": "sha1",
            "source_commit": self.source,
            "file_count": 1,
            "total_bytes": len(self.raw),
            "files": [self.row],
        }
        self.manifest = self.root / "manifest.json"
        self.save(self.data)
        self.run_git("rm", "-q", "qa/evidence/archive.bin")
        self.run_git("commit", "-qm", "retain in source ancestor")

    def run_git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True)

    def save(self, value):
        self.manifest.write_text(json.dumps(value), encoding="utf-8")

    def test_restores_exact_bytes_after_current_path_removal(self):
        output = self.root / "restored"
        receipt = storage.restore(self.repo, self.manifest, output)
        self.assertEqual((output / self.row["original_path"]).read_bytes(), self.raw)
        self.assertTrue(receipt["sha256_and_git_blob_identity_verified"])
        self.assertFalse(receipt["network_fetch_performed"])
        self.assertFalse((self.repo / self.row["original_path"]).exists())

    def test_verify_only_does_not_create_output(self):
        before = set(self.root.iterdir())
        receipt = storage.restore(self.repo, self.manifest)
        self.assertEqual(receipt["files"], 1)
        self.assertIsNone(receipt["output"])
        self.assertEqual(set(self.root.iterdir()), before)

    def test_rejects_hash_and_size_tampering(self):
        for key, value in (("sha256", "f" * 64), ("bytes", len(self.raw) + 1)):
            data = copy.deepcopy(self.data)
            data["files"][0][key] = value
            data["total_bytes"] = data["files"][0]["bytes"]
            self.save(data)
            with self.assertRaisesRegex(ValueError, "mismatch"):
                storage.restore(self.repo, self.manifest)

    def test_requires_original_path_binding_not_just_a_valid_object(self):
        data = copy.deepcopy(self.data)
        data["files"][0]["original_path"] = "qa/evidence/different.bin"
        self.save(data)
        with self.assertRaisesRegex(ValueError, "recorded path/blob"):
            storage.restore(self.repo, self.manifest)

    def test_refuses_nonancestor_even_when_its_blobs_exist(self):
        self.run_git("checkout", "--orphan", "unrelated")
        self.run_git("commit", "--allow-empty", "-qm", "unrelated history")
        with self.assertRaisesRegex(ValueError, "merge-base"):
            storage.restore(self.repo, self.manifest)

    def test_refuses_traversal_duplicates_and_nonexternal_destinations(self):
        data = copy.deepcopy(self.data)
        data["files"][0]["original_path"] = "qa/../../escape"
        self.save(data)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            storage.restore(self.repo, self.manifest)
        data = copy.deepcopy(self.data)
        data["files"].append(copy.deepcopy(data["files"][0]))
        data["file_count"] = 2
        data["total_bytes"] *= 2
        self.save(data)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            storage.restore(self.repo, self.manifest)
        self.save(self.data)
        for output in (self.repo / "new-output", self.root):
            with self.assertRaisesRegex(ValueError, "external|outside"):
                storage.restore(self.repo, self.manifest, output)

    def test_never_overwrites_an_existing_destination(self):
        output = self.root / "restored"
        output.mkdir()
        marker = output / "keep"
        marker.write_bytes(b"owned existing bytes")
        with self.assertRaisesRegex(ValueError, "new external"):
            storage.restore(self.repo, self.manifest, output)
        self.assertEqual(marker.read_bytes(), b"owned existing bytes")

    def test_replacement_refs_cannot_substitute_different_historical_bytes(self):
        replacement = subprocess.check_output(
            ["git", "-C", str(self.repo), "hash-object", "-w", "--stdin"],
            input=b"substituted fixture bytes",
        ).decode("ascii").strip()
        self.run_git("replace", self.oid, replacement)
        self.assertEqual(
            self.run_git("cat-file", "blob", self.oid), "substituted fixture bytes"
        )
        output = self.root / "restored"
        storage.restore(self.repo, self.manifest, output)
        self.assertEqual((output / self.row["original_path"]).read_bytes(), self.raw)

    def test_missing_local_blob_refuses_without_invoking_a_promisor(self):
        marker = self.root / "promisor-invoked"
        helper = self.root / "synthetic-promisor"
        helper.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        helper.chmod(0o700)
        self.run_git("config", "remote.fixture.promisor", "true")
        self.run_git("config", "remote.fixture.url", f"ext::{helper}")
        self.run_git("config", "protocol.ext.allow", "always")
        (self.repo / ".git/objects" / self.oid[:2] / self.oid[2:]).unlink()
        with self.assertRaisesRegex(ValueError, "already be available locally"):
            storage.restore(self.repo, self.manifest)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
