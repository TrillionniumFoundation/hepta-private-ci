"""Synthetic controls; no formal source family or trained checkpoint is read."""

from copy import deepcopy
import inspect
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch
from torch import nn

from . import programs as p
from .models import SignedHCSN
from . import baselines
from qualification.hcsn_smallnet_20261124.model import ModelConfig


class DummyParent(nn.Module):
    def __init__(self):
        super().__init__()
        self.readout = nn.Linear(6, 2)
        self.config = SimpleNamespace(neurons=8)

    def initial_state(self, batch, initial_margin=None):
        return None

    def forward(self, x, state=None, return_features=False):
        features = x.cumsum(0)
        return self.readout(features), features, None


class ProgramTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1); torch.manual_seed(903)
        self.protocol = p.default_protocol()
        self.protocol.update(sources={"train": [71, 72], "dev": [73], "test": [74, 75]},
                             per_source=4, parent_ids=["n8-s1"], test_only=True)

    def test_rule_compiler_installs_relations_for_nonzero_parent_margins(self):
        source = {"weight": torch.tensor([[0.], [1.]]), "bias": torch.zeros(2)}
        grid = torch.tensor([-.9, -.3, -.01, .04, .5, 1.1])
        a, b = torch.cartesian_prod(grid, grid).unbind(1)
        head = p.RelationHead(source); head.load_state_dict(p.strict_program(source))
        scores = head(a[:, None], b[:, None])
        expected = torch.stack(((a > 0) & (b > 0), (a > 0) | (b > 0), (a > 0) ^ (b > 0)), -1)
        self.assertTrue(torch.equal(scores > 0, expected))
        # A continuous XOR score cannot encode every discrete tie convention.
        tied = head(torch.tensor([[0.]]), torch.tensor([[.5]]))
        self.assertEqual(float(tied[0, 2]), 0.)

    def test_weight_only_program_owns_no_label_activation_or_gradient_path(self):
        source = nn.Linear(7, 2).state_dict(); before = deepcopy(source)
        with patch("torch.linalg.solve", side_effect=AssertionError("no solve")), \
                patch("torch.autograd.grad", side_effect=AssertionError("no differentiation")):
            compiled = p.strict_program(source)
        self.assertEqual(set(inspect.signature(p.strict_program).parameters), {"readout_state", "rules"})
        self.assertEqual(p.tensor_digest(source), p.tensor_digest(before))
        self.assertFalse(any(t.requires_grad for t in compiled.values()))
        with self.assertRaises(TypeError):
            p.strict_program(source, labels=torch.ones(3))
        with self.assertRaises(ValueError):
            p.strict_program(source, rules=("UNKNOWN",))

    def test_program_regenerates_on_signed_permuted_feature_coordinates(self):
        source = nn.Linear(7, 2).state_dict(); a, b = torch.randn(32, 7), torch.randn(32, 7)
        head = p.RelationHead(source); head.load_state_dict(p.strict_program(source))
        order, signs = torch.tensor([4, 1, 6, 0, 3, 2, 5]), torch.tensor([-1., 1., -1., 1., 1., -1., 1.])
        current = {"weight": source["weight"][:, order]*signs, "bias": source["bias"].clone()}
        transformed = p.RelationHead(current); transformed.load_state_dict(p.strict_program(current))
        original, actual = head(a, b), transformed(a[:, order]*signs, b[:, order]*signs)
        torch.testing.assert_close(actual, original, atol=1e-6, rtol=1e-6)
        self.assertGreater(float((head(a[:, order]*signs, b[:, order]*signs)-original).abs().max()), .1)

    def test_observable_query_keeps_old_logits_exactly(self):
        scores, old = torch.randn(16, 3, dtype=torch.float64), torch.randn(16, 2)
        query = torch.arange(16) % 4
        actual = p.query_logits(scores, old, query)
        self.assertTrue(torch.equal(actual[query == 0], old[query == 0]))
        for index in range(1, 4):
            value = scores[query == index, index-1].float()
            self.assertTrue(torch.equal(actual[query == index], torch.stack((-value/2, value/2), -1)))

    def test_ridge_and_bp_use_one_objective_and_bounded_closures(self):
        design, labels = torch.randn(256, 4, dtype=torch.float64), torch.randint(0, 2, (256, 3))
        direct = p.RelationHead(nn.Linear(7, 2).state_dict()); iterative = deepcopy(direct)
        p.fit_head(direct, design, labels, "ANALYTIC", self.protocol)
        loss = p.objective(direct, design, 2*labels.double()-1, self.protocol["ridge"]); loss.backward()
        self.assertLess(max(float(v.grad.abs().max()) for v in direct.readout.parameters()), 1e-12)
        receipt = p.fit_head(iterative, design, labels, "BP", self.protocol)
        self.assertGreater(receipt["closures"], 0); self.assertLessEqual(receipt["closures"], 96)
        self.assertLess(abs(receipt["objective"]-float(loss.detach())), 1e-8)

    def test_real_hcsn_forwards_preserve_regenerated_program_and_parent(self):
        model = SignedHCSN(ModelConfig(neurons=8, message_mode="flow", precision="mixed", backend="uniformized"))
        pairs = p.make_pair_data("dev", self.protocol); before = p.tensor_digest(model.state_dict())
        result = p.transfer_controls(model, pairs, self.protocol)
        self.assertEqual(result["independent_parent_count"], 1)
        self.assertEqual(p.tensor_digest(model.state_dict()), before)
        for control in result["controls"].values():
            self.assertTrue(control["equivalent"]); self.assertTrue(control["old_parent_logits_equivalent"])
            self.assertEqual(control["prediction_disagreements"], 0)
        self.assertFalse(result["controls"]["readout_signed_basis"]["copied_old_program_equivalent"])

    def prepare_fixture(self, directory):
        model = DummyParent()
        with patch.object(p, "transfer_controls", return_value={"synthetic_test_fixture": True}):
            p.prepare(model, {"parent_id": "n8-s1", "synthetic_fixture": True}, directory, self.protocol)
        return model

    def test_missing_global_seal_refuses_before_test_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/"attempt"; model = self.prepare_fixture(output)
            with patch.object(p, "make_pair_data", side_effect=AssertionError("test constructed")):
                with self.assertRaises(FileNotFoundError):
                    p.final_test(model, output, self.protocol, Path(temporary)/"MISSING.json")
            self.assertFalse((output/"FINAL_CLAIM.json").exists())

    def test_corrupt_candidate_refuses_before_test_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/"attempt"; model = self.prepare_fixture(output)
            seal = Path(temporary)/"GLOBAL.json"; p.seal_all([output], seal, self.protocol)
            with (output/"BP.pt").open("ab") as stream:
                stream.write(b"corruption")
            with patch.object(p, "make_pair_data", side_effect=AssertionError("test constructed")):
                with self.assertRaises(ValueError):
                    p.final_test(model, output, self.protocol, seal)
            self.assertFalse((output/"FINAL_CLAIM.json").exists())

    def test_rehashed_wrong_method_metadata_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/"attempt"; self.prepare_fixture(output)
            file = output/"BP.pt"; value = torch.load(file, weights_only=True)
            value["method"] = "ANALYTIC"; torch.save(value, file)
            seal = json.loads((output/"SEAL.json").read_text()); seal["files"]["BP.pt"] = p.digest(file)
            (output/"SEAL.json").write_text(json.dumps(seal))
            with self.assertRaises(ValueError):
                p.validate_prepared(output, self.protocol)

    def test_five_arm_roundtrip_and_independent_saved_prediction_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/"attempt"; model = self.prepare_fixture(output)
            seal = Path(temporary)/"GLOBAL.json"; p.seal_all([output], seal, self.protocol)
            result = p.final_test(model, output, self.protocol, seal)
            arrays = np.load(output/"FINAL_PREDICTIONS.npz")
            for method, record in result["methods"].items():
                self.assertEqual(record["status"], "completed")
                self.assertTrue(record["metrics"]["old_logits_exact"])
                scores = arrays[method+"_scores"]; labels = arrays["labels"]
                for column, rule in enumerate(p.RULES):
                    actual = float(((scores[:, column] > 0) == labels[:, column]).mean())
                    self.assertEqual(actual, record["metrics"]["rules"][rule]["accuracy"])
            self.assertEqual(result["methods"]["STRICT_WSP"]["optimization"]["labels_read"], 0)
            with self.assertRaises(FileExistsError):
                p.final_test(model, output, self.protocol, seal)


class ConventionalBaselineTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1); torch.manual_seed(721)

    def test_actual_parameter_counts(self):
        cases = ((baselines.GRUClassifier, (4, 16, 32), (154, 1186, 3906)),
                 (baselines.LIFClassifier, (9, 30, 58), (155, 1142, 3830)),
                 (baselines.CausalTransformer, (3, 11, 21), (134, 1190, 3950)))
        for cls, widths, expected in cases:
            for width, count in zip(widths, expected):
                self.assertEqual(baselines.parameter_accounting(cls(width))["total_parameters"], count)

    def test_causal_streaming_and_complete_state_all_nine_architectures(self):
        x = torch.randn(12, 2, 6)
        for cls, widths in ((baselines.GRUClassifier, (4, 16, 32)),
                            (baselines.LIFClassifier, (9, 30, 58)),
                            (baselines.CausalTransformer, (3, 11, 21))):
            for width in widths:
                result = baselines.causal_streaming_control(cls(width), x)
                self.assertTrue(result["stream_equivalent"], result)
                self.assertTrue(result["future_invariant"], result)
                expected = (2*width if cls is baselines.GRUClassifier else
                            3*2*width if cls is baselines.LIFClassifier else 2*2*12*width)*4
                self.assertEqual(result["state_bytes"], expected)

    def test_hard_spike_and_declared_surrogate_are_distinct(self):
        gap = torch.tensor([-1., -.2, .3, 1.], requires_grad=True)
        value = baselines.SurrogateSpike.apply(gap)
        self.assertTrue(torch.equal(value, torch.tensor([0., 0., 1., 1.])))
        value.sum().backward()
        torch.testing.assert_close(gap.grad, 1/(1+5*gap.detach().abs()).square())

    def test_finite_backprop_and_update_in_all_baseline_families(self):
        x, y = torch.randn(12, 8, 6), torch.randint(0, 2, (8,))
        for cls, width in ((baselines.GRUClassifier, 4), (baselines.LIFClassifier, 9),
                           (baselines.CausalTransformer, 3)):
            model = cls(width); before = p.tensor_digest(model.state_dict())
            optimizer = torch.optim.Adam(model.parameters(), lr=.01)
            loss = nn.functional.cross_entropy(model(x)[-1], y); loss.backward()
            self.assertTrue(all(v.grad is not None and bool(torch.isfinite(v.grad).all()) for v in model.parameters()))
            optimizer.step(); self.assertNotEqual(before, p.tensor_digest(model.state_dict()))

    def test_original_train_loop_executes_three_smoke_updates_for_baseline(self):
        from . import runner
        protocol = json.loads(Path(runner.__file__).with_name("protocol.json").read_text())
        slot = {"id": "TEST-ONLY-GRU", "kind": "GRU", "width": 4, "seed": 721}
        with tempfile.TemporaryDirectory() as temporary:
            with patch.multiple(runner, make_model=baselines.make_model,
                                parameter_accounting=baselines.parameter_accounting,
                                evaluate=baselines.evaluate):
                result = runner.fit(Path(temporary), protocol, slot, smoke=True)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["updates"], 3)
            self.assertTrue(result["smoke"])
            self.assertEqual(result["parameter_accounting"]["total_parameters"], 154)
            self.assertIsNotNone(result["checkpoint_sha256"])


class CompanionRunnerTests(unittest.TestCase):
    def test_launch_timeout_keeps_full_terminal_cost_receipt(self):
        from . import baselines_run as run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(run.subprocess, "run", side_effect=run.subprocess.TimeoutExpired("fixture", 1800)):
                code = run.launch(root, {"suite": "baselines", "synthetic_fixture": True}, "fit", "fixture")
            self.assertEqual(code, 124)
            receipt = json.loads((root/"fixture/fit_launch_cost.json").read_text())
            self.assertTrue(receipt["timed_out"])
            self.assertEqual(receipt["returncode"], 124)

    def test_missing_main_seal_refuses_before_long_delay_generation(self):
        from . import baselines_run as run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(run, "check_joint", side_effect=ValueError("unsealed")), \
                    patch.object(run, "generate_sources", side_effect=AssertionError("data constructed")):
                with self.assertRaises(ValueError):
                    run.stress(root, {"suite": "baselines"}, "fixture")
            self.assertFalse((root/"stress").exists())


if __name__ == "__main__":
    unittest.main()
