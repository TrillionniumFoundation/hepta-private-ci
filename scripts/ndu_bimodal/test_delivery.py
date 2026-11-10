"""Actual local file commits and process-cold reads; no semantic/daemon claim."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.ndu_bimodal import delivery


class LocalDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "result"
        self.assets = {"generated.txt": b"red square", "generated.ppm": b"P6\n1 1\n255\n\xff\0\0"}
        original = {
            "action": "SUBMIT", "production_update": "no-update", "semantic_quality": None,
            "text_utf8": "red square",
            "image_sha256": hashlib.sha256(self.assets["generated.ppm"]).hexdigest(),
            "checkpoint_sha256": "1" * 64, "public_sha256": "2" * 64,
            "state_sha256": "3" * 64, "calls": [{"status": "passed", "request_sha256": "4" * 64}],
        }
        self.result = delivery.prepare_delivery(original, self.assets)
        self.identity = self.result["delivery"]["identity"]

    def commit(self, before_commit=lambda: None):
        return delivery.commit_delivery(self.output, self.result, self.assets,
                                        before_commit=before_commit)

    def read(self):
        return delivery.read_delivery(self.output, expected_identity=self.identity)

    def test_exact_bytes_are_read_in_a_separate_process(self):
        self.assertEqual(self.commit(), self.result)
        child = subprocess.run([
            sys.executable, "-m", "scripts.ndu_bimodal.cli", "read-delivery",
            "--output", str(self.output), "--identity", self.identity,
        ], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(child.stdout), self.result)
        for name, raw in self.assets.items():
            self.assertEqual((self.output / name).read_bytes(), raw)

    def test_partial_intent_is_not_delivery_and_same_intent_resumes(self):
        calls = []

        def expire_before_commit():
            calls.append(1)
            if len(calls) == 2:
                raise TimeoutError("original deadline")

        with self.assertRaises(TimeoutError):
            self.commit(expire_before_commit)
        self.assertTrue((self.output / "delivery.intent.json").is_file())
        self.assertFalse((self.output / "delivery.json").exists())
        with self.assertRaises(FileNotFoundError):
            self.read()
        refused = subprocess.run([
            sys.executable, "-m", "scripts.ndu_bimodal.cli", "read-delivery",
            "--output", str(self.output), "--identity", self.identity,
        ], capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(refused.stdout, "")
        with patch.object(delivery, "_write_once", wraps=delivery._write_once) as writes:
            self.assertEqual(self.commit(), self.result)
            self.assertEqual(writes.call_count, len(self.assets))

    def test_failed_asset_write_never_publishes_a_receipt(self):
        original_write = delivery._write_once

        def fail_image(path, raw):
            if path.name == "generated.ppm":
                raise OSError("disk full")
            return original_write(path, raw)

        with patch.object(delivery, "_write_once", side_effect=fail_image):
            with self.assertRaises(OSError):
                self.commit()
        self.assertFalse((self.output / "delivery.json").exists())
        self.assertEqual(self.commit(), self.result)

    def test_lost_commit_ack_reconciles_without_another_write_or_budget(self):
        original_link = os.link

        def lose_ack(source, destination):
            original_link(source, destination)
            if Path(destination).name == "delivery.json":
                raise OSError("lost publication acknowledgement")

        with patch.object(delivery.os, "link", side_effect=lose_ack):
            with self.assertRaises(delivery.DeliveryCommitUncertain):
                self.commit()
        original = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()}
        with patch.object(delivery.os, "link", side_effect=AssertionError("no re-publication")):
            self.assertEqual(self.commit(lambda: self.fail("no new budget")), self.result)
        self.assertEqual({p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()}, original)

    def test_existing_foreign_or_empty_directory_is_not_overwritten(self):
        self.output.mkdir()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.commit()
        self.assertEqual(list(self.output.iterdir()), [])
        (self.output / "foreign").write_bytes(b"keep")
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.commit()
        self.assertEqual((self.output / "foreign").read_bytes(), b"keep")

    def test_changed_intent_or_artifacts_are_refused_without_replacement(self):
        self.commit()
        with self.assertRaises(ValueError):
            delivery.read_delivery(self.output, expected_identity="0" * 64)
        target = self.output / "generated.txt"
        target.write_bytes(b"substituted")
        with self.assertRaises(ValueError):
            self.read()
        with self.assertRaises(ValueError):
            self.commit()
        self.assertEqual(target.read_bytes(), b"substituted")

    def test_symlink_and_unknown_members_are_not_original_artifacts(self):
        self.commit()
        target = self.output / "generated.txt"
        original = target.read_bytes()
        target.unlink()
        outside = Path(self.temporary.name) / "outside"
        outside.write_bytes(original)
        target.symlink_to(outside)
        with self.assertRaises((ValueError, OSError)):
            self.read()
        target.unlink()
        target.write_bytes(original)
        (self.output / "extra").write_bytes(b"unknown")
        with self.assertRaises(ValueError):
            self.read()

    def test_expiry_before_writing_and_invalid_binding_leave_no_destination(self):
        with self.assertRaises(TimeoutError):
            self.commit(lambda: (_ for _ in ()).throw(TimeoutError("expired")))
        self.assertFalse(self.output.exists())
        changed = dict(self.assets, **{"generated.txt": b"wrong"})
        with self.assertRaises(ValueError):
            delivery.commit_delivery(self.output, self.result, changed, before_commit=lambda: None)
        self.assertFalse(self.output.exists())

    def test_replaced_fifo_is_refused_without_blocking_cold_readback(self):
        self.commit()
        target = self.output / "generated.txt"
        target.unlink()
        os.mkfifo(target)
        refused = subprocess.run([
            sys.executable, "-m", "scripts.ndu_bimodal.cli", "read-delivery",
            "--output", str(self.output), "--identity", self.identity,
        ], capture_output=True, text=True, timeout=2)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(refused.stdout, "")

    def test_local_receipt_cannot_claim_production_adoption(self):
        original = dict(self.result)
        del original["delivery"]
        original["production_update"] = "adopt"
        with self.assertRaises(ValueError):
            delivery.prepare_delivery(original, self.assets)


if __name__ == "__main__":
    unittest.main()
