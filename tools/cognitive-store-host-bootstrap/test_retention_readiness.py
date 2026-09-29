#!/usr/bin/env python3
"""Real Ed25519 regressions for retention readiness; no effects are executed."""
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
            "schema": "hepta.cognitive.lifecycle-trust.v1", "revision": 1,
            "valid_until": self.now + 600,
            "coordinator": public("coordinator", self.coordinator),
            "owners": [public("segment-owner", self.segment_owner),
                       public("rebuild-owner", self.rebuild_owner)],
        }
        first = "1" * 64
        self.plan = {
            "schema": module.PLAN_SCHEMA, "request_id": "retention-checkpoint-1",
            "owner_agent_id": "00000000-0000-4000-8000-00000000c059",
            "source_commit": "2" * 40, "source_tree": "3" * 40,
            "writer_generation": 9, "schema_sha256": "4" * 64,
            "current_cut_sha256": "5" * 64, "head_set_sha256": "6" * 64,
            "tombstone_frontier": 7, "source_frontier": 11,
            "fact_frontier": 13, "kg_frontier": 17,
            "policy_sha256": "7" * 64, "hold_state_sha256": "8" * 64,
            "pending_operations_sha256": "9" * 64,
            "predecessor_image_sha256": "a" * 64,
            "successor_image_sha256": "b" * 64, "successor_image_bytes": 4096,
            "rebuild_owner": "rebuild-owner", "created_at": self.now - 10,
            "expires_at": self.now + 300,
            "segments": [
                {"segment_id": "segment-0", "storage_owner": "segment-owner", "ordinal": 0,
                 "first_key_sha256": "c" * 64, "last_key_sha256": "d" * 64,
                 "row_count": 5, "plaintext_sha256": "e" * 64,
                 "ciphertext_sha256": "f" * 64, "manifest_sha256": first,
                 "predecessor_manifest_sha256": None},
                {"segment_id": "segment-1", "storage_owner": "segment-owner", "ordinal": 1,
                 "first_key_sha256": "0" * 63 + "1", "last_key_sha256": "0" * 63 + "2",
                 "row_count": 3, "plaintext_sha256": "0" * 63 + "3",
                 "ciphertext_sha256": "0" * 63 + "4", "manifest_sha256": "0" * 63 + "5",
                 "predecessor_manifest_sha256": first},
            ],
        }
        self.plan.update({
            "segment_set_sha256": lifecycle.sha256(self.plan["segments"]),
            "segment_count": 2, "segment_row_count": 8,
            "first_segment_manifest_sha256": first,
            "last_segment_manifest_sha256": self.plan["segments"][-1]["manifest_sha256"],
        })
        self.plan_envelope = self.sign(self.plan, "coordinator", self.coordinator)
        self.segment_receipts = [
            self.sign({
                "schema": module.SEGMENT_RECEIPT_SCHEMA,
                "plan_sha256": lifecycle.sha256(self.plan),
                **{key: segment[key] for key in ("segment_id", "storage_owner", "ordinal",
                    "row_count", "plaintext_sha256", "manifest_sha256", "ciphertext_sha256",
                    "predecessor_manifest_sha256")},
                "status": "completed", "method": "immutable_encrypted_segment",
                "observed_at": self.now, "evidence_sha256": format(100 + index, "064x")[-64:],
            }, "segment-owner", self.segment_owner)
            for index, segment in enumerate(self.plan["segments"])
        ]
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
        copied = ("rebuild_owner", "owner_agent_id", "source_commit", "source_tree",
                  "writer_generation", "schema_sha256", "predecessor_image_sha256",
                  "successor_image_sha256", "successor_image_bytes", "head_set_sha256",
                  "tombstone_frontier", "source_frontier", "fact_frontier", "kg_frontier",
                  "segment_set_sha256", "segment_count", "segment_row_count",
                  "first_segment_manifest_sha256", "last_segment_manifest_sha256")
        return {
            "schema": module.REBUILD_RECEIPT_SCHEMA,
            "plan_sha256": lifecycle.sha256(self.plan), **{key: self.plan[key] for key in copied},
            "before_cut_sha256": self.plan["current_cut_sha256"],
            "after_cut_sha256": self.plan["current_cut_sha256"],
            "segments_resolved": True, "integrity_check": True, "foreign_key_check": True,
            "projection_check": True, "pending_operation_check": True, "published": False,
            "status": "completed", "observed_at": self.now, "evidence_sha256": "6" * 64,
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
        self.segment_receipts[index] = self.sign(
            {**self.segment_receipts[index]["payload"], **changes},
            "segment-owner", self.segment_owner)

    def resign_rebuild(self, **changes):
        self.rebuild = self.sign({**self.rebuild["payload"], **changes},
                                 "rebuild-owner", self.rebuild_owner)

    def test_complete_readiness_never_performs_effects(self):
        report = self.reconcile()
        self.assertEqual((report["result"], report["segment_count"], report["segment_row_count"]),
                         ("retention_ready", 2, 8))
        for field in ("successor_published", "hot_history_pruned", "predecessor_erased",
                      "physical_erasure_proved", "activation_authorized"):
            self.assertIs(report[field], False)

    def test_missing_segment_receipt_is_incomplete(self):
        self.segment_receipts.pop()
        self.assertEqual(self.reconcile()["result"], "incomplete")

    def test_pending_segment_is_incomplete(self):
        self.resign_segment(0, status="pending", method="upload_pending")
        self.assertEqual(self.reconcile()["result"], "incomplete")

    def test_rebuild_owner_is_independent(self):
        self.plan["rebuild_owner"] = "segment-owner"
        self.plan_envelope = self.sign(self.plan, "coordinator", self.coordinator)
        self.rebuild = self.sign(self.rebuild_payload(), "segment-owner", self.segment_owner)
        with self.assertRaisesRegex(ValueError, "independent"):
            self.reconcile()

    def test_completed_rebuild_follows_segment_observations(self):
        self.resign_rebuild(observed_at=self.now - 1)
        with self.assertRaisesRegex(ValueError, "predates"):
            self.reconcile()

    def test_wrong_rebuild_signer_rejects(self):
        self.rebuild = self.sign(self.rebuild["payload"], "segment-owner", self.segment_owner)
        with self.assertRaisesRegex(ValueError, "planned owner"):
            self.reconcile()

    def test_wrong_requested_plan_digest_rejects(self):
        with self.assertRaisesRegex(ValueError, "requested"):
            module.reconcile(self.plan_envelope, self.bundle(), self.trust, self.now, "f" * 64)

    def test_revoked_storage_owner_rejects(self):
        self.trust["owners"][0]["revoked"] = True
        with self.assertRaises(ValueError):
            self.reconcile()

    def test_cli_complete_and_incomplete_exit_codes(self):
        trust, plan, receipts = (self.root / name for name in ("trust.json", "plan.json", "receipts.json"))
        self.write(trust, self.trust); self.write(plan, self.plan_envelope); self.write(receipts, self.bundle())
        command = [sys.executable, str(Path(module.__file__)), "--plan", str(plan),
                   "--receipts", str(receipts), "--trusted-owners", str(trust),
                   "--expected-plan-sha256", lifecycle.sha256(self.plan),
                   "--expected-trust-sha256", lifecycle.sha256(self.trust)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        bundle = self.bundle(); bundle["segments"] = bundle["segments"][:-1]; self.write(receipts, bundle)
        self.assertEqual(subprocess.run(command, capture_output=True, text=True,
                                        timeout=30, check=False).returncode, 2)

    def test_final_trust_change_rejects(self):
        trust, plan, receipts = (self.root / name for name in ("trust.json", "plan.json", "receipts.json"))
        self.write(trust, self.trust); self.write(plan, self.plan_envelope); self.write(receipts, self.bundle())
        changed = copy.deepcopy(self.trust); changed["revision"] = 2
        original = module.reconcile
        def verify_then_change(*args):
            report = original(*args); self.write(trust, changed); return report
        with mock.patch.object(module, "reconcile", side_effect=verify_then_change):
            with self.assertRaisesRegex(ValueError, "trust changed"):
                module.reconcile_files(plan, receipts, trust,
                                       lifecycle.sha256(self.plan), lifecycle.sha256(self.trust))


def _plan_case(name, mutate, pattern):
    def test(self):
        mutate(self)
        self.resign_plan_and_rebuild()
        with self.assertRaisesRegex(ValueError, pattern):
            self.reconcile()
    setattr(RetentionReadinessTests, "test_" + name, test)


def _segment_case(name, changes, pattern):
    def test(self):
        self.resign_segment(0, **changes)
        with self.assertRaisesRegex(ValueError, pattern):
            self.reconcile()
    setattr(RetentionReadinessTests, "test_" + name, test)


def _rebuild_case(name, changes, pattern):
    def test(self):
        self.resign_rebuild(**changes)
        with self.assertRaisesRegex(ValueError, pattern):
            self.reconcile()
    setattr(RetentionReadinessTests, "test_" + name, test)


_plan_case("segment_set_digest", lambda s: s.plan.__setitem__("segment_set_sha256", "f" * 64), "segment-set")
_plan_case("segment_count", lambda s: s.plan.__setitem__("segment_count", 3), "segment count")
_plan_case("segment_row_count", lambda s: s.plan.__setitem__("segment_row_count", 9), "row count")
_plan_case("segment_endpoints", lambda s: s.plan.__setitem__("last_segment_manifest_sha256", "f" * 64), "endpoints")
_plan_case("broken_chain", lambda s: s.plan["segments"][1].__setitem__("predecessor_manifest_sha256", "f" * 64), "chain")
_plan_case("reordered_ordinal", lambda s: s.plan["segments"][1].__setitem__("ordinal", 2), "ordinal")
_plan_case("duplicate_identity", lambda s: s.plan["segments"][1].__setitem__("segment_id", s.plan["segments"][0]["segment_id"]), "duplicate")
_plan_case("duplicate_digest", lambda s: s.plan["segments"][1].__setitem__("ciphertext_sha256", s.plan["segments"][0]["manifest_sha256"]), "duplicate")
_plan_case("coordinator_segment", lambda s: s.plan["segments"][0].__setitem__("storage_owner", "coordinator"), "independent")
_plan_case("same_successor", lambda s: s.plan.__setitem__("successor_image_sha256", s.plan["predecessor_image_sha256"]), "distinct")
_plan_case("expired_plan", lambda s: s.plan.__setitem__("expires_at", s.now), "expired")
_plan_case("oversized_successor", lambda s: s.plan.__setitem__("successor_image_bytes", module.MAX_IMAGE_BYTES + 1), "exceeds")
_segment_case("wrong_segment_method", {"method": "ordinary_copy"}, "immutable encrypted")
_segment_case("segment_plaintext", {"plaintext_sha256": "f" * 64}, "plaintext_sha256")
_segment_case("segment_rows", {"row_count": 999}, "row_count")
_rebuild_case("rebuild_segment_set", {"segment_set_sha256": "f" * 64}, "segment_set_sha256")
_rebuild_case("unresolved_segments", {"segments_resolved": False}, "oracle check")
_rebuild_case("changed_cut", {"after_cut_sha256": "f" * 64}, "semantic cut")
_rebuild_case("published_successor", {"published": True}, "must not publish")
_rebuild_case("failed_integrity", {"integrity_check": False}, "oracle check")
_rebuild_case("source_identity", {"source_tree": "f" * 40}, "source_tree")
_rebuild_case("frontier", {"tombstone_frontier": 8}, "tombstone_frontier")


if __name__ == "__main__":
    unittest.main()
