"""Spatial-grid admission and checkpoint compatibility, without a training campaign."""

import copy
from dataclasses import asdict, replace
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

import torch
from .joint_graph import (digest, graph_spec_dict, load_training_checkpoint,
                          model_bytes, tensor_digest)
from .population_graph import PopulationCellGraph, PopulationGraphSpec
from .population_age_graph import PopulationAgeCellGraph, PopulationAgeGraphSpec, migrate_fixed_grid
from .training_state import state_digest
from .worker import propose


class PopulationSpatialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hcsn-spatial-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    @staticmethod
    def model(age, bins=32):
        arguments = (("encoder", "memory"), 1, 1, 1, 100_000)
        if age:
            model = PopulationAgeCellGraph(PopulationAgeGraphSpec(*arguments, 16, spatial_bins=bins))
        else:
            model = PopulationCellGraph(PopulationGraphSpec(*arguments, spatial_bins=bins))
        model = model.double()
        with torch.no_grad():
            for name, parameter in model.named_parameters():
                parameter.fill_(.1 if "bias" in name else .3)
        return model

    def load(self, payload):
        path = self.directory/"checkpoint.pt"
        path.write_bytes(payload)
        return load_training_checkpoint(path, hashlib.sha256(payload).hexdigest())

    def test_default_grid_keeps_legacy_spec_identity_and_complete_state_replay(self):
        inputs = torch.tensor([[[.25], [.45]]], dtype=torch.float64)
        for age in (False, True):
            with self.subTest(age=age):
                model = self.model(age)
                intervals = (73_001, 99_999) if age else (1, 1)
                legacy_spec = asdict(model.spec)
                del legacy_spec["spatial_bins"]
                self.assertEqual(graph_spec_dict(model.spec), legacy_spec)
                self.assertEqual(digest(graph_spec_dict(model.spec)), digest(legacy_spec))
                with torch.no_grad():
                    _, state = model(inputs, intervals)
                payload = model_bytes(model, optimizer=dict(kind="sgd", momentum=0, learning_rate=.02, steps=1),
                                      binding={}, final_state=state, last_end_micros=200_000)
                saved = torch.load(io.BytesIO(payload), weights_only=True)
                self.assertEqual(saved["spec"], legacy_spec)
                restored, restored_state, metadata = self.load(payload)
                self.assertEqual(metadata["spec"], legacy_spec)
                self.assertEqual(restored.spec, model.spec)
                self.assertEqual(tensor_digest(restored.state_dict()), tensor_digest(model.state_dict()))
                self.assertEqual(state_digest(restored_state), state_digest(state))
                with torch.no_grad():
                    expected, expected_state = model(inputs, intervals, state)
                    actual, actual_state = restored(inputs, intervals, restored_state)
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                self.assertEqual(state_digest(actual_state), state_digest(expected_state))

    def test_explicit_grid_roundtrip_binds_identity_and_refuses_spec_only_substitution(self):
        inputs = torch.tensor([[[.25]]], dtype=torch.float64)
        for age in (False, True):
            with self.subTest(age=age):
                model = self.model(age, 8)
                intervals = (73_001,) if age else (1,)
                legacy = replace(model.spec, spatial_bins=32)
                self.assertNotEqual(digest(graph_spec_dict(model.spec)), digest(graph_spec_dict(legacy)))
                self.assertEqual(graph_spec_dict(model.spec)["spatial_bins"], 8)
                payload = model_bytes(model)
                restored, state, _ = self.load(payload)
                self.assertIsNone(state)
                self.assertEqual(restored.spec, model.spec)
                self.assertEqual(tensor_digest(restored.state_dict()), tensor_digest(model.state_dict()))
                with torch.no_grad():
                    expected, expected_state = model(inputs, intervals)
                    actual, actual_state = restored(inputs, intervals)
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                self.assertEqual(state_digest(actual_state), state_digest(expected_state))
                self.assertEqual(tuple(values[1].shape[-1] for values in actual_state), (8, 8))
                saved = torch.load(io.BytesIO(payload), weights_only=True)
                saved["spec"]["spatial_bins"] = 32
                changed = io.BytesIO()
                torch.save(saved, changed)
                with self.assertRaisesRegex(ValueError, "fixed population"):
                    self.load(changed.getvalue())

    def test_fixed_grid_migration_preserves_explicit_grid_and_release_state(self):
        source = self.model(False, 8)
        inputs = torch.tensor([[[.25], [.45]]], dtype=torch.float64)
        with torch.no_grad():
            _, state = source(inputs, (1, 1))
        model, migrated = migrate_fixed_grid(source, state, max_step_micros=100_000, max_substeps=16)
        self.assertEqual(model.spec.spatial_bins, 8)
        self.assertEqual(tensor_digest(model.state_dict()), tensor_digest(source.state_dict()))
        self.assertEqual(state_digest(tuple(values[:5] for values in migrated)), state_digest(state))
        for before, after in zip(state, migrated):
            expected_ages = torch.arange(1, before[2].shape[-1]+1, dtype=inputs.dtype)*source.spec.step_micros
            torch.testing.assert_close(after[5], expected_ages, rtol=0, atol=0)
            for old, new in zip(before, after):
                self.assertFalse(new.requires_grad)
                self.assertNotEqual(new.data_ptr(), old.data_ptr())
        self.assertEqual(model.event_schedule((100_000,), migrated), (((100_000, 1),),))
        with torch.no_grad():
            _, advanced = model(inputs[:, :1], (100_000,), migrated)
        model.validate_state(advanced, 1, inputs.dtype, inputs.device)

    def test_invalid_grid_sizes_are_refused_before_model_allocation(self):
        for age in (False, True):
            for bins in (True, False, 7, 129, 8.0, "8", None):
                with self.subTest(age=age, bins=bins), self.assertRaises(ValueError):
                    self.model(age, bins)

    def test_long_cancellation_traces_pass_real_admission_at_the_existing_bound(self):
        from .cancellation_fixture import prepare_cancellation_fixture
        for backend in ("population_grid", "population_age"):
            with self.subTest(backend=backend):
                directory = self.directory/backend
                directory.mkdir()
                model, request, inputs, _, intervals, workload = prepare_cancellation_fixture(directory, backend)
                self.assertEqual(model.spec.spatial_bins, 8)
                self.assertGreater(workload["event_steps_per_sample"], 16)
                self.assertLessEqual(request["optimizer_steps"], 64)
                self.assertLessEqual(workload["working_elements"], request["limits"]["max_elements"])
                self.assertLessEqual(request["limits"]["max_elements"], 1_048_576)
                original_grid = self.model(backend == "population_age")
                self.assertGreater(original_grid.working_elements(inputs.shape[0], intervals),
                                   request["limits"]["max_elements"])
                one = copy.deepcopy(request)
                one["optimizer_steps"] = 1
                payload, receipt = propose(model, one)
                self.assertEqual(receipt["completed_optimizer_steps"], 1)
                self.assertEqual(receipt["training_intervals_seen"], inputs.shape[0]*len(intervals))
                self.assertEqual(receipt["graph_digest"], workload["graph_digest"])
                recovered, state, _ = self.load(payload)
                recovered.validate_state(state, inputs.shape[0], inputs.dtype, inputs.device)
                self.assertEqual(recovered.spec, model.spec)
                one["limits"]["max_elements"] = workload["working_elements"]-1
                with self.assertRaisesRegex(ValueError, "tensor budget"):
                    propose(model, one)


if __name__ == "__main__":
    unittest.main()
