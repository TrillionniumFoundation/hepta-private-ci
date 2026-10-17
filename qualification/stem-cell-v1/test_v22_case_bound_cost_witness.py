"""V22 adversarial research fixtures: signed numbers do not imply genuine host.

The fixture is entirely synthetic; it simulates post-freeze source/measurement
for exercising fail-closed contracts, and MUST NOT be counted as real future
samples, physical encoder work, independent publishers or AI progress.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

import v22_case_bound_cost_witness as v22
import v21_prospective_cost_gate as old
import v18_future_source_intake as sign

UTC_FUTURE = datetime(2026, 11, 2, tzinfo=timezone.utc)  # injectable tests only
EARLY = datetime(2026, 10, 16, tzinfo=timezone.utc)
FILES = Path(__file__).parent


def private():
    return Ed25519PrivateKey.generate()


def pub(key):
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw).hex()


def signed(payload, key):
    return {"payload":payload,"signature_hex":key.sign(sign.canonical(payload)).hex()}


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def fixture():
    # Unlike the published study, these 200 case names are intentionally fake.
    keys=[private() for _ in range(4)]
    pubs=list(map(pub,keys))
    cases=[]
    for i in range(200):
        cases.append({"case_sha256":sha(f"SIMULATED-source-case-{i}"),
            "family_sha256":sha(f"SIMULATED-future-family-{i}"),
            "window":"future1" if i<100 else "future2"})
    cases=sorted(cases,key=lambda r:r["case_sha256"])
    source={"schema":sign.PANEL,"rows":cases}
    source_sha=sign.sha(sign.canonical(source))
    execution={"schema":"hepta.v20.frozen-execution.v1",
        "source_payload_sha256":source_sha,
        "material_payload_sha256":sha("synthetic source payload"),
        "sealed_at":"2026-10-30T00:00:00Z",
        "model_weight_sha256":{
            "41-extra_continued":old.PRECOMMIT["no_change_model_file_sha256"],
            "41-joint":old.PRECOMMIT["candidate_model_file_sha256"],
            "41-joint_gate":old.PRECOMMIT["candidate_gate_file_sha256"]},
        "rows":[{"case_sha256":r["case_sha256"],"baseline_probability":[.25]*4,
                 "candidate_probability":[.25]*4,"hard_route":i%2}
                 for i,r in enumerate(cases)]}
    execution_sha=sign.sha(sign.canonical(execution))
    costs={}
    for arm in v22.ARMS:
        costs[arm]={"train_cpu_ns":2000000,"encoder_cpu_ns":2000000,
            "serving_cpu_ns":2000000,"recovery_cpu_ns":1000000,
            "peak_rss_bytes":33554432,"energy_microjoules":10000,
            "latency_ns_samples":[10000+i*5 for i in range(200)]}
    meter={"schema":old.COST_SCHEMA,"frozen_protocol_sha256":v22.FROZEN_PROTOCOL_SHA,
        "v20_execution_payload_sha256":execution_sha,
        "v20_source_payload_sha256":source_sha,"host_identity":"synthetic-unsigned-virtual-host",
        "measured_at":"2026-10-30T00:00:00Z","arms":costs}
    meter_sha=sign.sha(sign.canonical(meter))
    run={"schema":v22.LEDGER_SCHEMA,
         "v22_protocol_sha256":sign.sha(sign.canonical(v22.PRECOMMIT)),
         "v21_meter_payload_sha256":meter_sha,
         "source_payload_sha256":source_sha,
         "execution_payload_sha256":execution_sha,
         "run_id":sha("simulated run"),"boot_id":sha("simulated boot"),
         "principal_id":"synthetic-principal","purpose":"synthetic-research-only",
         "generation":41,"fence_sha256":sha("simulated fence"),
         "issued_at":"2026-10-30T01:00:00Z","arms":{}}
    route_by_id={r["case_sha256"]:r["hard_route"] for r in execution["rows"]}
    for arm in v22.ARMS:
        run["arms"][arm]=[{"case_sha256":case["case_sha256"],
            "request_sha256":v22.request_digest(run,arm,case["case_sha256"]),
            "model_sha256":v22.frozen_model(arm),
            "latency_ns":costs[arm]["latency_ns_samples"][i],
            "finished_at":"2026-10-30T00:30:00Z",
            "hard_route":None if arm=="no_change" else route_by_id[case["case_sha256"]]}
             for i,case in enumerate(cases)]
    v20={"decision":"SIGNED_MATERIAL_AND_ORIGINAL_MODEL_NUMERIC_REPLAY_ONLY",
         "original_encoder_forward_authenticated":False,
         "source_payload_sha256":source_sha,"execution_payload_sha256":execution_sha,
         "replayed_original_source_rows":200,
         "original_model_weight_sha256":execution["model_weight_sha256"],
         "scientific_promotion_authorized":False,"production_authorized":False}
    return {"source":source,"executor":execution,"meter":meter,"ledger":run,
            "keys":keys,"pubs":pubs,"v20":v20}


def run(f, *, precommit=None, now=UTC_FUTURE):
    keys=f["keys"]
    return v22.verify_case_ledger(precommit or v22.PRECOMMIT,
         signed(f["source"],keys[0]), signed(f["executor"],keys[1]),
         signed(f["meter"],keys[3]), signed(f["ledger"],keys[3]), f["v20"],
         source_key=pub(keys[0]),executor_key=pub(keys[1]),
         evaluator_key=pub(keys[2]),meter_key=pub(keys[3]),now=now)


class SourceOnly(unittest.TestCase):
    def test_frozen_v21_and_v22_protocol(self):
        self.assertEqual(v22.check_precommit(v22.PRECOMMIT),
            sign.sha(sign.canonical(v22.PRECOMMIT)))
        self.assertEqual(old.PRECOMMIT["required_windows"],["future1","future2"])
        self.assertEqual(old.PRECOMMIT["production_authorized"],False)
        self.assertEqual(old.read(FILES/"STEM_V22_FROZEN_CASE_COST_PROTOCOL_20261016.json"),v22.PRECOMMIT)

    def test_real_missing_future_material_remains_hold(self):
        prior=old.read(FILES/"STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json")
        receipt=v22.blocked_result(v22.PRECOMMIT,prior,now=EARLY)
        self.assertEqual(receipt["decision"],"HOLD_MISSING_ORIGINAL_CASE_BOUND_HOST_EVIDENCE")
        self.assertEqual(receipt["new_signed_source_families"],0)
        self.assertFalse(receipt["production_authorized"])
        self.assertIsNone(receipt["model_selected"])

    def test_fixture_can_only_get_descriptive_not_scientific_go(self):
        r=run(fixture())
        self.assertEqual(r["verified_request_records"],400)
        self.assertEqual(r["source_families_claimed"],{"future1":100,"future2":100})
        self.assertTrue(r["latency_case_membership_recomputed"])
        self.assertFalse(r["meter_hardware_independently_attested"])
        self.assertFalse(r["original_encoder_text_to_feature_attested"])
        self.assertFalse(r["v20_independent_model_numeric_replay_reexecuted_by_v22"])
        self.assertFalse(r["scientific_promotion_authorized"])
        self.assertFalse(r["production_authorized"])

    def test_reordered_samples_rejected_after_resigning(self):
        f=fixture()
        f["ledger"]["arms"]["candidate"][0]["latency_ns"]+=5
        with self.assertRaisesRegex(ValueError,"not bound to original case"):
            run(f)

    def test_swapped_case_order_same_cardinality_denied(self):
        f=fixture()
        entries=f["ledger"]["arms"]["candidate"]
        entries[0],entries[1]=entries[1],entries[0]
        with self.assertRaisesRegex(ValueError,"reused or reordered"):
            run(f)

    def test_duplicated_case_denied(self):
        f=fixture()
        f["ledger"]["arms"]["candidate"][1]["case_sha256"]=f["ledger"]["arms"]["candidate"][0]["case_sha256"]
        with self.assertRaises(ValueError):run(f)

    def test_wrong_saved_weight_even_signed_denied(self):
        f=fixture()
        f["ledger"]["arms"]["candidate"][0]["model_sha256"]=sha("fake weight")
        with self.assertRaisesRegex(ValueError,"model weights"):
            run(f)

    def test_original_executor_route_swap_denied(self):
        f=fixture()
        rec=f["ledger"]["arms"]["candidate"][0]
        rec["hard_route"]=1-rec["hard_route"]
        with self.assertRaisesRegex(ValueError,"expert route"):
            run(f)

    def test_bool_route_denied(self):
        f=fixture()
        f["ledger"]["arms"]["candidate"][0]["hard_route"]=False
        with self.assertRaises(ValueError):run(f)

    def test_bool_generation_denied(self):
        f=fixture()
        f["ledger"]["generation"]=True
        with self.assertRaisesRegex(ValueError,"generation"):
            run(f)

    def test_generation_swapped_without_rerequest_denied(self):
        f=fixture()
        f["ledger"]["generation"]+=1
        with self.assertRaisesRegex(ValueError,"request source"):
            run(f)

    def test_principal_swapped_without_rerequest_denied(self):
        f=fixture()
        f["ledger"]["principal_id"]="ANOTHER-PRINCIPAL"
        with self.assertRaisesRegex(ValueError,"request source"):
            run(f)

    def test_route_fence_swapped_without_rerequest_denied(self):
        f=fixture()
        f["ledger"]["fence_sha256"]=sha("changed fence")
        with self.assertRaisesRegex(ValueError,"request source"):
            run(f)

    def test_different_run_no_replay_denied(self):
        f=fixture()
        f["ledger"]["run_id"]=sha("another run")
        with self.assertRaisesRegex(ValueError,"request source"):
            run(f)

    def test_packet_wrong_signer_rejected(self):
        f=fixture()
        f["keys"][3]=private()
        # The caller's old fourth key is no longer the returned signer.
        with self.assertRaisesRegex(ValueError,"signature"):
            v22.verify_case_ledger(v22.PRECOMMIT,
                signed(f["source"],f["keys"][0]),signed(f["executor"],f["keys"][1]),
                signed(f["meter"],f["keys"][2]),signed(f["ledger"],f["keys"][3]),f["v20"],
                source_key=f["pubs"][0],executor_key=f["pubs"][1],
                evaluator_key=f["pubs"][2],meter_key=f["pubs"][3],now=UTC_FUTURE)

    def test_future_dated_signed_evidence_denied(self):
        f=fixture()
        f["ledger"]["issued_at"]="2026-12-15T00:00:00Z"
        with self.assertRaisesRegex(ValueError,"future/stale"):
            run(f)

    def test_old_date_routing_denied(self):
        f=fixture()
        f["ledger"]["arms"]["candidate"][0]["finished_at"]="2026-10-16T00:00:00Z"
        with self.assertRaisesRegex(ValueError,"future/stale"):
            run(f)

    def test_request_after_witness_seal_denied(self):
        f=fixture()
        f["ledger"]["arms"]["candidate"][0]["finished_at"]="2026-10-31T00:00:00Z"
        with self.assertRaisesRegex(ValueError,"after claimed"):
            run(f)

    def test_missing_independent_source_families_denied(self):
        f=fixture()
        f["source"]["rows"][100]["family_sha256"]=f["source"]["rows"][0]["family_sha256"]
        with self.assertRaises(ValueError):run(f)

    def test_frozen_protocol_boolean_integer_substitution_rejected(self):
        p=deepcopy(v22.PRECOMMIT)
        p["production_authorized"]=0
        with self.assertRaisesRegex(ValueError,"immutable"):
            v22.check_precommit(p)

    def test_fake_frozen_v20_candidate_denied(self):
        f=fixture()
        f["v20"]["scientific_promotion_authorized"]=True
        with self.assertRaisesRegex(ValueError,"negative-only"):
            run(f)

    def test_signed_meter_cost_identity_drift_denied(self):
        f=fixture()
        f["meter"]["v20_execution_payload_sha256"]=sha("another-execution")
        with self.assertRaises(ValueError):run(f)

    def test_resigned_both_meter_and_ledger_wrong_case_sample_denied(self):
        f=fixture()
        a=f["meter"]["arms"]["candidate"]["latency_ns_samples"]
        a[0]=a[1]
        f["ledger"]["arms"]["candidate"][0]["latency_ns"]=a[0]
        f["ledger"]["v21_meter_payload_sha256"]=sign.sha(sign.canonical(f["meter"]))
        # Signatures can agree on a false physical number; this must remain
        # diagnostic-only rather than pretending to attest hardware timing.
        r=run(f)
        self.assertFalse(r["meter_hardware_independently_attested"])
        self.assertFalse(r["scientific_promotion_authorized"])

    def test_no_packet_cli_is_create_only_hold(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"hold.json"
            cmd=[sys.executable,str(FILES/"v22_case_bound_cost_witness.py"),
                "--protocol",str(FILES/"STEM_V22_FROZEN_CASE_COST_PROTOCOL_20261016.json"),
                "--v20-hold",str(FILES/"STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json"),
                "--out",str(out)]
            runproc=subprocess.run(cmd,capture_output=True,text=True,timeout=12)
            self.assertEqual(runproc.returncode,0,runproc.stderr)
            self.assertFalse(old.read(out)["production_authorized"])
            self.assertNotEqual(subprocess.run(cmd,capture_output=True,text=True,timeout=12).returncode,0)

    def test_partial_external_packets_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"hold.json"
            cmd=[sys.executable,str(FILES/"v22_case_bound_cost_witness.py"),
                "--protocol",str(FILES/"STEM_V22_FROZEN_CASE_COST_PROTOCOL_20261016.json"),
                "--v20-hold",str(FILES/"STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json"),
                "--source",str(FILES/"STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json"),
                "--out",str(out)]
            self.assertNotEqual(subprocess.run(cmd,capture_output=True,text=True,timeout=12).returncode,0)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
