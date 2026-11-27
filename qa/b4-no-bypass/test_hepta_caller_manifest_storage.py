"""Keep packaged caller bytes exact and refuse incomplete storage."""

import hashlib
import json
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from test_verify_hepta_callers import MODULE

import hepta_ci_scope

STORAGE = MODULE.manifest_storage
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = b"""schema_version = 2
plan_id = "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN"
source_roots = ["codex-rs"]
ignored_path_fragments = []
[privileged_inventory]
required_boundary_ids = ["gate"]
[[boundary]]
id = "gate"
symbol = "Gate::enter"
definition_path = "codex-rs/owner.rs"
definition_markers = ["pub struct Gate"]
product_callers = ["codex-rs/caller.rs"]
caller_markers = ["Gate::enter"]
[[protected_file]]
path = "codex-rs/owner.rs"
required = ["pub struct Gate"]
forbidden = ["unsafe"]
[authority]
runtime_authority = false
"""


class CallerManifestStorageTests(unittest.TestCase):
    def package(self, raw=FIXTURE):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for relative, data in STORAGE.build_package(raw).items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return root

    def index_value(self, root, key, value):
        index = root / "CALLERS.toml"
        replacement = json.dumps(value) if isinstance(value, str) else str(value)
        text, count = re.subn(
            rf"^{key} = .*$", f"{key} = {replacement}", index.read_text(), flags=re.M
        )
        self.assertEqual(count, 1)
        index.write_text(text)

    def part(self, root):
        index = tomllib.loads((root / "CALLERS.toml").read_text())
        self.assertEqual(len(index["part"]), 1)
        return root / index["part"][0]["path"]

    def replace_compressed(self, root, compressed):
        self.part(root).write_bytes(compressed)
        self.index_value(root, "compressed_bytes", len(compressed))
        self.index_value(
            root, "compressed_sha256", hashlib.sha256(compressed).hexdigest()
        )

    def replace_raw(self, root, raw):
        self.replace_compressed(root, STORAGE._gzip(raw))
        self.index_value(root, "raw_bytes", len(raw))
        self.index_value(root, "raw_sha256", hashlib.sha256(raw).hexdigest())
        self.index_value(root, "manifest_bytes", len(raw))
        self.index_value(root, "manifest_sha256", hashlib.sha256(raw).hexdigest())

    def refuses(self, root, message):
        with self.assertRaisesRegex(MODULE.VerificationFailure, message):
            MODULE._load_manifest(root / "CALLERS.toml")

    def test_native_fixture_and_package_preserve_exact_bytes_and_object(self):
        root = self.package()
        self.assertEqual(STORAGE.read_manifest_bytes(root / "CALLERS.toml"), FIXTURE)
        self.assertEqual(
            MODULE._load_manifest(root / "CALLERS.toml"),
            tomllib.loads(FIXTURE.decode()),
        )
        self.assertEqual(STORAGE.build_package(FIXTURE), STORAGE.build_package(FIXTURE))
        native = root / "native.toml"
        native.write_bytes(FIXTURE)
        self.assertEqual(STORAGE.read_manifest_bytes(native), FIXTURE)
        self.assertEqual(MODULE._load_manifest(native), tomllib.loads(FIXTURE.decode()))

    def test_multiple_parts_reassemble_in_order_without_rewriting_text(self):
        with patch.object(STORAGE, "MAX_PART_BYTES", 200):
            files = STORAGE.build_package(FIXTURE)
        self.assertGreater(len(files), 2)
        root = self.package()
        for target in (root / STORAGE.PARTS_DIRECTORY).iterdir():
            target.unlink()
        for relative, data in files.items():
            (root / relative).write_bytes(data)
        self.assertEqual(STORAGE.read_manifest_bytes(root / "CALLERS.toml"), FIXTURE)

    def test_current_manifest_matches_its_byte_and_row_commitments(self):
        path = ROOT / "CALLERS.toml"
        index = tomllib.loads(path.read_text())
        raw = STORAGE.read_manifest_bytes(path)
        data = MODULE._load_manifest(path)
        self.assertEqual(len(raw), index["manifest_bytes"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), index["manifest_sha256"])
        self.assertEqual(len(data["boundary"]), index["boundary_count"])
        self.assertEqual(len(data["protected_file"]), index["protected_file_count"])
        self.assertEqual(data, tomllib.loads(raw.decode()))

    def test_missing_and_extra_parts_refuse(self):
        for action in ("missing", "extra"):
            with self.subTest(action=action):
                root = self.package()
                if action == "missing":
                    self.part(root).unlink()
                else:
                    (root / STORAGE.PARTS_DIRECTORY / "extra.gz").write_bytes(b"extra")
                self.refuses(root, "missing or extra")

    def test_order_duplicate_and_traversal_paths_refuse(self):
        for path in (
            "../outside.gz",
            "/outside.gz",
            "scripts/../outside.gz",
            STORAGE.PARTS_DIRECTORY + "/part-0001.toml.gz",
        ):
            with self.subTest(path=path):
                root = self.package()
                self.index_value(root, "path", path)
                self.refuses(root, "unique ordered local paths")
        root = self.package()
        index = root / "CALLERS.toml"
        text = index.read_text()
        index.write_text(text + "\n[[part]]" + text.split("[[part]]")[1])
        self.refuses(root, "unique ordered local paths")

    def test_unknown_missing_and_duplicate_index_fields_refuse(self):
        for action in ("unknown", "missing_storage_format", "duplicate"):
            with self.subTest(action=action):
                root = self.package()
                index = root / "CALLERS.toml"
                text = index.read_text()
                if action == "unknown":
                    text = "unexpected = true\n" + text
                elif action == "missing_storage_format":
                    text = re.sub(r"^storage_format = .*\n", "", text, flags=re.M)
                else:
                    text = 'storage_format = "duplicate"\n' + text
                index.write_text(text)
                self.refuses(root, "index|invalid caller TOML")

    def test_unknown_part_field_and_wrong_storage_format_refuse(self):
        root = self.package()
        index = root / "CALLERS.toml"
        index.write_text(index.read_text() + "unexpected = true\n")
        self.refuses(root, "part has missing or unknown fields")
        root = self.package()
        self.index_value(root, "storage_format", "unknown-format")
        self.refuses(root, "storage format")

    def test_index_and_part_symlinks_refuse_even_for_matching_content(self):
        for which in ("index", "part", "parts_directory", "scripts_directory"):
            with self.subTest(which=which):
                root = self.package()
                if which == "index":
                    target = root / "CALLERS.toml"
                elif which == "part":
                    target = self.part(root)
                elif which == "parts_directory":
                    target = root / STORAGE.PARTS_DIRECTORY
                else:
                    target = root / "scripts"
                retained = root / "retained"
                target.rename(retained)
                target.symlink_to(retained, target_is_directory=retained.is_dir())
                self.refuses(root, "regular file|real directory")

    def test_compressed_raw_and_manifest_hashes_are_independent(self):
        for field in ("compressed_sha256", "raw_sha256", "manifest_sha256"):
            with self.subTest(field=field):
                root = self.package()
                self.index_value(root, field, "0" * 64)
                self.refuses(root, "digest mismatch")

    def test_lengths_counts_types_and_allocation_bounds_refuse(self):
        for field, value in (
            ("compressed_bytes", 1),
            ("raw_bytes", 1),
            ("manifest_bytes", STORAGE.MAX_MANIFEST_BYTES + 1),
            ("boundary_count", 2),
            ("protected_file_count", 2),
            ("boundary_count", "1"),
            ("compressed_bytes", STORAGE.MAX_PART_BYTES + 1),
        ):
            with self.subTest(field=field, value=value):
                root = self.package()
                self.index_value(root, field, value)
                self.refuses(root, "length|count|integer")

    def test_truncation_trailing_bytes_and_second_gzip_member_refuse(self):
        for action in ("truncated", "trailing", "second_member"):
            with self.subTest(action=action):
                root = self.package()
                compressed = self.part(root).read_bytes()
                if action == "truncated":
                    compressed = compressed[:-5]
                elif action == "trailing":
                    compressed += b"trailing"
                else:
                    compressed += STORAGE._gzip(b"second member")
                self.replace_compressed(root, compressed)
                self.refuses(root, "truncated, oversized, or has trailing")

    def test_declared_short_output_refuses_bounded_decompression(self):
        root = self.package()
        self.index_value(root, "raw_bytes", len(FIXTURE) - 1)
        self.index_value(root, "manifest_bytes", len(FIXTURE) - 1)
        self.refuses(root, "truncated, oversized, or has trailing")

    def test_corrupt_gzip_with_rebound_digest_refuses(self):
        root = self.package()
        self.replace_compressed(root, b"this is not a gzip stream")
        self.refuses(root, "invalid caller gzip")

    def test_wrong_payload_schema_unknown_fields_and_duplicate_rows_refuse(self):
        cases = (
            (FIXTURE.replace(b"schema_version = 2", b"schema_version = 3"), None),
            (b"unexpected = true\n" + FIXTURE, None),
            (FIXTURE + b'\n[[boundary]]\nid = "gate"\n', ("boundary_count", 2)),
            (
                FIXTURE + b'\n[[protected_file]]\npath = "codex-rs/owner.rs"\n',
                ("protected_file_count", 2),
            ),
        )
        for raw, count_change in cases:
            with self.subTest(raw=raw[-60:]):
                root = self.package()
                self.replace_raw(root, raw)
                if count_change is not None:
                    self.index_value(root, *count_change)
                self.refuses(root, "schema_version|unknown fields|duplicate")

    def test_invalid_utf8_and_toml_refuse_after_valid_decompression(self):
        for raw in (b"\xff", b"invalid = ["):
            with self.subTest(raw=raw):
                root = self.package()
                self.replace_raw(root, raw)
                self.refuses(root, "invalid caller TOML")

    def test_new_storage_paths_preserve_native_ci_scope(self):
        manifest = hepta_ci_scope.select(["CALLERS.toml"])
        part = hepta_ci_scope.select([STORAGE.PARTS_DIRECTORY + "/part-0000.toml.gz"])
        loader = hepta_ci_scope.select(["scripts/hepta_caller_manifest.py"])
        original_verifier = hepta_ci_scope.select(["scripts/verify_hepta_callers.py"])
        self.assertEqual(part, manifest)
        self.assertEqual(loader, original_verifier)
        self.assertTrue(part["native"])
        self.assertTrue(loader["full_repo"])
        for unexpected in ("unexpected.py", "nested/module.rs", "part-invalid.toml.gz"):
            scope = hepta_ci_scope.select([STORAGE.PARTS_DIRECTORY + "/" + unexpected])
            self.assertTrue(scope["full_repo"], unexpected)


if __name__ == "__main__":
    unittest.main()
