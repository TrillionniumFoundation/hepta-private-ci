"""R11 archive admission controls; no model imports or historical replay.

The production digest remains unchanged. Each synthetic ZIP has an independently
computed fixture digest supplied to the exact archive-validation functions.
Only those two complete stdlib functions are loaded, so this suite does not
import Torch, execute archived code, fit models, or evaluate frozen candidates.
"""

import ast
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


class ArchiveManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="r11-archive-admission-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def validator(self, trusted_digest):
        source = Path(__file__).with_name("run.py")
        tree = ast.parse(source.read_bytes(), filename=str(source))
        original_pin = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "R10_ZIP_SHA"
                for target in node.targets
            )
        )
        self.assertEqual(
            original_pin,
            "98d6e9b2cf2ba6f6c651d6a86bb42ebafd04631f811bd109ed00044607e9c04c",
        )
        definitions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in ("digest", "verify_R10_archive")
        ]
        self.assertEqual(
            {node.name for node in definitions}, {"digest", "verify_R10_archive"}
        )
        namespace = {
            "__name__": "r11_archive_fixture",
            "Path": Path,
            "hashlib": hashlib,
            "io": io,
            "json": json,
            "zipfile": zipfile,
            "R10_ZIP_SHA": trusted_digest,
        }
        exec(
            compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"),
            namespace,
        )
        return namespace["verify_R10_archive"]

    def build(self, *, embedded_duplicate=False, unlisted=False, duplicate_zip=False):
        packet = self.root / "packet"
        packet.mkdir()
        bodies = {
            f"members/{i:04d}.txt": f"fixed member {i}\n".encode() for i in range(1328)
        }
        files = [
            {
                "path": name,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
            for name, body in bodies.items()
        ]
        manifest = {"content_members": 1328, "files": files}
        if embedded_duplicate:
            manifest["files"] = [files[0]] * 1328
        manifest_bytes = (
            json.dumps(manifest, sort_keys=True, indent=2) + "\n"
        ).encode()
        archive = self.root / "fixed.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as writer:
            for name, body in bodies.items():
                writer.writestr(name, body)
                path = packet / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            writer.writestr("MANIFEST_SHA256.json", manifest_bytes)
            if unlisted:
                writer.writestr("unlisted.txt", b"not in the content census\n")
            if duplicate_zip:
                writer.writestr(files[0]["path"], bodies[files[0]["path"]])
        (packet / "MANIFEST_SHA256.json").write_bytes(manifest_bytes)
        return packet, archive, hashlib.sha256(archive.read_bytes()).hexdigest(), files

    def test_valid_fixed_archive_and_manifest(self):
        packet, archive, pin, _ = self.build()
        receipt = self.validator(pin)(packet, archive)
        self.assertEqual(receipt["zip_sha256"], pin)
        self.assertEqual(receipt["verified_members"], 1328)
        self.assertEqual(
            receipt["manifest_sha256"],
            hashlib.sha256((packet / "MANIFEST_SHA256.json").read_bytes()).hexdigest(),
        )

    def test_replaced_external_manifest_cannot_hide_changed_member(self):
        packet, archive, pin, files = self.build()
        replacement = {"content_members": 1328, "files": [files[0]] * 1328}
        (packet / "MANIFEST_SHA256.json").write_text(json.dumps(replacement))
        (packet / files[-1]["path"]).write_bytes(
            b"changed and omitted by replacement\n"
        )
        with self.assertRaisesRegex(ValueError, "unpacked manifest"):
            self.validator(pin)(packet, archive)

    def test_duplicate_content_manifest_entries_rejected(self):
        packet, archive, pin, _ = self.build(embedded_duplicate=True)
        with self.assertRaisesRegex(ValueError, "duplicate content"):
            self.validator(pin)(packet, archive)

    def test_unlisted_archive_member_rejected(self):
        packet, archive, pin, _ = self.build(unlisted=True)
        with self.assertRaisesRegex(ValueError, "archive content census"):
            self.validator(pin)(packet, archive)

    def test_duplicate_zip_member_rejected(self):
        packet, archive, pin, _ = self.build(duplicate_zip=True)
        with self.assertRaisesRegex(ValueError, "duplicate ZIP"):
            self.validator(pin)(packet, archive)

    def test_existing_expanded_member_digest_check_retained(self):
        packet, archive, pin, files = self.build()
        (packet / files[-1]["path"]).write_bytes(b"changed\n")
        with self.assertRaisesRegex(ValueError, "unpacked content mutated"):
            self.validator(pin)(packet, archive)

    def test_archive_path_replacement_after_hash_is_not_trusted(self):
        packet, archive, pin, files = self.build()
        changed_name = files[-1]["path"]
        changed_body = b"replacement archive content\n"
        manifest = json.loads((packet / "MANIFEST_SHA256.json").read_bytes())
        manifest["files"][-1] = {
            "path": changed_name,
            "bytes": len(changed_body),
            "sha256": hashlib.sha256(changed_body).hexdigest(),
        }
        manifest_bytes = (
            json.dumps(manifest, sort_keys=True, indent=2) + "\n"
        ).encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(archive) as original:
            with zipfile.ZipFile(
                buffer, "w", compression=zipfile.ZIP_DEFLATED
            ) as writer:
                for item in original.infolist():
                    body = original.read(item.filename)
                    if item.filename == "MANIFEST_SHA256.json":
                        body = manifest_bytes
                    elif item.filename == changed_name:
                        body = changed_body
                    writer.writestr(item.filename, body)
        replacement = buffer.getvalue()
        read_bytes = Path.read_bytes
        replaced = False

        def read_then_replace(path):
            nonlocal replaced
            payload = read_bytes(path)
            if path == archive and not replaced:
                replaced = True
                archive.write_bytes(replacement)
                (packet / "MANIFEST_SHA256.json").write_bytes(manifest_bytes)
                (packet / changed_name).write_bytes(changed_body)
            return payload

        with patch.object(Path, "read_bytes", new=read_then_replace):
            with self.assertRaisesRegex(ValueError, "unpacked manifest"):
                self.validator(pin)(packet, archive)
        self.assertTrue(replaced)

    def test_existing_archive_digest_check_retained(self):
        packet, archive, _, _ = self.build()
        with self.assertRaisesRegex(ValueError, "archive sha changed"):
            self.validator("0" * 64)(packet, archive)


if __name__ == "__main__":
    unittest.main(verbosity=2)
