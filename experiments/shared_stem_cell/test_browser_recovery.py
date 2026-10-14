"""Real process deaths with surviving private Chromium; not host crash acceptance."""
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

from experiments.shared_stem_cell.browser_loop import BrowserFixture, action_frame
from experiments.shared_stem_cell import browser_recovery as r
from experiments.shared_stem_cell.execution import InputError


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = BrowserFixture()

    @classmethod
    def tearDownClass(cls):
        cls.owner.close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "journal.jsonl"
        self.owner.reset()
        self.owner.action(action_frame(self.owner.observe(), "fill", "exactly one click"))

    def tearDown(self):
        self.temp.cleanup()

    def test_before_dispatch_crash_is_not_replayed(self):
        died = r.drive(self.owner, self.path, cut="before_dispatch")
        self.assertEqual(died["exit_code"], 73)
        restored = r.drive(self.owner, self.path, mode="recover")
        self.assertEqual(restored["result"]["status"], "not_applied")
        self.assertEqual(restored["action_calls"], 0)
        self.assertEqual(self.owner.observe()["state"]["count"], 0)

    def test_sigkill_after_real_effect_before_ack(self):
        died = r.drive(self.owner, self.path, cut="after_effect_before_ack")
        self.assertEqual(died["exit_code"], -9)
        self.assertEqual(self.owner.observe()["state"]["count"], 1)
        restored = r.drive(self.owner, self.path, mode="recover")
        self.assertNotEqual(died["controller_pid"], restored["controller_pid"])
        self.assertEqual(restored["result"]["status"], "applied")
        self.assertEqual(restored["action_calls"], 0)
        repeated = r.drive(self.owner, self.path, mode="recover")
        self.assertTrue(repeated["result"]["already_terminal"])
        self.assertEqual(self.owner.observe()["state"]["count"], 1)

    def test_after_terminal_crash_does_not_repeat_effect(self):
        died = r.drive(self.owner, self.path, cut="after_terminal")
        self.assertEqual(died["exit_code"], 75)
        restored = r.drive(self.owner, self.path, mode="recover")
        self.assertTrue(restored["result"]["already_terminal"])
        self.assertEqual(restored["action_calls"], 0)

    def test_start_again_rejected(self):
        r.drive(self.owner, self.path, cut="after_effect_before_ack")
        refused = r.drive(self.owner, self.path, mode="start")
        self.assertNotEqual(refused["exit_code"], 0)
        self.assertEqual(refused["action_calls"], 0)
        self.assertEqual(self.owner.observe()["state"]["count"], 1)

    def test_changed_browser_generation_stays_unknown(self):
        r.drive(self.owner, self.path, cut="after_effect_before_ack")
        self.owner.reset()
        restored = r.drive(self.owner, self.path, mode="recover")
        self.assertEqual(restored["result"]["status"], "unknown")
        self.assertEqual(restored["action_calls"], 0)
        journal = r.Journal(self.path)
        try:
            self.assertEqual(len(journal.rows), 1)
        finally:
            journal.close()

    def test_revocation_blocks_real_dispatch(self):
        self.owner.revoke()
        result = r.drive(self.owner, self.path)
        self.assertNotEqual(result["exit_code"], 0)
        self.assertEqual(self.owner.observe()["state"]["count"], 0)
        restored = r.drive(self.owner, self.path, mode="recover")
        self.assertEqual(restored["result"]["status"], "not_applied")
        self.assertFalse(restored["result"]["replay_permitted"])

    def test_truncated_journal_fails_before_any_effect(self):
        self.path.write_bytes(b'{"partial":')
        result = r.drive(self.owner, self.path, mode="recover")
        self.assertNotEqual(result["exit_code"], 0)
        self.assertEqual(result["action_calls"], 0)

    def test_single_writer_lock_is_real(self):
        journal = r.Journal(self.path)
        try:
            result = r.drive(self.owner, self.path)
            self.assertNotEqual(result["exit_code"], 0)
            self.assertEqual(result["action_calls"], 0)
        finally:
            journal.close()

    def test_controller_import_does_not_load_tensor_runtime(self):
        result = subprocess.run([sys.executable, "-S", "-c",
            "import sys; import experiments.shared_stem_cell.browser_recovery; "
            "assert 'torch' not in sys.modules and 'numpy' not in sys.modules"],
            capture_output=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_hash_chain_corruption_rejected(self):
        journal = r.Journal(self.path)
        journal.append({"kind": "entered"})
        journal.close()
        self.path.write_bytes(self.path.read_bytes().replace(b'"entered"', b'"changed"'))
        with self.assertRaises(InputError):
            r.Journal(self.path)


if __name__ == "__main__":
    unittest.main()
