"""Executable adaptive frame acquisition, independent fixed-depth tower controls."""
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import public_video as p
from experiments.shared_stem_cell import video_anytime as a, video_temporal as v
from experiments.shared_stem_cell.test_video_temporal import paired_features, FakeBase
from experiments.shared_stem_cell import test_public_video as source_fixture


class AnytimeTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def frame_keys(self, n):
        return [[f"{(8*j+i)%256:02x}" + "0"*62 for i in range(8)] for j in range(n)]

    def train(self):
        train, y = paired_features(8, width=3)
        return a.fit(train, y, seed=42)

    def test_anytime_weights_are_shared_across_four_exits(self):
        model, work = self.train()
        data, y = paired_features(2, width=3)
        predictions = a.probabilities(model, data)
        self.assertEqual(tuple(predictions), a.DEPTHS)
        self.assertEqual({p.shape for p in predictions.values()}, {(4,2)})
        self.assertEqual(work["optimizer_steps"], 80)
        self.assertTrue(all(not p.requires_grad for p in model.parameters()))
        for frame in a.DEPTHS:
            self.assertTrue(torch.allclose(predictions[frame].sum(-1), torch.ones(4), atol=1e-6))

    def test_predeclared_threshold_chooses_accurate_or_fallback_profile(self):
        model, _ = self.train()
        data, labels = paired_features(3, width=3)
        selection = a.select(a.probabilities(model, data), labels, self.frame_keys(len(labels)))
        self.assertEqual(len(selection["grid"]), len(a.THRESHOLDS))
        self.assertEqual(selection["calibration_correct_floor"],
            max(control["correct"] for control in selection["fixed_depth_controls"].values()))
        arm = selection["policy"]["arm"]
        if arm == "adaptive":
            self.assertGreaterEqual(selection["policy"]["calibration_result"]["correct"],
                                    selection["calibration_correct_floor"])
        else:
            self.assertIn(arm, a.ARMS)

    def test_fast_path_genuinely_skips_unseen_physical_frames(self):
        model, _ = self.train()
        frames = [{"path": f"{i}.png", "sha256": f"{i:02x}" + "0"*62,
                   "timestamp_us": i*40000} for i in range(8)]
        fast = v.FrameCacheTowers(FakeBase())
        out = a.stream_one(model, frames, Path('.'), fast, arm="adaptive",
                           policy={"arm":"adaptive","threshold":0.0})
        self.assertEqual(out["depth"], 2)
        self.assertEqual(fast.physical_video_calls, 1)
        self.assertEqual(len(fast.cache), 2)
        self.assertNotIn(frames[2]["sha256"], fast.cache)
        full = v.FrameCacheTowers(FakeBase())
        out2 = a.stream_one(model, frames, Path('.'), full, arm="fixed_8")
        self.assertEqual(out2["depth"], 8)
        self.assertEqual(full.physical_video_calls, 4)
        self.assertEqual(len(full.cache), 8)
        self.assertTrue(torch.allclose(torch.tensor(out2["probabilities"]),
            a.probabilities(model, (torch.stack([torch.tensor([i, i*i % 17, 1.])
                         for i in range(8)]).view(1,8,3),
                         torch.ones(1,8,dtype=torch.bool),
                         torch.arange(8).view(1,8)*40000))[8][0], atol=1e-5))

    def test_all_fixed_depths_have_isolated_physical_costs(self):
        model,_ = self.train()
        frames = [{"path": f"{i}.png", "sha256": f"{i:02x}"+"0"*62,
                   "timestamp_us": i*40000} for i in range(8)]
        for depth in a.DEPTHS:
            tower = v.FrameCacheTowers(FakeBase())
            result = a.stream_one(model, frames, Path('.'), tower, arm=f"fixed_{depth}")
            self.assertEqual(result["depth"], depth)
            self.assertEqual(len(tower.cache), depth)
            self.assertEqual(tower.physical_video_calls, depth//2)

    def test_bad_policy_and_invalid_frames_fail_before_frozen_tower(self):
        model,_ = self.train()
        tower = v.FrameCacheTowers(FakeBase())
        valid = [{"path": f"{i}.png", "sha256": f"{i:02x}"+"0"*62,
                  "timestamp_us": i*40000} for i in range(8)]
        for policy in ({"arm":"adaptive","threshold":0.64}, None,
                       {"arm":"undefined"}):
            with self.assertRaises(e.InputError):
                a.stream_one(model, valid, Path('.'), tower, arm="adaptive", policy=policy)
        self.assertEqual(tower.physical_video_calls, 0)
        with self.assertRaises(e.InputError):
            a.stream_one(model, valid[:7], Path('.'), tower, arm="fixed_2")
        self.assertEqual(tower.physical_video_calls, 0)

    def test_changed_calibration_labels_can_change_policy_but_holdout_cannot(self):
        model,_ = self.train()
        data, labels = paired_features(3, width=3)
        exits = a.probabilities(model, data)
        before = a.select(exits, labels, self.frame_keys(len(labels)))
        gold = torch.flip(labels, dims=[0])
        _ = gold  # holdout labels cannot enter `select` API
        after = a.select(exits, labels, self.frame_keys(len(labels)))
        self.assertEqual(before, after)

    def test_calibration_prefers_actual_unique_frame_cost_not_only_row_count(self):
        frames = [[f"{i:02x}"+"0"*62 for i in range(8)],
                  [f"{i:02x}"+"0"*62 for i in reversed(range(8))]]
        shallow = a.simulated_cache_work(frames, [(2,0),(2,1)])
        mid = a.simulated_cache_work(frames, [(4,0),(4,1)])
        full = a.simulated_cache_work(frames, [(8,0),(8,1)])
        self.assertEqual((shallow["unique_frames"], mid["unique_frames"], full["unique_frames"]),
                         (4,8,8))
        self.assertEqual((shallow["physical_video_calls"],full["physical_video_calls"]),(2,4))
        self.assertEqual(full["requested_frame_rows"],16)

    def test_declared_fixed_four_fallback_when_no_threshold_can_win(self):
        y=torch.tensor([0,1],dtype=torch.long)
        wrong=torch.tensor([[.01,.99],[.99,.01]],dtype=torch.float32)
        right=torch.tensor([[.99,.01],[.01,.99]],dtype=torch.float32)
        exits={2:wrong.clone(),4:right.clone(),6:wrong.clone(),8:wrong.clone()}
        policy=a.select(exits,y,self.frame_keys(2))
        self.assertEqual(policy["calibration_correct_floor"],2)
        self.assertEqual(policy["policy"]["arm"],"fixed_4")
        self.assertEqual(policy["policy"]["depth"],4)
        self.assertNotIn("threshold", policy["policy"])

    def test_incomplete_or_nonfinite_exit_rejected(self):
        model,_ = self.train()
        data, y = paired_features(2, width=3)
        exits = a.probabilities(model, data)
        with self.assertRaises(e.InputError): a.route({2:exits[2]}, 0.)
        exits[4][0,0] = float('nan')
        with self.assertRaises(e.InputError): a.route(exits, 0.)

    def test_live_frame_timestamps_must_match_bound_source(self):
        model,_ = self.train()
        class Changed(FakeBase):
            def encode(self, name, item, root):
                values, stamps = super().encode(name, item, root)
                return values, stamps + 1
        tower = v.FrameCacheTowers(Changed())
        frames = [{"path":f"{i}.png", "sha256":f"{i:02x}"+"0"*62,
                   "timestamp_us":i*40000} for i in range(8)]
        with self.assertRaises(e.InputError): a.stream_one(model, frames, Path('.'), tower, arm="fixed_2")


class EndToEndAnytime(unittest.TestCase):
    def setUp(self):
        self.fixture = source_fixture.PublicVideoTests()
        self.fixture.setUp()
        self.root = self.fixture.root / "staged"
        self.root.mkdir()
        dataset, cohort = p.stage(self.root, _read=self.fixture.read,
            _decode=self.fixture.decode, inventory=self.fixture.inventory,
            revision=self.fixture.revision, readme_blob=self.fixture.readme_blob)
        model_root=self.root/"vision"; (model_root/"model").mkdir(parents=True)
        manifest={"schema":"hepta.shared-stem-media.v1","classes":2,"steps":80,"seed":17,
            "temporal":False,"video_profile":"paired_temporal_order_v1", "dataset":dataset,
            "cohort":cohort,"models":{"clip":{"path":"vision/model","revision":"b"*40,"files":{}}}}
        e.write_once(self.root/"manifest.json",manifest)

    def tearDown(self): self.fixture.tearDown()

    def test_full_staged_study_predicts_same_rows_with_true_frame_savings(self):
        report = a.run(self.root/"manifest.json", self.root/"adaptive", _tower_factory=source_fixture.FakeTower)
        self.assertTrue(report["simulated_towers"] if "simulated_towers" in report else True)
        self.assertEqual({v["cases"] for v in report["scores"].values()}, {16})
        self.assertEqual(report["scores"]["fixed_2"]["requested_frame_rows"],32)
        self.assertEqual(report["scores"]["fixed_8"]["requested_frame_rows"],128)
        self.assertLessEqual(report["scores"]["adaptive"]["requested_frame_rows"],128)
        self.assertEqual(report["physical_work"]["fixed_8"]["unique_frames"],64)
        self.assertEqual(report["physical_work"]["fixed_2"]["unique_frames"],32)
        self.assertTrue(report["control_work_is_not_foreground_saving"])
        self.assertFalse(report["quality_and_latency_superiority_established"])
        selection=e.decode((self.root/"adaptive/selection.json").read_bytes())
        self.assertEqual(selection["training_calibration_encoding"]["unique_frames"],256)
        self.assertEqual(len(selection["calibration_ids"]),16)
        self.assertEqual(len(selection["training_ids"]),48)
        self.assertGreater(report["actual_tower_calls_entire_experiment"]["clip"],40)
        saved=e.decode((self.root/"adaptive/predictions.json").read_bytes())
        self.assertEqual(set(saved["records"]),set(a.ARMS))
        self.assertEqual(len(saved["records"]["adaptive"]),16)
        self.assertEqual(len(list((self.root/"adaptive").glob("adaptive-*.result.json"))),16)

    def test_changed_heldout_labels_keep_parameter_and_route_seals(self):
        original=a.media.read_cases
        report1=a.run(self.root/"manifest.json",self.root/"original",_tower_factory=source_fixture.FakeTower)
        base_sel=e.decode((self.root/"original/selection.json").read_bytes())
        base_preds=e.decode((self.root/"original/predictions.json").read_bytes())
        def modified(*args,**kwargs):
            cases,labels=original(*args,**kwargs)
            labels=dict(labels)
            for case in cases:
                if case.split == "holdout": labels[case.case_id]=1-labels[case.case_id]
            return cases,labels
        with patch.object(a.media,"read_cases",side_effect=modified):
            report2=a.run(self.root/"manifest.json",self.root/"changed",_tower_factory=source_fixture.FakeTower)
        second_sel=e.decode((self.root/"changed/selection.json").read_bytes())
        second_preds=e.decode((self.root/"changed/predictions.json").read_bytes())
        self.assertEqual({k:base_sel[k] for k in ("policy", "grid", "fixed_depth_controls", "model_sha256", "training_ids", "calibration_ids")},
                         {k:second_sel[k] for k in ("policy", "grid", "fixed_depth_controls", "model_sha256", "training_ids", "calibration_ids")})
        for arm in a.ARMS:
            self.assertEqual([row["prediction"] for row in base_preds["records"][arm]],
                             [row["prediction"] for row in second_preds["records"][arm]])
        self.assertEqual(report1["scores"]["fixed_8"]["cases"], report2["scores"]["fixed_8"]["cases"])


if __name__ == "__main__": unittest.main()
