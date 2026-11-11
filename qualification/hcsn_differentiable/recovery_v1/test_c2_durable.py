"""Fault and adversarial tests for separate HCSN C2 successor durability."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from .c2_durable import (
        EvidenceError, append_receipt, producer_roster,
        publish_checkpoint, read_receipts, verify_checkpoint,
    )
except ImportError:
    from c2_durable import (
        EvidenceError, append_receipt, producer_roster,
        publish_checkpoint, read_receipts, verify_checkpoint,
    )

OWNER = "owner-start-a1"
ROSTER = [f"hcsn-s{seed}-lr{rate}" for seed in (101, 211, 307)
          for rate in ("0.001", "0.003")]


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def receipt(self, name, event_type="terminal", **data):
        if event_type == "terminal":
            data = {"status": "budget_exhausted", "native_job_id": "native-job-1",
                    "result_sha256": "a" * 64, "resource_sha256": "b" * 64, **data}
        return append_receipt(self.root / "receipts", owner_start_id=OWNER,
                              attempt_id=name, event_type=event_type, payload=data)

    def roster(self):
        return producer_roster(self.root / "receipts",
                               owner_start_id=OWNER, expected_attempts=ROSTER)

    def test_six_missing_not_promoted(self):
        for name in ROSTER[:4]:
            self.receipt(name)
        result = self.roster()
        self.assertFalse(result["producer_complete"])
        self.assertEqual(result["producer_terminal_count"], 4)
        self.assertEqual(result["missing"], ROSTER[4:])
        self.assertEqual(result["scientific_admission"], "HOLD")

    def test_six_terminal_is_still_not_independent_admission(self):
        for name in ROSTER:
            self.receipt(name)
        result = self.roster()
        self.assertTrue(result["producer_complete"])
        self.assertFalse(result["independent_native_verification"])
        self.assertEqual(result["scientific_admission"], "HOLD")

    def test_duplicate_terminal_rejected(self):
        self.receipt(ROSTER[0])
        with self.assertRaises(EvidenceError):
            self.receipt(ROSTER[0], status="completed")
        self.assertEqual(len(read_receipts(self.root / "receipts",
                                           owner_start_id=OWNER)), 1)

    def test_nonfinite_spoof_and_missing_native_proof_rejected(self):
        with self.assertRaises(EvidenceError):
            self.receipt(ROSTER[0], resource_sha256=None)
        with self.assertRaises(EvidenceError):
            self.receipt(ROSTER[0], native_job_id="")
        with self.assertRaises(EvidenceError):
            self.receipt(ROSTER[0], result_sha256="x" * 64)
        with self.assertRaises(EvidenceError):
            self.receipt(ROSTER[0], event_type="progress", value=float("nan"))

    def test_mutated_checksum_and_gap_rejected(self):
        self.receipt(ROSTER[0])
        path = self.root / "receipts/00000000.json"
        original = path.read_bytes()
        path.write_bytes(original.replace(b"budget_exhausted", b"completed"))
        with self.assertRaises(EvidenceError):
            self.roster()
        path.write_bytes(original)
        path.rename(self.root / "receipts/00000001.json")
        with self.assertRaises(EvidenceError):
            self.roster()

    def test_torn_jsonl_is_not_a_receipt(self):
        self.receipt(ROSTER[0], event_type="progress", update_index=1)
        (self.root / "receipts/commands.jsonl").write_text('{"partial":')
        self.assertFalse(self.roster()["producer_complete"])
        self.assertEqual(len(read_receipts(self.root / "receipts",
                                           owner_start_id=OWNER)), 1)

    def test_atomic_checkpoint_nonempty_and_no_overwrite(self):
        dst = self.root / "state.pt"
        data = b"frozen-state-optimizer-rng-digest"
        info = publish_checkpoint(dst, lambda f: f.write(data),
                                  lambda p: p.read_bytes() == data)
        self.assertEqual(info["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(verify_checkpoint(
            dst, info, lambda p: p.read_bytes() == data), info)
        with self.assertRaises(FileExistsError):
            publish_checkpoint(dst, lambda f: f.write(b"other"),
                               lambda p: True)
        self.assertEqual(dst.read_bytes(), data)

    def test_zero_byte_existing_checkpoint_rejected_not_overwritten(self):
        dst = self.root / "interrupted.pt"
        dst.touch()
        with self.assertRaises(FileExistsError):
            publish_checkpoint(dst, lambda f: f.write(b"new"),
                               lambda p: True)
        with self.assertRaises(EvidenceError):
            verify_checkpoint(dst, {"bytes": 0, "sha256": "a" * 64},
                              lambda p: True)
        self.assertEqual(dst.stat().st_size, 0)

    def test_failing_serializer_never_publishes(self):
        def partial(stream):
            stream.write(b"only-partial")
            raise OSError("synthetic serialize interruption")

        with self.assertRaises(OSError):
            publish_checkpoint(self.root / "state.pt", partial, lambda p: True)
        self.assertFalse((self.root / "state.pt").exists())

    def test_semantically_invalid_checkpoint_never_publishes(self):
        with self.assertRaises(EvidenceError):
            publish_checkpoint(self.root / "state.pt", lambda f: f.write(b"data"),
                               lambda p: False)
        self.assertFalse((self.root / "state.pt").exists())
        with self.assertRaises(EvidenceError):
            publish_checkpoint(self.root / "zero.pt", lambda f: None,
                               lambda p: True)

    def test_hard_exit_while_serializing_no_false_checkpoint(self):
        code = (
            "import os,sys\n"
            "from pathlib import Path\n"
            "from c2_durable import publish_checkpoint\n"
            "def torn(f):\n"
            " f.write(b'half-written')\n"
            " f.flush()\n"
            " os._exit(23)\n"
            "publish_checkpoint(Path(sys.argv[1]), torn, lambda p: True)\n"
        )
        result = subprocess.run([sys.executable, "-c", code,
                                 str(self.root / "after-kill.pt")],
                                cwd=Path(__file__).parent, check=False,
                                capture_output=True)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertFalse((self.root / "after-kill.pt").exists())
        self.assertEqual(self.roster()["producer_terminal_count"], 0)

    def test_concurrent_append_has_unbroken_hash_chain(self):
        names = [f"candidate-{n}" for n in range(12)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            result = list(pool.map(lambda n: self.receipt(
                n, event_type="progress", update_index=1), names))
        self.assertEqual(len(result), 12)
        events = read_receipts(self.root / "receipts", owner_start_id=OWNER)
        self.assertEqual(len(events), 12)
        self.assertEqual({e["attempt_id"] for e in events}, set(names))
        self.assertEqual([e["seq"] for e in events], list(range(12)))

    def test_identity_spoof_and_roster_duplicates(self):
        class Fake(str):
            pass

        with self.assertRaises(EvidenceError):
            append_receipt(self.root / "receipts", owner_start_id=Fake(OWNER),
                           attempt_id=ROSTER[0], event_type="progress", payload={})
        with self.assertRaises(EvidenceError):
            producer_roster(self.root / "receipts", owner_start_id=OWNER,
                            expected_attempts=[ROSTER[0], ROSTER[0]])


if __name__ == "__main__":
    unittest.main()
