#!/usr/bin/env python3
"""Real Ed25519 regressions for selected-host receipt verification; no host effects."""
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

import host_qualification as module
import lifecycle


class HostQualificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.now = int(time.time())
        self.coordinator = Ed25519PrivateKey.generate()
        self.executor = Ed25519PrivateKey.generate()
        self.other = Ed25519PrivateKey.generate()

        def public(name, key):
            return {"signer_id": name, "key_epoch": 1, "revoked": False,
                    "public_key_hex": key.public_key().public_bytes_raw().hex()}

        self.trust = {
            "schema": "hepta.cognitive.lifecycle-trust.v1",
            "revision": 1,
            "valid_until": self.now + 600,
            "coordinator": public("coordinator", self.coordinator),
            "owners": [public("host-executor", self.executor), public("other-owner", self.other)],
        }
        self.plan = {
            "schema": module.PLAN_SCHEMA,
            "request_id": "host-qualification-1",
            "owner_agent_id": "00000000-0000-4000-8000-00000000c059",
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "writer_generation": 7,
            "authority_grant_sha256": "3" * 64,
            "recovery_anchor": {
                "profile": "hepta:cognitive:exact-current-cut:v1",
                "owner_agent_id": "00000000-0000-4000-8000-00000000c059",
                "schema_digest": "4" * 64,
                "state_digest": "5" * 64,
            },
            "witness_custody_sha256": "6" * 64,
            "host_identity_sha256": "7" * 64,
            "filesystem_identity_sha256": "8" * 64,
            "slo_profile_sha256": "9" * 64,
            "created_at": self.now - 10,
            "expires_at": self.now + 300,
            "steps": [
                {"step": name, "executor": "host-executor",
                 "evidence_profile_sha256": format(index + 10, "064x")[-64:]}
                for index, name in enumerate(module.STEP_DISPOSITIONS)
            ],
        }
        self.plan_envelope = self.sign(self.plan, "coordinator", self.coordinator)
        self.receipts = []
        for index, name in enumerate(module.STEP_DISPOSITIONS):
            before = format(100 + index, "064x")[-64:]
            after = format(200 + index, "064x")[-64:] if name in module.ADVANCING_STEPS else before
            payload = {
                "schema": module.RECEIPT_SCHEMA,
                "plan_sha256": lifecycle.sha256(self.plan),
                "step": name,
                "executor": "host-executor",
                "source_commit": self.plan["source_commit"],
                "source_tree": self.plan["source_tree"],
                "writer_generation": self.plan["writer_generation"],
                "host_identity_sha256": self.plan["host_identity_sha256"],
                "filesystem_identity_sha256": self.plan["filesystem_identity_sha256"],
                "before_cut_sha256": before,
                "after_cut_sha256": after,
                "status": "completed",
                "disposition": module.STEP_DISPOSITIONS[name],
                "observed_at": self.now,
                "evidence_sha256": format(300 + index, "064x")[-64:],
                "metrics_sha256": format(400 + index, "064x")[-64:],
            }
            self.receipts.append(self.sign(payload, "host-executor", self.executor))

    @staticmethod
    def sign(payload, name, key):
        envelope = {"payload": copy.deepcopy(payload), "signer_id": name, "key_epoch": 1}
        envelope["signature_hex"] = key.sign(lifecycle.signing_bytes(envelope)).hex()
        return envelope

    @staticmethod
    def write(path, value):
        path.write_bytes(lifecycle.canonical(value))
        path.chmod(0o600)

    def reconcile(self):
        return module.reconcile(self.plan_envelope, self.receipts, self.trust, self.now,
                                lifecycle.sha256(self.plan))

    def resign_plan(self):
        self.plan_envelope = self.sign(self.plan, "coordinator", self.coordinator)

    def resign_receipt(self, index, **changes):
        payload = {**self.receipts[index]["payload"], **changes}
        self.receipts[index] = self.sign(payload, "host-executor", self.executor)

    def test_complete_owner_attestation_never_self_qualifies_or_activates(self):
        report = self.reconcile()
        self.assertEqual(report["result"], "owner_attested_complete")
        self.assertTrue(report["all_required_owner_receipts_verified"])
        for field in ("target_host_qualified", "slo_accepted", "activation_authorized",
                      "release_authorized"):
            self.assertIs(report[field], False)

    def test_missing_receipt_is_incomplete(self):
        self.receipts.pop()
        report = self.reconcile()
        self.assertEqual(report["result"], "incomplete")
        self.assertIn("missing", {row["status"] for row in report["steps"]})

    def test_pending_receipt_is_incomplete(self):
        self.resign_receipt(0, status="pending", disposition="not_observed")
        self.assertEqual(self.reconcile()["result"], "incomplete")

    def test_wrong_completed_disposition_rejects(self):
        self.resign_receipt(0, disposition="ordinary_success")
        with self.assertRaisesRegex(ValueError, "wrong disposition"):
            self.reconcile()

    def test_canary_must_advance_cut(self):
        index = list(module.STEP_DISPOSITIONS).index("canary")
        before = self.receipts[index]["payload"]["before_cut_sha256"]
        self.resign_receipt(index, after_cut_sha256=before)
        with self.assertRaisesRegex(ValueError, "did not advance"):
            self.reconcile()

    def test_nonadvancing_step_cannot_change_cut(self):
        self.resign_receipt(0, after_cut_sha256="f" * 64)
        with self.assertRaisesRegex(ValueError, "changed the semantic cut"):
            self.reconcile()

    def test_receipt_source_identity_mismatch_rejects(self):
        self.resign_receipt(0, source_commit="a" * 40)
        with self.assertRaisesRegex(ValueError, "source_commit"):
            self.reconcile()

    def test_receipt_signed_by_unplanned_owner_rejects(self):
        payload = {**self.receipts[0]["payload"], "executor": "other-owner"}
        self.receipts[0] = self.sign(payload, "other-owner", self.other)
        with self.assertRaises(ValueError):
            self.reconcile()

    def test_duplicate_receipt_rejects(self):
        self.receipts[-1] = self.receipts[0]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.reconcile()

    def test_missing_plan_step_rejects(self):
        self.plan["steps"].pop()
        self.resign_plan()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.reconcile()

    def test_duplicate_plan_step_rejects(self):
        self.plan["steps"][-1] = copy.deepcopy(self.plan["steps"][0])
        self.resign_plan()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.reconcile()

    def test_coordinator_cannot_be_step_executor(self):
        self.plan["steps"][0]["executor"] = "coordinator"
        self.resign_plan()
        with self.assertRaisesRegex(ValueError, "independent"):
            self.reconcile()

    def test_expired_plan_rejects(self):
        self.plan["expires_at"] = self.now
        self.resign_plan()
        with self.assertRaisesRegex(ValueError, "expired"):
            self.reconcile()

    def test_future_receipt_rejects(self):
        self.resign_receipt(0, observed_at=self.now + 1)
        with self.assertRaisesRegex(ValueError, "future"):
            self.reconcile()

    def test_wrong_requested_plan_digest_rejects(self):
        with self.assertRaisesRegex(ValueError, "requested"):
            module.reconcile(self.plan_envelope, self.receipts, self.trust, self.now, "f" * 64)

    def test_revoked_executor_rejects(self):
        self.trust["owners"][0]["revoked"] = True
        with self.assertRaises(ValueError):
            self.reconcile()

    def test_invalid_git_object_format_rejects(self):
        self.plan["source_commit"] = "not-a-git-object"
        self.resign_plan()
        with self.assertRaisesRegex(ValueError, "source commit"):
            self.reconcile()

    def test_cli_complete_and_incomplete_exit_codes(self):
        trust_path = self.root / "trust.json"
        plan_path = self.root / "plan.json"
        receipts_path = self.root / "receipts.json"
        self.write(trust_path, self.trust)
        self.write(plan_path, self.plan_envelope)
        self.write(receipts_path, self.receipts)
        command = [sys.executable, str(Path(module.__file__)), "--plan", str(plan_path),
                   "--receipts", str(receipts_path), "--trusted-owners", str(trust_path),
                   "--expected-plan-sha256", lifecycle.sha256(self.plan),
                   "--expected-trust-sha256", lifecycle.sha256(self.trust)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "owner_attested_complete")
        self.write(receipts_path, self.receipts[:-1])
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "incomplete")

    def test_final_trust_change_rejects(self):
        trust_path = self.root / "trust.json"
        plan_path = self.root / "plan.json"
        receipts_path = self.root / "receipts.json"
        self.write(trust_path, self.trust)
        self.write(plan_path, self.plan_envelope)
        self.write(receipts_path, self.receipts)
        original = module.reconcile
        changed = copy.deepcopy(self.trust)
        changed["revision"] = 2
        def verify_then_change(*args):
            report = original(*args)
            self.write(trust_path, changed)
            return report
        with mock.patch.object(module, "reconcile", side_effect=verify_then_change):
            with self.assertRaisesRegex(ValueError, "trust changed"):
                module.reconcile_files(plan_path, receipts_path, trust_path,
                                       lifecycle.sha256(self.plan), lifecycle.sha256(self.trust))


if __name__ == "__main__":
    unittest.main()
