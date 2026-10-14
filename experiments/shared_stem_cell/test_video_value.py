"""Train/critic/calibration source separation and physical value-of-info work."""
from pathlib import Path
import hashlib
import json
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import public_video as source
from experiments.shared_stem_cell import video_anytime as anytime
from experiments.shared_stem_cell import video_temporal as temporal
from experiments.shared_stem_cell import video_value as value
from experiments.shared_stem_cell import audit_video_value
from experiments.shared_stem_cell.test_public_video import FakeTower, PublicVideoTests
from experiments.shared_stem_cell.test_video_temporal import paired_features, FakeBase


class ValueMechanics(unittest.TestCase):
    def setUp(self): torch.set_num_threads(1)

    def fitted(self):
        item, labels = paired_features(8, width=3)
        model, _ = anytime.fit(item, labels, seed=29)
        exits = anytime.probabilities(model, item)
        critic = value.fit_value(exits, labels)
        return model, item, labels, exits, critic

    def refs(self, n):
        return [[f"{(j*8+i)%256:02x}" + "0"*62 for i in range(8)] for j in range(n)]

    def test_exact_ridge_optimality_and_bounded_gain_targets(self):
        _, _, labels, exits, critic = self.fitted()
        self.assertEqual(set(critic["coefficients"]), {"2", "4", "6"})
        self.assertEqual({len(v) for v in critic["coefficients"].values()}, {5})
        self.assertTrue(all(row["ridge_equation_abs_max"] < 1e-9
                        for row in critic["diagnostics"].values()))
        self.assertEqual(critic["diagnostics"]["2"]["rows"], len(labels))
        for depth in (2, 4, 6):
            estimate = value.estimate(exits[depth], depth, critic)
            self.assertEqual(tuple(estimate.shape), (len(labels),))
            self.assertTrue(bool((estimate.abs() <= 1).all()))

    def test_value_route_has_same_reader_weights_and_no_gold_argument(self):
        _, _, labels, exits, critic = self.fitted()
        picks = value.route_value(exits, critic, 0.02)
        self.assertEqual(len(picks), len(labels))
        self.assertTrue(all(depth in value.DEPTHS and pred in (0, 1) for depth, pred in picks))
        labels_flipped = 1 - labels
        self.assertEqual(picks, value.route_value(exits, critic, 0.02))
        self.assertFalse(torch.equal(labels, labels_flipped))

    def test_value_and_confidence_calibration_strong_fixed_floor(self):
        _, _, y, exits, critic = self.fitted()
        selection = value.select(exits, y, self.refs(len(y)), critic)
        floor = selection["calibration_correct_floor"]
        for arm in value.ARMS:
            self.assertEqual(selection["calibration_profiles"][arm]["cases"], len(y))
            self.assertGreaterEqual(selection["calibration_profiles"][arm]["correct"], floor)
        self.assertEqual(len(selection["grids"]["value"]), len(value.COSTS))
        self.assertEqual(len(selection["grids"]["confidence"]), len(anytime.THRESHOLDS))

    def test_value_fallback_when_critic_never_matches_best_fixed(self):
        y = torch.tensor([0, 1], dtype=torch.long)
        wrong = torch.tensor([[.01, .99], [.99, .01]], dtype=torch.float32)
        right = torch.tensor([[.99, .01], [.01, .99]], dtype=torch.float32)
        exits = {2: wrong.clone(), 4: right.clone(), 6: wrong.clone(), 8: wrong.clone()}
        critic = {"schema": "hepta.video-value-critic.v1", "coefficients": {
            str(depth): [0.0]*5 for depth in value.DEPTHS[:-1]}}
        selection = value.select(exits, y, self.refs(2), critic)
        self.assertEqual(selection["policies"]["value"]["kind"], "fixed")
        self.assertEqual(selection["policies"]["value"]["depth"], 4)
        self.assertEqual(selection["calibration_correct_floor"], 2)

    def test_invalid_inputs_rejected_before_encoders(self):
        model, _, _, _, critic = self.fitted()
        refs = [{"path": f"{i}.png", "sha256": f"{i:02x}"+"0"*62,
                 "timestamp_us": i*40000} for i in range(8)]
        cache = temporal.FrameCacheTowers(FakeBase())
        bad = ({"kind":"value","price":.022}, {"kind":"fixed","depth":3},
               {"kind":"confidence","threshold":.123}, {"kind":"unknown"})
        for policy in bad:
            with self.assertRaises(e.InputError):
                value.stream_one(model, refs, Path('.'), cache, policy, critic)
        self.assertEqual(cache.physical_video_calls, 0)
        with self.assertRaises(e.InputError): value.observable(torch.ones(2,2), 8)

    def test_negative_or_zero_expected_gain_physically_stops_after_two(self):
        model, _, _, _, critic = self.fitted()
        zero = {**critic, "coefficients": {str(d):[0.0]*5 for d in value.DEPTHS[:-1]}}
        refs = [{"path":f"{i}.png", "sha256":f"{i:02x}"+"0"*62,
                 "timestamp_us":i*40000} for i in range(8)]
        tower = temporal.FrameCacheTowers(FakeBase())
        row = value.stream_one(model, refs, Path('.'), tower,
                               {"kind":"value","price":0.0},zero)
        self.assertEqual(row["depth"], 2)
        self.assertEqual(tower.physical_video_calls, 1)
        self.assertEqual(len(tower.cache), 2)
        self.assertNotIn(refs[2]["sha256"],tower.cache)
        tower2 = temporal.FrameCacheTowers(FakeBase())
        row2 = value.stream_one(model, refs, Path('.'), tower2,
                                {"kind":"fixed","depth":8},critic)
        self.assertEqual(row2["depth"], 8)
        self.assertEqual(tower2.physical_video_calls, 4)

    def test_holdout_labels_cannot_change_critic_or_calibration_selection(self):
        _, _, y, exits, critic = self.fitted()
        prior = value.select(exits, y, self.refs(len(y)),critic)
        after = value.select(exits, y, self.refs(len(y)),critic)
        self.assertEqual(prior, after)
        # There is deliberately no held-out label argument to value.route_value/stream_one.
        self.assertEqual(value.route_value(exits,critic,.05), value.route_value(exits,critic,.05))


