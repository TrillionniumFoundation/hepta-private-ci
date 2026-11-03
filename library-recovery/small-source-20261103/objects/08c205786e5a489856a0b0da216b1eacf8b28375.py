#!/usr/bin/env python3
"""Synthetic signing fixtures for the independent OFFLINE verifier only.

No fixture key/receipt in this test is a production owner, live readback,
qualified observer signature, or host attestation.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from verify_transcript import (
    INTENT_SCHEMA, SIGN_PREFIX, STEP_NAMES, TRANSCRIPT_PREFIX, TRUST_SCHEMA,
    VerificationError, canonical, key_is_weak, main, sha256, verify_transcript,
)


def sample_evidence():
    keys = [Ed25519PrivateKey.from_private_bytes(bytes([i + 1]) * 32) for i in range(4)]
    pub = [list(k.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)) for k in keys]
    plan = {
        "splitId": "synthetic-offline-test-only", "scopeDigest": "11" * 32,
        "parentGeneration": 7, "childGeneration": 8, "parentArtifactDigest": "22" * 32,
        "childArtifactDigest": "33" * 32, "nduSnapshotDigest": "44" * 32,
        "routeFenceDigest": "55" * 32,
        "ownerIds": ["synthetic-cas", "synthetic-state", "synthetic-cns", "synthetic-supervisor"],
    }
    plan_digest = sha256(canonical(plan))
    trust = {
        "schema": TRUST_SCHEMA, "planDigest": plan_digest,
        "ownerIds": plan["ownerIds"], "verifyingKeys": pub,
    }
    predecessor = plan_digest
    receipts = []
    for i in range(4):
        intent = {
            "schema": INTENT_SCHEMA, "planDigest": plan_digest, "step": STEP_NAMES[i],
            "ownerId": plan["ownerIds"][i],
            "idempotencyKey": sha256(f"{INTENT_SCHEMA}\0{plan_digest}\0{i}\0{predecessor}".encode()),
            "previousReceiptDigest": predecessor,
        }
        effect = b"synthetic-test-effect-" + str(i).encode()
        receipt = {
            "intent": intent, "ownerSequence": i + 1,
            "outputDigest": sha256(effect), "ownerReceiptBytes": list(effect),
            "ownerSignatureBytes": [], "receiptDigest": "",
        }
        signed = SIGN_PREFIX + canonical(receipt)
        receipt["ownerSignatureBytes"] = list(keys[i].sign(signed))
        receipt["receiptDigest"] = sha256(canonical(receipt))
        receipts.append(receipt)
        predecessor = receipt["receiptDigest"]
    transcript = {
        "plan": plan, "receipts": receipts,
        "transcriptDigest": sha256(TRANSCRIPT_PREFIX + canonical(plan) + canonical(receipts)),
    }
    return transcript, trust


class OfflineObserverTests(unittest.TestCase):
    def setUp(self):
        self.transcript, self.trust = sample_evidence()

    def succeeds(self):
        result = verify_transcript(self.transcript, self.trust)
        self.assertTrue(result["originalOwnerSignatureChainValid"])
        self.assertFalse(result["productionActivationAuthorized"])
        self.assertFalse(result["originalOwnerLiveReadbackVerified"])
        self.assertFalse(result["physicalSplitAuthorized"])

    def fails(self, mutate):
        t, p = copy.deepcopy((self.transcript, self.trust))
        mutate(t, p)
        with self.assertRaises(VerificationError):
            verify_transcript(t, p)

    def test_synthetic_four_step_positive(self):
        self.succeeds()

    def test_reordered_receipts_rejected(self):
        self.fails(lambda t, p: t["receipts"].reverse())

    def test_missing_step_rejected(self):
        self.fails(lambda t, p: t["receipts"].pop())

    def test_fake_fifth_step_rejected(self):
        self.fails(lambda t, p: t["receipts"].append(t["receipts"][3]))

    def test_child_generation_tamper_rejected(self):
        self.fails(lambda t, p: t["plan"].__setitem__("childGeneration", 9))

    def test_scope_tamper_rejected(self):
        self.fails(lambda t, p: t["plan"].__setitem__("scopeDigest", "ab"*32))

    def test_same_owner_ids_rejected(self):
        self.fails(lambda t, p: t["plan"]["ownerIds"].__setitem__(1, t["plan"]["ownerIds"][0]))

    def test_same_owner_keys_rejected(self):
        self.fails(lambda t, p: p["verifyingKeys"].__setitem__(1, p["verifyingKeys"][0]))

    def test_weak_ed25519_zero_key_rejected(self):
        self.fails(lambda t, p: p["verifyingKeys"].__setitem__(0, [0]*32))

    def test_known_identity_is_weak(self):
        self.assertTrue(key_is_weak(bytes([1] + [0]*31)))

    def test_invalid_owner_key_rejected(self):
        self.fails(lambda t, p: p["verifyingKeys"].__setitem__(0, [255]*32))

    def test_wrong_signer_rejected(self):
        self.fails(lambda t, p: p["verifyingKeys"].__setitem__(2, p["verifyingKeys"][1]))

    def test_signature_flip_rejected(self):
        self.fails(lambda t, p: t["receipts"][1]["ownerSignatureBytes"].__setitem__(0, 4))

    def test_noncanonical_signature_scalar_rejected(self):
        self.fails(lambda t, p: t["receipts"][0]["ownerSignatureBytes"].__setitem__(slice(32, 64), [255]*32))

    def test_weak_signature_r_rejected(self):
        self.fails(lambda t, p: t["receipts"][0]["ownerSignatureBytes"].__setitem__(slice(0, 32), [1]+[0]*31))

    def test_original_effect_mutation_rejected(self):
        self.fails(lambda t, p: t["receipts"][0]["ownerReceiptBytes"].__setitem__(0, 9))

    def test_output_digest_mutation_rejected(self):
        self.fails(lambda t, p: t["receipts"][2].__setitem__("outputDigest", "ab"*32))

    def test_record_digest_mutation_rejected(self):
        self.fails(lambda t, p: t["receipts"][2].__setitem__("receiptDigest", "ab"*32))

    def test_wrong_idempotency_rejected(self):
        self.fails(lambda t, p: t["receipts"][1]["intent"].__setitem__("idempotencyKey", "ab"*32))

    def test_wrong_previous_digest_rejected(self):
        self.fails(lambda t, p: t["receipts"][1]["intent"].__setitem__("previousReceiptDigest", "ab"*32))

    def test_wrong_sequence_rejected(self):
        self.fails(lambda t, p: t["receipts"][0].__setitem__("ownerSequence", 0))

    def test_replay_duplicate_step_rejected(self):
        self.fails(lambda t, p: t["receipts"].__setitem__(1, t["receipts"][0]))

    def test_unknown_receipt_field_rejected(self):
        self.fails(lambda t, p: t["receipts"][0].__setitem__("authorization", True))

    def test_boolean_byte_rejected(self):
        self.fails(lambda t, p: t["receipts"][0]["ownerReceiptBytes"].__setitem__(0, True))

    def test_large_receipt_rejected(self):
        self.fails(lambda t, p: t["receipts"][0].__setitem__("ownerReceiptBytes", [1]*32769))

    def test_transcript_digest_mutation_rejected(self):
        self.fails(lambda t, p: t.__setitem__("transcriptDigest", "ab"*32))

    def test_trust_plan_digest_rejected(self):
        self.fails(lambda t, p: p.__setitem__("planDigest", "ab"*32))

    def test_json_cli_with_out_of_band_trust_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tp = root / "trust.json"
            ts = root / "transcript.json"
            tp.write_bytes(canonical(self.trust))
            wrapper = {
                "schema": "hepta.learning.cell-split.execution-cli-result.v1",
                "action": "transcript", "completedSteps": 4, "complete": True,
                "receipt": None, "transcript": self.transcript,
                "productionActivationAuthorized": False,
            }
            ts.write_bytes(canonical(wrapper))
            rc = main(["--transcript", str(ts), "--trust-pins", str(tp),
                       "--trust-pins-sha256", sha256(tp.read_bytes())])
            self.assertEqual(rc, 0)
            rc = main(["--transcript", str(ts), "--trust-pins", str(tp),
                       "--trust-pins-sha256", "a"*64])
            self.assertEqual(rc, 2)

    def test_duplicate_json_keys_rejected(self):
        from verify_transcript import load_json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "double.json"
            path.write_text('{"a": 1, "a": 2}')
            with self.assertRaises(VerificationError):
                load_json(path)

    def test_symlink_trust_file_rejected(self):
        from verify_transcript import load_json
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.json"
            link = Path(tmp) / "link.json"
            target.write_bytes(canonical(self.trust))
            link.symlink_to(target)
            with self.assertRaises(VerificationError):
                load_json(link)

    def test_hardlink_trust_file_rejected(self):
        import os
        from verify_transcript import load_json
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.json"
            link = Path(tmp) / "link.json"
            target.write_bytes(canonical(self.trust))
            os.link(target, link)
            with self.assertRaises(VerificationError):
                load_json(link)

    def test_positive_offline_is_not_deployment_authorization(self):
        self.succeeds()


if __name__ == "__main__":
    unittest.main()
