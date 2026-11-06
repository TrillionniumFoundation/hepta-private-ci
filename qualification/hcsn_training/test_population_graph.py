"""Bounded CPU B engineering fixtures; no benchmark or scientific training."""

import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import torch
from .joint_graph import (digest, interval_seconds, load_model, load_training_checkpoint,
                          model_bytes, time_profile_digest)
from .population_graph import PopulationCellGraph, PopulationGraphSpec, population_intervals
from .worker import propose, task_gradients
from .handoff import encode_handoff, MAGIC
from .test_joint_graph import fixture as value_fixture


def fixture(directory):
    torch.manual_seed(31)
    model = PopulationCellGraph(PopulationGraphSpec(("encoder", "memory"), 1, 1, 1, 100_000)).double()
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            parameter.fill_(.1 if "bias" in name else .3)
    profile = dict(maximum_gap_micros=1_000_000, forecast_horizon_micros=500_000,
                   integration=dict(kind="population_grid", step_micros=100_000, max_substeps=10))
    identity, anchor, start, plans = time_profile_digest(profile), digest("checkpoint"), 17, []
    for count in (1, 1, 1, 1, 1):
        elapsed = count*100_000
        plans.append(dict(schema_version=1, start_micros=start, end_micros=start+elapsed,
                          elapsed_micros=elapsed, substep_micros=100_000, substeps=count,
                          forecast_horizon_micros=500_000, profile_digest=identity, checkpoint_before=anchor))
        start += elapsed
    inputs = torch.tensor([[[.25], [.45], [-.3], [.6], [-.2]]], dtype=torch.float64)
    targets = torch.tensor([[.4]], dtype=torch.float64)
    payload = model_bytes(model)
    path = Path(directory)/"base.pt"
    path.write_bytes(payload)
    checkpoint = hashlib.sha256(payload).hexdigest()
    request = dict(schema_version=1, mechanism="task_mse_bp_v1", operation_id="hcsn:population-fixture",
                   binding=dict(scope_digest=digest("scope"), generation=1, writer_epoch=1,
                                clock_epoch=digest("clock"), model_digest=checkpoint, profile_digest=identity),
                   intervals=plans, time_profile=profile, inputs=inputs.tolist(), targets=targets.tolist(),
                   target_time_micros=start+500_000, learning_rate=.02, optimizer_steps=1,
                   limits=dict(max_optimizer_steps=1, max_batch=1, max_intervals=5, max_elements=1_048_576),
                   base_checkpoint=dict(path=str(path), sha256=checkpoint))
    return model, request, inputs, targets, population_intervals(plans, profile, model.spec)


class PopulationGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def case(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return fixture(directory.name)

    def test_grid_advancement_matches_original_b_encoder_and_grouping(self):
        model, _, inputs, _, intervals = self.case()
        _, state = model(inputs, intervals)
        expected = model.cells[0](inputs, dt=.1)
        torch.testing.assert_close(state[0][0], expected[:, -1], rtol=0, atol=0)
        held = inputs[:, :1].expand(-1, 5, -1)
        grouped, whole = model(held[:, :1], (5,))
        split, parts = model(held, (1, 1, 1, 1, 1))
        torch.testing.assert_close(grouped[:, -1], split[:, -1], rtol=0, atol=0)
        for left, right in zip(whole, parts):
            for x, y in zip(left, right):
                torch.testing.assert_close(x, y, rtol=0, atol=0)
        shorter = model(held[:, :1], (1,))[0]
        self.assertGreater(float((grouped-shorter).abs().max().detach()), .01)

    def test_every_parameter_has_nonzero_task_gradient_and_matches_finite_difference(self):
        model, _, inputs, targets, intervals = self.case()
        _, gradients = task_gradients(model, inputs, targets, intervals)
        for name, parameter in model.named_parameters():
            index = (0,)*parameter.ndim
            analytic = float(gradients[name][index])
            self.assertGreater(abs(analytic), 1e-8, name)
            original = float(parameter[index].detach())
            losses = []
            for delta in (-1e-5, 1e-5):
                with torch.no_grad():
                    parameter[index] = original+delta
                    losses.append(float((model(inputs, intervals)[0][:, -1]-targets).square().mean()))
            with torch.no_grad():
                parameter[index] = original
            numeric = (losses[1]-losses[0])/2e-5
            self.assertAlmostEqual(analytic, numeric, delta=1e-8+abs(numeric)*3e-4, msg=name)
        self.assertTrue(torch.autograd.gradcheck(lambda x: model(x, intervals)[0][:, -1],
                                                (inputs.requires_grad_(),), eps=1e-6, atol=1e-7, rtol=1e-4))

    def test_fp32_profile_retains_finite_complete_state_and_task_gradients(self):
        model, _, inputs, targets, intervals = self.case()
        model, inputs, targets = model.float(), inputs.float(), targets.float()
        _, gradients = task_gradients(model, inputs, targets, intervals)
        for gradient in gradients.values():
            self.assertTrue(bool(torch.isfinite(gradient).all()))
            self.assertGreater(float(gradient.abs().max()), 0)
        _, state = model(inputs, intervals)
        model.validate_state(state, inputs.shape[0], inputs.dtype, inputs.device)

    def test_detached_first_cell_refuses_and_dormant_gradients_are_reported(self):
        model, request, _, _, _ = self.case()
        original = PopulationCellGraph.advance
        first = []
        def detached(cell, *args):
            if not first:
                first.append(cell)
            result = original(cell, *args)
            return tuple(value.detach() for value in result) if cell is first[0] else result
        with patch.object(PopulationCellGraph, "advance", staticmethod(detached)):
            with self.assertRaisesRegex(ValueError, "disconnected"):
                propose(model, request)
        request["inputs"] = [[[0.] for _ in request["intervals"]]]
        _, receipt = propose(model, request)
        self.assertIn("cells.0.input.weight", receipt["gradients"][0]["zero_gradient_parameter_names"])

    def test_candidate_sgd_handoff_and_complete_state_resume(self):
        model, request, inputs, targets, intervals = self.case()
        _, gradients = task_gradients(model, inputs, targets, intervals)
        before = {name: value.detach().clone() for name, value in model.named_parameters()}
        payload, receipt = propose(model, request)
        path = Path(request["base_checkpoint"]["path"]).with_name("candidate.pt")
        path.write_bytes(payload)
        recovered, state, metadata = load_training_checkpoint(path, receipt["checkpoint_sha256"])
        self.assertEqual(metadata["schema_version"], 2)
        self.assertEqual(receipt["edge_timing"], "previous_grid_boundary")
        self.assertEqual(receipt["gradients"][0]["nonzero_gradient_elements"], 8)
        for name, value in recovered.named_parameters():
            torch.testing.assert_close(value, before[name]-.02*gradients[name], rtol=0, atol=1e-16)
            torch.testing.assert_close(dict(model.named_parameters())[name], before[name], rtol=0, atol=0)
        self.assertTrue(all(len(values) == 5 for values in state))
        self.assertGreater(float(state[0][2].sum()), 0)
        prefix, first_state = recovered(inputs[:, :3], intervals[:3])
        suffix, _ = recovered(inputs[:, 3:], intervals[3:], first_state)
        whole, _ = recovered(inputs, intervals)
        torch.testing.assert_close(torch.cat((prefix, suffix), 1), whole, rtol=0, atol=0)
        diagnostics = json.dumps(receipt, sort_keys=True, allow_nan=False).encode()
        handoff = encode_handoff(request, receipt, diagnostics, payload)
        self.assertEqual(len(handoff), len(MAGIC)+1+11*32+7*8)
        code = """import json,sys,torch
from qualification.hcsn_training.joint_graph import load_training_checkpoint
m,s,_=load_training_checkpoint(sys.argv[1],sys.argv[2]); torch.set_num_threads(1)
y,_=m(torch.tensor([[[.3]]],dtype=torch.float64),(1,),s)
print(json.dumps(y.tolist()))
"""
        cold = subprocess.check_output([sys.executable, "-c", code, str(path), receipt["checkpoint_sha256"]], text=True)
        expected = recovered(torch.tensor([[[.3]]], dtype=torch.float64), (1,), state)[0]
        torch.testing.assert_close(torch.tensor(json.loads(cold), dtype=torch.float64), expected, rtol=0, atol=0)

    def test_stateful_base_is_rejected_for_both_backends(self):
        for make in (fixture, value_fixture):
            with tempfile.TemporaryDirectory() as directory:
                model, request, _, _, _ = make(directory)
                payload, receipt = propose(model, request)
                path = Path(directory)/"stateful.pt"
                path.write_bytes(payload)
                request["base_checkpoint"] = dict(path=str(path), sha256=receipt["checkpoint_sha256"])
                request["binding"]["model_digest"] = receipt["checkpoint_sha256"]
                loaded = load_model(path, receipt["checkpoint_sha256"])
                with self.assertRaisesRegex(ValueError, "fresh|state|resume"):
                    propose(loaded, request)

    def test_off_grid_incompatible_profile_state_and_budget_fail_closed(self):
        model, request, inputs, _, intervals = self.case()
        for field, value in (("elapsed_micros", 100_001), ("substep_micros", 50_000), ("substeps", 2)):
            invalid = copy.deepcopy(request["intervals"])
            invalid[0][field] = value
            with self.assertRaises(ValueError):
                population_intervals(invalid, request["time_profile"], model.spec)
        with self.assertRaises(ValueError):
            interval_seconds(request["intervals"], request["time_profile"])
        with self.assertRaisesRegex(ValueError, "queue budget"):
            PopulationGraphSpec(("encoder", "memory"), 1, 1, 1, 1)
        state = list(model.initial_state(inputs.shape[0], like=inputs))
        state[0] = state[0][:2]+state[0][3:]
        with self.assertRaises(ValueError):
            model(inputs, intervals, state)
        request["limits"]["max_elements"] = 1000
        with self.assertRaisesRegex(ValueError, "tensor budget"):
            propose(model, request)

    def test_population_buffers_cannot_silently_change_fixed_profile(self):
        model, request, _, _, _ = self.case()
        saved = torch.load(io.BytesIO(model_bytes(model)), weights_only=True)
        saved["model_state"]["cells.0.population.reset_weights"].zero_()
        buffer = io.BytesIO()
        torch.save(saved, buffer)
        payload = buffer.getvalue()
        path = Path(request["base_checkpoint"]["path"]).with_name("changed-grid.pt")
        path.write_bytes(payload)
        with self.assertRaisesRegex(ValueError, "fixed population"):
            load_model(path, hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()
