"""V17 original physical feature/weight checks and adversarial negative controls."""
from __future__ import annotations

import ast
from copy import deepcopy
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
import torch
from torch import nn

import stem_identity_alignment_v17 as v
import stem_identity_alignment_v17_review as independent


class Mechanism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_schema_and_no_authority(self):
        self.assertFalse(v.PROTOCOL["production_authorized"])
        self.assertFalse(v.PROTOCOL["blind_label_access"])
        self.assertEqual(v.PROTOCOL["router_steps"],80)
        self.assertEqual(set(v.ARM_NAMES),set(independent.ARMS))

    def test_independent_audit_has_no_producer_import(self):
        tree=ast.parse(Path(independent.__file__).read_text())
        imports=[]
        for item in ast.walk(tree):
            if isinstance(item,ast.Import):imports.extend(x.name for x in item.names)
            elif isinstance(item,ast.ImportFrom):imports.append(item.module or "")
        self.assertFalse(any(x.startswith("torch") or "stem_" in x for x in imports))

    def test_perturbed_source_denied_before_output(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"new"
            with self.assertRaises(ValueError):v.run(root,root,root,path)
            self.assertFalse(path.exists())

    def test_train_gate_counts_just_one_head(self):
        torch.manual_seed(18)
        x=torch.randn(64,384)
        y=(torch.arange(64)%2).long()
        gate,receipt=v.train_gate(x,y,[list(range(16))]*3)
        self.assertEqual(sum(p.numel() for p in gate.parameters()),385)
        self.assertEqual(receipt["steps"],3)
        self.assertEqual(receipt["examples"],48)
        self.assertEqual(receipt["label_counts"],[32,32])

    def test_train_gate_wrong_targets_denied(self):
        x=torch.randn(64,384)
        for y in (torch.ones(64),torch.full((64,),2,dtype=torch.long),torch.zeros(63,dtype=torch.long)):
            with self.subTest(kind=str(y.dtype),length=len(y)):
                with self.assertRaises(ValueError):v.train_gate(x,y,[])

    def test_route_chosen_head_only(self):
        x=torch.randn(16,384)
        parent=nn.Linear(384,4)
        split=v.v14.Split(parent,v.v14.fit_centers(x))
        continued=nn.Linear(384,4)
        gates={k:v.v16.make_gate() for k in ("unaligned_oof","geo_aligned_oof","logit_aligned_oof")}
        counts=[0,0]
        hooks=[split.heads[i].register_forward_pre_hook(lambda m,args,i=i:counts.__setitem__(i,counts[i]+len(args[0]))) for i in (0,1)]
        try:
            prob,routes=v.score_heads(x,split,continued,continued,v.v16.make_gate(),v.v16.make_gate(),gates,41)
        finally:
            for h in hooks:h.remove()
        self.assertEqual(set(prob),set(v.ARM_NAMES))
        self.assertEqual(set(routes),set(v.ROUTE_NAMES))
        # One and only one head is physically executed for each nonconstant routing arm.
        self.assertEqual(sum(counts),16*(len(v.ROUTE_NAMES)+2))

    def test_choose_no_growth_if_tied(self):
        x={k:.4 for k in v.ARM_NAMES}
        self.assertEqual(v.research_select(x,x),"extra_continued")
        self.assertEqual(independent.decide(x,x),"extra_continued")

    def test_choose_must_beat_unsplit(self):
        scores={k:.7 for k in v.ARM_NAMES}
        scores.update(extra_continued=.5,geo_aligned_oof=.495)
        old={k:.4 for k in v.ARM_NAMES}
        self.assertEqual(v.research_select(scores,old),"extra_continued")

    def test_choose_better_gate_only_calibration(self):
        scores={k:.7 for k in v.ARM_NAMES}
        scores.update(extra_continued=.5,geo_aligned_oof=.4)
        old={k:.4 for k in v.ARM_NAMES}
        self.assertEqual(v.research_select(scores,old),"geo_aligned_oof")
        self.assertEqual(independent.decide(scores,old),"geo_aligned_oof")

    def test_choose_old_task_veto(self):
        scores={k:.7 for k in v.ARM_NAMES}
        scores.update(extra_continued=.5,geo_aligned_oof=.3)
        old={k:.4 for k in v.ARM_NAMES}
        old["geo_aligned_oof"]=.6
        self.assertEqual(v.research_select(scores,old),"extra_continued")

    def test_numpy_route_matches_torch(self):
        x=torch.randn(25,384)
        centers=torch.stack((x[0],x[1]))
        self.assertTrue(np.array_equal(v.v14.assign(x,centers).numpy(),
                                      independent.assign(x.numpy(),centers.numpy())))

    def test_numpy_softmax_and_typed_gate(self):
        x=torch.randn(12,384)
        gate=v.v16.make_gate()
        with torch.no_grad():
            out=gate(x).numpy()
        state={k:p.detach().numpy() for k,p in gate.state_dict().items()}
        self.assertTrue(np.allclose(out,independent.linear(x.numpy(),state),atol=1e-6))

    def test_fold_malformed_denied(self):
        x=torch.randn(64,384)
        split=v.v14.Split(nn.Linear(384,4),torch.stack((x[0],x[1])))
        with self.assertRaises((KeyError,ValueError)):
            v.fold_permutations(x,x,split,"/missing",{},41,[list(range(32))]*4)

    def test_untrusted_tensors_denied(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"fixture.safetensors"
            path.write_bytes(b"wrong")
            with self.assertRaises(ValueError):
                v.load_v16_typed(d,"fixture",{"fixture":{"sha256":"0"*64,"state_scalars":1}})


@unittest.skipUnless(os.environ.get("HEPTA_V17_INPUTS") and os.environ.get("HEPTA_V17_V15")
                     and os.environ.get("HEPTA_V17_V16"),
                     "real archived V15/V16 weights unavailable; NOT an efficacy pass")
class Original(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.inputs=Path(os.environ["HEPTA_V17_INPUTS"])
        cls.v15=Path(os.environ["HEPTA_V17_V15"])
        cls.v16=Path(os.environ["HEPTA_V17_V16"])
        cls.v17=Path(cls.temp.name)/"v17"
        v.run(cls.inputs,cls.v15,cls.v16,cls.v17)
        cls.seal=v.v14.read_json(cls.v17/"sealed.json")
        cls.review=independent.review(cls.inputs,cls.v15,cls.v16,cls.v17)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def mutate(self,callback):
        with tempfile.TemporaryDirectory() as d:
            new=Path(d)/"v17"
            shutil.copytree(self.v17,new)
            payload=deepcopy(self.seal)
            callback(payload,new)
            (new/"sealed.json").write_bytes(v.v14.canonical(payload))
            with self.assertRaises((ValueError,KeyError,IndexError)):
                independent.review(self.inputs,self.v15,self.v16,new)

    def test_v15_v16_v17_physical_rosters(self):
        self.assertEqual(self.review["v15_model_files_verified"],58)
        self.assertEqual(self.review["v16_model_files_verified"],15)
        self.assertEqual(self.review["v17_gate_files_verified"],9)
        self.assertLess(self.review["max_probability_deviation"],5e-5)

    def test_same_original_fold_alignment(self):
        for item in self.seal["seeds"].values():
            self.assertEqual(sum(a["geo_flip"] for a in item["alignment"]),1)
            self.assertEqual(sum(a["logit_flip"] for a in item["alignment"]),2)
            self.assertEqual(item["selected_research_candidate"],"extra_continued")

    def test_blind_labels_never_in_admitted_features(self):
        meta=v.v14.read_json(self.inputs/"input.json")
        self.assertFalse(set(map(str,meta["partitions"]["holdout"]))&set(meta["labels"]))
        self.assertFalse(self.seal["held_labels_read"])
        self.assertIsNone(self.review["held_scores"])
        self.assertFalse(self.review["production_authorized"])

    def test_independent_replay_is_deterministic(self):
        self.assertEqual(self.review,independent.review(self.inputs,self.v15,self.v16,self.v17))

    def test_fake_production_denied(self):
        self.mutate(lambda r,d:r.__setitem__("production_authorized",True))

    def test_fake_future_denied(self):
        self.mutate(lambda r,d:r.__setitem__("future_utility",1.0))

    def test_fake_blind_score_denied(self):
        self.mutate(lambda r,d:r.__setitem__("held_scores",{"accuracy":1.0}))

    def test_source_digest_change_denied(self):
        self.mutate(lambda r,d:r.__setitem__("source_sha256","0"*64))

    def test_model_file_change_denied(self):
        def edit(r,d):
            name="41-geo_aligned_oof"
            path=d/(name+".safetensors")
            b=bytearray(path.read_bytes());b[-1]^=1;path.write_bytes(b)
        self.mutate(edit)

    def test_rehashed_wrong_model_denied_by_numeric(self):
        def edit(r,d):
            name="47-logit_aligned_oof"
            path=d/(name+".safetensors")
            from safetensors.numpy import load as load_numpy, save as save_numpy
            tensors=load_numpy(path.read_bytes())
            tensors["weight"][0,0]+=3.0
            b=save_numpy(tensors)
            path.write_bytes(b)
            r["models"][name]["sha256"]=v.v14.sha(b)
        self.mutate(edit)

    def test_alignment_flip_forgery_denied(self):
        self.mutate(lambda r,d:r["seeds"]["41"]["alignment"][1].__setitem__("geo_flip",0))

    def test_extra_trainer_claim_denied(self):
        self.mutate(lambda r,d:r["seeds"]["47"]["work"]["unaligned_oof"].__setitem__("steps",160))

    def test_bad_target_hash_denied(self):
        self.mutate(lambda r,d:r["seeds"]["41"]["targets_sha256"].__setitem__("geo_aligned_oof","0"*64))

    def test_bad_observed_calibration_denied(self):
        self.mutate(lambda r,d:r["seeds"]["41"]["calibration"]["constant1"].__setitem__("brier",0.0))

    def test_bad_oracle_denied(self):
        self.mutate(lambda r,d:r["seeds"]["41"].__setitem__("post_label_calibration_oracle_brier",0.0))

    def test_bad_route_denied(self):
        self.mutate(lambda r,d:r["seeds"]["53"]["calibration_routes"]["geo_aligned_oof"].__setitem__(0,2))

    def test_bad_blind_probability_denied(self):
        self.mutate(lambda r,d:r["seeds"]["53"]["blind_probabilities"]["geo_aligned_oof"][0].__setitem__(0,0.001))

    def test_extra_unregistered_file_denied(self):
        self.mutate(lambda r,d:(d/"fake.json").write_text("{}"))


if __name__=="__main__":unittest.main()
