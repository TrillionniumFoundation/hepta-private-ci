"""Exercise complete export, reconstruction, and explicit diagnostic failures."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from ndu_synapse_diagnostics import collect


class DiagnosticExportTests(unittest.TestCase):
    def test_complete_logs_reconstruct_across_parts_without_changing_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "evidence"
            commands = source / "preparation/controller-commands"
            commands.mkdir(parents=True)
            expected = {
                "CI_RESULT.json": b'{"status":"failed"}\n',
                "preparation/controller-commands/042-START.json": b"{}\n",
                "preparation/controller-commands/042-END.json": b'{"exit_code":1}\n',
                "preparation/controller-commands/042-start-native-tool-probe.stdout": b"",
                "preparation/controller-commands/042-start-native-tool-probe.stderr": bytes(
                    range(256)
                )
                * 40,
            }
            for name, data in expected.items():
                (source / name).write_bytes(data)
            (source / "builder-image.tar.gz").write_bytes(b"original opaque archive")
            output = root / "diagnostics"
            result = collect(source, output, part_bytes=4096, max_parts=8)
            self.assertTrue(result["complete"])
            self.assertGreater(len(result["parts"]), 1)
            joined = bytearray()
            for part in result["parts"]:
                data = (output / part["file"]).read_bytes()
                self.assertLessEqual(len(data), 4096)
                self.assertEqual(
                    {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
                    {key: part[key] for key in ("bytes", "sha256")},
                )
                joined.extend(data)
            self.assertEqual(hashlib.sha256(joined).hexdigest(), result["tar_sha256"])
            with tarfile.open(fileobj=io.BytesIO(joined), mode="r:") as archive:
                restored = {
                    name: archive.extractfile(name).read()
                    for name in archive.getnames()
                }
            self.assertEqual(restored, expected)
            self.assertEqual(
                {name: (source / name).read_bytes() for name in expected}, expected
            )
            self.assertEqual(
                (source / "builder-image.tar.gz").read_bytes(),
                b"original opaque archive",
            )
            self.assertEqual(
                result["native_tool_probe"][0]["end"]["path"],
                "preparation/controller-commands/042-END.json",
            )
            self.assertEqual(
                result, json.loads((output / "DIAGNOSTICS.json").read_text())
            )

    def test_export_limit_is_a_recorded_failure_and_preserves_complete_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "evidence"
            source.mkdir()
            raw = bytes(range(256)) * 40
            (source / "command.stderr").write_bytes(raw)
            output = root / "diagnostics"
            result = collect(source, output, part_bytes=4096, max_parts=1)
            self.assertFalse(result["complete"])
            self.assertIn("part bound", result["error"]["message"])
            self.assertEqual(result["selected_bytes"], len(raw))
            self.assertEqual((source / "command.stderr").read_bytes(), raw)
            self.assertEqual(len(result["parts"]), 1)
            self.assertEqual(result["parts"][0]["bytes"], 4096)

    def test_missing_evidence_has_an_explicit_failed_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = collect(root / "absent", root / "diagnostics")
            self.assertFalse(result["complete"])
            self.assertEqual(result["parts"], [])
            self.assertEqual(result["file_count"], 0)
            self.assertTrue((root / "diagnostics/DIAGNOSTICS.json").is_file())

    def test_link_to_external_evidence_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "evidence"
            source.mkdir()
            (root / "outside").write_bytes(b"not owned by the qualification")
            try:
                (source / "linked.stderr").symlink_to(root / "outside")
            except OSError as error:
                self.skipTest(f"This host does not allow test symlinks: {error}")
            result = collect(source, root / "diagnostics")
            self.assertFalse(result["complete"])
            self.assertEqual(result["parts"], [])
            self.assertIn("not a regular file", result["error"]["message"])

    def test_export_must_not_add_files_to_the_original_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            with self.assertRaisesRegex(ValueError, "outside the original"):
                collect(source, source / "export")
            self.assertFalse((source / "export").exists())


if __name__ == "__main__":
    unittest.main()
