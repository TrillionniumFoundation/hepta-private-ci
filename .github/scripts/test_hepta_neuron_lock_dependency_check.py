"""Offline manifest/lock regression for the production Worker integration."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from hepta_neuron_lock_dependency_check import LockMismatch, verify


class WorkerCargoLockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.manifest = root / "Cargo.toml"
        self.lock = root / "Cargo.lock"
        self.manifest.write_text("""[package]
name = "codex-hepta-infer-worker-host"
[dependencies]
codex-hepta-neuron = { path = "../hepta-neuron" }
foo = "1"
[dev-dependencies]
other = { package = "code-other", path = "../other" }
""")
        self.lock.write_text("""version = 4
[[package]]
name = "codex-hepta-infer-worker-host"
version = "0.0.0"
dependencies = ["codex-hepta-neuron", "code-other", "foo"]
""")

    def test_exact_local_dependencies_present(self):
        result = verify(self.manifest, self.lock)
        self.assertEqual(
            result["checked_direct_path_dependencies"],
            ["code-other", "codex-hepta-neuron"],
        )

    def test_missing_neuron_direct_dependency_is_rejected(self):
        self.lock.write_text(
            self.lock.read_text().replace('"codex-hepta-neuron", ', "")
        )
        with self.assertRaisesRegex(LockMismatch, "codex-hepta-neuron"):
            verify(self.manifest, self.lock)

    def test_duplicate_worker_lock_package_is_rejected(self):
        self.lock.write_text(
            self.lock.read_text()
            + """\n[[package]]\nname = "codex-hepta-infer-worker-host"\nversion = "0.0.0"\n"""
        )
        with self.assertRaisesRegex(LockMismatch, "exactly one"):
            verify(self.manifest, self.lock)

    def test_target_specific_path_dependency_is_checked(self):
        self.manifest.write_text(
            self.manifest.read_text()
            + """\n[target.'cfg(unix)'.dependencies]\nunix-only = { path = "../unix" }\n"""
        )
        with self.assertRaisesRegex(LockMismatch, "unix-only"):
            verify(self.manifest, self.lock)

    def test_corrupt_toml_is_rejected(self):
        self.lock.write_text("[[package]\n")
        with self.assertRaises(LockMismatch):
            verify(self.manifest, self.lock)


if __name__ == "__main__":
    unittest.main()
