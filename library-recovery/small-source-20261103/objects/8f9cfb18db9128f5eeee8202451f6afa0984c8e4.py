import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parent / "hepta_local_blocker_sweep.py"
spec = importlib.util.spec_from_file_location("hepta_local_blocker_sweep", FILE)
sweep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sweep)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "hepta"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "test@example.invalid"], check=True)
        for p in ("codex-rs/Cargo.toml", "scripts/hepta_ci_scope.py"):
            path = self.root / p
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_text("# fixture\n")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)
        self.out = Path(self.temp.name) / "evidence"
        self.out.mkdir()

    def test_strict_source_identity(self):
        source = sweep.identify(self.root)
        self.assertTrue(source["clean"])
        self.assertEqual(len(source["head"]), 40)

    def test_dirty_tree_is_not_clean(self):
        (self.root / "new.file").write_text("dirty")
        self.assertFalse(sweep.identify(self.root)["clean"])

    def test_output_inside_worktree_denied(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            sweep.sweep(self.root, "smoke", self.root / "reports", 10)

    def test_missing_executable_fails_closed(self):
        r = sweep.execute("absent", ["this-command-does-not-exist-84af4a"], self.root, self.out, 1)
        self.assertEqual(r["state"], "BLOCKED_ENV")

    def test_real_command_receipts_and_checksum(self):
        r = sweep.execute("hello", [sys.executable, "-c", "print('test')"], self.root, self.out, 5)
        self.assertEqual(r["state"], "PASS")
        self.assertEqual(r["log_sha256"], sweep.digest_file(Path(r["log"])))
        f = sweep.execute("nonzero", [sys.executable, "-c", "raise SystemExit(3)"], self.root, self.out, 5)
        self.assertEqual(f["state"], "FAIL")
        self.assertEqual(f["returncode"], 3)

    def test_no_local_success_can_claim_production(self):
        with patch.object(sweep, "steps", return_value=[]):
            r = sweep.sweep(self.root, "smoke", self.out, 5)
        self.assertEqual(r["overall"], "LOCAL_ONLY_PASS_CROSS_PLATFORM_UNVERIFIED")
        self.assertEqual(r["external_gates"]["signed_final_use"], "UNVERIFIED")

    def test_timeout_is_failure(self):
        r = sweep.execute("timeout", [sys.executable, "-c", "import time; time.sleep(3)"], self.root, self.out, 1)
        self.assertEqual(r["state"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
