"""Development-helper guards; these are not Rust or target-host execution."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "hepta_memory_retrieval_native_format.py"
spec = importlib.util.spec_from_file_location("retrieval_native_format", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class NativeFormatGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "fixture")
        self.run_git("config", "user.email", "fixture@example.invalid")
        self.source = self.root / "codex-rs/hepta-memory/src/fixture.rs"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("pub fn value() -> u8 { 1 }\n")
        self.base = self.commit()
        self.source.write_text("pub fn value() -> u8 { 2 }\n")
        self.head = self.commit()

    def run_git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self):
        self.run_git("add", "-A")
        self.run_git("commit", "-qm", "fixture")
        return self.run_git("rev-parse", "HEAD")

    def test_selects_exact_changed_rust_source(self):
        self.assertEqual(module.prepare(self.root, self.base, self.head),
                         ["codex-rs/hepta-memory/src/fixture.rs"])

    def test_rejects_wrong_head(self):
        with self.assertRaises(module.FormatError):
            module.prepare(self.root, self.base, self.base)

    def test_rejects_symbolic_or_uppercase_identity(self):
        for head in ["HEAD", "main", self.head.upper(), "0" * 39]:
            with self.subTest(head=head), self.assertRaises(module.FormatError):
                module.prepare(self.root, self.base, head)

    def test_rejects_tracked_dirty_source(self):
        self.source.write_text("changed after observation\n")
        with self.assertRaises(module.FormatError):
            module.prepare(self.root, self.base, self.head)

    def test_rejects_untracked_source(self):
        (self.root / "untracked.rs").write_text("untracked")
        with self.assertRaises(module.FormatError):
            module.prepare(self.root, self.base, self.head)

    def test_rejects_source_symlink(self):
        target = self.root / "target.txt"
        target.write_text("pub fn value() {}\n")
        self.source.unlink()
        self.source.symlink_to(target)
        head = self.commit()
        with self.assertRaises(module.FormatError):
            module.prepare(self.root, self.base, head)

    def test_rejects_nonancestor_base(self):
        future = self.head
        self.run_git("checkout", "--detach", "-q", self.base)
        self.source.write_text("pub fn value() -> u8 { 3 }\n")
        divergent = self.commit()
        with self.assertRaises(module.FormatError):
            module.prepare(self.root, future, divergent)

    def test_source_scope_rejects_traversal_and_other_owners(self):
        for path in ["codex-rs/core/src/lib.rs", "/codex-rs/hepta-memory/src/x.rs",
                     "codex-rs/hepta-memory/src/../Cargo.rs", "codex-rs/hepta-memory/src/a\\b.rs",
                     "codex-rs/hepta-memory/src/x\n.rs", "codex-rs/hepta-memory/src/x.json"]:
            with self.subTest(path=path):
                self.assertFalse(module.safe_source(path))

    def test_unchanged_candidate_does_not_claim_formatting(self):
        with self.assertRaises(module.FormatError):
            module.prepare(self.root, self.head, self.head)

if __name__ == "__main__":
    unittest.main()
