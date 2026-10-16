"""V18 mechanistic and actual original-mmBERT archive negative/physical regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
import torch
from torch import nn

import stem_output_residual_v18 as p
import stem_output_residual_v18_review as review


class Mechanism(unittest.TestCase):
    def test_initial_behavior_and_parameter_budget(self):
        torch.manual_seed(2)
        parent = nn.Linear(384, 4)
        x = torch.randn(5, 384)
        original = parent(x).detach()
        for model, scalars in ((p.LinearResidual(parent), 3080), (p.GatedRank4(parent), 3485)):
            self.assertTrue(torch.equal(model(x), original))
            self.assertEqual(sum(t.numel() for t in model.state_dict().values()), scalars)
            self.assertEqual(len(list(model.buffers())), 2)
            self.assertTrue(all(not b.requires_grad for b in model.buffers()))

    def test_training_does_not_change_frozen_buffers(self):
        torch.manual_seed(6)
        parent = nn.Linear(384, 4)
        model = p.GatedRank4(parent)
        before = {k: v.clone() for k, v in model.state_dict().items() if k.startswith("base_")}
        x = torch.nn.functional.normalize(torch.randn(12, 384), dim=1)
        y = torch.arange(12) % 4
        rows = [torch.arange(8)] * 3
        ret = p.fit(model, x, y, rows)
        self.assertEqual(ret["updates"], 3)
        self.assertEqual(ret["examples"], 24)
        self.assertTrue(all(torch.equal(before[k], model.state_dict()[k]) for k in before))

    def test_research_selector_requires_strong_margin(self):
        cal = {k: {"brier": 0.6, "correct": 1, "count": 32} for k in p.ARMS}
        old = {k: {"brier": 0.2, "correct": 1, "count": 32} for k in p.ARMS}
        cal["continued160"]["brier"] = 0.52
        cal["gated_rank4_80"]["brier"] = 0.515
        self.assertEqual(p.research_selector(cal, old), "continued160")
        cal["gated_rank4_80"]["brier"] = 0.49
        self.assertEqual(p.research_selector(cal, old), "gated_rank4_80")
        old["gated_rank4_80"]["brier"] = 0.25
        self.assertEqual(p.research_selector(cal, old), "continued160")

    def test_no_forged_producer_and_create_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(ValueError):
                p.prepare(root / "missing.zip", root / "out")
            p.write_new(root / "one", b"ok")
            with self.assertRaises(ValueError):
                p.write_new(root / "one", b"changed")
            with self.assertRaises(ValueError):
                p.load_inputs(root)

    def test_duplicate_json_nonfinite_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, data in (("dupe", b'{"a":0,"a":1}'), ("nan", b'{"a":NaN}')):
                (root / name).write_bytes(data)
                with self.assertRaises(ValueError):
                    p.read_json(root / name)
            (root / "alias").symlink_to(root / "dupe")
            with self.assertRaises(ValueError):
                p.read_json(root / "alias")

    def test_numpy_reference_honors_output_residual(self):
        x = np.zeros((2, 384), dtype=np.float32)
        w = {"base_w": np.ones((4, 384), dtype=np.float32), "base_b": np.ones(4, dtype=np.float32),
             "delta.weight": np.zeros((4, 384), dtype=np.float32),
             "delta.bias": np.zeros(4, dtype=np.float32)}
        self.assertTrue(np.array_equal(review.forward(w, "linear_residual80", x), np.ones((2, 4))))
        w["delta.bias"][0] = 2
        self.assertTrue(np.all(review.forward(w, "linear_residual80", x)[:, 0] == 3))

    def test_nonfinite_review_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            pth = Path(d) / "rec.json"
            pth.write_text('{"a":Infinity}')
            with self.assertRaises(ValueError):
                review.safe_json(pth, 1000)


class OriginalPhysical(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = os.environ.get("HEPTA_V18_ORIGINAL_ZIP")
        if not s:
            raise unittest.SkipTest("original positive requires exact archived Actions bytes")
        cls.archive = Path(s)

    def test_real_training_two_process_replay_and_independent_review(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inp = root / "data"
            p.prepare(self.archive, inp)
            self.assertEqual(len(p.load_inputs(inp)[1]["labels"]), 96)
            snapshots = []
            for n in ("run_a", "run_b"):
                out = root / n
                result = p.run(inp, out)
                self.assertEqual(result["total_updates"], 1464)
                self.assertEqual(len(result["model_files"]), 18)
                audited = review.verify(self.archive, inp, out)
                self.assertLess(audited["maximum_numerical_deviation"], 3e-6)
                self.assertIsNone(audited["future_gain"])
                self.assertFalse(audited["production_authorized"])
                snapshots.append((result, out))
            first, second = snapshots
            self.assertEqual({k: v["sha256"] for k, v in first[0]["model_files"].items()},
                             {k: v["sha256"] for k, v in second[0]["model_files"].items()})
            for seed in ("41", "47", "53"):
                for arm in p.ARMS:
                    self.assertEqual(first[0]["seeds"][seed]["blind_probabilities"][arm],
                                     second[0]["seeds"][seed]["blind_probabilities"][arm])
                self.assertEqual(first[0]["seeds"][seed]["selected_calibration_only"], "continued160")
                self.assertAlmostEqual(first[0]["seeds"][seed]["calibration"]["continued80"]["brier"],
                                       first[0]["seeds"][seed]["calibration"]["linear_residual80"]["brier"],
                                       places=6)

    def test_negative_tamper_model_report_and_blind_label(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inp, out = root / "inputs", root / "out"
            p.prepare(self.archive, inp)
            p.run(inp, out)
            polluted = root / "dirty"
            shutil.copytree(inp, polluted)
            meta = json.loads((polluted / "meta.json").read_text())
            blind_id = meta["partitions"]["holdout"][0]
            meta["labels"][str(blind_id)] = 1
            (polluted / "meta.json").write_bytes(p.canonical(meta))
            with self.assertRaises(ValueError):
                p.load_inputs(polluted)
            changed = root / "changed"
            shutil.copytree(out, changed)
            report = json.loads((changed / "predictions.json").read_text())
            report["seeds"]["41"]["calibration"]["continued160"]["brier"] += 0.1
            (changed / "predictions.json").write_bytes(p.canonical(report))
            with self.assertRaises(ValueError):
                review.verify(self.archive, inp, changed)
            changed2 = root / "changed2"
            shutil.copytree(out, changed2)
            name = "41-gated_rank4_80.safetensors"
            raw = bytearray((changed2 / name).read_bytes())
            raw[-1] ^= 1
            (changed2 / name).write_bytes(raw)
            with self.assertRaises(ValueError):
                review.verify(self.archive, inp, changed2)
            (out / "alias").symlink_to(out / name)
            with self.assertRaises(ValueError):
                review.verify(self.archive, inp, out)


if __name__ == "__main__":
    unittest.main()
