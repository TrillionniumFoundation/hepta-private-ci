"""Small CPU derivative/owner-handoff fixtures; no scientific training campaign."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import torch
from qualification.hcsn.cells import ValueKernelCell
from .joint_graph import (GraphSpec, JointCellGraph, digest, interval_seconds, load_model,
                          load_training_checkpoint, model_bytes, strict_json, tensor_digest, time_profile_digest)
from .worker import propose, task_gradients
from .handoff import MAGIC


def fixture(directory):
    torch.manual_seed(31)
    model = JointCellGraph(GraphSpec(("memory", "association"), 2, 3, 1)).double()
    time_profile = dict(maximum_gap_micros=1_000_000, forecast_horizon_micros=500_000,
                        integration=dict(kind="value_kernel"))
    profile, checkpoint = time_profile_digest(time_profile), digest("checkpoint")
    intervals, start = [], 17
    for elapsed in (100_000, 200_000, 150_000, 300_000):
        intervals.append(dict(schema_version=1, start_micros=start, end_micros=start+elapsed,
                              elapsed_micros=elapsed, substep_micros=elapsed, substeps=1,
                              forecast_horizon_micros=500_000, profile_digest=profile, checkpoint_before=checkpoint))
        start += elapsed
    inputs = torch.tensor([[[.25, -.35], [.45, .15], [-.3, .5], [.6, -.2]],
                           [[-.15, .3], [.2, -.4], [.35, -.1], [.25, .7]]], dtype=torch.float64)
    targets = torch.tensor([[.4], [-.2]], dtype=torch.float64)
    base = model_bytes(model)
    base_path = Path(directory)/"base.pt"
    base_path.write_bytes(base)
    base_digest = hashlib.sha256(base).hexdigest()
    request = dict(schema_version=1, mechanism="task_mse_bp_v1", operation_id="hcsn:fixture", binding=dict(
        scope_digest=digest("scope"), generation=1, writer_epoch=1, clock_epoch=digest("clock"),
        model_digest=base_digest, profile_digest=profile), intervals=intervals, time_profile=time_profile,
        inputs=inputs.tolist(), targets=targets.tolist(), target_time_micros=start+500_000,
        learning_rate=.02, optimizer_steps=1,
        limits=dict(max_optimizer_steps=1, max_batch=2, max_intervals=4, max_elements=1000),
        base_checkpoint={"path": str(base_path), "sha256": base_digest})
    return model, request, inputs, targets, interval_seconds(intervals, time_profile)


class SharedGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def case(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return fixture(directory.name)

    def test_previous_boundary_matches_manual_advancement_and_elapsed_changes_result(self):
        model, request, inputs, _, intervals = self.case()
        actual, final = model(inputs, intervals)
        states = [cell.initial_state(2, like=inputs) for cell in model.cells]
        expected = []
        for k, dt in enumerate(intervals):
            prior = states[0][0]
            states = [model.cells[0].step(inputs[:, k], states[0], dt),
                      model.cells[1].step(prior, states[1], dt)]
            expected.append(model.readout(states[-1][0]))
        torch.testing.assert_close(actual, torch.stack(expected, 1), rtol=0, atol=0)
        for a, b in zip(final, states):
            for x, y in zip(a, b):
                torch.testing.assert_close(x, y, rtol=0, atol=0)
        self.assertGreater(float((actual-model(inputs, [1e-6]*4)[0]).abs().max().detach()), .001)

    def test_two_cell_task_derivatives_match_independent_finite_differences(self):
        model, _, inputs, targets, intervals = self.case()
        inputs.requires_grad_()
        loss, gradients = task_gradients(model, inputs, targets, intervals)
        for name in ("cells.0.candidate_input.weight", "cells.1.candidate_input.weight",
                     "cells.0.raw_financial", "cells.1.raw_financial"):
            parameter = dict(model.named_parameters())[name]
            index = (5, 0) if name.endswith("raw_financial") else (0, 0)
            original = float(parameter[index].detach())
            values = []
            for delta in (-1e-5, 1e-5):
                with torch.no_grad():
                    parameter[index] = original+delta
                    values.append(float((model(inputs, intervals)[0][:, -1]-targets).square().mean()))
            with torch.no_grad():
                parameter[index] = original
            numeric, analytic = (values[1]-values[0])/2e-5, float(gradients[name][index])
            self.assertGreater(abs(analytic), 1e-10)
            self.assertAlmostEqual(analytic, numeric, delta=1e-8+abs(numeric)*2e-4)
        self.assertTrue(torch.autograd.gradcheck(lambda x: model(x, intervals)[0][:, -1],
                                                (inputs,), eps=1e-6, atol=1e-7, rtol=1e-4))

    def test_detaching_first_logical_cell_refuses_candidate(self):
        model, request, _, _, _ = self.case()
        original = ValueKernelCell.step
        def detached(cell, *args, **kwargs):
            result = original(cell, *args, **kwargs)
            return tuple(v.detach() for v in result) if cell.candidate_input.in_features == 2 else result
        with patch.object(ValueKernelCell, "step", detached), self.assertRaisesRegex(ValueError, "disconnected"):
            propose(model, request)

    def test_ndu_plasticity_and_external_gradient_cannot_substitute_for_task_bp(self):
        model, request, _, _, _ = self.case()
        for kind in ("ndu_score", "eligibility_times_modulator"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "distinct"):
                propose(model, dict(request, mechanism=kind))
        with self.assertRaisesRegex(ValueError, "schema/fields"):
            propose(model, dict(request, gradients=[1.], loss=0.))

    def test_schedule_horizon_and_budget_reject_before_parameter_change(self):
        model, request, _, _, _ = self.case()
        before = tensor_digest(model.state_dict())
        for field, value in (("optimizer_steps", 2), ("target_time_micros", 10)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                propose(model, dict(request, **{field: value}))
        changed = copy.deepcopy(request)
        changed["intervals"][1]["start_micros"] += 1
        with self.assertRaises(ValueError):
            propose(model, changed)
        changed = copy.deepcopy(request)
        changed["limits"]["max_elements"] = 1
        with self.assertRaisesRegex(ValueError, "budget"):
            propose(model, changed)
        changed = copy.deepcopy(request)
        changed["time_profile"]["maximum_gap_micros"] = 200_000
        profile = time_profile_digest(changed["time_profile"])
        changed["binding"]["profile_digest"] = profile
        for plan in changed["intervals"]:
            plan["profile_digest"] = profile
        with self.assertRaisesRegex(ValueError, "time plan"):
            propose(model, changed)
        changed = copy.deepcopy(request)
        changed["intervals"][1]["checkpoint_before"] = digest("different outer anchor")
        with self.assertRaisesRegex(ValueError, "time plan"):
            propose(model, changed)
        self.assertEqual(tensor_digest(model.state_dict()), before)

    def test_candidate_sgd_matches_gradient_and_keeps_original_immutable(self):
        model, request, inputs, targets, intervals = self.case()
        before = {k: v.clone() for k, v in model.state_dict().items()}
        _, gradients = task_gradients(model, inputs, targets, intervals)
        payload, receipt = propose(model, request)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"candidate.pt"
            path.write_bytes(payload)
            restored, state, metadata = load_training_checkpoint(path, receipt["checkpoint_sha256"])
        with torch.no_grad():
            whole = restored(torch.cat((inputs, inputs[:, :2]), 1), (*intervals, .2, .1))[0][:, -2:]
            resumed = restored(inputs[:, :2], (.2, .1), state=state)[0]
            torch.testing.assert_close(resumed, whole, rtol=0, atol=0)
        self.assertEqual(metadata["last_end_micros"], request["intervals"][-1]["end_micros"])
        for name, value in model.state_dict().items():
            torch.testing.assert_close(value, before[name], rtol=0, atol=0)
            torch.testing.assert_close(restored.state_dict()[name], before[name]-.02*gradients[name])
        self.assertTrue(all(v > 0 for v in receipt["gradients"][0]["per_cell_gradient_norm"].values()))
        self.assertNotEqual(receipt["base_weights_digest"], receipt["candidate_weights_digest"])
        self.assertEqual(receipt["training_examples_seen"], 2)
        self.assertFalse(receipt["evaluation_passed"])

    def test_cli_cold_load_reuse_refusal_and_byte_tamper_rejection(self):
        model, request, inputs, _, intervals = self.case()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = model_bytes(model)
            (root/"base.pt").write_bytes(base)
            request["base_checkpoint"] = dict(path=str(root/"base.pt"), sha256=hashlib.sha256(base).hexdigest())
            request["binding"]["model_digest"] = request["base_checkpoint"]["sha256"]
            (root/"request.json").write_text(json.dumps(request))
            command = [sys.executable, "-m", "qualification.hcsn_training.worker",
                       "--request", str(root/"request.json"), "--output", str(root/"result")]
            subprocess.run(command, check=True, capture_output=True, text=True)
            receipt = json.loads((root/"result/receipt.json").read_text())
            handoff = (root/"result/handoff.bin").read_bytes()
            self.assertEqual(len(handoff), len(MAGIC)+1+11*32+7*8)
            self.assertEqual(handoff[:len(MAGIC)+1], MAGIC+b"\0")
            self.assertEqual(handoff[len(MAGIC)+1+10*32:len(MAGIC)+1+11*32],
                             hashlib.sha256((root/"result/receipt.json").read_bytes()).digest())
            restored = load_model(root/"result/candidate.pt", receipt["checkpoint_sha256"])
            self.assertEqual(restored(inputs, intervals)[0][:, -1].tolist(), receipt["final_prediction"])
            code = ("import json,sys,torch; from qualification.hcsn_training.joint_graph import load_training_checkpoint; "
                    "torch.set_num_threads(1); m,s,meta=load_training_checkpoint(sys.argv[1],sys.argv[2]); "
                    "x=torch.tensor(json.loads(sys.argv[3]),dtype=next(m.parameters()).dtype); "
                    "print(json.dumps(m(x,(.2,.1),state=s)[0].tolist()))")
            cold = subprocess.run([sys.executable, "-c", code, str(root/"result/candidate.pt"),
                                   receipt["checkpoint_sha256"], json.dumps(inputs[:, :2].tolist())],
                                  check=True, capture_output=True, text=True)
            with torch.no_grad():
                whole = restored(torch.cat((inputs, inputs[:, :2]), 1), (*intervals, .2, .1))[0][:, -2:]
            self.assertEqual(json.loads(cold.stdout), whole.tolist())
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            self.assertEqual((root/"base.pt").read_bytes(), base)
            (root/"base.pt").write_bytes(base+b"tamper")
            with self.assertRaisesRegex(ValueError, "identity"):
                load_model(root/"base.pt", request["base_checkpoint"]["sha256"])

    def test_binding_mismatch_in_memory_mutation_and_noncanonical_json_reject(self):
        model, request, _, _, _ = self.case()
        changed = copy.deepcopy(request)
        changed["binding"]["model_digest"] = digest("different base")
        with self.assertRaisesRegex(ValueError, "binding"):
            propose(model, changed)
        with torch.no_grad():
            model.readout.bias.add_(1)
        with self.assertRaisesRegex(ValueError, "in-memory"):
            propose(model, request)
        for raw in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                strict_json(raw)


if __name__ == "__main__":
    unittest.main()
