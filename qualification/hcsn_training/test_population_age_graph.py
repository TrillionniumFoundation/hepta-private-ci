"""Actual variable-time transport, derivatives and complete-state recovery."""

import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import torch
from .joint_graph import digest, load_training_checkpoint, model_bytes, tensor_digest, time_profile_digest
from .population_age_graph import PopulationAgeCellGraph, PopulationAgeGraphSpec, migrate_fixed_grid
from .population_graph import PopulationCellGraph, PopulationGraphSpec
from .training_state import state_digest
from .worker import task_gradients


def model_fixture(step=100_000, maximum=16):
    model = PopulationAgeCellGraph(PopulationAgeGraphSpec(("encoder", "memory"), 1, 1, 1,
                                                         step, maximum)).double()
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            parameter.fill_(.1 if "bias" in name else .3)
    return model


def fixture(directory):
    model = model_fixture()
    profile = dict(maximum_gap_micros=1_000_000, forecast_horizon_micros=500_000,
                   integration=dict(kind="population_age", max_step_micros=100_000, max_substeps=16))
    identity, anchor, start, plans = time_profile_digest(profile), digest("checkpoint"), 17, []
    intervals = (73_001, 99_999, 70_000)
    for elapsed in intervals:
        plans.append(dict(schema_version=1, start_micros=start, end_micros=start+elapsed,
                          elapsed_micros=elapsed, substep_micros=100_000, substeps=16,
                          forecast_horizon_micros=500_000, profile_digest=identity, checkpoint_before=anchor))
        start += elapsed
    inputs = torch.tensor([[[.25], [.45], [-.3]]], dtype=torch.float64)
    targets = torch.tensor([[.4]], dtype=torch.float64)
    payload = model_bytes(model)
    path = Path(directory)/"base.pt"
    path.write_bytes(payload)
    identity_checkpoint = hashlib.sha256(payload).hexdigest()
    request = dict(schema_version=1, mechanism="task_mse_bp_v1", operation_id="hcsn:population-age-fixture",
                   binding=dict(scope_digest=digest("scope"), generation=1, writer_epoch=1,
                                clock_epoch=digest("clock"), model_digest=identity_checkpoint,
                                profile_digest=identity),
                   intervals=plans, time_profile=profile, inputs=inputs.tolist(), targets=targets.tolist(),
                   target_time_micros=start+500_000, learning_rate=.02, optimizer_steps=1,
                   limits=dict(max_optimizer_steps=1, max_batch=1, max_intervals=3, max_elements=1_048_576),
                   base_checkpoint=dict(path=str(path), sha256=identity_checkpoint))
    return model, request, inputs, targets, intervals


def waiting_state(model, micros):
    initial = model.initial_state(torch.zeros(1, 1, 1, dtype=torch.float64))
    return tuple((trace, torch.zeros_like(active), trace.new_ones(1, 1, 1), recovery, escaped,
                  trace.new_tensor([micros]))
                 for trace, active, _, recovery, escaped, _ in initial)


class PopulationAgeGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_exact_expiry_survives_unequal_intervals_without_early_release(self):
        model = model_fixture()
        inputs = torch.tensor([[[.2]]], dtype=torch.float64)
        state = waiting_state(model, 137_001)
        _, before = model(inputs, (137_000,), state)
        for values in before:
            self.assertEqual(float(values[1].sum().detach()), 0)
            self.assertEqual(float(values[2].sum().detach()), 1)
            self.assertEqual(float(values[5][0]), 1)
        _, boundary = model(inputs, (1,), before)
        for cell, values in zip(model.cells, boundary):
            torch.testing.assert_close(values[1][0, 0], cell.population.reset_weights, rtol=0, atol=0)
            self.assertEqual(float(values[2].sum().detach()), 0)
            self.assertEqual(float(values[4].detach()), 0)
        _, later = model(inputs, (31_007,), boundary)
        self.assertGreater(float(later[0][2].sum().detach()), 0)
        model.validate_state(later, 1, torch.float64, torch.device("cpu"))

    def test_grouping_at_actual_boundaries_preserves_all_six_slots(self):
        model = model_fixture()
        inputs = torch.tensor([[[.25]]], dtype=torch.float64)
        whole, state = model(inputs, (500_000,))
        grouped, parts = model(inputs.expand(-1, 2, -1), (200_000, 300_000))
        torch.testing.assert_close(whole[:, -1], grouped[:, -1], rtol=0, atol=0)
        self.assertEqual(state_digest(state), state_digest(parts))
        self.assertEqual(model.event_schedule((500_000,))[0],
                         tuple(step for group in model.event_schedule((200_000, 300_000)) for step in group))

    def test_irregular_time_gradients_match_independent_finite_differences(self):
        model = model_fixture()
        inputs = torch.tensor([[[.25], [.45], [-.3], [.6], [-.2]]], dtype=torch.float64)
        intervals, target = (73_001, 99_999, 70_000, 10_001, 149_999), torch.tensor([[.4]], dtype=torch.float64)
        _, gradients = task_gradients(model, inputs, target, intervals)
        for name, parameter in model.named_parameters():
            index = (0,)*parameter.ndim
            analytic = float(gradients[name][index])
            self.assertGreater(abs(analytic), 1e-10, name)
            original, losses = float(parameter[index].detach()), []
            for delta in (-1e-5, 1e-5):
                with torch.no_grad():
                    parameter[index] = original+delta
                    losses.append(float((model(inputs, intervals)[0][:, -1]-target).square().mean()))
            with torch.no_grad():
                parameter[index] = original
            numeric = (losses[1]-losses[0])/2e-5
            self.assertAlmostEqual(analytic, numeric, delta=1e-8+abs(numeric)*3e-4, msg=name)
        self.assertTrue(torch.autograd.gradcheck(lambda x: model(x, intervals)[0][:, -1],
                                                (inputs.requires_grad_(),), eps=1e-6, atol=1e-7, rtol=1e-4))

    def test_checkpoint_cold_process_recovers_cohort_ages_and_mass(self):
        model = model_fixture()
        inputs = torch.tensor([[[.3]]], dtype=torch.float64)
        _, state = model(inputs, (173_001,))
        before = state_digest(state)
        payload = model_bytes(model, final_state=tuple(tuple(v.detach() for v in values) for values in state),
                              last_end_micros=173_018, optimizer={}, binding={})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"age.pt"
            path.write_bytes(payload)
            identity = hashlib.sha256(payload).hexdigest()
            restored, saved, metadata = load_training_checkpoint(path, identity)
            self.assertEqual(metadata["schema_version"], 3)
            self.assertEqual(state_digest(saved), before)
            self.assertEqual(tensor_digest(restored.state_dict()), tensor_digest(model.state_dict()))
            code = """import sys,torch
from qualification.hcsn_training.joint_graph import load_training_checkpoint
from qualification.hcsn_training.training_state import state_digest
m,s,_=load_training_checkpoint(sys.argv[1],sys.argv[2]); torch.set_num_threads(1)
y,s=m(torch.tensor([[[.3]]],dtype=torch.float64),(301007,),s)
print(state_digest(s))
"""
            cold = subprocess.check_output([sys.executable, "-c", code, str(path), identity], text=True).strip()
            _, expected = model(inputs, (301_007,), state)
            self.assertEqual(cold, state_digest(expected))
        self.assertEqual(state_digest(state), before)

    def test_event_budget_includes_restored_expiries_before_kernel_execution(self):
        model = model_fixture(maximum=2)
        inputs = torch.zeros(1, 1, 1, dtype=torch.float64)
        state = waiting_state(model, 50_000)
        with patch("qualification.hcsn_training.population_age_graph.finite_volume_transition") as kernel:
            with self.assertRaisesRegex(ValueError, "event-step budget"):
                model(inputs, (200_000,), state)
            kernel.assert_not_called()
        with self.assertRaisesRegex(ValueError, "event-step budget"):
            model.working_elements(1, (200_000,), state)

    def test_explicit_legacy_migration_preserves_effective_delay_and_all_tensors(self):
        source = PopulationCellGraph(PopulationGraphSpec(("encoder", "memory"), 1, 1, 1, 100_000)).double()
        inputs = torch.zeros(1, 1, 1, dtype=torch.float64)
        state = source.initial_state(inputs)
        for values in state:
            values[1].zero_()
            values[2][..., -1] = 1
        before = state_digest(state)
        model, migrated = migrate_fixed_grid(source, state, max_step_micros=100_000, max_substeps=16)
        self.assertEqual(model.spec.legacy_step_micros, 100_000)
        self.assertEqual(model.spec.maximum_remaining_micros, 300_000)
        self.assertEqual(tensor_digest(model.state_dict()), tensor_digest(source.state_dict()))
        for old, new in zip(state, migrated):
            self.assertEqual(new[5].tolist(), [100_000, 200_000, 300_000])
            for previous, copied in zip(old, new):
                torch.testing.assert_close(previous, copied, rtol=0, atol=0)
                self.assertFalse(copied.requires_grad)
        _, collision = model(inputs, (60_000,), migrated)
        self.assertEqual(collision[0][5].tolist(), [40_000, 140_000, 240_000, 240_000])
        _, before_release = model(inputs, (239_999,), collision)
        self.assertEqual(float(before_release[0][1].sum().detach()), 0)
        self.assertEqual(float(before_release[0][2].sum().detach()), 1)
        _, released = model(inputs, (1,), before_release)
        for cell, values in zip(model.cells, released):
            torch.testing.assert_close(values[1][0, 0], cell.population.reset_weights, rtol=0, atol=0)
            self.assertEqual(float(values[2].sum().detach()), 0)
        self.assertEqual(state_digest(state), before)
        payload = model_bytes(model, final_state=migrated, last_end_micros=100_000,
                              optimizer={}, binding={})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"migrated.pt"
            path.write_bytes(payload)
            restored, saved, _ = load_training_checkpoint(path, hashlib.sha256(payload).hexdigest())
            self.assertEqual(restored.spec, model.spec)
            self.assertEqual(state_digest(saved), state_digest(migrated))
        with self.assertRaises(ValueError):
            model_fixture().validate_state(migrated, 1, torch.float64, torch.device("cpu"))
        with self.assertRaisesRegex(ValueError, "legacy refractory times"):
            PopulationAgeGraphSpec(("encoder", "memory"), 1, 1, 1, 100_000, 16,
                                   legacy_step_micros=2**24+1)

    def test_age_checkpoint_cannot_implicitly_choose_its_numerical_kernel(self):
        saved = torch.load(io.BytesIO(model_bytes(model_fixture())), weights_only=True)
        del saved["spec"]["kernel"]
        output = io.BytesIO()
        torch.save(saved, output)
        payload = output.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"ambiguous.pt"
            path.write_bytes(payload)
            with self.assertRaisesRegex(ValueError, "explicit kernel"):
                load_training_checkpoint(path, hashlib.sha256(payload).hexdigest())

    def test_corrupt_or_misaligned_age_state_is_rejected(self):
        model = model_fixture()
        inputs = torch.zeros(1, 1, 1, dtype=torch.float64)
        for bad in (0, -.1, 1.5, 240_001, float("nan")):
            with self.subTest(age=bad), self.assertRaises(ValueError):
                model(inputs, (1,), waiting_state(model, bad))
        state = waiting_state(model, 137_001)
        state[1][5].add_(1)
        with self.assertRaises(ValueError):
            model(inputs, (1,), state)
        model32 = model.float()
        _, state32 = model32(inputs.float(), (73_001,))
        self.assertEqual(float(state32[0][5][0]), 240_000)
        model32.validate_state(state32, 1, torch.float32, torch.device("cpu"))


if __name__ == "__main__":
    unittest.main()
