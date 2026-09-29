#!/usr/bin/env python3
"""Real Ed25519 regressions for external acceptance evidence; no deployment effects."""
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

import acceptance_governance as module
import lifecycle


class AcceptanceGovernanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.now = int(time.time())
        self.coordinator = Ed25519PrivateKey.generate()
        self.reviewers = {
            role: Ed25519PrivateKey.generate() for role in module.REQUIRED_ROLES
        }
        self.other = Ed25519PrivateKey.generate()

        def public(name, key):
            return {"signer_id": name, "key_epoch": 1, "revoked": False,
                    "public_key_hex": key.public_key().public_bytes_raw().hex()}

        self.role_reviewers = {role: f"reviewer-{index}"
                               for index, role in enumerate(module.REQUIRED_ROLES)}
        owners = [public(self.role_reviewers[role], self.reviewers[role])
                  for role in module.REQUIRED_ROLES]
        owners.append(public("other-reviewer", self.other))
        self.trust = {
            "schema": "hepta.cognitive.lifecycle-trust.v1",
            "revision": 1,
            "valid_until": self.now + 600,
            "coordinator": public("coordinator", self.coordinator),
            "owners": owners,
        }
        self.plan = {
            "schema": module.PLAN_SCHEMA,
            "request_id": "acceptance-1",
            "owner_agent_id": "00000000-0000-4000-8000-00000000c059",
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "source_head_manifest_sha256": "3" * 64,
            "base_merge_manifest_sha256": "4" * 64,
            "host_qualification_report_sha256": "5" * 64,
            "retention_readiness_report_sha256": "6" * 64,
            "lifecycle_reconciliation_report_sha256": "7" * 64,
            "created_at": self.now - 10,
            "expires_at": self.now + 300,
            "roles": [
                {"role": role, "reviewer": self.role_reviewers[role],
                 "criteria_sha256": format(100 + index, "064x")[-64:]}
                for index, role in enumerate(module.REQUIRED_ROLES)
            ],
        }
        self.plan_envelope = self.sign(self.plan, "coordinator", self.coordinator)
        self.receipts = []
        for index, role in enumerate(module.REQUIRED_ROLES):
            payload = {
                "schema": module.RECEIPT_SCHEMA,
                "plan_sha256": lifecycle.sha256(self.plan),
                "role": role,
                "reviewer": self.role_reviewers[role],
                "criteria_sha256": self.plan["roles"][index]["criteria_sha256"],
                "owner_agent_id": self.plan["owner_agent_id"],
                "source_commit": self.plan["source_commit"],
                "source_tree": self.plan["source_tree"],
                **{field: self.plan[field] for field in module.EVIDENCE_FIELDS},
                "decision": "approved",
                "observed_at": self.now,
                "review_sha256": format(200 + index, "064x")[-64:],
            }
            reviewer = self.role_reviewers[role]
            self.receipts.append(self.sign(payload, reviewer, self.reviewers[role]))

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
        role = self.receipts[index]["payload"]["role"]
        reviewer = self.role_reviewers[role]
        self.receipts[index] = self.sign(payload, reviewer, self.reviewers[role])

    def test_complete_external_approval_set_never_performs_effects(self):
        report = self.reconcile()
        self.assertEqual(report["result"], "external_approval_set_verified")
        self.assertTrue(report["all_required_independent_approvals_verified"])
        self.assertTrue(report["independent_acceptance_verified"])
        for field in ("authorized_effects", "activation_performed", "release_performed"):
            self.assertIs(report[field], False)

    def test_missing_receipt_is_incomplete(self):
        self.receipts.pop()
        report = self.reconcile()
        self.assertEqual(report["result"], "incomplete")
        self.assertIn("missing", {row["decision"] for row in report["roles"]})

    def test_pending_receipt_is_incomplete(self):
        self.resign_receipt(0, decision="pending")
        self.assertEqual(self.reconcile()["result"], "incomplete")

    def test_rejected_receipt_is_incomplete(self):
        self.resign_receipt(0, decision="rejected")
        self.assertEqual(self.reconcile()["result"], "incomplete")

    def test_duplicate_receipt_rejects(self):
        self.receipts[-1] = self.receipts[0]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.reconcile()

    def test_missing_plan_role_rejects(self):
        self.plan["roles"].pop()
        self.resign_plan()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.reconcile()

    def test_duplicate_plan_role_rejects(self):
        self.plan["roles"][-1] = copy.deepcopy(self.plan["roles"][0])
        self.resign_plan()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.reconcile()

    def test_roles_require_distinct_reviewers(self):
        self.plan["roles"][1]["reviewer"] = self.plan["roles"][0]["reviewer"]
        self.resign_plan()
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.reconcile()

    def test_coordinator_cannot_review(self):
        self.plan["roles"][0]["reviewer"] = "coordinator"
        self.resign_plan()
        with self.assertRaisesRegex(ValueError, "independently trusted"):
            self.reconcile()

    def test_unplanned_reviewer_signature_rejects(self):
        payload = {**self.receipts[0]["payload"], "reviewer": "other-reviewer"}
        self.receipts[0] = self.sign(payload, "other-reviewer", self.other)
        with self.assertRaises(ValueError):
            self.reconcile()

    def test_criteria_mismatch_rejects(self):
        self.resign_receipt(0, criteria_sha256="f" * 64)
        with self.assertRaisesRegex(ValueError, "criteria"):
            self.reconcile()

    def test_source_identity_mismatch_rejects(self):
        self.resign_receipt(0, source_tree="f" * 40)
        with self.assertRaisesRegex(ValueError, "source_tree"):
            self.reconcile()

    def test_each_evidence_digest_is_bound(self):
        for field in module.EVIDENCE_FIELDS:
            with self.subTest(field=field):
                original = self.receipts[0]
                self.resign_receipt(0, **{field: "f" * 64})
                with self.assertRaisesRegex(ValueError, field):
                    self.reconcile()
                self.receipts[0] = original

    def test_expired_plan_rejects(self):
        self.plan["expires_at"] = self.now
        self.resign_plan()
        with self.assertRaisesRegex(ValueError, "expired"):
            self.reconcile()

    def test_future_receipt_rejects(self):
        self.resign_receipt(0, observed_at=self.now + 1)
        with self.assertRaisesRegex(ValueError, "future"):
            self.reconcile()

    def test_review_approval_time_order_cannot_regress(self):
        self.resign_receipt(1, observed_at=self.now - 1)
        with self.assertRaisesRegex(ValueError, "review order"):
            self.reconcile()

    def test_revoked_reviewer_rejects(self):
        self.trust["owners"][0]["revoked"] = True
        with self.assertRaises(ValueError):
            self.reconcile()

    def test_wrong_requested_plan_digest_rejects(self):
        with self.assertRaisesRegex(ValueError, "requested"):
            module.reconcile(self.plan_envelope, self.receipts, self.trust, self.now, "f" * 64)

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
        self.assertEqual(json.loads(result.stdout)["result"], "external_approval_set_verified")
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
