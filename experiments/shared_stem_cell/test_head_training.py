"""Independent AdamW equivalence, budgets, isolation and real artifact integration."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import head_training as h
from experiments.shared_stem_cell.head_artifacts import load_head
from experiments.shared_stem_cell.head_training_study import split_pixels


class HeadTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(51)
        self.x = torch.randn(53, 8)
        self.rows = (torch.arange(3), torch.arange(3, 18), torch.arange(18, 53))
        self.ys = tuple(torch.arange(len(r)) % 3 for r in self.rows)
        self.seeds = (13, 17, 29)

    def heads(self, kind="gated"):
        return tuple(e.Head(8, 3, kind, 4).eval() for _ in self.rows)

    def run_group(self, initial, steps=(4, 4, 4), **kwargs):
        return h.fit_cells(initial, self.x, self.rows, self.ys,
                           seeds=self.seeds, step_counts=steps, **kwargs)

    def test_all_four_heads_match_original_fit_and_sample_streams(self):
        for kind in ("linear", "gated", "low_rank", "sparse_expert"):
            initial = self.heads(kind)
            models, report = self.run_group(initial)
            for i, (a, m, r, y, seed) in enumerate(zip(models, initial, self.rows, self.ys, self.seeds)):
                expected, scalar = e.fit(m, self.x[r], y, steps=4, seed=seed)
                self.assertEqual(report["cells"][i]["minibatch_sha256"], scalar["minibatch_sha256"])
                torch.testing.assert_close(a(self.x), expected(self.x), atol=h.ATOL, rtol=h.RTOL)
                for p, q in zip(a.parameters(), expected.parameters()):
                    torch.testing.assert_close(p, q, atol=h.ATOL, rtol=h.RTOL)

    def test_equal_width_buckets_batched_without_idle_or_padded_updates(self):
        self.rows = (torch.arange(20), torch.arange(18, 38), torch.arange(30, 53))
        self.ys = tuple(torch.arange(len(r)) % 3 for r in self.rows)
        calls = []
        original = torch.optim.AdamW.step
        def observed(opt, *a, **kw):
            calls.append(1)
            return original(opt, *a, **kw)
        with patch.object(torch.optim.AdamW, "step", observed):
            _, report = self.run_group(self.heads())
        self.assertEqual(len(calls), 4)
        self.assertEqual(sum(g["cell_updates"] for g in report["groups"]), 12)
        self.assertEqual(sum(g["examples_processed"] for g in report["groups"]), 3*4*16)
        self.assertEqual(report["padded_example_lanes"], 0)

    def test_different_budgets_and_zero_step_preserve_adam_step_semantics(self):
        initial = self.heads()
        models, report = self.run_group(initial, (0, 2, 5))
        self.assertEqual(e.parameters(models[0]), e.parameters(initial[0]))
        self.assertEqual(report["cells"][0]["examples_processed"], 0)
        self.assertEqual(sum(g["cell_updates"] for g in report["groups"]), 7)
        for i in (1, 2):
            ref, _ = e.fit(initial[i], self.x[self.rows[i]], self.ys[i], steps=(0,2,5)[i], seed=self.seeds[i])
            torch.testing.assert_close(models[i](self.x), ref(self.x), atol=h.ATOL, rtol=h.RTOL)

    def test_all_zero_steps_no_optimizer(self):
        initial = self.heads()
        with patch.object(torch.optim, "AdamW") as optimizer:
            candidates, report = self.run_group(initial, (0, 0, 0))
        optimizer.assert_not_called()
        self.assertEqual(report["groups"], [])
        self.assertEqual([e.parameters(m) for m in initial], [e.parameters(m) for m in candidates])

    def test_gradient_clipping_is_per_cell_not_whole_bank(self):
        self.x *= 100
        initial = self.heads()
        self.rows = (torch.arange(20), torch.arange(10, 30), torch.arange(20, 40))
        self.ys = tuple(torch.arange(len(r)) % 3 for r in self.rows)
        models, report = self.run_group(initial, (8, 8, 8))
        original = torch.nn.utils.clip_grad_norm_
        for i in range(3):
            norms = []
            def observe(*a, **kw):
                value = original(*a, **kw); norms.append(float(value)); return value
            with patch.object(torch.nn.utils, "clip_grad_norm_", observe):
                reference, _ = e.fit(initial[i], self.x[self.rows[i]], self.ys[i], steps=8, seed=self.seeds[i])
            self.assertEqual(report["cells"][i]["gradient_clipped_steps"], sum(n + 1e-6 > 1 for n in norms))
            self.assertGreater(report["cells"][i]["gradient_clipped_steps"], 0)
            torch.testing.assert_close(models[i](self.x), reference(self.x), atol=h.ATOL, rtol=h.RTOL)

    def test_global_rng_inputs_and_source_parameters_unchanged(self):
        initial = self.heads(); before = [e.parameters(m) for m in initial]
        x = self.x.clone(); self.x.requires_grad_(True)
        state = torch.get_rng_state().clone()
        candidates, _ = self.run_group(initial)
        self.assertTrue(torch.equal(state, torch.get_rng_state()))
        self.assertTrue(torch.equal(x, self.x))
        self.assertIsNone(self.x.grad)
        self.assertEqual(before, [e.parameters(m) for m in initial])
        with torch.no_grad():
            candidates[0].base.weight.add_(5)
        self.assertEqual(before, [e.parameters(m) for m in initial])

    def test_different_labels_in_one_cell_do_not_change_peers(self):
        self.rows = (torch.arange(20), torch.arange(10,30), torch.arange(20,40))
        self.ys = tuple(torch.arange(len(r)) % 3 for r in self.rows)
        initial = self.heads(); a, report = self.run_group(initial)
        self.assertEqual(len(report["groups"]), 1)
        self.ys = ((self.ys[0]+1)%3, *self.ys[1:])
        b, _ = self.run_group(initial)
        for i in (1, 2):
            self.assertEqual(e.parameters(a[i]), e.parameters(b[i]))
        self.assertNotEqual(e.parameters(a[0]), e.parameters(b[0]))

    def test_budget_rejection_precedes_stacking_and_optimizer(self):
        with patch.object(h, "stack_module_state") as stack, patch.object(torch.optim, "AdamW") as opt:
            with self.assertRaises(e.InputError):
                self.run_group(self.heads(), maximum_parameter_bytes=1)
        stack.assert_not_called(); opt.assert_not_called()

    def test_late_bad_labels_rejected_before_any_training(self):
        self.ys = (*self.ys[:-1], torch.full_like(self.ys[-1], 3))
        with patch.object(h, "stack_module_state") as stack:
            with self.assertRaises(e.InputError):
                self.run_group(self.heads())
        stack.assert_not_called()

    def test_nonfinite_features_wrong_shapes_and_unknown_types_reject(self):
        for value in (torch.full_like(self.x, float("nan")), self.x.double(), self.x.unsqueeze(0)):
            with self.assertRaises(e.InputError):
                h.fit_cells(self.heads(), value, self.rows, self.ys, seeds=self.seeds, step_counts=(1,1,1))
        with self.assertRaises(e.InputError):
            self.run_group((torch.nn.Linear(8,3), *self.heads()[1:]))
        with self.assertRaises(e.InputError):
            self.run_group(self.heads(), (1, True, 1))

    def test_prescribed_group_size_does_not_change_training_contract(self):
        initial = self.heads()
        a, _ = self.run_group(initial, group_size=1)
        b, _ = self.run_group(initial, group_size=32)
        for left,right in zip(a,b):
            torch.testing.assert_close(left(self.x), right(self.x), atol=h.ATOL, rtol=h.RTOL)

    def test_artifact_export_reloads_grouped_candidate_not_scalar_substitute(self):
        cases = tuple(e.Case(str(i), str(i), "train" if i < 36 else "holdout", None,
                            i%3, "scope", str(i)) for i in range(53))
        labels = {c.case_id: i%3 for i,c in enumerate(cases) if c.split=="train"}
        binding = {"scope":"scope", "stem_sha256":"a"*64, "dataset_sha256":"b"*64,
                   "feature_profile_sha256":"c"*64, "generation":1}
        with tempfile.TemporaryDirectory() as td, patch.object(e,"fit",side_effect=AssertionError("no scalar fallback")):
            out,costs = e.head_trial(self.x,cases,labels,classes=3,kind="gated",steps=4,seed=17,
                fitting_backend="grouped",artifact_dir=Path(td)/"heads",artifact_binding=binding)
            self.assertEqual(sum("shared_training_report" in c for c in costs),1)
            for cost in costs:
                entry=cost["offline_head_artifacts"]["learned"]
                model=load_head(Path(td)/"heads"/entry["relative_path"],entry["manifest_sha256"],entry["binding"])
                ids=[i for i,c in enumerate(cases) if c.cell==cost["cell"] and c.split=="holdout"]
                self.assertEqual(model(self.x[ids]).softmax(-1).tolist(),[p["probabilities"] for p in out if p["cell"]==cost["cell"]])

    def test_trial_scalar_default_matches_opt_in_grouped(self):
        cases=tuple(e.Case(str(i),str(i),"train" if i<36 else "holdout",None,i%3,"scope",str(i)) for i in range(53))
        labels={c.case_id:i%3 for i,c in enumerate(cases) if c.split=="train"}
        left,_=e.head_trial(self.x,cases,labels,classes=3,kind="gated",steps=5,seed=17)
        right,_=e.head_trial(self.x,cases,labels,classes=3,kind="gated",steps=5,seed=17,fitting_backend="grouped")
        torch.testing.assert_close(torch.tensor([p["probabilities"] for p in left]),torch.tensor([p["probabilities"] for p in right]),atol=h.ATOL,rtol=h.RTOL)

    def test_existing_full_entrypoint_uses_grouped_learning_and_one_encoder_call(self):
        class Encoder:
            identity = "a" * 64
            simulated = True
            calls = 0
            def __init__(self, *args):
                pass
            def encode(self, texts):
                Encoder.calls += 1
                return torch.tensor([[len(t), i+1] for i,t in enumerate(texts)], dtype=torch.float32)
            def close(self):
                pass
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [{"case_id": str(i), "group": str(i), "split": split,
                     "observed_at": None, "cell": i%2, "scope": "test-only",
                     "text": f"fixture {i}", "label": i%2}
                    for i,split in enumerate(("train", "train", "calibration", "calibration", "holdout", "holdout"))]
            raw = b"".join(e.canonical(row) for row in rows)
            (root/"data.jsonl").write_bytes(raw)
            manifest = {"schema": "hepta.shared-stem-execution.v1", "classes":2, "cells":2,
                "steps":2, "head_training_backend":"grouped", "measure_head_batch":True,
                "dataset":{"path":"data.jsonl", "sha256":e.sha(raw)}, "model":{"path":"fixture"}}
            e.write_once(root/"manifest.json", manifest)
            with patch.object(e,"LocalEncoder",Encoder), patch.object(e,"fit",side_effect=AssertionError("no fallback")):
                report = e.run(root/"manifest.json",root/"out")
            self.assertEqual(Encoder.calls,1)
            self.assertEqual(len(report["scores"]),4)
            for costs in report["training"].values():
                self.assertEqual(sum("shared_training_report" in c for c in costs),1)
                self.assertEqual(costs[0]["shared_training_report"]["encoder_calls"],0)
            self.assertTrue(report["head_batch_executed"])

    def test_trial_parameter_census_precedes_source_head_allocation(self):
        cases = tuple(e.Case(str(i), str(i), "train", None, i, "scope", str(i)) for i in range(64))
        with patch.object(e, "Head") as constructor:
            with self.assertRaisesRegex(e.InputError, "before allocation"):
                e.head_trial(torch.zeros(64,8192),cases,{},classes=256,kind="gated",steps=1,
                             seed=17,fitting_backend="grouped")
        constructor.assert_not_called()

    def test_digit_partition_is_pixel_only_and_duplicate_stable(self):
        pixels=torch.randint(0,17,(20,64));pixels[19]=pixels[0]
        identities,folds,cells=split_pixels(pixels,8)
        self.assertEqual((identities[0],folds[0],cells[0]),(identities[19],folds[19],cells[19]))
        for i in range(20):
            self.assertEqual(folds[i],int(identities[i][:8],16)%5==0)
            self.assertEqual(cells[i],int(identities[i][8:16],16)%8)


if __name__ == "__main__":
    unittest.main()
