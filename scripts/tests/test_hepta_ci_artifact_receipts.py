import hashlib
from http.client import IncompleteRead
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from scripts import hepta_ci_artifact_receipts as export


class OriginalReceiptExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def archive(self, members):
        path = self.root / "original.zip"
        with warnings.catch_warnings(), zipfile.ZipFile(path, "w") as writer:
            warnings.simplefilter("ignore", UserWarning)
            for name, value in members:
                writer.writestr(name, value)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_exact_original_receipts_and_all_member_inventory_are_preserved(self):
        raw = b'{"decision":"NoUpdate", "actual_rows":32}\n'
        path, digest = self.archive(
            [
                ("native/readback.json", raw),
                ("native/worker.log", b"original log\n"),
                ("native/model.safetensors", b"model bytes stay in original artifact"),
            ]
        )
        result = export.select_receipts(
            path,
            self.root / "selected",
            digest,
            ["native/readback.json", "native/worker.log"],
        )
        self.assertEqual(
            (self.root / "selected/native/readback.json").read_bytes(), raw
        )
        self.assertEqual(result["selected_members"], 2)
        self.assertEqual(len(result["members"]), 3)
        self.assertFalse((self.root / "selected/native/model.safetensors").exists())
        self.assertEqual(result["original_zip_sha256"], digest)

    def test_complete_zip_digest_checked_before_any_extraction(self):
        path, _ = self.archive([("receipt.json", b"{}"), ("weights.bin", b"other")])
        with self.assertRaisesRegex(ValueError, "LOCAL_COMPLETE_ZIP_DIGEST"):
            export.select_receipts(path, self.root / "selected", "0" * 64, [])
        self.assertFalse((self.root / "selected").exists())

    def test_escaping_alias_and_duplicate_names_are_refused(self):
        for index, bad in enumerate(
            (
                "../bad.json",
                "/bad.json",
                "a//bad.json",
                "a/../bad.json",
                "a\\bad.json",
                "C:bad.json",
            )
        ):
            path, digest = self.archive([(bad, b"{}")])
            with (
                self.subTest(name=bad),
                self.assertRaisesRegex(ValueError, "ARCHIVE_MEMBER_PATH"),
            ):
                export.select_receipts(path, self.root / str(index), digest, [])
        path, digest = self.archive([("same.json", b"{}"), ("same.json", b"different")])
        with self.assertRaisesRegex(ValueError, "ARCHIVE_MEMBER_PATH"):
            export.select_receipts(path, self.root / "duplicate", digest, [])

    def test_symlink_member_and_missing_required_receipt_are_refused(self):
        link = zipfile.ZipInfo("receipt.json")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        path, digest = self.archive([(link, b"../outside")])
        with self.assertRaisesRegex(ValueError, "ARCHIVE_MEMBER_TYPE"):
            export.select_receipts(path, self.root / "link", digest, [])
        path, digest = self.archive([("present.json", b"{}")])
        with self.assertRaisesRegex(ValueError, "REQUIRED_ORIGINAL_RECEIPT_MISSING"):
            export.select_receipts(
                path, self.root / "missing", digest, ["missing.json"]
            )

    def test_each_member_and_total_selected_bytes_are_bounded(self):
        path, digest = self.archive([("one.json", b"12345"), ("two.json", b"12345")])
        for name, limits in (
            ("member", {"MAX_MEMBER": 4}),
            ("total", {"MAX_MEMBER": 5, "MAX_SELECTED": 9}),
        ):
            with (
                self.subTest(bound=name),
                patch.multiple(export, **limits),
                self.assertRaisesRegex(ValueError, "RECEIPT_BYTE_BOUND"),
            ):
                export.select_receipts(path, self.root / name, digest, [])

    def test_original_repository_run_source_and_digest_context(self):
        expected = {"id": 7, "name": "original", "bytes": 8, "sha256": "a" * 64}
        metadata = {
            "id": 7,
            "name": "original",
            "size_in_bytes": 8,
            "digest": "sha256:" + "a" * 64,
            "expired": False,
            "workflow_run": {"id": 9, "head_sha": "b" * 40},
        }
        export.check_metadata(metadata, expected, "b" * 40, 9)
        for key, wrong in (
            ("id", 8),
            ("name", "other"),
            ("size_in_bytes", 9),
            ("digest", "sha256:" + "c" * 64),
            ("expired", True),
            ("workflow_run", {"id": 10, "head_sha": "b" * 40}),
            ("workflow_run", {"id": 9, "head_sha": "c" * 40}),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                export.check_metadata(
                    dict(metadata, **{key: wrong}), expected, "b" * 40, 9
                )

    def test_failure_keeps_every_planned_artifact_in_denominator(self):
        manifest = {
            "schema": "hepta-pinned-cell-receipt-export-v1",
            "repository": export.REPOSITORY,
            "source": "a" * 40,
            "run": 3,
            "required": [],
            "artifacts": [
                {"id": n, "bytes": 10, "sha256": "b" * 64, "name": str(n)}
                for n in (1, 2)
            ],
        }
        for index, error in enumerate(
            (OSError("not logged URL"), IncompleteRead(b"not logged URL", 20))
        ):
            output = self.root / str(index)
            with patch.object(export, "api", side_effect=error) as api:
                result = export.run(manifest, output, "synthetic")
            self.assertEqual(api.call_count, 2)
            self.assertEqual([row["id"] for row in result["observations"]], [1, 2])
            self.assertFalse(result["all_exports_complete"])
            self.assertNotIn("not logged URL", json.dumps(result))
            self.assertEqual(json.loads((output / "export.json").read_text()), result)
        output = self.root / "interrupted"
        with patch.object(export, "api", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                export.run(manifest, output, "synthetic")
        interrupted = json.loads((output / "export.json").read_text())
        self.assertFalse(interrupted["completed"])
        self.assertFalse(interrupted["all_exports_complete"])
        self.assertEqual(
            [row["status"] for row in interrupted["observations"]],
            ["running", "not_started"],
        )

    def test_failed_atomic_replace_preserves_previous_complete_receipt(self):
        path = self.root / "export.json"
        export.save(path, {"completed": False})
        original = path.read_bytes()
        with patch.object(export.os, "replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                export.save(path, {"completed": True})
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
