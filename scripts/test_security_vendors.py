import difflib
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import verify_security_vendors as audit


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


class SecurityVendorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.relative = "codex-rs/third_party/example-1.0.0"
        self.package = self.root / self.relative
        (self.package / "src").mkdir(parents=True)
        self.original = b"fn first() {}\nfn old() {}\nfn last() {}\n"
        self.current = self.original.replace(b"old", b"new")
        (self.package / "src/lib.rs").write_bytes(self.current)
        (self.package / "Cargo.toml").write_text('[package]\nname = "example"\n')
        self.upstream = {
            "name": "example",
            "version": "1.0.0",
            "sha256": "a" * 64,
            "upstream_files": {
                "src/lib.rs": sha(self.original),
                "Cargo.toml": sha((self.package / "Cargo.toml").read_bytes()),
            },
        }
        write_json(self.package / audit.UPSTREAM_MANIFEST, self.upstream)
        patch = "".join(
            difflib.unified_diff(
                self.original.decode().splitlines(keepends=True),
                self.current.decode().splitlines(keepends=True),
                fromfile="a/src/lib.rs",
                tofile="b/src/lib.rs",
            )
        )
        (self.package / audit.PATCH).write_text(patch)
        self.refresh()

    def refresh(self):
        files = {}
        for path in self.package.rglob("*"):
            if path.is_file() and path.name != audit.PATCH_MANIFEST:
                data = path.read_bytes()
                files[path.relative_to(self.package).as_posix()] = {
                    "sha256": sha(data),
                    "bytes": len(data),
                }
        manifest = {
            "schema": "hepta.security-vendor-patch.v1",
            "upstream_manifest_sha256": sha(
                (self.package / audit.UPSTREAM_MANIFEST).read_bytes()
            ),
            "upstream_archive_sha256": self.upstream["sha256"],
            "files": files,
            "modified_upstream_files": ["src/lib.rs"],
        }
        write_json(self.package / audit.PATCH_MANIFEST, manifest)
        index = {
            "schema": "hepta.security-vendor-index.v1",
            "packages": [
                {
                    "directory": self.relative,
                    "manifest_sha256": sha(
                        (self.package / audit.PATCH_MANIFEST).read_bytes()
                    ),
                }
            ],
        }
        write_json(self.root / audit.INDEX, index)

    def test_retained_source_and_reverse_patch_match_original(self):
        receipt = audit.verify(self.root)
        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(
            receipt["packages"][0]["modified_upstream_files"], ["src/lib.rs"]
        )

    def test_source_tampering_is_rejected(self):
        (self.package / "src/lib.rs").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "vendor file changed"):
            audit.verify(self.root)

    def test_undeclared_file_is_rejected(self):
        (self.package / "injected.rs").write_text("unregistered source")
        with self.assertRaisesRegex(ValueError, "file set differs"):
            audit.verify(self.root)

    def test_manifest_refresh_cannot_hide_unpatched_upstream_edits(self):
        (self.package / "Cargo.toml").write_text("unreported manifest change\n")
        self.refresh()
        with self.assertRaisesRegex(ValueError, "upstream identity mismatch"):
            audit.verify(self.root)

    def test_patch_is_checked_against_actual_content(self):
        patch = self.package / audit.PATCH
        patch.write_text(patch.read_text().replace("+fn new", "+fn other"))
        self.refresh()
        with self.assertRaisesRegex(ValueError, "patch does not match"):
            audit.verify(self.root)

    def test_symlink_and_traversal_are_rejected(self):
        for name in ("../escape", "/absolute", "src/../escape", "src\\escape"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.safe_path(self.package, name)
        target = self.package / "src/lib.rs"
        target.unlink()
        target.symlink_to(self.root / "outside")
        with self.assertRaisesRegex(ValueError, "symlink"):
            audit.verify(self.root)

    def test_duplicate_manifest_fields_are_rejected(self):
        path = self.root / audit.INDEX
        path.write_text('{"schema": "first", "schema": "second"}')
        with self.assertRaisesRegex(ValueError, "duplicate manifest key"):
            audit.verify(self.root)


if __name__ == "__main__":
    unittest.main()
