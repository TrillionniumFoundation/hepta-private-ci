"""Strict original-byte two-cut source gating; fixtures never count as evidence."""

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

import project_two_cut_source_gate as gate


def fake_row(repo="r/a", partition="train", blob=b"alpha"):
    return {
        "repo": repo,
        "partition": partition,
        "head_sha": "b" * 40,
        "path": "src/file.py",
        "blob_sha": gate.git_blob_sha(blob),
        "bytes": len(blob),
        "sha256": gate.sha256(blob),
        "mode": "100644",
    }


def zip_bytes(contents):
    manifest = "".join(
        f"{hashlib.sha256(value).hexdigest()}  ./{name}\n"
        for name, value in sorted(contents.items())
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in contents.items():
            archive.writestr(name, value)
        archive.writestr("SHA256SUMS", manifest)
    return buffer.getvalue()


class SourceCutIntegrityTests(unittest.TestCase):
    def test_full_inner_manifest_is_required(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.zip"
            original = zip_bytes({"a.json": b"{}", "b.json": b"[]"})
            path.write_bytes(original)
            self.assertEqual(
                gate.checked_zip(path, gate.sha256(original))["a.json"], b"{}"
            )
            with zipfile.ZipFile(path, "r") as archive:
                manifest = archive.read("SHA256SUMS")
            partial = io.BytesIO()
            with zipfile.ZipFile(partial, "w") as archive:
                archive.writestr("a.json", b"{}")
                archive.writestr("b.json", b"[]")
                archive.writestr("SHA256SUMS", manifest.splitlines()[0] + b"\n")
            path.write_bytes(partial.getvalue())
            with self.assertRaises(ValueError):
                gate.checked_zip(path, gate.sha256(path.read_bytes()))

    def test_changed_original_bytes_cannot_keep_same_zip_pin(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.zip"
            original = zip_bytes({"a.txt": b"alpha"})
            path.write_bytes(original)
            path.write_bytes(zip_bytes({"a.txt": b"bravo"}))
            with self.assertRaises(ValueError):
                gate.checked_zip(path, gate.sha256(original))

    def test_rejects_duplicate_json_fields_and_nonfinite(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.assertRaises(ValueError):
                gate.strict_json(raw)

    def test_source_content_requires_both_git_and_sha256_identity(self):
        row = fake_row()
        blob = b"alpha"
        inventory = {"original_file_bindings": 1, "files": [row]}
        files = {"original/blobs/" + row["blob_sha"] + ".blob": blob}
        self.assertEqual(len(gate.census(files, inventory, 1, "repo")), 1)
        altered = {"original/blobs/" + row["blob_sha"] + ".blob": b"wrong"}
        with self.assertRaises(ValueError):
            gate.census(altered, inventory, 1, "repo")

    def test_source_census_rejects_duplicate_binding(self):
        row = fake_row()
        inventory = {"original_file_bindings": 2, "files": [row, row]}
        files = {"original/blobs/" + row["blob_sha"] + ".blob": b"alpha"}
        with self.assertRaises(ValueError):
            gate.census(files, inventory, 2, "repo")

    def test_different_source_cuts_may_not_share_same_project(self):
        with self.assertRaises(ValueError):
            gate.joined_projects([fake_row()], [fake_row()])

    def test_project_family_cannot_cross_partitions(self):
        a = fake_row()
        b = dict(fake_row(partition="evaluation"), path="next/file.py")
        with self.assertRaises(ValueError):
            gate.joined_projects([a, b], [])

    def test_original_binary_stays_non_utf8(self):
        payload = b"coffee=\xe9\n"
        row = fake_row(blob=payload)
        contents = {"original/blobs/" + row["blob_sha"] + ".blob": payload}
        inventory = {"original_file_bindings": 1, "files": [row]}
        self.assertEqual(len(gate.census(contents, inventory, 1, "repo")), 1)
        with self.assertRaises(UnicodeDecodeError):
            payload.decode("utf-8")

    def test_original_external_artifacts_if_pinned_paths_supplied(self):
        names = (
            "HEPTA_FOUR_PROJECT_ZIP",
            "HEPTA_SIX_PROJECT_ZIP",
            "HEPTA_SIX_REOPEN_ZIP",
        )
        if not all(os.environ.get(name) for name in names):
            self.skipTest("only run real ZIP test with all three original archives")
        result = gate.audit(*(Path(os.environ[name]) for name in names))
        self.assertEqual(result["verified_original_file_bindings"], 112)
        self.assertEqual(result["original_project_repositories"], 10)
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["training_on_unreviewed_proposals_qualified"])


if __name__ == "__main__":
    unittest.main()
