"""Exercise the declared view, original bounds, custody and failure receipts."""

from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zlib

import ndu_synapse_projection as projection


SOURCE = "a" * 40


class SynapseProjectionTests(unittest.TestCase):
    def source(self, root):
        source = root / "source"
        source.mkdir()
        (source / "CI_STARTED.json").write_text(json.dumps({"source_commit": SOURCE}))
        return source

    def assert_reconstructed(self, source, output, expected):
        result = projection.collect_projection(source, output, SOURCE)
        self.assertTrue(result["complete_projection"])
        self.assertFalse(result["whole_original_artifact_restorable"])
        diagnostics = json.loads((output / "DIAGNOSTICS.json").read_text())
        self.assertEqual(diagnostics["bounds"], result["bounds"])
        raw = b"".join((output / p["file"]).read_bytes() for p in diagnostics["parts"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), diagnostics["tar_sha256"])
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            restored = {
                member.name: archive.extractfile(member).read() for member in archive
            }
        self.assertEqual(restored, expected)
        for name, data in expected.items():
            self.assertEqual(
                result["files"][name],
                {
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "crc32": f"{zlib.crc32(data):08x}",
                },
            )
            self.assertEqual((source / name).read_bytes(), data)
        return result

    def test_original_inventory_failure_and_complete_declared_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.source(root)
            cache = source / "preparation/prefetch/cargo-home"
            cache.mkdir(parents=True)
            for i in range(5001):
                (cache / f"input-{i}.json").write_bytes(b"{}")
            (source / "command.stderr").write_bytes(b"actual failure\x00\xff\n")
            expected = {
                name: (source / name).read_bytes()
                for name in ["CI_STARTED.json", "command.stderr"]
            }
            original = projection.collector_module().collect(
                source, root / "old-export"
            )
            self.assertFalse(original["complete"])
            self.assertIn("inventory exceeds", original["error"]["message"])
            result = self.assert_reconstructed(source, root / "view-export", expected)
            self.assertEqual(
                result["excluded_inventory"][projection.EXCLUDED_PREFIXES[0]],
                {"entries": 5001, "lstat_bytes": 10002, "suffix_files": 5001},
            )
            self.assertTrue(all(p.read_bytes() == b"{}" for p in cache.iterdir()))

    def test_selected_file_limit_still_accepts_5000_and_refuses_5001(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.source(root)
            for i in range(4999):
                (source / f"record-{i}.json").write_bytes(b"")
            accepted = projection.collect_projection(source, root / "accepted", SOURCE)
            self.assertTrue(accepted["complete_projection"])
            self.assertEqual(len(accepted["files"]), 5000)
            (source / "one-more.json").write_bytes(b"")
            rejected = projection.collect_projection(source, root / "rejected", SOURCE)
            self.assertFalse(rejected["complete_projection"])
            self.assertEqual(rejected["error"]["code"], "SELECTED_FILE_BOUND")
            self.assertFalse(rejected["collector_called"])

    def test_long_selected_path_and_sparse_oversize_remain_failures(self):
        for kind in ["path", "bytes"]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = self.source(root)
                if kind == "path":
                    parent = source.joinpath(*(["p" * 100] * 11))
                    parent.mkdir(parents=True)
                    (parent / "log.stderr").write_bytes(b"")
                else:
                    with (source / "oversize.stderr").open("wb") as out:
                        out.truncate(8 * 128 * 1024 * 1024 + 1)
                result = projection.collect_projection(source, root / "export", SOURCE)
                self.assertFalse(result["complete_projection"])
                self.assertEqual(
                    result["error"]["code"],
                    "PATH_BOUND" if kind == "path" else "SELECTED_BYTE_BOUND",
                )
                self.assertFalse(result["collector_called"])

    def test_selected_link_and_directory_link_are_rejected(self):
        for kind in ["file", "directory"]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = self.source(root)
                outside = root / "outside"
                if kind == "file":
                    outside.write_bytes(b"not a selected owned file")
                    (source / "linked.stderr").symlink_to(outside)
                else:
                    outside.mkdir()
                    (source / "linked").symlink_to(outside, target_is_directory=True)
                result = projection.collect_projection(source, root / "export", SOURCE)
                self.assertFalse(result["complete_projection"])
                self.assertEqual(
                    result["error"]["code"],
                    "SELECTED_NONREGULAR" if kind == "file" else "DIRECTORY_LINK",
                )

    def test_suffix_rule_keeps_unlisted_command_paths_and_omits_opaque_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.source(root)
            (source / "new-phase.stdout").write_bytes(b"new actual command output")
            (source / "sealed-image.tar").write_bytes(b"opaque original")
            expected = {
                name: (source / name).read_bytes()
                for name in ["CI_STARTED.json", "new-phase.stdout"]
            }
            self.assert_reconstructed(source, root / "export", expected)
            self.assertEqual(
                (source / "sealed-image.tar").read_bytes(), b"opaque original"
            )

    def test_original_change_after_copy_is_not_a_complete_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.source(root)
            path = source / "command.stderr"
            path.write_bytes(b"before")
            original = projection.read_file

            def change_after_copy(src, name, expected, destination=None):
                result = original(src, name, expected, destination)
                if name == "command.stderr" and destination is not None:
                    path.write_bytes(b"changed after copy")
                return result

            with patch.object(projection, "read_file", side_effect=change_after_copy):
                result = projection.collect_projection(source, root / "export", SOURCE)
            self.assertFalse(result["complete_projection"])
            self.assertEqual(result["error"]["code"], "SOURCE_OPEN_CHANGED")

    def test_wrong_source_and_external_exception_text_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.source(root)
            wrong = projection.collect_projection(source, root / "wrong", "b" * 40)
            self.assertFalse(wrong["complete_projection"])
            self.assertEqual(wrong["error"]["code"], "SOURCE_RECEIPT_MISMATCH")
            with patch.object(
                projection,
                "inventory",
                side_effect=ValueError("SENSITIVE_UPPERCASE_SENTINEL"),
            ):
                unknown = projection.collect_projection(
                    source, root / "unknown", SOURCE
                )
            self.assertEqual(unknown["error"], {"type": "ValueError"})
            self.assertNotIn(
                "SENSITIVE_UPPERCASE_SENTINEL",
                (root / "unknown/PROJECTION.json").read_text(),
            )

    def test_projection_output_cannot_mutate_original_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.source(Path(tmp))
            with self.assertRaisesRegex(
                projection.ProjectionError, "OUTPUT_INSIDE_SOURCE"
            ):
                projection.collect_projection(source, source / "export", SOURCE)
            self.assertFalse((source / "export").exists())

    def test_failure_after_packing_cannot_keep_a_success_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.source(root)
            original = tempfile.TemporaryDirectory

            @contextmanager
            def fail_on_exit(*args, **kwargs):
                with original(*args, **kwargs) as directory:
                    yield directory
                raise OSError("SENSITIVE_EXTERNAL_ERROR")

            with patch.object(projection.tempfile, "TemporaryDirectory", fail_on_exit):
                result = projection.collect_projection(source, root / "export", SOURCE)
            self.assertFalse(result["complete_projection"])
            self.assertEqual(result["error"], {"type": "OSError"})
            self.assertNotIn("SENSITIVE_EXTERNAL_ERROR", json.dumps(result))

    def test_directory_read_error_cannot_silently_omit_a_subtree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.source(root)
            with patch.object(
                projection.os, "scandir", side_effect=PermissionError("PRIVATE_PATH")
            ):
                result = projection.collect_projection(source, root / "export", SOURCE)
            self.assertFalse(result["complete_projection"])
            self.assertFalse(result["source_catalogue_complete"])
            self.assertEqual(result["error"], {"type": "PermissionError"})
            self.assertNotIn("PRIVATE_PATH", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
