#!/usr/bin/env python3
"""Real Ed25519 verification against isolated fixture keys; no storage deletion."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import lifecycle as module


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name).resolve()
        cls.keys = {}
        signers = []
        for name in ("coordinator", "storage-owner"):
            key = cls.root / (name + ".pem")
            subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)], check=True, capture_output=True, timeout=10)
            key.chmod(0o600)
            public = subprocess.check_output(["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER"], timeout=10)
            cls.keys[name] = key
            signers.append({"signer_id": name, "key_epoch": 1, "public_key_hex": public[-32:].hex(), "revoked": False})
        cls.base_trust = {"schema": "hepta.cognitive.lifecycle-trust.v1", "revision": 1, "valid_until": 9999999999,
                          "coordinator": signers[0], "owners": signers[1:]}
        cls.base_plan = {"schema": "hepta.cognitive.lifecycle-plan.v1", "request_id": "delete-1",
                         "owner_agent_id": "00000000-0000-4000-8000-00000000c059", "writer_generation": 7,
                         "cut_sha256": "a" * 64, "policy_sha256": "b" * 64, "inventory_sha256": "c" * 64,
                         "created_at": 100, "obligations": [
                             {"storage_class": kind, "storage_owner": "storage-owner", "requirement": "erase", "inventory_sha256": "d" * 64}
                             for kind in sorted(module.CLASSES)]}
        cls.base_signed = cls.sign(cls.base_plan, "coordinator")
        cls.base_receipts = []
        for index, obligation in enumerate(cls.base_plan["obligations"]):
            payload = {"schema": "hepta.cognitive.lifecycle-receipt.v1", "plan_sha256": module.sha256(cls.base_plan),
                       "storage_class": obligation["storage_class"], "storage_owner": "storage-owner",
                       "inventory_sha256": obligation["inventory_sha256"], "status": "completed", "method": "physical_storage",
                       "observed_at": 102, "evidence_sha256": f"{500 + index:064x}"}
            cls.base_receipts.append(cls.sign(payload, "storage-owner"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def sign(cls, payload, signer):
        envelope = {"payload": deepcopy(payload), "signer_id": signer, "key_epoch": 1}
        with tempfile.TemporaryDirectory(dir=cls.root) as temporary:
            source = Path(temporary) / "message"
            source.write_bytes(module.signing_bytes(envelope))
            signature = subprocess.check_output(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(cls.keys[signer]), "-in", str(source)], timeout=10)
        return {**envelope, "signature_hex": signature.hex()}

    def setUp(self):
        self.trust = deepcopy(self.base_trust)
        self.plan = deepcopy(self.base_signed)
        self.receipts = deepcopy(self.base_receipts)

    def run_reconcile(self):
        return module.reconcile(self.plan, self.receipts, self.trust, 105, module.sha256(self.plan["payload"]))

    def change_receipt(self, **fields):
        self.receipts[0]["payload"].update(fields)
        self.receipts[0] = self.sign(self.receipts[0]["payload"], "storage-owner")

    def test_all_classes_require_authentic_observations(self):
        report = self.run_reconcile()
        self.assertTrue(report["all_required_owner_receipts_verified"])
        self.assertEqual(report["result"], "owner_attested_complete")
        self.assertFalse(report["authorized_effects"])
        self.assertFalse(report["physical_erasure_independently_proved"])

    def test_missing_receipt_is_incomplete(self):
        self.receipts.pop()
        self.assertFalse(self.run_reconcile()["all_required_owner_receipts_verified"])

    def test_no_receipts_is_incomplete(self):
        self.receipts = []
        self.assertEqual(self.run_reconcile()["result"], "incomplete")

    def test_duplicate_receipt_rejects(self):
        self.receipts.append(self.receipts[0])
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_omitted_class_cannot_be_silently_waived(self):
        self.plan["payload"]["obligations"].pop()
        self.plan = self.sign(self.plan["payload"], "coordinator")
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_changed_cut_rejects_old_receipts(self):
        self.plan["payload"]["cut_sha256"] = "f" * 64
        self.plan = self.sign(self.plan["payload"], "coordinator")
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_other_requested_plan_rejects(self):
        with self.assertRaises(ValueError):
            module.reconcile(self.plan, self.receipts, self.trust, 105, "f" * 64)

    def test_coordinator_cannot_attest_storage(self):
        self.receipts[0] = self.sign(self.receipts[0]["payload"], "coordinator")
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_owner_cannot_sign_coordinator_plan(self):
        self.plan = self.sign(self.plan["payload"], "storage-owner")
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_signature_tamper_rejects(self):
        self.receipts[0]["signature_hex"] = "0" * 128
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_path_injected_openssl_cannot_bless_tampered_signature(self):
        fake = self.root / "fake-bin"
        fake.mkdir(exist_ok=True)
        executable = fake / "openssl"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        self.receipts[0]["signature_hex"] = "0" * 128
        with mock.patch.dict(os.environ, {"PATH": str(fake)}, clear=False):
            with self.assertRaisesRegex(ValueError, "signature verification"):
                self.run_reconcile()

    def test_unsigned_field_drift_rejects(self):
        self.receipts[0]["payload"]["status"] = "pending"
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_revoked_owner_rejects(self):
        self.trust["owners"][0]["revoked"] = True
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_shared_coordinator_owner_key_rejects(self):
        self.trust["owners"][0]["public_key_hex"] = self.trust["coordinator"]["public_key_hex"]
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_logical_tombstone_is_not_erasure(self):
        self.change_receipt(method="logical_tombstone")
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_revocation_is_not_erasure(self):
        self.change_receipt(method="revoked_and_rebuilt")
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_pending_remains_incomplete(self):
        self.change_receipt(status="pending")
        self.assertEqual(self.run_reconcile()["result"], "incomplete")

    def test_indeterminate_remains_incomplete(self):
        self.change_receipt(status="indeterminate")
        self.assertEqual(self.run_reconcile()["result"], "incomplete")

    def test_wrong_inventory_rejects(self):
        self.change_receipt(inventory_sha256="f" * 64)
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_duplicate_evidence_identity_rejects(self):
        payload = {**self.receipts[1]["payload"],
                   "evidence_sha256": self.receipts[0]["payload"]["evidence_sha256"]}
        self.receipts[1] = self.sign(payload, "storage-owner")
        with self.assertRaisesRegex(ValueError, "reuse one evidence"):
            self.run_reconcile()

    def test_evidence_cannot_reuse_inventory_identity(self):
        self.change_receipt(evidence_sha256=self.base_plan["inventory_sha256"])
        with self.assertRaisesRegex(ValueError, "plan, cut, policy or inventory"):
            self.run_reconcile()

    def test_future_observation_rejects(self):
        self.change_receipt(observed_at=106)
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_pre_plan_observation_rejects(self):
        self.change_receipt(observed_at=99)
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_expired_trust_rejects(self):
        self.trust["valid_until"] = 104
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_unknown_signed_field_rejects(self):
        self.change_receipt(override=True)
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_boolean_key_epoch_rejects(self):
        self.receipts[0]["key_epoch"] = True
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_receipt_budget_rejects(self):
        self.receipts = [self.receipts[0]] * 129
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_cli_checks_pinned_trust_and_plan(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary)
            for name, value in (("plan", self.plan), ("receipts", self.receipts), ("trust", self.trust)):
                (root / name).write_text(json.dumps(value))
            argv = [sys.executable, str(Path(module.__file__)), "--plan", str(root / "plan"), "--receipts", str(root / "receipts"),
                    "--trusted-owners", str(root / "trust"), "--expected-trust-sha256", module.sha256(self.trust),
                    "--expected-plan-sha256", module.sha256(self.plan["payload"])]
            result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            argv[-1] = "f" * 64
            result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)

    def test_explicit_not_applicable_requires_owner_absence(self):
        self.plan["payload"]["obligations"][0]["requirement"] = "not_applicable"
        self.plan = self.sign(self.plan["payload"], "coordinator")
        for index, envelope in enumerate(self.receipts):
            payload = envelope["payload"]
            payload["plan_sha256"] = module.sha256(self.plan["payload"])
            if index == 0:
                payload["method"] = "owner_absence"
            self.receipts[index] = self.sign(payload, "storage-owner")
        self.assertEqual(self.run_reconcile()["result"], "owner_attested_complete")

    def test_unlearning_has_separate_attestation(self):
        for obligation in self.plan["payload"]["obligations"]:
            if obligation["storage_class"] == "trained_parameters":
                obligation["requirement"] = "unlearn"
        self.plan = self.sign(self.plan["payload"], "coordinator")
        for index, envelope in enumerate(self.receipts):
            payload = envelope["payload"]
            payload["plan_sha256"] = module.sha256(self.plan["payload"])
            if payload["storage_class"] == "trained_parameters":
                payload["method"] = "parameter_unlearning"
            self.receipts[index] = self.sign(payload, "storage-owner")
        self.assertEqual(self.run_reconcile()["result"], "owner_attested_complete")

    def test_oversize_input_is_rejected_before_json(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            path = Path(temporary) / "oversize"
            path.write_bytes(b" " * (module.MAX_INPUT_BYTES + 1))
            with self.assertRaises(ValueError):
                module.load_bounded(path)

    def test_wrong_key_epoch_rejects(self):
        self.trust["owners"][0]["key_epoch"] = 2
        with self.assertRaises(ValueError):
            self.run_reconcile()

    def test_duplicate_json_field_rejects(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            path = Path(temporary) / "duplicate"
            path.write_text('{"state":"pending","state":"completed"}')
            with self.assertRaises(ValueError):
                module.load_bounded(path)

    def test_float_rejects(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            path = Path(temporary) / "float"
            path.write_text('{"epoch":1.0}')
            with self.assertRaises(ValueError):
                module.load_bounded(path)

    def test_symlink_rejects(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            path = Path(temporary) / "source"
            path.write_text('{}')
            alias = Path(temporary) / "alias"
            alias.symlink_to(path)
            with self.assertRaises((OSError, ValueError)):
                module.load_bounded(alias)

    def test_intermediate_symlink_rejects(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary).resolve()
            real = root / "real"
            real.mkdir()
            source = real / "source"
            source.write_text('{}')
            source.chmod(0o600)
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with self.assertRaises((OSError, ValueError)):
                module.load_bounded(alias / "source")

    def test_parent_replacement_during_read_rejects(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary).resolve()
            parent = root / "input"
            parent.mkdir()
            source = parent / "source"
            source.write_text('{}')
            source.chmod(0o600)
            retained = root / "retained-input"
            replaced = False
            real_stat = module.os.stat

            def replace_before_parent_recheck(path, *args, **kwargs):
                nonlocal replaced
                if not replaced and path == source.name and kwargs.get("dir_fd") is not None:
                    replaced = True
                    parent.rename(retained)
                    parent.mkdir()
                    replacement = parent / source.name
                    replacement.write_text('{}')
                    replacement.chmod(0o600)
                return real_stat(path, *args, **kwargs)

            with mock.patch.object(module.os, "stat", side_effect=replace_before_parent_recheck):
                with self.assertRaisesRegex(ValueError, "parent directory"):
                    module.load_bounded(source)


if __name__ == "__main__":
    unittest.main()
