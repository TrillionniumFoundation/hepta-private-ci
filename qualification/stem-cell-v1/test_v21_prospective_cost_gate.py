"""Research negative-gate tests, including actual original-weight numerical replay.

FUTURE signed cases below are synthetic fixtures and never certify 2026-10-17+
observations, independent signers, source issuers or device-host measurements.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

import v21_prospective_cost_gate as v21
import v18_future_source_intake as previous
import test_v20_original_material_challenge as old

DIRECTORY=Path(__file__).parent
AFTER_FAKE=datetime(2026,11,1,tzinfo=timezone.utc)
BEFORE=datetime(2026,10,16,tzinfo=timezone.utc)


def synthetic_source_and_outcome(*, positive=False):
    source={"schema": previous.PANEL, "rows": []}
    outcome={"schema": previous.OUTCOME,"source_payload_sha256": "", "rows": []}
    for i in range(200):
        family=hashlib.sha256(f"test-only-family:{i}".encode()).hexdigest()
        cid=hashlib.sha256(f"test-only-case:{i}".encode()).hexdigest()
        window="future1" if i < 100 else "future2"
        source["rows"].append({"case_sha256":cid,"family_sha256":family,"window":window})
        outcome["rows"].append({"case_sha256":cid,"no_change_loss":.6,
                                "candidate_loss":.3 if positive else .7})
    outcome["source_payload_sha256"]=previous.sha(previous.canonical(source))
    return source,outcome


def signed(packet, key):
    return {"payload":packet, "signature_hex":key.sign(previous.canonical(packet)).hex()}


def pub(key):
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw).hex()


def synthetic_meter(result, key, *, samples=200, stamp="2026-10-30T00:00:00Z"):
    arm={"train_cpu_ns":8_000_000,"encoder_cpu_ns":4_000_000,
         "serving_cpu_ns":2_000_000,"recovery_cpu_ns":1_000_000,
         "peak_rss_bytes":500_000_000,"energy_microjoules":100_000,
         "latency_ns_samples":[20_000+i*200 for i in range(samples)]}
    return signed({"schema":v21.COST_SCHEMA,"frozen_protocol_sha256":v21.sha(v21.encode(v21.PRECOMMIT)),
          "v20_execution_payload_sha256":result["execution_payload_sha256"],
          "v20_source_payload_sha256":result["source_payload_sha256"],
          "host_identity":"SYNTHETIC-UNATTESTED-HOST-ONLY",
          "measured_at":stamp,
          "arms":{"no_change":deepcopy(arm),"candidate":deepcopy(arm)}},key)


class SourceOnly(unittest.TestCase):
    def test_exact_precommitted_protocol(self):
        self.assertEqual(v21.read(DIRECTORY/"STEM_V21_FROZEN_PROSPECTIVE_PROTOCOL_20261016.json"),
                         v21.PRECOMMIT)
        self.assertEqual(len(v21.check_protocol(v21.PRECOMMIT)),64)
        self.assertEqual(v21.PRECOMMIT["frozen_research_commit"],
                         "d80b7ba5593dbab8257a20f4a090d5c2e11f7f6e")

    def test_changed_frozen_model_or_window_is_refused(self):
        for key,value in (("minimum_observed_at_utc","2026-10-16T00:00:00Z"),
                          ("no_change_model_file_sha256","0"*64),
                          ("production_authorized",True),
                          ("bootstrap_iterations",5000),
                          ("bootstrap_iterations",2048.0),
                          ("production_authorized",0)):
            altered=deepcopy(v21.PRECOMMIT)
            altered[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                v21.check_protocol(altered)

    def test_historical_real_hold(self):
        prior=v21.read(DIRECTORY/"STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json")
        result=v21.hold(v21.PRECOMMIT,prior,clock=BEFORE)
        self.assertEqual(result["decision"],"HOLD_NO_INDEPENDENT_FUTURE_AND_HOST_EVIDENCE")
        self.assertEqual(result["new_signed_source_families"],0)
        self.assertFalse(result["science_authorized"])
        self.assertFalse(result["production_authorized"])
        self.assertIsNone(result["future_effect_selected"])

    def test_v20_original_physical_source_drift_denied(self):
        from unittest.mock import patch
        receipt=v21.read(DIRECTORY/"STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json")
        with patch.object(v21,"V20_SHA256","0"*64):
            with self.assertRaisesRegex(ValueError,"original V20 physical replay source drift"):
                v21.hold(v21.PRECOMMIT,receipt,clock=BEFORE)

    def test_false_v20_promoted_or_future_claim_denied(self):
        for k,bad in (("production_authorized",True),
                      ("scientific_promotion_authorized",True),
                      ("independent_future_windows",2),
                      ("new_signed_future_roots",200)):
            old_hold=v21.read(DIRECTORY/"STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json")
            old_hold[k]=bad
            with self.subTest(k=k),self.assertRaises(ValueError):
                v21.hold(v21.PRECOMMIT,old_hold)

    def test_duplicate_json_fields_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            fp=Path(folder)/"bad.json"
            fp.write_bytes(b'{"schema":"one","schema":"two"}')
            with self.assertRaises(ValueError):v21.read(fp)

    def test_nonfinite_json_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            fp=Path(folder)/"bad.json"
            fp.write_bytes(b'{"value":NaN}')
            with self.assertRaises(ValueError):v21.read(fp)

    def test_source_first_family_repeated_seeds_not_independent(self):
        source, outcome=synthetic_source_and_outcome(positive=False)
        res=v21.paired_window_screen(source,outcome,source_sha=previous.sha(previous.canonical(source)),
                                    outcome_sha=previous.sha(previous.canonical(outcome)),protocol=v21.PRECOMMIT)
        self.assertEqual(res["window_diagnostics"]["future1"]["claimed_unique_family_count"],100)
        self.assertFalse(res["window_diagnostics"]["future2"]["positive_lower_bound_on_claimed_families"])
        self.assertFalse(res["prospective_generalization_verified"])

    def test_pseudoreplicated_family_row_does_not_create_100(self):
        source,outcome=synthetic_source_and_outcome()
        for row in source["rows"][:100]:row["family_sha256"]="0"*64
        outcome["source_payload_sha256"]=previous.sha(previous.canonical(source))
        with self.assertRaisesRegex(ValueError,"100 independent claimed family"):
            v21.paired_window_screen(source,outcome,
                                    source_sha=previous.sha(previous.canonical(source)),
                                    outcome_sha=previous.sha(previous.canonical(outcome)),protocol=v21.PRECOMMIT)

    def test_positive_synthetic_interval_is_not_prospective_proof(self):
        source, outcome=synthetic_source_and_outcome(positive=True)
        d=v21.paired_window_screen(source,outcome,
            source_sha=previous.sha(previous.canonical(source)),
            outcome_sha=previous.sha(previous.canonical(outcome)),protocol=v21.PRECOMMIT)
        self.assertTrue(all(d["window_diagnostics"][w]["positive_lower_bound_on_claimed_families"]
                            for w in v21.WINDOWS))
        self.assertFalse(d["family_origin_independently_authenticated"])
        self.assertFalse(d["prospective_generalization_verified"])

    def test_bootstrap_is_deterministic(self):
        s,o=synthetic_source_and_outcome()
        fn=lambda:v21.paired_window_screen(s,o,
             source_sha=previous.sha(previous.canonical(s)),
             outcome_sha=previous.sha(previous.canonical(o)),protocol=v21.PRECOMMIT)
        self.assertEqual(v21.sha(v21.encode(fn())),v21.sha(v21.encode(fn())))

    def test_fake_raw_counter_cost_rejected(self):
        key=Ed25519PrivateKey.generate()
        original={"source_payload_sha256":"a"*64,"execution_payload_sha256":"b"*64,
                  "replayed_original_source_rows":200}
        packet=synthetic_meter(original,key,samples=99)
        with self.assertRaisesRegex(ValueError,"latencies"):
            v21.verify_cost_packet(packet,pub(key),
                distinct_signing_keys=("0"*64,"1"*64,"2"*64),original_v20=original,
                frozen_sha=v21.sha(v21.encode(v21.PRECOMMIT)),now=AFTER_FAKE)

    def test_future_dated_meter_is_refused(self):
        key=Ed25519PrivateKey.generate()
        original={"source_payload_sha256":"a"*64,"execution_payload_sha256":"b"*64,
                  "replayed_original_source_rows":200}
        packet=synthetic_meter(original,key,stamp="2027-01-01T00:00:00Z")
        with self.assertRaisesRegex(ValueError,"future-dated"):
            v21.verify_cost_packet(packet,pub(key),
                distinct_signing_keys=("0"*64,"1"*64,"2"*64),original_v20=original,
                frozen_sha=v21.sha(v21.encode(v21.PRECOMMIT)),now=AFTER_FAKE)

    def test_fake_cost_signature_resigned_but_bad_source_fails(self):
        key=Ed25519PrivateKey.generate()
        original={"source_payload_sha256":"a"*64,"execution_payload_sha256":"b"*64,
                  "replayed_original_source_rows":200}
        packet=synthetic_meter(original,key)
        packet["payload"]["v20_source_payload_sha256"]="0"*64
        packet=signed(packet["payload"],key)
        with self.assertRaisesRegex(ValueError,"physical execution"):
            v21.verify_cost_packet(packet,pub(key),
                distinct_signing_keys=("0"*64,"1"*64,"2"*64),original_v20=original,
                frozen_sha=v21.sha(v21.encode(v21.PRECOMMIT)),now=AFTER_FAKE)

    def test_resigned_good_cost_cannot_attest_host(self):
        key=Ed25519PrivateKey.generate()
        original={"source_payload_sha256":"a"*64,"execution_payload_sha256":"b"*64,
                  "replayed_original_source_rows":200}
        packet=synthetic_meter(original,key)
        r=v21.verify_cost_packet(packet,pub(key),
           distinct_signing_keys=("0"*64,"1"*64,"2"*64),original_v20=original,
           frozen_sha=v21.sha(v21.encode(v21.PRECOMMIT)),now=AFTER_FAKE)
        self.assertTrue(r["passes_precommitted_descriptive_cost_frontier"])
        self.assertFalse(r["measurement_host_identity_independently_attested"])
        self.assertFalse(r["complete_lifecycle_cost_independently_verified"])

    def test_duplicated_signer_rejected(self):
        key=Ed25519PrivateKey.generate()
        original={"source_payload_sha256":"a"*64,"execution_payload_sha256":"b"*64,
                  "replayed_original_source_rows":200}
        with self.assertRaisesRegex(ValueError,"four cryptographically separate"):
            v21.verify_cost_packet(synthetic_meter(original,key),pub(key),
                  distinct_signing_keys=(pub(key),"1"*64,"2"*64),original_v20=original,
                  frozen_sha=v21.sha(v21.encode(v21.PRECOMMIT)),now=AFTER_FAKE)

    def test_corrupted_cost_receipt_signed_by_other_key_rejected(self):
        holder=Ed25519PrivateKey.generate()
        attacker=Ed25519PrivateKey.generate()
        base={"source_payload_sha256":"a"*64,"execution_payload_sha256":"b"*64,
              "replayed_original_source_rows":200}
        receipt=synthetic_meter(base,attacker)
        with self.assertRaisesRegex(ValueError,"signature"):
            v21.verify_cost_packet(receipt,pub(holder),
               distinct_signing_keys=("0"*64,"1"*64,"2"*64),original_v20=base,
               frozen_sha=v21.sha(v21.encode(v21.PRECOMMIT)),now=AFTER_FAKE)

    def test_bogus_resource_cost_resigned_format_denied(self):
        key=Ed25519PrivateKey.generate()
        base={"source_payload_sha256":"a"*64,"execution_payload_sha256":"b"*64,
              "replayed_original_source_rows":200}
        receipt=synthetic_meter(base,key)
        for broken in (-1, 1.5, True, 2**64):
            packet=deepcopy(receipt["payload"])
            packet["arms"]["candidate"]["train_cpu_ns"]=broken
            with self.subTest(broken=str(broken)), self.assertRaises(ValueError):
                v21.verify_cost_packet(signed(packet,key),pub(key),
                   distinct_signing_keys=("0"*64,"1"*64,"2"*64),original_v20=base,
                   frozen_sha=v21.sha(v21.encode(v21.PRECOMMIT)),now=AFTER_FAKE)

    def test_precommitted_cost_frontier_must_charge_extra_training(self):
        key=Ed25519PrivateKey.generate()
        base={"source_payload_sha256":"a"*64,"execution_payload_sha256":"b"*64,
              "replayed_original_source_rows":200}
        receipt=synthetic_meter(base,key)
        receipt["payload"]["arms"]["candidate"]["train_cpu_ns"] += 100_000
        result=v21.verify_cost_packet(signed(receipt["payload"],key),pub(key),
                  distinct_signing_keys=("0"*64,"1"*64,"2"*64),original_v20=base,
                  frozen_sha=v21.sha(v21.encode(v21.PRECOMMIT)),now=AFTER_FAKE)
        self.assertFalse(result["passes_precommitted_descriptive_cost_frontier"])
        self.assertFalse(result["complete_lifecycle_cost_independently_verified"])

    def test_source_family_cannot_repeat_across_windows(self):
        source,outcome=synthetic_source_and_outcome()
        source["rows"][100]["family_sha256"]=source["rows"][0]["family_sha256"]
        outcome["source_payload_sha256"]=previous.sha(previous.canonical(source))
        with self.assertRaisesRegex(ValueError,"source family reappeared"):
            v21.paired_window_screen(source,outcome,
                source_sha=previous.sha(previous.canonical(source)),
                outcome_sha=previous.sha(previous.canonical(outcome)),protocol=v21.PRECOMMIT)

    def test_bogus_source_digest_not_inferred_from_caller(self):
        source,outcome=synthetic_source_and_outcome()
        with self.assertRaisesRegex(ValueError,"identities"):
            v21.paired_window_screen(source,outcome,source_sha="0"*64,
                outcome_sha=previous.sha(previous.canonical(outcome)),protocol=v21.PRECOMMIT)

    def test_no_packet_cli_produces_create_only_hold(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"hold.json"
            cmd=[sys.executable,str(DIRECTORY/"v21_prospective_cost_gate.py"),
                 "--protocol",str(DIRECTORY/"STEM_V21_FROZEN_PROSPECTIVE_PROTOCOL_20261016.json"),
                 "--v20-hold",str(DIRECTORY/"STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json"),
                 "--output",str(out)]
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(v21.read(out)["decision"],"HOLD_NO_INDEPENDENT_FUTURE_AND_HOST_EVIDENCE")
            self.assertNotEqual(subprocess.run(cmd,capture_output=True,text=True,timeout=15).returncode,0)

    def test_partial_source_packet_cli_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"hold.json"
            cmd=[sys.executable,str(DIRECTORY/"v21_prospective_cost_gate.py"),
                 "--protocol",str(DIRECTORY/"STEM_V21_FROZEN_PROSPECTIVE_PROTOCOL_20261016.json"),
                 "--v20-hold",str(DIRECTORY/"STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json"),
                 "--output",str(out),"--source",str(out)]
            self.assertNotEqual(subprocess.run(cmd,capture_output=True,text=True,timeout=15).returncode,0)
            self.assertFalse(out.exists())


@unittest.skipUnless(all(os.environ.get(k) for k in
  ("HEPTA_V20_INPUTS","HEPTA_V20_V15","HEPTA_V20_V16","HEPTA_V20_ARCHIVE")),
  "exact original feature/model material unavailable: no positive claim")
class Original(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inp=os.environ["HEPTA_V20_INPUTS"]
        cls.v15=os.environ["HEPTA_V20_V15"]
        cls.v16=os.environ["HEPTA_V20_V16"]
        cls.archive=os.environ["HEPTA_V20_ARCHIVE"]
        cls.roots=previous.original_roots(cls.inp)
        cls.packets, cls.keys, cls.pubs=old.fresh_packets(cls.v15,cls.v16,cls.roots)
        cls.meter_key=Ed25519PrivateKey.generate()
        cls.original_result=old.call(cls.packets,cls.keys,cls.pubs,cls.roots,cls.archive,
                                     cls.v15,cls.v16,now=old.FUTURE)
        cls.meter=synthetic_meter(cls.original_result,cls.meter_key)

    def audit(self, meter=None, *, now=old.FUTURE):
        return v21.external_audit(v21.PRECOMMIT,old.baseline(),
            old.sign(self.packets[0],self.keys[0]),old.sign(self.packets[1],self.keys[2]),
            old.sign(self.packets[2],self.keys[0]),old.sign(self.packets[3],self.keys[1]),
            old.sign(self.packets[4],self.keys[2]), self.meter if meter is None else meter,
            source_key=self.pubs[0],executor_key=self.pubs[1],evaluator_key=self.pubs[2],
            meter_key=pub(self.meter_key),existing_roots=self.roots,
            original_archive=self.archive,v15=self.v15,v16=self.v16,now=now)

    def test_genuine_frozen_model_replay_but_no_promotion(self):
        r=self.audit()
        self.assertEqual(r["case_count"],200)
        self.assertFalse(r["scientific_promotion_authorized"])
        self.assertFalse(r["production_authorized"])
        self.assertIsNone(r["model_selected"])
        self.assertTrue(r["cost_screen"]["passes_precommitted_descriptive_cost_frontier"])
        self.assertFalse(r["trusted_source_issuer_enrollment_attested"])
        self.assertFalse(r["target_host_cost_attested"])

    def test_expired_source_before_window_denied(self):
        with self.assertRaises(ValueError):self.audit(now=BEFORE)

    def test_bad_os_cost_resigned_signed_packet_denied(self):
        packet=deepcopy(self.meter["payload"])
        packet["arms"]["candidate"]["latency_ns_samples"]=[500000]*199
        with self.assertRaisesRegex(ValueError,"latencies"):
            self.audit(meter=signed(packet,self.meter_key))

    def test_duplicate_meter_roles_denied(self):
        packet=deepcopy(self.meter)
        with self.assertRaises(ValueError):
            v21.external_audit(v21.PRECOMMIT,old.baseline(),
              old.sign(self.packets[0],self.keys[0]),old.sign(self.packets[1],self.keys[2]),
              old.sign(self.packets[2],self.keys[0]),old.sign(self.packets[3],self.keys[1]),
              old.sign(self.packets[4],self.keys[2]), packet,
              source_key=self.pubs[0],executor_key=self.pubs[1],evaluator_key=self.pubs[2],
              meter_key=self.pubs[0],existing_roots=self.roots,
              original_archive=self.archive,v15=self.v15,v16=self.v16,now=old.FUTURE)


if __name__=="__main__":unittest.main()
