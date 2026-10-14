"""Cached-artifact/readout integration fixtures; never pretrained results."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import torch
from safetensors.torch import save_file

import five_causal_experiments as c
import shared_question_gate as gate
import shared_gate_crossed_evidence as crossed
import shared_gate_similarity as control
import shared_gate_similarity_trial as trial
from test_shared_gate_crossed import material


def fixture(root):
    original, selected, inventory = material(True)
    inputs = crossed.build_plan(original, selected, inventory)
    names = {a+"-"+str(s) for a in gate.ARMS for s in gate.SEEDS}
    raw = {name:[{"pair_id":u["pair_id"],"status":"succeeded" if u["status"]=="available" else "unavailable",
                  "logits":[2.,-1.,-1.,2.] if u["status"]=="available" else None} for u in inputs["units"]] for name in names}
    plan={"schema":crossed.PROFILE,"head_source":control.ORIGINS["heads"]["source"],"head_run":control.ORIGINS["heads"]["run"],
          "head_archive_sha256":"a"*64,"arms":list(gate.ARMS),"seeds":list(gate.SEEDS)}
    study=root/"study";study.mkdir(parents=True)
    (root/"source").mkdir();(root/"source/tested-commit.txt").write_text(control.ORIGINS["crossed"]["source"]+"\n")
    c.write_new(root/"execution-disposition.json",{"model_execution_completed":True})
    c.write_new(study/"plan.json",plan);c.write_new(study/"crossed-inputs.json",inputs)
    c.write_new(study/"raw-logits.json",raw)
    digest=c.file_sha(study/"raw-logits.json")
    c.write_new(study/"prediction-seal.json",{"sha256":digest,"before_summary":True})
    for name in names:c.write_new(study/(name+"-raw.json"),raw[name])
    save_file({"fixture":torch.ones(8)},str(study/"frozen-features.safetensors"))
    c.write_new(study/"encoder-receipt.json",{"feature_file_sha256":c.file_sha(study/"frozen-features.safetensors")})
    report={"schema":crossed.PROFILE+".result","errors":[],"new_optimizer_updates":0,"new_reader_calls":0,
            "plan_sha256":c.digest(plan),"raw_sha256":digest,
            "replays":{name:{"all_passed":True} for name in names},
            "summaries":{name:crossed.summarize(inputs["units"],rows) for name,rows in raw.items()}}
    c.write_new(study/"report.json",report)
    return original,names


def mutate(path,fn):
    value=c.load(path);fn(value);path.write_bytes(c.canonical(value)+b"\n")


class CacheTests(unittest.TestCase):
    def check(self,change=None):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);original,names=fixture(root)
            if change:change(root)
            return trial.validate_crossed(root,original,"a"*64,names)

    def test_exact_saved_geometry_and_all_model_seeds(self):
        _,inputs,raw,_=self.check()
        self.assertEqual(len(raw),15)
        self.assertEqual(len(inputs["units"]),2)

    def test_green_deferred_job_is_not_an_encoded_cache(self):
        with self.assertRaises(c.Invalid):self.check(lambda p:mutate(p/"execution-disposition.json",lambda d:d.update(model_execution_completed=False)))

    def test_feature_byte_tampering_is_rejected(self):
        with self.assertRaises(c.Invalid):self.check(lambda p:(p/"study/frozen-features.safetensors").write_bytes(b"not saved features"))

    def test_wrong_crossed_source_is_not_latest_fallback(self):
        with self.assertRaises(c.Invalid):self.check(lambda p:(p/"source/tested-commit.txt").write_text("0"*40))

    def test_failed_original_replay_blocks_new_baseline(self):
        with self.assertRaises(c.Invalid):self.check(lambda p:mutate(p/"study/report.json",lambda d:d["replays"][next(iter(d["replays"]))].update(all_passed=False)))

    def test_missing_model_or_seed_is_not_dropped(self):
        with self.assertRaises(c.Invalid):self.check(lambda p:mutate(p/"study/raw-logits.json",lambda d:d.pop(next(iter(d)))))

    def test_old_pair_corner_cannot_be_swapped(self):
        def change(p):
            def edit(d):
                u=next(x for x in d["units"] if x["status"]=="available")
                u["variants"][0]["question_key"]=u["variants"][2]["question_key"]
            mutate(p/"study/crossed-inputs.json",edit)
        with self.assertRaises(c.Invalid):self.check(change)

    def test_wrong_head_artifact_cannot_supply_features(self):
        with self.assertRaises(c.Invalid):self.check(lambda p:mutate(p/"study/plan.json",lambda d:d.update(head_archive_sha256="b"*64)))

    def test_summary_must_recompute_from_original_logits(self):
        with self.assertRaises(c.Invalid):self.check(lambda p:mutate(p/"study/report.json",lambda d:d["summaries"][next(iter(d["summaries"]))].update(mean_interaction=100.)))

    def test_shared_readout_and_paired_counts_do_not_compare_scales(self):
        original,selected,inventory=material(True);units=crossed.build_plan(original,selected,inventory)["units"]
        def rows(scale):
            return [{"pair_id":u["pair_id"],"status":"succeeded" if u["status"]=="available" else "unavailable",
                     "logits":[scale,-scale,-scale,scale] if u["status"]=="available" else None} for u in units]
        a,b=rows(10.),rows(.1);before=c.digest([units,a,b])
        result=control.compare_flags(units,trial.flags(units,a),trial.flags(units,b))
        self.assertTrue(all(v["both"]==1 for v in result["criteria"].values()))
        self.assertEqual(result["unavailable_pairs"],1)
        self.assertEqual(before,c.digest([units,a,b]))
        self.assertIsNone(result["semantic_accuracy"])


if __name__=="__main__":
    unittest.main()
