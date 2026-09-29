#!/usr/bin/env python3
"""Actual signed-owner reconciliation and file replacement at the normal CLI boundary."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import lifecycle


class LifecycleFinalUseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.now = int(time.time())
        self.coordinator = Ed25519PrivateKey.generate()
        self.owner = Ed25519PrivateKey.generate()
        def public(name, key):
            return {"signer_id": name, "key_epoch": 1, "revoked": False,
                    "public_key_hex": key.public_key().public_bytes_raw().hex()}
        self.trust = {"schema": "hepta.cognitive.lifecycle-trust.v1", "revision": 1,
                      "valid_until": self.now + 600, "coordinator": public("coordinator", self.coordinator),
                      "owners": [public("storage-owner", self.owner)]}
        self.plan = {"schema": "hepta.cognitive.lifecycle-plan.v1", "request_id": "delete-cut-1",
                     "owner_agent_id": "00000000-0000-4000-8000-000000000058", "writer_generation": 3,
                     "cut_sha256": "a" * 64, "policy_sha256": "b" * 64, "inventory_sha256": "c" * 64,
                     "created_at": self.now - 1, "obligations": [
                         {"storage_class": name, "storage_owner": "storage-owner",
                          "requirement": "unlearn" if name == "trained_parameters" else "erase",
                          "inventory_sha256": "d" * 64} for name in sorted(lifecycle.CLASSES)]}
        self.receipts = [self.sign({
            "schema": "hepta.cognitive.lifecycle-receipt.v1", "plan_sha256": lifecycle.sha256(self.plan),
            "storage_class": item["storage_class"], "storage_owner": "storage-owner",
            "inventory_sha256": item["inventory_sha256"], "status": "completed",
            "method": "parameter_unlearning" if item["requirement"] == "unlearn" else "physical_storage",
            "observed_at": self.now, "evidence_sha256": f"{700 + index:064x}"}, "storage-owner", self.owner)
            for index, item in enumerate(self.plan["obligations"])]
        self.trust_path, self.plan_path, self.receipts_path = (self.root / name for name in
                                                             ("trust.json", "plan.json", "receipts.json"))
        self.write(self.trust_path, self.trust)
        self.write(self.plan_path, self.sign(self.plan, "coordinator", self.coordinator))
        self.write(self.receipts_path, self.receipts)

    @staticmethod
    def sign(payload, name, key):
        envelope = {"payload": payload, "signer_id": name, "key_epoch": 1}
        envelope["signature_hex"] = key.sign(lifecycle.signing_bytes(envelope)).hex()
        return envelope

    @staticmethod
    def write(path, value):
        path.write_bytes(lifecycle.canonical(value))
        path.chmod(0o600)

    def verify(self):
        return lifecycle.reconcile_files(self.plan_path, self.receipts_path, self.trust_path,
                                         lifecycle.sha256(self.plan), lifecycle.sha256(self.trust))

    def after_verification(self, effect):
        original = lifecycle.reconcile
        def verify_then_change(*args):
            result = original(*args)
            effect()
            return result
        return mock.patch.object(lifecycle, "reconcile", side_effect=verify_then_change)

    def test_real_signatures_preserve_attestation_only_boundary(self):
        result = self.verify()
        self.assertEqual(result["result"], "owner_attested_complete")
        self.assertTrue(result["all_required_owner_receipts_verified"])
        for flag in ("authorized_effects", "physical_erasure_independently_proved", "target_host_qualified"):
            self.assertIs(result[flag], False)

    def test_coordinator_revocation_during_crypto_rejected(self):
        changed = copy.deepcopy(self.trust)
        changed["coordinator"]["revoked"] = True
        with self.after_verification(lambda: self.write(self.trust_path, changed)):
            with self.assertRaisesRegex(ValueError, "trust changed"):
                self.verify()

    def test_owner_revocation_during_crypto_rejected(self):
        changed = copy.deepcopy(self.trust)
        changed["owners"][0]["revoked"] = True
        with self.after_verification(lambda: self.write(self.trust_path, changed)):
            with self.assertRaisesRegex(ValueError, "trust changed"):
                self.verify()

    def test_trust_expiration_at_final_read_rejected(self):
        with mock.patch.object(lifecycle.time, "time", side_effect=[self.now, self.trust["valid_until"]]):
            with self.assertRaisesRegex(ValueError, "current"):
                self.verify()

    def test_clock_regression_rejected(self):
        with mock.patch.object(lifecycle.time, "time", side_effect=[self.now, self.now - 1]):
            with self.assertRaisesRegex(ValueError, "clock regressed"):
                self.verify()

    def test_correctly_signed_different_plan_during_crypto_rejected(self):
        changed = {**self.plan, "writer_generation": 4}
        replacement = self.sign(changed, "coordinator", self.coordinator)
        with self.after_verification(lambda: self.write(self.plan_path, replacement)):
            with self.assertRaisesRegex(ValueError, "plan changed"):
                self.verify()

    def test_receipt_removal_during_crypto_rejected(self):
        with self.after_verification(lambda: self.write(self.receipts_path, self.receipts[:-1])):
            with self.assertRaisesRegex(ValueError, "receipt set changed"):
                self.verify()

    def test_receipt_status_change_during_crypto_rejected(self):
        changed = copy.deepcopy(self.receipts)
        payload = {**changed[0]["payload"], "status": "indeterminate"}
        changed[0] = self.sign(payload, "storage-owner", self.owner)
        with self.after_verification(lambda: self.write(self.receipts_path, changed)):
            with self.assertRaisesRegex(ValueError, "receipt set changed"):
                self.verify()

    def test_missing_final_trust_is_not_completion(self):
        with self.after_verification(self.trust_path.unlink):
            with self.assertRaises(FileNotFoundError):
                self.verify()

    def test_late_trust_symlink_is_rejected(self):
        def redirect():
            self.trust_path.rename(self.root / "old-trust")
            self.trust_path.symlink_to(self.root / "old-trust")
        with self.after_verification(redirect):
            with self.assertRaises(ValueError):
                self.verify()

    def test_incomplete_inventory_stays_incomplete(self):
        self.write(self.receipts_path, self.receipts[:-1])
        report = self.verify()
        self.assertEqual(report["result"], "incomplete")
        self.assertFalse(report["all_required_owner_receipts_verified"])
        self.assertIn("missing", {row["status"] for row in report["obligations"]})

    def test_cli_uses_current_read_path(self):
        command = [sys.executable, str(Path(lifecycle.__file__)), "--plan", str(self.plan_path),
                   "--receipts", str(self.receipts_path), "--trusted-owners", str(self.trust_path),
                   "--expected-plan-sha256", lifecycle.sha256(self.plan),
                   "--expected-trust-sha256", lifecycle.sha256(self.trust)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "owner_attested_complete")
        self.write(self.receipts_path, self.receipts[:-1])
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "incomplete")


if __name__ == "__main__":
    unittest.main()
