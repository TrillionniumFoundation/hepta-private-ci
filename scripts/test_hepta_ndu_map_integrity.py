#!/usr/bin/env python3
"""Adversarial source-evidence tests; not host qualification receipts."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from hepta_ndu_map_integrity import checked_path, code_only, executable_test_exists, rust_symbol_exists, verify_manifest


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.rs"

    def test_comments_strings_and_plain_helpers_are_not_executable_tests(self):
        self.source.write_text('/* nested /* fn decoy() {} */ comment */\n// fn decoy() {}\nconst NOTE: &str = r###"#[test] fn decoy() {}"###;\nfn helper() {}\n#[test]\nfn real_test() {}\n')
        self.assertFalse(rust_symbol_exists(self.source, "decoy"))
        self.assertTrue(rust_symbol_exists(self.source, "helper"))
        self.assertFalse(executable_test_exists(self.source, "helper"))
        self.assertTrue(executable_test_exists(self.source, "real_test"))

    def test_async_test_and_lifetime_lexing(self):
        self.source.write_text("fn borrowed<'a>(s: &'a str) {}\n#[tokio::test(flavor = \"multi_thread\")]\nasync fn test_async() {}\n")
        self.assertTrue(rust_symbol_exists(self.source, "borrowed"))
        self.assertTrue(executable_test_exists(self.source, "test_async"))
        with self.assertRaises(ValueError): code_only("/* never closed")

    def test_path_escape_and_symlink_are_rejected(self):
        self.source.write_text("fn real() {}")
        (self.root / "alias.rs").symlink_to(self.source)
        for name in ("../source.rs", "/etc/passwd", "./source.rs", "alias.rs", "a/../source.rs"):
            with self.subTest(name=name), self.assertRaises(ValueError): checked_path(self.root, name)

    def test_stale_duplicate_and_missing_objects_are_rejected(self):
        self.source.write_text("#[test] fn real() {}\n")
        def git(*args):
            return subprocess.check_output(["git", "-C", str(self.root), *args], text=True, stderr=subprocess.DEVNULL).strip()
        git("init", "-q")
        git("add", ".")
        git("-c", "user.name=fixture", "-c", "user.email=fixture@invalid", "commit", "-qm", "fixture")
        oid = git("rev-parse", "HEAD:source.rs")
        entry = {"path": "source.rs", "object": oid}
        verify_manifest(self.root, [entry], {"source.rs"})
        for objects in ([entry, entry], [], [{"path": "source.rs", "object": "0"*40}]):
            with self.subTest(objects=objects), self.assertRaises(ValueError): verify_manifest(self.root, objects, {"source.rs"})
        self.source.write_text("#[test] fn changed() {}\n")
        git("add", ".")
        git("-c", "user.name=fixture", "-c", "user.email=fixture@invalid", "commit", "-qm", "drift")
        with self.assertRaises(ValueError): verify_manifest(self.root, [entry], {"source.rs"})


if __name__ == "__main__":
    unittest.main()
