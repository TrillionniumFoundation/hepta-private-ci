"""Real Ed25519 fixture tests assert integrity, NOT real future evidence."""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

import v18_future_source_intake as gate


def fixture():
    source_key=Ed25519PrivateKey.generate()
    evaluator_key=Ed25519PrivateKey.generate()
    rootset={gate.sha(f"old-{i}".encode()) for i in range(128)}
    rows=[]; scores=[]
    for i in range(200):
        case=gate.sha(f"new-case-{i}".encode())
        row={"case_sha256":case, "root_sha256":gate.sha(f"root-{i}".encode()),
             "family_sha256":gate.sha(f"family-{i}".encode()),
             "window":"future1" if i < 100 else "future2",
             "observed_at":"2026-10-18T00:00:00Z" if i<100 else "2026-10-25T00:00:00Z"}
        rows.append(row)
        scores.append({"case_sha256":case,"no_change_loss":.5,"candidate_loss":.4,
                       "old_task_baseline_loss":.3,"old_task_candidate_loss":.35})
    source={"schema":gate.PANEL,"frozen_commit":gate.COMMIT,
            "original_archive_sha256":gate.ARCHIVE,"rows":rows}
    outcome={"schema":gate.OUTCOME,"frozen_commit":gate.COMMIT,
             "source_payload_sha256":gate.sha(gate.canonical(source)),"rows":scores,
             "cost":{k:10 for k in {"baseline_training_cpu_s","candidate_training_cpu_s",
                 "baseline_serving_cpu_ms","candidate_serving_cpu_ms","baseline_peak_rss_bytes",
                 "candidate_peak_rss_bytes","baseline_p99_ms","candidate_p99_ms",
                 "baseline_energy_joules","candidate_energy_joules","baseline_recovery_ms","candidate_recovery_ms"}}}
    signed=lambda x,k:{"payload":x,"signature_hex":k.sign(gate.canonical(x)).hex()}
    pub=lambda k:k.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
    return (source,outcome,source_key,evaluator_key,rootset,signed,pub)


def baseline():
    return {"schema":"hepta.stem.v18.source-first-uncertainty.research",
        "production_authorized":False,"scientific_promotion_authorized":False,
        "source_family_independence_authenticated":False,"prospective_outcomes":0,
        "independent_model_bytes_verified":82,"distinct_original_calibration_cases":32,
        "calibration_case_roster_sha256":"a"*64}


class Gate(unittest.TestCase):
    def test_original_source_roster_requires_exact_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):gate.original_roots(tmp)

    def test_real_historical_baseline_is_hold(self):
        result=gate.blocked(baseline())
        self.assertEqual(result["verdict"],"HOLD_MISSING_NEW_INDEPENDENT_WINDOWS")
        self.assertFalse(result["scientific_promotion_authorized"])
        self.assertIsNone(result["prospective_future_utility"])

    def test_fake_authorization_or_source_rejected(self):
        for key,value in (("production_authorized",True),
                         ("scientific_promotion_authorized",True),
                         ("source_family_independence_authenticated",True),
                         ("prospective_outcomes",2)):
            obj=baseline();obj[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):gate.blocked(obj)

    def test_two_independently_signed_test_panels_are_not_promotion(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        response=gate.verify_signed(baseline(),sign(source,sk),sign(outcome,ek),
                 trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=roots)
        self.assertEqual(response["new_source_roots"],200)
        self.assertEqual(response["source_family_results"]["future1"]["source_family_roots"],100)
        self.assertEqual(response["verdict"],"SIGNATURES_AND_NUMERIC_CONTRACTS_CONSISTENT_NOT_AUTHORIZED")
        self.assertFalse(response["production_authorized"])
        self.assertIsNone(response["prospective_future_utility"])
        self.assertFalse(response["independent_original_owner_qualified"])

    def test_tampered_signed_source_rejected(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        pkt=sign(source,sk);pkt["payload"]["rows"][0]["observed_at"]="2026-10-15T00:00:00Z"
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),pkt,sign(outcome,ek),
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=roots)

    def test_tampered_signed_metric_rejected(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        pkt=sign(outcome,ek);pkt["payload"]["rows"][1]["candidate_loss"]=0
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),sign(source,sk),pkt,
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=roots)

    def test_self_signed_not_independent(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),sign(source,sk),sign(outcome,sk),
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(sk),existing_root_sha256=roots)

    def test_signature_valid_but_past_event_rejected(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        source["rows"][0]["observed_at"]="2026-10-15T00:00:00Z"
        outcome["source_payload_sha256"]=gate.sha(gate.canonical(source))
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),sign(source,sk),sign(outcome,ek),
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=roots)

    def test_signed_reused_family_denied(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        source["rows"][1]["family_sha256"]=source["rows"][0]["family_sha256"]
        outcome["source_payload_sha256"]=gate.sha(gate.canonical(source))
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),sign(source,sk),sign(outcome,ek),
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=roots)

    def test_signed_old_source_reuse_denied(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        source["rows"][1]["root_sha256"]=next(iter(roots))
        outcome["source_payload_sha256"]=gate.sha(gate.canonical(source))
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),sign(source,sk),sign(outcome,ek),
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=roots)

    def test_partial_roster_is_denied(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),sign(source,sk),sign(outcome,ek),
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=set())

    def test_incomplete_cost_not_silently_zero(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        outcome["cost"].pop("candidate_energy_joules")
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),sign(source,sk),sign(outcome,ek),
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=roots)

    def test_boolean_cost_fabrication_denied(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        outcome["cost"]["candidate_energy_joules"]=True
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),sign(source,sk),sign(outcome,ek),
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=roots)

    def test_missing_families_second_window_denied(self):
        source,outcome,sk,ek,roots,sign,pub=fixture()
        source["rows"][199]["window"]="future1"
        outcome["source_payload_sha256"]=gate.sha(gate.canonical(source))
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),sign(source,sk),sign(outcome,ek),
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=roots)


@unittest.skipUnless(os.environ.get("HEPTA_V18_INPUTS"),
    "exact original source must be provisioned; skip is not scientific acceptance")
class Original(unittest.TestCase):
    def test_original_source_roster_has_128_real_cases(self):
        path=os.environ.get("HEPTA_V18_INPUTS")
        if path is None:
            self.skipTest("actual original source not provisioned")
        roots=gate.original_roots(path)
        self.assertGreaterEqual(len(roots),128)

    def test_original_source_claim_rejected_even_when_signed(self):
        path=os.environ.get("HEPTA_V18_INPUTS")
        if path is None:
            self.skipTest("actual original source not provisioned")
        source,outcome,sk,ek,roots,sign,pub=fixture()
        actual=gate.original_roots(path)
        source["rows"][1]["root_sha256"]=next(iter(actual))
        outcome["source_payload_sha256"]=gate.sha(gate.canonical(source))
        with self.assertRaises(ValueError):gate.verify_signed(baseline(),sign(source,sk),sign(outcome,ek),
                  trusted_source_key=pub(sk),trusted_evaluator_key=pub(ek),existing_root_sha256=actual)


if __name__=="__main__":unittest.main()
