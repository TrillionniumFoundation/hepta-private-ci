import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import codespell_custody


class CodespellCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = "library-recovery/captured/objects/original.txt"
        self.payload = b"Original captured source spelling.\n"
        source = self.root / self.path
        source.parent.mkdir(parents=True)
        source.write_bytes(self.payload)
        (self.root / ".github").mkdir()
        self.manifest = {
            "schema": codespell_custody.SCHEMA,
            "files": {self.path: hashlib.sha256(self.payload).hexdigest()},
        }
        self.write_manifest()

    def write_manifest(self):
        (self.root / codespell_custody.MANIFEST).write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )

    def test_only_exact_named_original_is_excluded(self):
        other = self.root / "library-recovery/captured/current-guide.txt"
        other.write_bytes(b"Ordinary maintenance guide.\n")
        self.assertEqual(codespell_custody.verified_skip(self.root), f"./{self.path}")

    def test_changed_original_is_rejected(self):
        (self.root / self.path).write_bytes(self.payload + b"Changed.\n")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            codespell_custody.verified_skip(self.root)

    def test_missing_original_is_rejected(self):
        (self.root / self.path).unlink()
        with self.assertRaises(FileNotFoundError):
            codespell_custody.verified_skip(self.root)

    def test_path_patterns_and_escape_forms_are_rejected(self):
        for path in (
            "library-recovery/**",
            "library-recovery/captured/?.txt",
            "library-recovery/captured/[ab].txt",
            "library-recovery/captured/a,b.txt",
            "library-recovery/captured/a\nb.txt",
            "library-recovery/../README.md",
            "library-recovery/captured/./a.txt",
            "library-recovery//captured/a.txt",
            "/library-recovery/captured/a.txt",
            "library-recovery\\captured\\a.txt",
            "scripts/current.py",
        ):
            with self.subTest(path=path):
                self.manifest["files"] = {path: "0" * 64}
                self.write_manifest()
                with self.assertRaisesRegex(ValueError, "exact repository path"):
                    codespell_custody.verified_skip(self.root)

    def test_duplicate_manifest_keys_are_rejected(self):
        for raw in (
            '{"schema":"one","schema":"two","files":{}}',
            '{"schema":"hepta.codespell-custody.v1","files":{"x":"a","x":"b"}}',
        ):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                    codespell_custody.parse_manifest(raw)

    def test_invalid_manifest_and_digest_are_rejected(self):
        for document in (
            [],
            {},
            {"schema": "other", "files": {}},
            {"schema": codespell_custody.SCHEMA, "files": {}},
            {**self.manifest, "extra": True},
        ):
            with self.subTest(document=document):
                with self.assertRaisesRegex(
                    ValueError, "invalid Codespell custody manifest"
                ):
                    codespell_custody.parse_manifest(json.dumps(document))
        for digest in ("0" * 63, "A" * 64, True, None):
            with self.subTest(digest=digest):
                self.manifest["files"] = {self.path: digest}
                self.write_manifest()
                with self.assertRaisesRegex(ValueError, "exact SHA-256"):
                    codespell_custody.verified_skip(self.root)

    def test_directory_and_symbolic_link_are_rejected(self):
        source = self.root / self.path
        source.unlink()
        source.mkdir()
        with self.assertRaisesRegex(ValueError, "regular single-link file"):
            codespell_custody.verified_skip(self.root)
        source.rmdir()
        target = self.root / "target.txt"
        target.write_bytes(self.payload)
        source.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "regular single-link file"):
            codespell_custody.verified_skip(self.root)
        source.unlink()
        source.parent.rmdir()
        source.parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            codespell_custody.verified_skip(self.root)

    def test_read_is_bounded_and_replacement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "byte limit"):
            codespell_custody.read_regular(self.root, self.path, 1)
        source = self.root / self.path
        replacement = source.with_name("replacement.txt")
        replacement.write_bytes(self.payload)
        original_lstat = Path.lstat
        calls = 0

        def replace_on_final_stat(path):
            nonlocal calls
            if path == source:
                calls += 1
                if calls == 2:
                    replacement.replace(source)
            return original_lstat(path)

        with patch.object(Path, "lstat", replace_on_final_stat):
            with self.assertRaisesRegex(ValueError, "changed while reading"):
                codespell_custody.read_regular(self.root, self.path, 1024)

    def test_failed_verification_does_not_emit_skip_output(self):
        destination = self.root / "output"
        destination.write_text("previous=value\n", encoding="utf-8")
        script_path = self.root / ".github/scripts/codespell_custody.py"
        with (
            patch.object(codespell_custody, "__file__", str(script_path)),
            patch.object(
                codespell_custody, "verified_skip", side_effect=ValueError("drift")
            ),
        ):
            self.assertEqual(
                codespell_custody.main(["--github-output", str(destination)]), 1
            )
        self.assertEqual(destination.read_text(encoding="utf-8"), "previous=value\n")


if __name__ == "__main__":
    unittest.main()
