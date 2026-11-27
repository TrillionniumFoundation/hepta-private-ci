"""Independent source/projection and actual tiny-Torch continuation regressions.

Fixtures are authored synthetic feature tensors, never real Granite outputs.
The physical pretrained job MUST separately execute the pinned model.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qualification.cell_meta_execution_af import physical_router_real_bridge as bridge
from qualification.cell_meta_execution_af import physical_router_real_review as reviewer
from qualification.cell_meta_execution_af import physical_router_trial as trial
from qualification.cell_meta_execution_af import physical_router_audit as numerical


def source_fixture():
    cases=[]
    for split,n in bridge.ROWS.items():
        for i in range(n):
            label=i % 2
            text=f"Fixture {split}: independent public-like text {i}, class {label}"
            identity=hashlib.sha256(text.encode()).hexdigest()
            joint={"state":text,"question":"Which category does the news report describe?",
                   "options":["world","sports"]}
            cases.append({"case_id":identity[:24],"source_digest":identity,
                          "group_id":identity,"joint_input_digest":bridge.sha_object(joint),
                          "label":label,"label_name":("world","sports")[label],
                          "split":split,"joint_input":joint})
    return {"schema":bridge.PANEL_SCHEMA,"dataset":bridge.SOURCE_DATASET,
            "dataset_commit_prefix":bridge.SOURCE_DATASET_COMMIT[:7],
            "dataset_file_sha256":bridge.SOURCE_BYTES,
            "label_mapping":{"world":0,"sports":1},"case_count":224,
            "cross_sectional_not_future":True,"production_promotion":"DENY_ALL",
            "cases":cases}


def fixture_table(source):
    entries=[]
    for k,case in enumerate(source["cases"]):
        unscaled=[math.sin((k+3)*(i+1)/100) for i in range(384)]
        size=math.sqrt(sum(v*v for v in unscaled))
        q=[int(round(bridge.Q24*v/size)) for v in unscaled]
        # Inputs are synthetic but respect the actual Q24 serialized shape.
        entries.append({"case_id":case["case_id"],
                        "source_digest":case["source_digest"],
                        "joint_input_digest":case["joint_input_digest"],
                        "feature_q24":q,"original_tokens":56,
                        "feature_sha256":bridge.feature_hash(case["case_id"],case["source_digest"],q)})
    return {"schema":bridge.TABLE_SCHEMA,"dataset_panel_sha256":bridge.SOURCE_PANEL_SHA,
            "model_id":bridge.MODEL_ID,"model_revision":bridge.MODEL_REVISION,
            "encoder_source_sha":bridge.REVIEWED_ENCODER_SOURCE,
            "snapshot_files_sha256":hashlib.sha256(b"fake-mocked-fixture-only").hexdigest(),
            "pooling":"cls_l2_q24","dim":384,"reported_physical_model_requests":224,
            "observed_encoder_elapsed_seconds":0.5,
            "independent_model_origin_verified":False,"production_admission":"BLOCKED",
            "rows":entries}


class FrozenSourceAndProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=source_fixture()
        cls.sha=bridge.sha_object(cls.source)
        cls.orig_bridge=bridge.SOURCE_PANEL_SHA
        cls.orig_review=reviewer.ORIGINAL_SHA
        bridge.SOURCE_PANEL_SHA=cls.sha
        reviewer.ORIGINAL_SHA=cls.sha
        cls.table=fixture_table(cls.source)
        cls.panel,cls.receipt=bridge.convert(cls.source,cls.table,seed=41)

    @classmethod
    def tearDownClass(cls):
        bridge.SOURCE_PANEL_SHA=cls.orig_bridge
        reviewer.ORIGINAL_SHA=cls.orig_review

    def verify(self, *,source=None,table=None,panel=None,receipt=None):
        return reviewer.independent_replay(source or self.source,table or self.table,
                                           panel or self.panel,receipt or self.receipt,seed=41)

    def test_registered_source_lock(self):
        self.assertEqual(len(bridge.verify_panel(self.source)),224)
        self.assertEqual(bridge.sha_object(self.source),self.sha)

    def test_source_cannot_relabel(self):
        s=copy.deepcopy(self.source)
        s["cases"][0]["label"]=1
        with self.assertRaises(bridge.BridgeError):bridge.verify_panel(s)

    def test_source_cannot_change_text(self):
        s=copy.deepcopy(self.source)
        s["cases"][0]["joint_input"]["state"]+="tamper"
        with self.assertRaises(bridge.BridgeError):bridge.verify_panel(s)

    def test_source_cannot_remove_or_insert_cases(self):
        for change in ("pop", "duplicate"):
            s=copy.deepcopy(self.source)
            if change=="pop":s["cases"].pop()
            else:s["cases"].append(copy.deepcopy(s["cases"][0]))
            with self.assertRaises(bridge.BridgeError):bridge.verify_panel(s)

    def test_source_cannot_swap_case_group(self):
        s=copy.deepcopy(self.source)
        s["cases"][0]["group_id"]=s["cases"][1]["group_id"]
        with self.assertRaises(bridge.BridgeError):bridge.verify_panel(s)

    def test_feature_table_replay(self):
        bridge.validate_table(self.table,self.source["cases"])
        self.assertEqual(self.verify()["outcome"],"PINNED_SOURCE_AND_Q24_PROJECTION_REPLAY_ONLY")
        self.assertFalse(self.verify()["production_selection_authorized"])

    def test_all_three_seeds_preserve_shared_physical_features(self):
        for seed in bridge.SEEDS:
            panel,receipt=bridge.convert(self.source,self.table,seed=seed)
            self.assertEqual(panel["source"]["seed"],seed)
            self.assertEqual(panel["partitions"],self.panel["partitions"])
            self.assertEqual(receipt["panel_seed"],seed)

    def test_train_eval_cohorts_unchanged_and_nonprospective(self):
        self.assertEqual({k:len(v) for k,v in self.panel["partitions"].items()},
                         {"old_train":64,"new_train":64,"old_retention":16,
                          "future_1":32,"future_2":32,"ood":16})
        trial.validate(self.panel)
        self.assertFalse(self.receipt["future_window_prospective"])
        self.assertTrue(self.receipt["ood_is_calibration_samesource_placeholder"])

    def test_feature_order_swap_fails(self):
        t=copy.deepcopy(self.table)
        t["rows"][0],t["rows"][1]=t["rows"][1],t["rows"][0]
        with self.assertRaises(bridge.BridgeError):bridge.validate_table(t,self.source["cases"])

    def test_feature_q24_altered_hash_fails(self):
        t=copy.deepcopy(self.table)
        t["rows"][0]["feature_q24"][0]+=1
        with self.assertRaises(bridge.BridgeError):bridge.validate_table(t,self.source["cases"])

    def test_forged_hash_even_if_recomputed_changes_converted_panel(self):
        t=copy.deepcopy(self.table)
        t["rows"][0]["feature_q24"][0]+=1
        row=t["rows"][0]
        row["feature_sha256"]=bridge.feature_hash(row["case_id"],row["source_digest"],row["feature_q24"])
        self.assertEqual(len(bridge.validate_table(t,self.source["cases"])),224)
        with self.assertRaises(reviewer.Denied): self.verify(table=t)
        # A coherent different feature source is not automatically authenticated.
        p,r=bridge.convert(self.source,t,seed=41)
        self.assertNotEqual(bridge.sha_object(p),bridge.sha_object(self.panel))
        self.assertFalse(r["independent_model_origin_verified"])

    def test_projection_math_tamper(self):
        p=copy.deepcopy(self.panel)
        p["partitions"]["future_1"][0]["features"][0]+=.001
        with self.assertRaises(reviewer.Denied):self.verify(panel=p)

    def test_forged_stage_clock_rejected(self):
        p=copy.deepcopy(self.panel)
        p["partitions"]["future_2"][0]["step"]+=100000
        with self.assertRaises(reviewer.Denied):self.verify(panel=p)

    def test_counterfeit_prospective_and_ood_claim_rejected(self):
        for key in ("future_window_prospective","real_ood_verified",
                    "independent_model_origin_verified", "independent_scientific_outcomes_verified"):
            r=copy.deepcopy(self.receipt)
            r[key]=True
            with self.subTest(key=key),self.assertRaises(reviewer.Denied):self.verify(receipt=r)

    def test_independent_reviewer_rejects_self_consistent_other_model(self):
        t=copy.deepcopy(self.table)
        t["model_id"]="not-granite"
        p=copy.deepcopy(self.panel)
        p["source"]["stem_sha256"]=bridge.sha_object({
            "model_id":t["model_id"],"model_revision":t["model_revision"],
            "snapshot_files_sha256":t["snapshot_files_sha256"],"pooling":"cls_l2_q24",
            "projection":bridge.PROJECTION})
        r=copy.deepcopy(self.receipt)
        r["meta_trial_panel_sha256"]=bridge.sha_object(p)
        r["real_encoder_feature_table_sha256"]=bridge.sha_object(t)
        with self.assertRaises(reviewer.Denied):self.verify(table=t,panel=p,receipt=r)

    def test_wrong_model_identity_rejected(self):
        for key,value in (("model_revision","0"*40),("model_id","fake-encoder"),
                          ("pooling","wrong-pooling"),("encoder_source_sha","0"*40)):
            t=copy.deepcopy(self.table);t[key]=value
            with self.subTest(key=key),self.assertRaises(bridge.BridgeError):
                bridge.validate_table(t,self.source["cases"])

    def test_fake_nonunit_encoder_vector_rejected(self):
        t=copy.deepcopy(self.table)
        row=t["rows"][0]
        row["feature_q24"]=[int(x/2) for x in row["feature_q24"]]
        row["feature_sha256"]=bridge.feature_hash(row["case_id"],row["source_digest"],
                                                    row["feature_q24"])
        with self.assertRaises(bridge.BridgeError):
            bridge.validate_table(t,self.source["cases"])

    def test_numerical_bounds_and_no_label_in_feature_rows(self):
        self.assertNotIn("label",self.table["rows"][0])
        for changed in (True,float("nan"),bridge.Q24+1):
            t=copy.deepcopy(self.table);t["rows"][0]["feature_q24"][0]=changed
            with self.subTest(changed=repr(changed)),self.assertRaises(bridge.BridgeError):
                bridge.validate_table(t,self.source["cases"])

    def test_strict_source_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); p=root/"source.json";p.write_bytes(bridge.canonical(self.source))
            self.assertEqual(bridge.read_json(p),self.source)
            (root/"duplicate").write_text('{"a":1,"a":2}')
            (root/"nonfinite").write_text('{"a":NaN}')
            for f in ("duplicate","nonfinite"):
                with self.subTest(f=f),self.assertRaises(bridge.BridgeError):bridge.read_json(root/f)
            link=root/"link";link.symlink_to(p)
            with self.assertRaises(OSError):bridge.read_json(link)
            fifo=root/"pipe";os.mkfifo(fifo)
            with self.assertRaises(bridge.BridgeError):bridge.read_json(fifo)

    def test_no_overwrite_of_source_output(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"original.json"
            bridge.create_json(path,self.receipt)
            with self.assertRaises(FileExistsError):bridge.create_json(path,self.receipt)

    def test_cannot_prove_4k_resources_from_224_rows(self):
        self.assertEqual(self.panel["source"]["dim"],64)
        self.assertEqual(len(self.table["rows"]),224)
        self.assertFalse(self.receipt["real_ood_verified"])

    def test_torch_paired_followup_real_cpu_on_unverified_features(self):
        # Actual small FP32 SGD over fixture Q24 values, NOT actual pretrained inference.
        result=trial.run(self.panel,steps=4)
        report=numerical.validate(self.panel,result)
        self.assertEqual(report["outcome"],"NUMERIC_REPLAY_ONLY")
        self.assertFalse(result["real_pretrained_encoder_executed"])
        self.assertFalse(result["future_window_prospective"])
        self.assertFalse(result["ndu_selection_authorized"])

    def test_future_label_relabel_does_not_change_train_parameters(self):
        changed=copy.deepcopy(self.panel)
        for part in ("future_1","future_2","ood"):
            for row in changed["partitions"][part]:row["label"]=1-row["label"]
        a=trial.train_arm(self.panel,"adaptive_split",steps=2)
        b=trial.train_arm(changed,"adaptive_split",steps=2)
        self.assertEqual(a["weights_sha256"],b["weights_sha256"])
        self.assertEqual(a["prediction_sha256"],b["prediction_sha256"])

    def test_wrong_seeds_not_admitted(self):
        for seed in (0,54,2**33,True):
            with self.subTest(seed=seed),self.assertRaises(bridge.BridgeError):
                bridge.convert(self.source,self.table,seed=seed)

    def test_independent_reviewer_does_not_import_trainer(self):
        from pathlib import Path
        body=Path(reviewer.__file__).read_text()
        self.assertNotIn("import torch",body)
        self.assertNotIn("physical_router_trial",body)
        self.assertNotIn("physical_router_real_bridge",body)

if __name__ == "__main__":
    unittest.main()
