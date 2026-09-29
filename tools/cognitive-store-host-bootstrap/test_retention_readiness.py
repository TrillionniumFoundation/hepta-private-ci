#!/usr/bin/env python3
"""Real Ed25519 regressions for retention readiness; no pruning or publication."""
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
import retention_readiness as module


class RetentionReadinessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.now = int(time.time())
        self.coordinator = Ed25519PrivateKey.generate()
        self.segment_owner = Ed25519PrivateKey.generate()
        self.rebuild_owner = Ed25519PrivateKey.generate()

        def public(name, key):
            return {"signer_id": name, "key_epoch": 1, "revoked": False,
                    "public_key_hex": key.public_key().public_bytes_raw().hex()}

        self.trust = {
            "schema": "hepta.cognitive.lifecycle-trust.v1",
            "revision": 1,
            "valid_until": self.now + 600,
            "coordinator": public("coordinator", self.coordinator),
            "owners": [public("segment-owner", self.segment_owner),
                       public("rebuild-owner", self.rebuild_owner)],
        }
        first_manifest = "1" * 64
        self.plan = {
            "schema": module.PLAN_SCHEMA,
            "request_id": "retention-checkpoint-1",
            "owner_agent_id": "00000000-0000-4000-8000-00000000c059",
            "source_commit": "2" * 40,
            "source_tree": "3" * 40,
            "writer_generation": 9,
            "schema_sha256": "4" * 64,
            "current_cut_sha256": "5" * 64,
            "head_set_sha256": "6" * 64,
            "tombstone_frontier": 7,
            "source_frontier": 11,
            "fact_frontier": 13,
            "kg_frontier": 17,
            "policy_sha256": "7" * 64,
            "hold_state_sha256": "8" * 64,
            "pending_operations_sha256": "9" * 64,
            "predecessor_image_sha256": "a" * 64,
            "successor_image_sha256": "b" * 64,
            "successor_image_bytes": 4096,
            "rebuild_owner": "rebuild-owner",
            "created_at": self.now - 10,
            "expires_at": self.now + 300,
            "segments": [
                {
                    "segment_id": "segment-0",
                    "storage_owner": "segment-owner",
                    "ordinal": 0,
                    "first_key_sha256": "c" * 64,
                    "last_key_sha256": "d" * 64,
                    "row_count": 5,
                    "plaintext_sha256": "e" * 64,
                    "ciphertext_sha256": "f" * 64,
                    "manifest_sha256": first_manifest,
                    "predecessor_manifest_sha256": None,
                },
                {
                    "segment_id": "segment-1",
                    "storage_owner": "segment-owner",
                    "ordinal": 1,
                    "first_key_sha256": "0" * 63 + "1",
                    "last_key_sha256": "0" * 63 + "2",
                    "row_count": 3,
                    "plaintext_sha256": "0" * 63 + "3",
                    "ciphertext_sha256": "0" * 63 + "4",
                    "manifest_sha256": "0" * 63 + "5",
                    "predecessor_manifest_sha256": first_manifest,
                },
            ],
        }
        self.plan_envelope = self.sign(self.plan, "coordinator", self.coordinator)
        self.segment_receipts = []
        for index, segment in enumerate(self.plan["segments"]):
            payload = {
                "schema": module.SEGMENT_RECEIPT_SCHEMA,
                "plan_sha256": lifecycle.sha256(self.plan),
                "segment_id": segment["segment_id"],
                "storage_owner": segment["storage_owner"],
                "manifest_sha256": segment["manifest_sha256"],
                "ciphertext_sha256": segment["ciphertext_sha256"],
                "status": "completed",
                "method": "immutable_encrypted_segment",
                "observed_at": self.now,
                "evidence_sha256": format(100 + index, "064x")[-64:],
            }
            self.segment_receipts.append(self.sign(payload, "segment-owner", self.segment_owner))
        self.rebuild = self.sign(self.rebuild_payload(), "rebuild-owner", self.rebuild_owner)

    @staticmethod
    def sign(payload, name, key):
        envelope = {"payload": copy.deepcopy(payload), "signer_id": name, "key_epoch": 1}
        envelope["signature_hex"] = key.sign(lifecycle.signing_bytes(envelope)).hex()
        return envelope

    @staticmethod
    def write(path, value):
        path.write_bytes(lifecycle.canonical(value))
        path.chmod(0o600)

    def rebuild_payload(self):
        return {
            "schema": module.REBUILD_RECEIPT_SCHEMA,
            "plan_sha256": lifecycle.sha256(self.plan),
            "rebuild_owner": self.plan["rebuild_owner"],
            "owner_agent_id": self.plan["owner_agent_id"],
            "source_commit": self.plan["source_commit"],
            "source_tree": self.plan["source_tree"],
            "writer_generation": self.plan["writer_generation"],
            "schema_sha256": self.plan["schema_sha256"],
            "predecessor_image_sha256": self.plan["predecessor_image_sha256"],
            "successor_image_sha256": self.plan["successor_image_sha256"],
            "successor_image_bytes": self.plan["successor_image_bytes"],
            "before_cut_sha256": self.plan["current_cut_sha256"],
            "after_cut_sha256": self.plan["current_cut_sha256"],
            "head_set_sha256": self.plan["head_set_sha256"],
            "tombstone_frontier": self.plan["tombstone_frontier"],
            "source_frontier": self.plan["source_frontier"],
            "fact_frontier": self.plan["fact_frontier"],
            "kg_frontier": self.plan["kg_frontier"],
            "integrity_check": True,
            "foreign_key_check": True,
            "projection_check": True,
            "pending_operation_check": True,
            "published": False,
            "status": "completed",
            "observed_at": self.now,
            "evidence_sha256": "6" * 64,
        }

    def bundle(self):
        return {"segments": self.segment_receipts, "rebuild": self.rebuild}

    def reconcile(self):
        return module.reconcile(self.plan_envelope, self.bundle(), self.trust, self.now,
                                lifecycle.sha256(self.plan))

    def resign_plan_and_rebuild(self):
        self.plan_envelope = self.sign(self.plan, "coordinator", self.coordinator)
        self.rebuild = self.sign(self.rebuild_payload(), "rebuild-owner", self.rebuild_owner)

    def resign_segment(self, index, **changes):
        payload = {**self.segment_receipts[index]["payload"], **changes}
        self.segment_receipts[index] = self.sign(payload, "segment-owner", self.segment_owner)

    def resign_rebuild(self, **changes):
        payload = {**self.rebuild["payload"], **changes}
        self.rebuild = self.sign(payload, "rebuild-owner", self.rebuild_owner)

    def test_complete_readiness_never_publishes_prunes_or_erases(self):
        report = self.reconcile()
        self.assertEqual(report["result"], "retention_ready")
        self.assertTrue(report["all_required_owner_receipts_verified"])
        for field in ("successor_published", "hot_history_pruned", "predecessor_erased",
                      "physical_erasure_proved", "activation_authorized"):
            self.assertIs(report[field], False)

    def test_missing_segment_receipt_is_incomplete(self):
        self.segment_receipts.pop()
        report = self.reconcile()
        self.assertEqual(report["result"], "incomplete")
        self.assertIn("missing", {row["status"] for row in report["segments"]})

    def test_pending_segment_is_incomplete(self):
        self.resign_segment(0, status="pending", method="upload_pending")
        self.assertEqual(self.reconcile()["result"], "incomplete")

    def test_wrong_completed_segment_method_rejects(self):
        self.resign_segment(0, method="ordinary_copy")
        with self.assertRaisesRegex(ValueError, "immutable encrypted"):
            self.reconcile()

    def test_broken_segment_chain_rejects(self):
        self.plan["segments"][1]["predecessor_manifest_sha256"] = "f" * 64
        self.resign_plan_and_rebuild()
        with self.assertRaisesRegex(ValueError, "chain"):
            self.reconcile()

    def test_reordered_segment_ordinal_rejects(self):
        self.plan["segments"][1]["ordinal"] = 2
        self.resign_plan_and_rebuild()
        with self.assertRaisesRegex(ValueError, "ordinal"):
            self.reconcile()

    def test_duplicate_segment_identity_rejects(self):
        self.plan["segments"][1]["segment_id"] = self.plan["segments"][0]["segment_id"]
        self.resign_plan_and_rebuild()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.reconcile()

    def test_duplicate_segment_digest_rejects(self):
        self.plan["segments"][1]["ciphertext_sha256"] = self.plan["segments"][0]["manifest_sha256"]
        self.resign_plan_and_rebuild()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.reconcile()

    def test_coordinator_cannot_own_segment(self):
        self.plan["segments"][0]["storage_owner"] = "coordinator"
        self.resign_plan_and_rebuild()
        with self.assertRaisesRegex(ValueError, "independent"):
            self.reconcile()

    def test_wrong_rebuild_signer_rejects(self):
        self.rebuild = self.sign(self.rebuild["payload"], "segment-owner", self.segment_owner)
        with self.assertRaisesRegex(ValueError, "planned owner"):
            self.reconcile()

    def test_rebuild_must_preserve_exact_cut(self):
        self.resign_rebuild(after_cut_sha256="f" * 64)
        with self.assertRaisesRegex(ValueError, "semantic cut"):
            self.reconcile()

    def test_readiness_receipt_cannot_publish_successor(self):
        self.resign_rebuild(published=True)
        with self.assertRaisesRegex(ValueError, "must not publish"):
            self.reconcile()

    def test_failed_integrity_check_rejects_completed_rebuild(self):
        self.resign_rebuild(integrity_check=False)
        with self.assertRaisesRegex(ValueError, "oracle check"):
            self.reconcile()

    def test_successor_must_be_distinct_image(self):
        self.plan["successor_image_sha256"] = self.plan["predecessor_image_sha256"]
        self.resign_plan_and_rebuild()
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.reconcile()

    def test_rebuild_source_identity_mismatch_rejects(self):
        self.resign_rebuild(source_tree="f" * 40)
        with self.assertRaisesRegex(ValueError, "source_tree"):
            self.reconcile()

    def test_rebuild_frontier_mismatch_rejects(self):
        self.resign_rebuild(tombstone_frontier=self.plan["tombstone_frontier"] + 1)
        with self.assertRaisesRegex(ValueError, "tombstone_frontier"):
            self.reconcile()

    def test_expired_plan_rejects(self):
        self.plan["expires_at"] = self.now
        self.resign_plan_and_rebuild()
        with self.assertRaisesRegex(ValueError, "expired"):
            self.reconcile()

    def test_wrong_requested_plan_digest_rejects(self):
        with self.assertRaisesRegex(ValueError, "requested"):
            module.reconcile(self.plan_envelope, self.bundle(), self.trust, self.now, "f" * 64)

    def test_revoked_storage_owner_rejects(self):
        self.trust["owners"][0]["revoked"] = True
        with self.assertRaises(ValueError):
            self.reconcile()

    def test_oversized_successor_rejects(self):
        self.plan["successor_image_bytes"] = module.MAX_IMAGE_BYTES + 1
        self.resign_plan_and_rebuild()
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.reconcile()

    def test_cli_complete_and_incomplete_exit_codes(self):
        trust_path = self.root / "trust.json"
        plan_path = self.root / "plan.json"
        receipts_path = self.root / "receipts.json"
        self.write(trust_path, self.trust)
        self.write(plan_path, self.plan_envelope)
        self.write(receipts_path, self.bundle())
        command = [sys.executable, str(Path(module.__file__)), "--plan", str(plan_path),
                   "--receipts", str(receipts_path), "--trusted-owners", str(trust_path),
                   "--expected-plan-sha256", lifecycle.sha256(self.plan),
                   "--expected-trust-sha256", lifecycle.sha256(self.trust)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "retention_ready")
        bundle = self.bundle()
        bundle["segments"] = bundle["segments"][:-1]
        self.write(receipts_path, bundle)
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "incomplete")

    def test_final_trust_change_rejects(self):
        trust_path = self.root / "trust.json"
        plan_path = self.root / "plan.json"
        receipts_path = self.root / "receipts.json"
        self.write(trust_path, self.trust)
        self.write(plan_path, self.plan_envelope)
        self.write(receipts_path, self.bundle())
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
