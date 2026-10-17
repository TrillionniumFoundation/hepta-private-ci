"""V23 CPU operator fixtures and exact original-feature/weight readback regressions.

Only original-archive class attests actual archived frozen mmBERT feature use;
source-only fixtures are explicitly synthetic and cannot prove learning utility.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

import v23_original_feature_batch_cost as p
import v23_original_feature_batch_cost_review as review
import v23_original_feature_cpu_summary as report

HERE=Path(__file__).resolve().parent
SIZES=(64,256,1024,4096)


def fixture():
    rng=np.random.default_rng(23)
    state={"centers":np.zeros((2,384),dtype=np.float32)}
    for k in (0,1):
        state[f"heads.{k}.weight"] = rng.normal(size=(4,384)).astype(np.float32)/100
        state[f"heads.{k}.bias"] = rng.normal(size=(4,)).astype(np.float32)/100
    return state


class Mechanism(unittest.TestCase):
    def test_preregistered_population_census(self):
        self.assertEqual(p.SIZES,(64,256,1024,4096))
        self.assertEqual(p.ACTIVE,32)
        self.assertEqual(p.PROBE_CASES,4)
        self.assertEqual(p.REQUIRED_TIMED_ROUNDS,128)

    def test_materialize_unique_physically_allocated_head_slots(self):
        for n in SIZES:
            w,b=p.materialize_heads(n,fixture())
            self.assertEqual(w.shape,(n,4,384))
            self.assertEqual(w.nbytes+b.nbytes,n*1540*4)
            self.assertTrue(w.flags.owndata)
            self.assertFalse(np.shares_memory(w,b))
            self.assertFalse(np.shares_memory(w[0],w[1]))
            self.assertTrue(np.array_equal(w[0],w[2]))

    def test_reject_any_fake_4096_independent_trained_head_claim(self):
        x=fixture()
        w,_=p.materialize_heads(4096,x)
        self.assertTrue(np.array_equal(w[0],w[4094]))
        self.assertFalse(np.array_equal(w[0],w[4095]))

    def test_bool_and_unsupported_slot_counts_denied(self):
        for n in (True,0,32,65,4095,4097,100_000):
            with self.subTest(n=n),self.assertRaises(ValueError):
                p.materialize_heads(n,fixture())

    def test_physical_tensor_census_missing_or_nonfinite_denied(self):
        x=fixture();x.pop("heads.1.bias")
        with self.assertRaises(ValueError):p.materialize_heads(64,x)
        x=fixture();x["heads.0.weight"][0,0]=float("nan")
        with self.assertRaises(ValueError):p.materialize_heads(64,x)

    def test_unmodified_per_head_vs_fused_output(self):
        w,b=p.materialize_heads(1024,fixture())
        x=np.random.default_rng(24).normal(size=(384,)).astype(np.float32)
        a=p.per_head(w,b,x);c=p.packed(w,b,x)
        self.assertLess(float(np.max(np.abs(a-c))),1e-5)
        self.assertTrue(np.array_equal(np.argmax(a,axis=1),np.argmax(c,axis=1)))

    def test_original_feature_source_not_copied_per_cell(self):
        x=np.random.default_rng(25).normal(size=(384,)).astype(np.float32)
        w,b=p.materialize_heads(4096,fixture())
        self.assertFalse(np.shares_memory(x,w))
        self.assertEqual(x.size,384)
        self.assertEqual(p.packed(w,b,x).shape,(4096,4))

    def test_bounded_active_32_selection(self):
        for n in SIZES:
            ids=p.selected_ids(n)
            self.assertEqual(len(set(ids.tolist())),32)
            self.assertEqual(ids[0],0)
            self.assertEqual(ids[-1],31*n//32)
        for n in (True,5,63,5000):
            with self.assertRaises(ValueError):p.selected_ids(n)

    def test_full_vs_selected_topology_numerical_proof(self):
        w,b=p.materialize_heads(64,fixture())
        x=np.random.default_rng(26).normal(size=(4,384)).astype(np.float32)
        p.baseline_proof(w,b,x,p.selected_ids(64))

    def test_nonfinite_numeric_probe_denied(self):
        with self.assertRaises(ValueError):
            p.quantized_digest(np.array([[0,np.nan,0,0]],dtype=np.float32))

    def test_requires_100_plus_real_latency_samples(self):
        for sample in ([1]*99,[],[1]*99+[True],[1]*99+[0],[-1]*100):
            with self.assertRaises(ValueError):p.percentile(sample,.99)
        self.assertEqual(p.percentile(list(range(1,101)),.95),95.05)

    def test_create_only_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"x.json"
            sha=p.create_only(file,{"authority_posture":"DENY_ALL"})
            self.assertEqual(sha,p.sha(file.read_bytes()))
            with self.assertRaises(ValueError):p.create_only(file,{})

    def test_clean_producer_separate_from_reviewer(self):
        tree=ast.parse(Path(review.__file__).read_text())
        imported=[]
        for t in ast.walk(tree):
            if isinstance(t,ast.Import):imported.extend(n.name for n in t.names)
            if isinstance(t,ast.ImportFrom):imported.append(t.module or "")
        self.assertFalse(any(name.endswith("v23_original_feature_batch_cost") for name in imported))

    def test_missing_original_process_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises((ValueError, FileNotFoundError)):
                report.aggregate(td)

    def test_missing_original_inputs_not_synthetic_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):p.load_observations(td,td,td)


@unittest.skipUnless(all(os.environ.get(x) for x in
    ("HEPTA_V23_ORIGINAL_INPUTS","HEPTA_V23_ORIGINAL_V15","HEPTA_V23_ORIGINAL_V16",
     "HEPTA_V23_RECEIPT_64","HEPTA_V23_RECEIPT_256","HEPTA_V23_RECEIPT_1024",
     "HEPTA_V23_RECEIPT_4096")), "actual original archived feature/model/receipts not provisioned")
class OriginalEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs=Path(os.environ["HEPTA_V23_ORIGINAL_INPUTS"])
        cls.v15=Path(os.environ["HEPTA_V23_ORIGINAL_V15"])
        cls.v16=Path(os.environ["HEPTA_V23_ORIGINAL_V16"])
        cls.paths=[Path(os.environ[f"HEPTA_V23_RECEIPT_{n}"]) for n in SIZES]
        cls.original=[review.read(p) for p in cls.paths]
        cls.review=review.review(cls.inputs,cls.v15,cls.v16,cls.paths)

    def forged(self,action):
        with tempfile.TemporaryDirectory() as td:
            names=[]
            for i,o in enumerate(self.original):
                data=deepcopy(o)
                if i==0:action(data)
                f=Path(td)/f"{i}.json";f.write_bytes(review.canon(data));names.append(f)
            with self.assertRaises((ValueError,KeyError,TypeError)):
                review.review(self.inputs,self.v15,self.v16,names)

    def test_actual_original_mmbert_features_and_weight_identity(self):
        self.assertEqual(self.review["source_feature_sha256"],p.SOURCE_FEATURE_SHA)
        self.assertEqual(self.review["model_sha256"],p.MODEL_SHA)
        self.assertTrue(self.review["independent_forward_replay"])

    def test_all_four_exact_real_fleet_sizes(self):
        self.assertEqual(tuple(sorted(map(int,self.review["per_size"]))),SIZES)
        self.assertEqual(self.review["per_size"]["4096"]["allocated_individual_head_weight_bytes"],25231360)
        self.assertFalse(self.review["production_authorized"])
        self.assertFalse(self.review["independently_attested_cpu_or_host"])

    def test_duplicate_size_denied(self):
        with self.assertRaises(ValueError):
            review.review(self.inputs,self.v15,self.v16,[self.paths[0]]*4)

    def test_source_claim_tampered_and_resigned_denied(self):
        self.forged(lambda x:x.__setitem__("feature_sha256","0"*64))

    def test_false_production_claim_denied(self):
        self.forged(lambda x:x.__setitem__("production_authorized",True))

    def test_fake_true_4096_independent_learning_denied(self):
        self.forged(lambda x:x.__setitem__("unique_independently_trained_head_values",4096))

    def test_false_entitlement_or_cache_fence_denied(self):
        self.forged(lambda x:x.__setitem__("feature_cache_authority_verified",True))

    def test_false_device_host_status_denied(self):
        self.forged(lambda x:x.__setitem__("actual_target_device_host_verified",True))

    def test_forged_p99_with_unchanged_raw_samples_denied(self):
        self.forged(lambda x:x["profiles"]["all_packed"].__setitem__("p99_ns",42))

    def test_forged_latency_series_denied(self):
        self.forged(lambda x:x["profiles"]["all_loop"]["latency_ns_samples"].__setitem__(0,0))

    def test_model_numeric_probe_changed_denied(self):
        self.forged(lambda x:x["probe_numeric_consistency"][0].__setitem__("full_logit_quantized_sha256","0"*64))

    def test_logical_active_id_replacement_denied(self):
        self.forged(lambda x:x["logical_active_ids"].__setitem__(0,1))

    def test_parameter_count_changed_denied(self):
        self.forged(lambda x:x.__setitem__("weight_bank_bytes",0))

    def test_changed_reported_producer_source_denied(self):
        self.forged(lambda x:x.__setitem__("producer_source_sha256","0"*64))

    def test_false_active_weight_cache_bytes_denied(self):
        self.forged(lambda x:x.__setitem__("selected_cached_head_weight_bytes",0))

    def test_false_total_head_storage_denied(self):
        self.forged(lambda x:x.__setitem__("total_actual_head_storage_bytes",1))

    def test_false_future_generalization_denied(self):
        self.forged(lambda x:x.__setitem__("new_independent_future_sources",200))

    def test_actual_two_process_aggregation_is_reproducible(self):
        report_dir=self.paths[0].parent
        result=report.aggregate(report_dir)
        expected=os.environ.get("HEPTA_V23_RUN_SUMMARY")
        if expected:
            self.assertEqual(result,report.read(expected))
        self.assertEqual(result["authority_posture"],"DENY_ALL")
        self.assertTrue(result["independent_numpy_source_and_logits_replay"])
        self.assertEqual(tuple(sorted(map(int,result["per_size"]))),SIZES)

    def test_aggregator_denies_rehashed_raw_latency_change(self):
        source=self.paths[0].parent
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)
            for r in ("A","B"):
                (target/f"v23-{r}-independent-review.json").write_bytes((source/f"v23-{r}-independent-review.json").read_bytes())
                for n in SIZES:
                    name=f"v23-{r}-{n}.json"
                    (target/name).write_bytes((source/name).read_bytes())
            data=report.read(target/"v23-A-64.json")
            data["profiles"]["all_packed"]["latency_ns_samples"][0]+=900
            (target/"v23-A-64.json").write_bytes(review.canon(data))
            with self.assertRaisesRegex(ValueError,"independent reviewer did not reread"):
                report.aggregate(target)

    def test_aggregator_rejects_false_independent_host_status(self):
        source=self.paths[0].parent
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)
            for r in ("A","B"):
                name=f"v23-{r}-independent-review.json"
                data=report.read(source/name)
                if r=="A":data["independently_attested_cpu_or_host"]=True
                (target/name).write_bytes(review.canon(data))
            with self.assertRaisesRegex(ValueError,"negative-only"):
                report.aggregate(target)

    def test_source_inputs_changed_on_disk_denied(self):
        with tempfile.TemporaryDirectory() as td:
            dst=Path(td)
            orig=(self.inputs/"features.safetensors").read_bytes()
            (dst/"features.safetensors").write_bytes(orig[:-1]+bytes([orig[-1]^1]))
            (dst/"input.json").write_bytes((self.inputs/"input.json").read_bytes())
            with self.assertRaises(ValueError):
                review.review(dst,self.v15,self.v16,self.paths)


if __name__=="__main__":unittest.main()
