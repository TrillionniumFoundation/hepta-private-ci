"""Independent source-split batch calibration with real Head training and fake vision tower."""
from pathlib import Path
import hashlib
import json
import unittest

import torch

from experiments.shared_stem_cell import execution as e, media_execution as media
from experiments.shared_stem_cell import video_anytime as anytime
from experiments.shared_stem_cell import video_batch as batch
from experiments.shared_stem_cell import video_batch_calibration as bc
from experiments.shared_stem_cell import video_temporal as temporal
from experiments.shared_stem_cell import video_value as value
from experiments.shared_stem_cell.test_video_batch import examples, critic
from experiments.shared_stem_cell.test_video_temporal import FakeBase


class BatchCalibrationTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.cases = examples()
        self.model = anytime.AnytimeCell(3).eval().requires_grad_(False)
        self.ids = [[frame["sha256"] for frame in c.inputs["video"]] for c in self.cases]
        towers = temporal.FrameCacheTowers(FakeBase())
        observation = media.extract(towers, self.cases, Path("."))["video"]
        self.exits = anytime.probabilities(self.model, observation)
        self.gold = torch.tensor([i%2 for i in range(len(self.cases))], dtype=torch.long)

    def test_exact_microbatch_cache_replay_matches_physical_runtime_for_all_kinds(self):
        policies = ({"kind":"fixed", "depth":2}, {"kind":"fixed", "depth":8},
                    {"kind":"confidence", "threshold":.75},
                    {"kind":"value", "price":.02},
                    {"kind":"cache_value", "price":.02})
        for policy in policies:
            with self.subTest(policy=policy):
                planned=bc.replay(self.exits,self.ids,critic(),policy)
                actual=batch.stream_cases(self.model,self.cases,Path("."),FakeBase(),policy,critic())
                self.assertEqual(planned["picks"],
                    [(r["depth"],r["prediction"]) for r in actual["records"]])
                for key in ("physical_video_calls","unique_frames","cache_hits","requested_frame_rows"):
                    self.assertEqual(planned[key],actual["physical_work"][key])

    def test_batch_cache_changes_price_without_future_pixels_or_labels(self):
        keys=[f"{i:02x}"+"0"*62 for i in range(8)]
        ids=[keys, [keys[i] for i in (2,3,0,1,4,5,6,7)]]
        exits={d:torch.tensor([[.8,.2],[.8,.2]],dtype=torch.float32) for d in anytime.DEPTHS}
        high=critic(.02)
        policy={"kind":"cache_value","price":.05}
        grouped=bc.replay(exits,ids,high,policy,batch_size=2)
        scalar=bc.replay(exits,ids,high,policy,batch_size=1)
        self.assertEqual(grouped["picks"][0][0],4)
        self.assertEqual(scalar["picks"][0][0],2)
        self.assertFalse("labels" in bc.replay.__code__.co_varnames)

    def test_sealed_selection_depends_only_on_calibration_labels(self):
        normal=bc.select(self.exits,self.gold,self.ids,critic())
        self.assertEqual(normal["schema"],"hepta.video-batch-calibration.v1")
        self.assertEqual(set(normal["policies"]),set(bc.FAMILIES))
        self.assertEqual(normal["batch_size"],4)
        self.assertIn(normal["research_best_arm"],(*[f"fixed_{d}" for d in anytime.DEPTHS],*bc.FAMILIES))
        self.assertTrue(normal["selection_uses_holdout_labels"] is False)
        for family,row in normal["family_profiles"].items():
            self.assertGreaterEqual(row["correct"], normal["best_fixed_correct"])
        heldout_labels=[1-y for y in self.gold.tolist()]
        before=json.dumps(normal,sort_keys=True)
        self.assertEqual(before,json.dumps(bc.select(self.exits,self.gold,self.ids,critic()),sort_keys=True))
        self.assertNotIn("heldout_labels",str(bc.select.__code__.co_varnames))
        self.assertEqual(len(heldout_labels),len(self.cases))

    def test_no_eligible_adaptive_grid_falls_back_to_best_fixed_depth(self):
        y=torch.tensor([0,1],dtype=torch.long)
        wrong=torch.tensor([[.01,.99],[.99,.01]],dtype=torch.float32)
        right=torch.tensor([[.99,.01],[.01,.99]],dtype=torch.float32)
        exits={2:wrong.clone(),4:right.clone(),6:wrong.clone(),8:wrong.clone()}
        chosen=bc.select(exits,y,self.ids[:2],critic())
        self.assertEqual(chosen["best_fixed_correct"],2)
        self.assertEqual(chosen["best_fixed_depth"],4)
        self.assertEqual(chosen["policies"]["value"]["kind"],"fixed")
        self.assertEqual(chosen["policies"]["value"]["depth"],4)
        self.assertEqual(chosen["policies"]["cache_value"]["depth"],4)
        self.assertEqual(chosen["policies"]["confidence"]["depth"],4)

    def test_bad_identity_rows_and_not_predeclared_policy_reject(self):
        for ids in (self.ids[:-1], [*self.ids[:-1],["0"*64]*7],
                    [*self.ids[:-1],["malformed"]*8]):
            with self.assertRaises(e.InputError): bc.select(self.exits,self.gold,ids,critic())
        for policy in ({"kind":"confidence","threshold":.123},
                       {"kind":"fixed","depth":3},{"kind":"cache_value","price":.123}):
            with self.assertRaises(e.InputError):bc.replay(self.exits,self.ids,critic(),policy)
        with self.assertRaises(e.InputError):bc.replay(self.exits,self.ids,critic(),{"kind":"fixed","depth":2},batch_size=True)

    def test_bad_model_outputs_and_incorrect_targets_reject(self):
        bad=dict(self.exits)
        broken=self.exits[2].clone();broken[0,0]=float("nan");bad[2]=broken
        with self.assertRaises(e.InputError):bc.select(bad,self.gold,self.ids,critic())
        with self.assertRaises(e.InputError):bc.select(self.exits,self.gold[:-1],self.ids,critic())
        with self.assertRaises(e.InputError):bc.select(self.exits,torch.tensor([5]*len(self.gold)),self.ids,critic())

    def test_fixed_calibration_cost_tracks_one_dispatch_per_active_depth(self):
        two=bc.replay(self.exits,self.ids,critic(),{"kind":"fixed","depth":2})
        eight=bc.replay(self.exits,self.ids,critic(),{"kind":"fixed","depth":8})
        self.assertEqual(two["requested_frame_rows"],2*len(self.ids))
        self.assertEqual(eight["requested_frame_rows"],8*len(self.ids))
        self.assertLessEqual(two["physical_video_calls"],eight["physical_video_calls"])


