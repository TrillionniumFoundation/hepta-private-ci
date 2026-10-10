"""Synthetic owner signatures only; do not mistake key fixtures for independence."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from hepta_neuron_model_trials import ARMS, compare, sha_file, write_new
from hepta_neuron_trial_evidence_gate import (EVIDENCE_SCHEMA, ROLES, _canonical, verify_report)
from test_hepta_neuron_model_trials import fixture, packet


def evidence_files(root):
    manifest, rows, _, manifest_path = fixture(root)
    files = {}
    for arm in ARMS["decisions"]:
        dest = root / f"{arm}.json"
        write_new(dest, packet(manifest, rows, arm))
        files[arm] = dest
    baseline = sha_file(files["laya"])
    comparison = root / "comparison.json"
    write_new(comparison, compare(manifest, rows, files, baseline))
    compare_report = json.loads(comparison.read_text())

    trust = {"schema": EVIDENCE_SCHEMA, "version": 1, "roles": {}}
    paths = {}
    for role in ROLES:
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw).hex()
        key = {"principal": f"synthetic-{role}-fixture", "key_id": f"fixture-{role}",
               "public_key_ed25519_hex": public}
        trust["roles"][role] = key
        body = {"manifest_sha256": sha_file(manifest_path),
                "comparison_sha256": sha_file(comparison),
                "baseline_sha256": baseline, "source_sha": manifest["source_sha"],
                "sealed_dataset_sha256": manifest["dataset_sha256"],
                "host_profile_digest": manifest["host_profile_digest"],
                "family": manifest["family"], "signed_at_ms": 2000,
                "principal": key["principal"]}
        if role == "shadow":
            body.update({"run_receipt_sha256": compare_report["receipt_sha256"],
                         "shadow_only": True, "effect_count": 0,
                         "shadow_execution_log_sha256": "1" * 64})
        elif role == "evaluator":
            body.update({"holdout_sealed": True,
                         "windows_independently_scored": ["holdout", "future_1", "future_2"],
                         "independent_scoring_code_sha256": "2" * 64,
                         "sealed_metrics_sha256": "3" * 64})
        elif role == "recovery":
            body.update({"physical_replay_log_sha256": "4" * 64,
                         "journal_cas_recovered": True, "generation_fence_passed": True,
                         "old_route_rejected": True, "rollback_passed": True,
                         "tombstone_no_resurrection_passed": True})
        else:
            body.update({"baseline_receipt_sha256": baseline,
                         "selected_no_change_as_baseline": True,
                         "resources_measured": True,
                         "retention_measured": True,
                         "negative_transfer_measured": True,
                         "underlying_ndu_receipt_sha256": "5" * 64,
                         "net_gain_q24_by_window": {"typed": {"future_1": 8, "future_2": 7}}})
        unsigned = {"schema": EVIDENCE_SCHEMA, "role": role,
                    "key_id": key["key_id"], "body": body}
        signed = {**unsigned, "signature_ed25519_hex": private.sign(_canonical(unsigned)).hex()}
        dest = root / f"attestation-{role}.json"
        write_new(dest, signed)
        paths[role] = dest
    trust_file = root / "trust.json"
    write_new(trust_file, trust)
    return manifest_path, comparison, trust_file, paths


class IndependentGateTests(unittest.TestCase):
    def test_valid_signatures_do_not_grant_production_or_ndu_authority(self):
        with tempfile.TemporaryDirectory() as path:
            mp, cp, tp, evidence = evidence_files(Path(path))
            result = verify_report(mp, cp, sha_file(tp), tp, evidence)
            self.assertTrue(result["positive_signed_ndu_claims"]["typed"])
            self.assertTrue(result["signed_owner_claims_verified"])
            self.assertFalse(result["production_evidence_verified"])
            self.assertFalse(result["ndu_selection_authorized"])
            self.assertFalse(result["promotion_authorized"])
            self.assertFalse(result["physical_truth_independently_observed_by_this_script"])

    def test_signature_replay_tampering_and_wrong_trust_fail_closed(self):
        with tempfile.TemporaryDirectory() as path:
            mp, cp, tp, evidence = evidence_files(Path(path))
            with self.assertRaisesRegex(ValueError, "operator pin"):
                verify_report(mp, cp, "1" * 64, tp, evidence)
            obj = json.loads(evidence["ndu"].read_text())
            obj["body"]["net_gain_q24_by_window"]["typed"]["future_1"] = -100
            evidence["ndu"].write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError, "signature verification"):
                verify_report(mp, cp, sha_file(tp), tp, evidence)

    def test_missing_evaluator_and_duplicate_principals_fail_closed(self):
        with tempfile.TemporaryDirectory() as path:
            mp, cp, tp, evidence = evidence_files(Path(path))
            with self.assertRaisesRegex(ValueError, "incomplete"):
                verify_report(mp, cp, sha_file(tp), tp,
                              {r: p for r, p in evidence.items() if r != "evaluator"})
            t = json.loads(tp.read_text())
            t["roles"]["evaluator"]["principal"] = t["roles"]["shadow"]["principal"]
            tp.write_text(json.dumps(t))
            with self.assertRaisesRegex(ValueError, "independently keyed"):
                verify_report(mp, cp, sha_file(tp), tp, evidence)

    def test_changed_comparison_receipt_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as path:
            mp, cp, tp, evidence = evidence_files(Path(path))
            data = json.loads(cp.read_text())
            data["baseline_sha256"] = "a" * 64
            cp.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                verify_report(mp, cp, sha_file(tp), tp, evidence)


if __name__ == "__main__":
    unittest.main()
