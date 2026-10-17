"""Mechanism-only and real-original-state tests; synthetic future fixtures are NOT evidence."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

import v18_future_source_intake as prev
import v20_original_material_challenge as v20

FUTURE = datetime(2026, 10, 30, tzinfo=timezone.utc)
BEFORE = datetime(2026, 10, 16, tzinfo=timezone.utc)


def baseline():
    return {"schema":"hepta.stem.v18.source-first-uncertainty.research",
        "production_authorized":False,"scientific_promotion_authorized":False,
        "source_family_independence_authenticated":False,"prospective_outcomes":0,
        "independent_model_bytes_verified":82,"distinct_original_calibration_cases":32,
        "calibration_case_roster_sha256":"a"*64}


def signing():
    keys = [Ed25519PrivateKey.generate() for _ in range(3)]
    pub = [k.public_key().public_bytes(serialization.Encoding.Raw,
              serialization.PublicFormat.Raw).hex() for k in keys]
    return keys, pub


def sign(payload, key):
    return {"payload":payload, "signature_hex":key.sign(v20.canonical(payload)).hex()}


def fresh_packets(v15, v16, roots):
    """All 200 future cases are authored synthetic unit fixtures, never real future data."""
    keys, pubs = signing()
    mean, base, split, gate, _ = v20.physically_reload(v15,v16)
    rng = np.random.default_rng(20261016)
    features = rng.standard_normal((200, 384)).astype(np.float32) * 12
    bp, cp, selected = v20.physically_predict(features,mean,base,split,gate)
    source = {"schema":prev.PANEL,"frozen_commit":prev.COMMIT,
              "original_archive_sha256":prev.ARCHIVE,"rows":[]}
    material = {"schema":v20.MATERIAL,"source_payload_sha256":None,
                "sealed_at":"2026-10-26T00:00:00Z","model_input_format":v20.MODEL_FORMAT,
                "rows":[]}
    executor = {"schema":v20.EXECUTION,"source_payload_sha256":None,
                "material_payload_sha256":None,"sealed_at":"2026-10-27T00:00:00Z",
                "model_weight_sha256":v20.SAVED_MODEL_SHA,"rows":[]}
    labels = {"schema":v20.LABELS,"source_payload_sha256":None,
              "execution_payload_sha256":None,"sealed_at":"2026-10-28T00:00:00Z","rows":[]}
    losses=[]
    for i in range(200):
        root, family = f"artificial-source-root-{i}", f"artificial-source-family-{i}"
        root_sha = v20.source_root_id("root", root)
        family_sha = v20.source_root_id("family",family)
        window = "future1" if i < 100 else "future2"
        stamp = "2026-10-18T00:00:00Z" if i < 100 else "2026-10-25T00:00:00Z"
        text = f"SYNTHETIC TEST ONLY: original independent case {i}, not a collected publisher record"
        cid = v20.bound_case(None,root_sha,family_sha,window,stamp,v20.text_key(text))
        source["rows"].append({"case_sha256":cid,"root_sha256":root_sha,
            "family_sha256":family_sha,"window":window,"observed_at":stamp})
        material["rows"].append({"case_sha256":cid,"root_id":root,
            "family_id":family,"window":window,"observed_at":stamp,
            "text":text,"feature":features[i].astype(float).tolist()})
        executor["rows"].append({"case_sha256":cid,"baseline_probability":bp[i].tolist(),
            "candidate_probability":cp[i].tolist(),"hard_route":int(selected[i])})
        label = i % 4
        labels["rows"].append({"case_sha256":cid,"label":label})
        t=np.eye(4)[label]
        losses.append({"case_sha256":cid,"no_change_loss":float(np.square(bp[i]-t).sum()),
                       "candidate_loss":float(np.square(cp[i]-t).sum()),
                       "old_task_baseline_loss":.3,"old_task_candidate_loss":.35})
    outcome = {"schema":prev.OUTCOME,"frozen_commit":prev.COMMIT,
       "source_payload_sha256":None,"rows":losses,
       "cost":{k:1 for k in {"baseline_training_cpu_s","candidate_training_cpu_s",
       "baseline_serving_cpu_ms","candidate_serving_cpu_ms","baseline_peak_rss_bytes",
       "candidate_peak_rss_bytes","baseline_p99_ms","candidate_p99_ms",
       "baseline_energy_joules","candidate_energy_joules","baseline_recovery_ms",
       "candidate_recovery_ms"}}}
    data = [source,outcome,material,executor,labels]
    rebind(data)
    return data,keys,pubs


def rebind(data):
    source,outcome,material,executor,labels=data
    s = prev.sha(prev.canonical(source))
    outcome["source_payload_sha256"] = s
    material["source_payload_sha256"] = s
    executor["source_payload_sha256"] = s
    labels["source_payload_sha256"] = s
    executor["material_payload_sha256"] = prev.sha(prev.canonical(material))
    labels["execution_payload_sha256"] = prev.sha(prev.canonical(executor))


def call(packets, keys, pubs, roots, archive, v15, v16, now=FUTURE):
    return v20.verify(baseline(), sign(packets[0],keys[0]), sign(packets[1],keys[2]),
      sign(packets[2],keys[0]), sign(packets[3],keys[1]), sign(packets[4],keys[2]),
      source_key=pubs[0],executor_key=pubs[1],evaluator_key=pubs[2],
      existing_roots=roots,original_archive=archive,v15=v15,v16=v16,now=now)


class SourceOnly(unittest.TestCase):
    def test_historical_no_future_remains_hold(self):
        v = v20.hold(baseline(),clock=BEFORE)
        self.assertEqual(v["decision"],"HOLD_NO_REAL_SIGNED_POST_FREEZE_MATERIAL")
        self.assertEqual(v["new_signed_future_roots"],0)
        self.assertFalse(v["production_authorized"])

    def test_no_source_future_day_is_not_today(self):
        self.assertGreater(prev.AFTER,BEFORE)

    def test_normalized_alias_collapses_to_one_key(self):
        self.assertEqual(v20.text_key("Hello  WORLD"),v20.text_key("hello world"))
        self.assertEqual(v20.text_key("ＡＢＣ"),v20.text_key("abc"))

    def test_invalid_text_rejected(self):
        for s in ("", " ", "x"*4097, None):
            with self.subTest(s=str(s)[:8]),self.assertRaises(ValueError):v20.text_key(s)

    def test_root_metadata_requires_real_bytes(self):
        for s in ("", "x"*257, True):
            with self.assertRaises(ValueError):v20.source_root_id("root",s)

    def test_original_hash_context_separation(self):
        self.assertNotEqual(v20.source_root_id("root","same"),
                            v20.source_root_id("family","same"))

    def test_json_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.json"
            p.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):v20.read(p)

    def test_json_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.json"
            p.write_text('{"value":NaN}')
            with self.assertRaises(ValueError):v20.read(p)

    def test_sealed_no_future_false_authority(self):
        bad=baseline();bad["production_authorized"]=True
        with self.assertRaises(ValueError):v20.hold(bad,clock=BEFORE)

    def test_invalid_feature_rejected(self):
        z=np.ones((2,384),dtype=np.float32)
        z[0,0]=np.nan
        for x in (z, np.ones((2,383),dtype=np.float32),np.ones((2,384))):
            with self.assertRaises(ValueError):v20.physically_predict(x,
                np.zeros(384,dtype=np.float32),{}, {}, {})

    def test_create_only_cli_refuses_partial_signed_args(self):
        # This holds even if no original checkpoint exists.
        import subprocess,sys
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            (p/"base.json").write_bytes(v20.canonical(baseline()))
            cmd=[sys.executable,v20.__file__,"--retrospective",str(p/"base.json"),
                 "--output",str(p/"result.json"),"--source",str(p/"source.json")]
            status=subprocess.run(cmd,capture_output=True,text=True,timeout=12)
            self.assertNotEqual(status.returncode,0)
            self.assertFalse((p/"result.json").exists())


@unittest.skipUnless(all(os.environ.get(k) for k in
    ("HEPTA_V20_INPUTS","HEPTA_V20_V15","HEPTA_V20_V16","HEPTA_V20_ARCHIVE")),
    "original physical source/model material required; no synthetic fallback")
class Original(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inp = os.environ["HEPTA_V20_INPUTS"]
        cls.v15 = os.environ["HEPTA_V20_V15"]
        cls.v16 = os.environ["HEPTA_V20_V16"]
        cls.archive = os.environ["HEPTA_V20_ARCHIVE"]
        cls.roots = prev.original_roots(cls.inp)
        cls.packets,cls.keys,cls.pubs=fresh_packets(cls.v15,cls.v16,cls.roots)

    def try_mutation(self,fn,reason=None):
        packets=deepcopy(self.packets)
        fn(packets)
        rebind(packets)
        with self.assertRaises(ValueError) as ctx:
            call(packets,self.keys,self.pubs,self.roots,self.archive,self.v15,self.v16)
        if reason:self.assertIn(reason,str(ctx.exception))

    def test_physical_prospective_packet_consistent_but_not_authorized(self):
        result=call(self.packets,self.keys,self.pubs,self.roots,self.archive,self.v15,self.v16)
        self.assertEqual(result["decision"],
             "SIGNED_MATERIAL_AND_ORIGINAL_MODEL_NUMERIC_REPLAY_ONLY")
        self.assertEqual(result["replayed_original_source_rows"],200)
        self.assertFalse(result["future_utility_independently_qualified"])
        self.assertFalse(result["original_encoder_forward_authenticated"])
        self.assertFalse(result["production_authorized"])
        self.assertLessEqual(result["max_replayed_probability_error"],v20.PROB_TOLERANCE)

    def test_signed_future_material_not_yet_observed(self):
        with self.assertRaisesRegex(ValueError,"not-yet-observed"):
            call(self.packets,self.keys,self.pubs,self.roots,self.archive,self.v15,self.v16,now=BEFORE)

    def test_text_rehashed_to_old_original_is_rejected(self):
        with zipfile.ZipFile(self.archive) as z:
            old_text=json.loads(z.read("hepta-public-study/dataset.jsonl").splitlines()[0])["text"]
        def attack(p):
            source,_,material,_,_=p
            row=material["rows"][0];row["text"]=old_text
            source["rows"][0]["case_sha256"]=row["case_sha256"]=v20.bound_case(
                None,source["rows"][0]["root_sha256"],source["rows"][0]["family_sha256"],
                row["window"],row["observed_at"],v20.text_key(old_text))
            for collection in (p[1]["rows"],p[3]["rows"],p[4]["rows"]):
                collection[0]["case_sha256"]=row["case_sha256"]
        self.try_mutation(attack,"source text replay")

    def test_original_root_alias_cannot_be_rehashed_under_new_namespace(self):
        old_input=json.loads((Path(self.inp)/"input.json").read_text())
        historical_root=old_input["roster"][0]["group"]
        def attack(p):
            source,_,material,_,_=p
            record=material["rows"][0];record["root_id"]=historical_root
            src=source["rows"][0]
            src["root_sha256"]=v20.source_root_id("root",historical_root)
            src["case_sha256"]=record["case_sha256"]=v20.bound_case(
                None,src["root_sha256"],src["family_sha256"],
                record["window"],record["observed_at"],v20.text_key(record["text"]))
            for collection in (p[1]["rows"],p[3]["rows"],p[4]["rows"]):
                collection[0]["case_sha256"]=record["case_sha256"]
        self.try_mutation(attack,"reused original source root/family")

    def test_signed_future_reuses_other_new_text_alias(self):
        def attack(p):
            one,two=p[2]["rows"][:2]
            two["text"]=one["text"].swapcase()
            s=p[0]["rows"][1]
            s["case_sha256"]=two["case_sha256"]=v20.bound_case(None,s["root_sha256"],
                s["family_sha256"],two["window"],two["observed_at"],v20.text_key(two["text"]))
            for arr in (p[1]["rows"],p[3]["rows"],p[4]["rows"]):arr[1]["case_sha256"]=s["case_sha256"]
        self.try_mutation(attack,"aliased new material")

    def test_future_window_not_temporally_separated(self):
        def attack(p):
            s=p[0]["rows"][100];m=p[2]["rows"][100]
            s["observed_at"]=m["observed_at"]="2026-10-18T00:00:00Z"
            s["case_sha256"]=m["case_sha256"]=v20.bound_case(None,s["root_sha256"],
                s["family_sha256"],m["window"],m["observed_at"],v20.text_key(m["text"]))
            for arr in (p[1]["rows"],p[3]["rows"],p[4]["rows"]):arr[100]["case_sha256"]=s["case_sha256"]
        self.try_mutation(attack,"future windows overlap")

    def test_valid_resigned_fake_prediction_rejected(self):
        self.try_mutation(lambda p:p[3]["rows"][0]["baseline_probability"].__setitem__(0,.9),
                          "fake original Head execution probability")

    def test_valid_resigned_fake_label_rejected(self):
        self.try_mutation(lambda p:p[4]["rows"][0].__setitem__("label",3),
                          "evaluator loss not reproducible")

    def test_valid_resigned_fake_loss_rejected(self):
        self.try_mutation(lambda p:p[1]["rows"][0].__setitem__("candidate_loss",0.0),
                          "evaluator loss not reproducible")

    def test_causally_reversed_seal_rejected(self):
        self.try_mutation(lambda p:p[3].__setitem__("sealed_at","2026-10-20T00:00:00Z"),
                          "causally reversed")

    def test_wrong_executed_model_rejected(self):
        self.try_mutation(lambda p:p[3]["model_weight_sha256"].__setitem__(
            "41-extra_continued","0"*64),"frozen executable model")

    def test_reordered_signed_predictions_still_join_correctly(self):
        packets=deepcopy(self.packets)
        packets[3]["rows"].reverse();packets[4]["rows"].reverse()
        rebind(packets)
        result=call(packets,self.keys,self.pubs,self.roots,self.archive,self.v15,self.v16)
        self.assertEqual(result["replayed_original_source_rows"],200)

    def test_duplicate_executed_case_rejected(self):
        self.try_mutation(lambda p:p[3]["rows"][1].__setitem__("case_sha256",
                      p[3]["rows"][0]["case_sha256"]),"repeated original executed case")

    def test_source_payload_fails_if_keys_not_independent(self):
        source,outcomes,material,execute,labels=self.packets
        with self.assertRaisesRegex(ValueError,"three independent signing roles"):
            v20.verify(baseline(),sign(source,self.keys[0]),sign(outcomes,self.keys[2]),
               sign(material,self.keys[0]),sign(execute,self.keys[1]),sign(labels,self.keys[2]),
               source_key=self.pubs[0],executor_key=self.pubs[0],evaluator_key=self.pubs[2],
               existing_roots=self.roots,original_archive=self.archive,v15=self.v15,
               v16=self.v16,now=FUTURE)

    def test_historical_source_renaming_cannot_erase_old_text(self):
        old=v20.load_old_texts(self.archive)
        self.assertEqual(len(old),128)

    def test_actual_checkpoint_normalizer_modified_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            p=Path(tmp)/"v15";p.mkdir()
            raw=(Path(self.v15)/"normalizer.safetensors").read_bytes()
            data=bytearray(raw);data[-1]^=1
            (p/"normalizer.safetensors").write_bytes(data)
            with self.assertRaisesRegex(ValueError,"pinned V15"):
                v20.physically_reload(p,self.v16)

    def test_actual_checkpoint_weight_modified_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            p=Path(tmp)/"v16";p.mkdir()
            for name in ["sealed.json",* [n+".safetensors" for n in v20.SAVED_MODEL_SHA]]:
                (p/name).write_bytes((Path(self.v16)/name).read_bytes())
            data=bytearray((p/"41-joint.safetensors").read_bytes())
            data[-1]^=1;(p/"41-joint.safetensors").write_bytes(data)
            with self.assertRaisesRegex(ValueError,"original physical model changed"):
                v20.physically_reload(self.v15,p)


if __name__=="__main__":unittest.main()