class BatchCalibratedArchiveTests(unittest.TestCase):
    def setUp(self):
        from experiments.shared_stem_cell.test_video_value import ValueEndToEnd
        self.fixture=ValueEndToEnd()
        self.fixture.setUp()
        self.root=self.fixture.root

    def tearDown(self):self.fixture.tearDown()

    def study(self):
        from experiments.shared_stem_cell.test_public_video import FakeTower
        return value.run(self.root/"manifest.json",self.root/"value",
                         _tower_factory=FakeTower,microbatch_shadow=True)

    def test_full_train_holdout_sealed_batch_native_and_independent_recalculation(self):
        from experiments.shared_stem_cell import audit_video_batch_calibration as audit
        report=self.study()
        checked=audit.audit(self.root)
        self.assertEqual(set(checked["batch_native"]),set(bc.FAMILIES))
        self.assertEqual(checked["batch_native_extra_calls"],report["microbatch_native_total_extra_calls"])
        self.assertEqual(checked["legacy_batch_extra_calls"],report["microbatch_shadow_total_extra_calls"])
        self.assertEqual(set(report["microbatch_native_scores"]),set(bc.FAMILIES))
        self.assertTrue((self.root/"value/batch/predictions.json").exists())
        selected=e.decode((self.root/"value/selection.json").read_bytes())
        self.assertEqual(selected["microbatch_calibration"]["batch_size"],4)
        self.assertEqual(selected["microbatch_calibration"]["reader_retrained"],False)
        self.assertEqual({q["cases"] for q in report["microbatch_native_scores"].values()},{16})

    def test_heldout_target_changes_cannot_change_presealed_batch_choice(self):
        from copy import deepcopy
        from unittest.mock import patch
        from experiments.shared_stem_cell.test_public_video import FakeTower
        self.study()
        prior=e.decode((self.root/"value/selection.json").read_bytes())
        original=value.media.read_cases
        def altered(*args,**kwargs):
            cases,labels=original(*args,**kwargs)
            targets=deepcopy(labels)
            for case in cases:
                if case.split=="holdout":targets[case.case_id]=1-targets[case.case_id]
            return cases,targets
        with patch.object(value.media,"read_cases",side_effect=altered):
            other=value.run(self.root/"manifest.json",self.root/"relabeled",
                            _tower_factory=FakeTower,microbatch_shadow=True)
        changed=e.decode((self.root/"relabeled/selection.json").read_bytes())
        self.assertEqual(prior["microbatch_calibration"],changed["microbatch_calibration"])
        self.assertEqual(prior["policies"],changed["policies"])
        self.assertEqual(prior["model_sha256"],changed["model_sha256"])
        self.assertNotEqual(other["scores"]["fixed_2"]["correct"],-1)

    def test_independent_auditor_rejects_forged_calls_even_after_rehash(self):
        from experiments.shared_stem_cell import audit_video_batch_calibration as audit
        self.study()
        path=self.root/"value/batch/predictions.json"
        data=json.loads(path.read_bytes());data["batch_native"]["cache_value"]["events"][0]["physical_video_calls"]+=1
        path.write_bytes(e.canonical(data))
        (self.root/"value/batch/batch-native-cache_value.json").write_bytes(e.canonical(data["batch_native"]["cache_value"]))
        report_path=self.root/"value/report.json";report=json.loads(report_path.read_bytes())
        report["microbatch_shadow"]["predictions_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
        report_path.write_bytes(e.canonical(report))
        with self.assertRaisesRegex(ValueError,"physical event/count drift"):
            audit.audit(self.root)

    def test_independent_auditor_rejects_forged_selection_even_with_rehash(self):
        from experiments.shared_stem_cell import audit_video_batch_calibration as audit
        self.study()
        selected_path=self.root/"value/selection.json"
        data=json.loads(selected_path.read_bytes())
        data["microbatch_calibration"]["grids"]["cache_value"][0]["physical_video_calls"]+=1
        selected_path.write_bytes(e.canonical(data))
        report_path=self.root/"value/report.json";report=json.loads(report_path.read_bytes())
        report["selection_sha256"]=hashlib.sha256(selected_path.read_bytes()).hexdigest()
        report_path.write_bytes(e.canonical(report))
        with self.assertRaises(ValueError):audit.audit(self.root)


if __name__=="__main__":unittest.main()