class ValueEndToEnd(unittest.TestCase):
    def setUp(self):
        self.fixture = PublicVideoTests()
        self.fixture.setUp()
        self.root = self.fixture.root / "study"
        self.root.mkdir()
        dataset, cohort = source.stage(self.root, _read=self.fixture.read,
             _decode=self.fixture.decode, inventory=self.fixture.inventory,
             revision=self.fixture.revision, readme_blob=self.fixture.readme_blob)
        (self.root/"vision/model").mkdir(parents=True)
        manifest = {"schema":"hepta.shared-stem-media.v1", "classes":2, "steps":80,
            "seed":17,"temporal":False,"video_profile":"paired_temporal_order_v1",
            "dataset":dataset,"cohort":cohort,"models":{"clip":{"path":"vision/model",
            "revision":"b"*40,"files":{}}}}
        e.write_once(self.root/"manifest.json",manifest)

    def tearDown(self): self.fixture.tearDown()

    def test_real_optimizer_disjoint_critic_and_all_physical_controls(self):
        report = value.run(self.root/"manifest.json",self.root/"value",_tower_factory=FakeTower)
        selection = e.decode((self.root/"value/selection.json").read_bytes())
        self.assertEqual(len(selection["reader_ids"]),32)
        self.assertEqual(len(selection["critic_ids"]),16)
        self.assertEqual(len(selection["calibration_ids"]),16)
        self.assertEqual(len(set(selection["reader_ids"] + selection["critic_ids"] +
                                 selection["calibration_ids"])),64)
        self.assertEqual(set(report["scores"]),set(value.ARMS))
        self.assertEqual({s["cases"] for s in report["scores"].values()}, {16})
        self.assertEqual(report["physical_work"]["fixed_8"]["unique_frames"],64)
        self.assertEqual(report["physical_work"]["fixed_2"]["unique_frames"],32)
        self.assertFalse(report["general_ndu_fbsde_established"])
        self.assertFalse(report["quality_advantage_established"])
        self.assertEqual(report["reader_parameters"]>0,True)
        saved=e.decode((self.root/"value/predictions.json").read_bytes())
        self.assertEqual(len(saved["records"]["value"]),16)
        self.assertGreaterEqual(sum(x["depth"] for x in saved["records"]["value"]),32)

    def test_independent_auditor_recalculates_sealed_stream_and_refuses_forged_cost(self):
        value.run(self.root/"manifest.json",self.root/"audit-case",_tower_factory=FakeTower)
        # Audit helper requires the conventional /value directory.
        (self.root/"audit-case").rename(self.root/"value")
        summary = audit_video_value.audit(self.root)
        self.assertEqual(summary["status"],"audited_archived_consistency_only")
        self.assertEqual(summary["holdout"]["value"]["cases"],16)
        path=self.root/"value/predictions.json"
        report_path=self.root/"value/report.json"
        payload=json.loads(path.read_bytes())
        payload["physical_work"]["value"]["physical_video_calls"] += 1
        tampered=e.canonical(payload)
        path.write_bytes(tampered)
        report=json.loads(report_path.read_bytes())
        report["prediction_sha256"]=hashlib.sha256(tampered).hexdigest()
        report["physical_work"]["value"]["physical_video_calls"] += 1
        report_path.write_bytes(e.canonical(report))
        with self.assertRaisesRegex(ValueError,"physical frame cache cost drift"):
            audit_video_value.audit(self.root)

    def test_changed_heldout_labels_do_not_change_presealed_selection_or_route(self):
        value.run(self.root/"manifest.json",self.root/"base",_tower_factory=FakeTower)
        original=value.media.read_cases
        def altered(*args,**kwargs):
            cases,labels=original(*args,**kwargs)
            labels=dict(labels)
            for case in cases:
                if case.split=="holdout": labels[case.case_id]=1-labels[case.case_id]
            return cases,labels
        with patch.object(value.media,"read_cases",side_effect=altered):
            value.run(self.root/"manifest.json",self.root/"flipped",_tower_factory=FakeTower)
        old=e.decode((self.root/"base/selection.json").read_bytes())
        new=e.decode((self.root/"flipped/selection.json").read_bytes())
        for k in ("policies", "grids", "model_sha256"):
            self.assertEqual(old[k],new[k])
        self.assertEqual(old["critic"]["coefficients"],new["critic"]["coefficients"])
        self.assertEqual(old["critic"]["diagnostics"],new["critic"]["diagnostics"])
        preds=lambda loc:e.decode((self.root/loc/"predictions.json").read_bytes())["records"]
        for arm in value.ARMS:
            self.assertEqual([r["prediction"] for r in preds("base")[arm]],
                             [r["prediction"] for r in preds("flipped")[arm]])


if __name__ == "__main__": unittest.main()
