"""Synthetic full nine-arm archive for standard-library independent verifier.

Fixtures are deliberately fabricated and cannot establish model/host efficacy.
The protocol replay, hashes, group labels and denial boundaries are real code.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

import torch
from torch import nn
from torch.nn import functional as F

from bridge_gradient_guard import ARMS, OLD_TASK, NEW_TASK, gradient_step
from bridge_gradient_review import (review, _digest, file_hash,
    GUARD_SOURCE_SHA256, CAMPAIGN_SOURCE_SHA256)


class MiniReader(nn.Module):
    max_hops = 3
    def __init__(self):
        super().__init__()
        self.linear = nn.Linear(2,2,bias=False)
    def forward(self,x,*,steps):
        return self.linear(x)


class MiniBatch:
    def __init__(self,x,y):
        self.x=torch.tensor(x,dtype=torch.float32)
        self.targets=torch.tensor(y,dtype=torch.long)
    def features(self):
        return (self.x,)


def write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+'\n')


def old_and_new():
    old_x=[[1.,0.],[0.,1.],[-1.,0.],[0.,-1.]]*4
    new_x=[[1.,1.],[-1.,-1.],[1.,-1.],[-1.,1.]]*4
    return (MiniBatch(old_x,[1,0,0,1]*4), MiniBatch(new_x,[0,1,0,1]*4),
            tuple((i,i+2) for i in range(0,16,4)) + tuple((i+1,i+3) for i in range(0,16,4)))


class CompleteReviewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        fake=types.ModuleType("binding_training")
        def loss_fn(logits,targets,pairs):
            left,right=(torch.tensor(x,dtype=torch.long) for x in zip(*pairs))
            dif=logits[:,1]-logits[:,0]
            return F.softplus(1. -(2*targets[left]-1)*(dif[left]-dif[right])).mean()
        fake.paired_margin_loss=loss_fn
        old_module=sys.modules.get("binding_training")
        sys.modules["binding_training"]=fake
        try:
            cls.rows={}
            old,new,pairs=old_and_new()
            for arm in ARMS:
                model=MiniReader().train()
                opt=torch.optim.Adam(model.parameters(),lr=.01,foreach=False)
                cls.rows[arm]=gradient_step(model,opt,old,new,pairs,arm=arm)
        finally:
            if old_module is None:sys.modules.pop("binding_training",None)
            else:sys.modules["binding_training"]=old_module

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.previous=root/"original-v6"
        self.output=root/"v7-1"
        write(self.previous/"design.json",{
            "source":"explicit_synthetic_fixture",
            "runtime_source_sha256":{"original_v6_example":"a"*64}})
        write(self.previous/"warmup-completion.json",{
            "primary_all_passed":True,"fresh_scoring_authorized":False,
            "gates":{str(seed):{"bridge":{"passed":True}} for seed in (41,47,53)}})
        write(self.output/"start.json",{
            "schema":"hepta.bridge.gradient-campaign.v7.1",
            "task_roles":{"old":OLD_TASK,"new":NEW_TASK},
            "official_validation_unopened":True,
            "previous_v6_design_sha256":file_hash(self.previous/"design.json"),
            "previous_warmup_sha256":file_hash(self.previous/"warmup-completion.json"),
            "original_source_validation_scope":"original_V6_checked_design_and_cached_features",
            "candidate_guard_source_sha256":GUARD_SOURCE_SHA256,
            "candidate_campaign_source_sha256":CAMPAIGN_SOURCE_SHA256,
            "original_runtime_sha256":{"original_v6_example":"a"*64},
            "original_pretrained_snapshots_independently_authenticated":False})
        results={}
        for seed in (41,47,53):
            plan={"schema":"hepta.binding.continuation-plan.v1","seed":seed,
                  "updates":500,"batch_size":16,
                  "binding_case_ids":[f"binding-{seed}-{i}" for i in range(128)],
                  "binding_targets":[1,0,0,1]*32,
                  "natural_case_ids":[f"natural-{seed}-{i}" for i in range(32)],
                  "binding_batches":[list(range(16)) for _ in range(500)],
                  "natural_batches":[list(range(16)) for _ in range(500)]}
            plan["plan_sha256"]=_digest(plan)
            write(self.output/f"seed-{seed}"/"plan.json",plan)
            original=self.previous/f"seed-{seed}"/"bridge"
            write(original/"warmup-model.json",{"execution_parameter_sha256":"c"*64,
                "training_parameter_sha256":"2"*64})
            write(original/"warmup-binding-train.json",{"metrics":{
                "accuracy":1.,"both_worlds_correct":1.}})
            write(original/"continuation-plan.json",plan)
            for arm in ARMS:
                folder=self.output/f"seed-{seed}"/arm
                row=self.rows[arm]
                steps=[dict(row,logical_step=i+1,
                            old_case_ids=plan["binding_case_ids"][:16],
                            new_case_ids=plan["natural_case_ids"][:16]) for i in range(500)]
                accepted=sum(x["accepted_optimizer_steps"] for x in steps)
                rejected=500-accepted
                receipt=dict(schema="hepta.bridge.gradient-continuation.v7.1",
                    status="completed",arm=arm,old_task=OLD_TASK,new_task=NEW_TASK,
                    source_scope="original_train_only",plan_sha256=plan["plan_sha256"],
                    initial_model_sha256="2"*64,final_model_sha256="1"*64,
                    old_train_batches=500,new_train_batches=500,
                    attempted_optimizer_steps=500,accepted_optimizer_steps=accepted,
                    rejected_optimizer_steps=rejected,actual_reader_forwards=1500,
                    actual_backward_calls=1000,old_train_rows=8000,new_train_rows=8000,
                    cpu_ns=500*row["cpu_ns"]+1_000_000,
                    wall_ns=500*row["wall_ns"]+1_000_000,
                    equal_backward_calls=True,actual_compute_equal=False,
                    old_task_retention_verified=False,
                    natural_task_generalization_verified=False,
                    production_authorized=False,updates=steps)
                write(folder/"candidate-training.json",receipt)
                (folder/"candidate.pt").write_bytes(b"NOT_A_REAL_CHECKPOINT\0"+arm.encode())
                write(folder/"candidate-model.json",{
                    "seed":seed,"architecture":{"arm":"bridge"},
                    "initial_execution_parameter_sha256":"c"*64,
                    "file":"candidate.pt","file_sha256":file_hash(folder/"candidate.pt"),
                    "training_receipt_file":"candidate-training.json",
                    "training_receipt_sha256":file_hash(folder/"candidate-training.json"),
                    "training_parameter_sha256":"1"*64})
                write(folder/"attempt.json",{
                    "arm":arm,"seed":seed,
                    "plan_sha256":plan["plan_sha256"],
                    "original_warmup_sha256":file_hash(original/"warmup-model.json"),
                    "original_baseline_sha256":file_hash(original/"warmup-binding-train.json")})
                write(folder/"old-binding-train.json",{
                    "case_ids":plan["binding_case_ids"],
                    "probabilities":[.9 if y else .1 for y in plan["binding_targets"]],
                    "metrics":{"accuracy":1.,"both_worlds_correct":1.}})
                write(folder/"descriptive.json",{
                    "arm":arm,"seed":seed,
                    "old_training_retention":{"passed":True},
                    "old_task_future_retention_verified":False,
                    "independent_new_task_verified":False,
                    "production_authorized":False})
                write(folder/"new-natural-internal-tune.json",{
                    "fixture":True,"not_future_efficacy":True})
                results[f"{seed}/{arm}"]=dict(
                    model_sha256="1"*64,retained_train_only=True,
                    actual_cpu_ns=receipt["cpu_ns"],actual_wall_ns=receipt["wall_ns"],
                    old_train_rows=8000,new_train_rows=8000,
                    accepted_optimizer_steps=accepted,rejected_optimizer_steps=rejected)
        write(self.output/"completed.json",{
            "schema":"hepta.bridge.gradient-campaign.v7.1","complete":True,
            "task_roles":{"old":OLD_TASK,"new":NEW_TASK},
            "source_disjoint_future_windows":0,
            "production_authorized":False,"cell_split_authorized":False,
            "native_ndu_admitted":False,"model_selected":False,
            "results":results})

    def test_all_nine_fixture_arms_replay_exact_counter(self):
        result=review(self.output,self.previous)
        self.assertEqual(len(result["arms"]),9)
        self.assertEqual(result["total_physical_reader_forwards"], 13_500)
        self.assertEqual(result["total_physical_backward_calls"], 9_000)
        self.assertFalse(result["production_authorized"])
        self.assertFalse(result["source_provenance_independently_authenticated"])

    def test_reject_corrupted_candidate_checkpoint(self):
        path=self.output/"seed-41"/"protect_old"/"candidate.pt"
        path.write_bytes(path.read_bytes()+b"tamper")
        with self.assertRaisesRegex(ValueError,"weights/receipts"):
            review(self.output,self.previous)

    def test_reject_rehashed_unapproved_producer_source(self):
        path=self.output/"start.json"
        data=json.loads(path.read_text())
        data["candidate_guard_source_sha256"]="b"*64
        write(path,data)
        with self.assertRaisesRegex(ValueError,"trainer/original V6 runtime"):
            review(self.output,self.previous)

    def test_reject_changed_original_v6_source(self):
        write(self.previous/"design.json",{"changed":True})
        with self.assertRaisesRegex(ValueError,"lineage drift"):
            review(self.output,self.previous)

    def test_reject_incomplete_cohort(self):
        path=self.output/"seed-41"/"joint"/"candidate-training.json"
        path.unlink()
        with self.assertRaisesRegex(ValueError,"regular non-symlink"):
            review(self.output,self.previous)

    def test_reject_rehashed_wrong_old_task_accuracy(self):
        folder=self.output/"seed-41"/"protect_old"
        score=folder/"old-binding-train.json"
        data=json.loads(score.read_text())
        data["metrics"]["accuracy"]=.75
        write(score,data)
        with self.assertRaisesRegex(ValueError,"scalar replay mismatch"):
            review(self.output,self.previous)

    def test_reject_wrong_gradient_stream_even_when_receipt_rehashed(self):
        folder=self.output/"seed-41"/"protect_old_guarded"
        path=folder/"candidate-training.json"
        data=json.loads(path.read_text())
        data["updates"][0]["old_case_ids"]=data["updates"][0]["new_case_ids"]
        write(path,data)
        model=folder/"candidate-model.json"
        entry=json.loads(model.read_text())
        entry["training_receipt_sha256"]=file_hash(path)
        write(model,entry)
        with self.assertRaisesRegex(ValueError,"sources"):
            review(self.output,self.previous)

    def test_reject_forged_aggregate_production(self):
        path=self.output/"completed.json"
        completed=json.loads(path.read_text())
        completed["production_authorized"]=True
        write(path,completed)
        with self.assertRaisesRegex(ValueError,"research-only"):
            review(self.output,self.previous)


if __name__ == '__main__':
    unittest.main()
