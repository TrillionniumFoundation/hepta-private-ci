"""Finite optimizer replay, context integrity and paired-control checks."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead


class CompleteTrainingStateTests(unittest.TestCase):
    def setUp(self):
        self.x = np.random.default_rng(51).normal(size=(32, 4))
        self.y = np.arange(32, dtype=np.int64) % 2
        self.new_y = 1 - self.y
        self.bindings = {"encoder": "frozen-checkpoint", "preprocessing": "fixed-v1",
                         "source_groups": "source-groups-v1", "task": "binary-v1",
                         "topology": "one-cell", "protocol": "frozen-experiment-v1"}
        self.contexts = {"old": dataset_digest(self.x, self.y),
                         "current": dataset_digest(self.x, self.new_y)}

    def state(self, mode="gated", sampler="full_batch"):
        return CellTrainingState(NumpyCellHead(4, 2, mode, rank=2, seed=11),
                                 bindings=self.bindings, seed=72, contexts=self.contexts,
                                 active_context="old", protocol={"sampler": sampler, "batch_size": 9})

    def test_full_batch_default_update_matches_legacy_head_exactly(self):
        for mode in ("linear", "gated", "residual"):
            state = self.state(mode)
            legacy = NumpyCellHead(4, 2, mode, rank=2, seed=11)
            legacy.train(self.x, self.y, steps=31)
            for _ in range(31):
                state.advance(self.x, self.y)
            with self.subTest(mode=mode):
                self.assertEqual(state.head.digest(), legacy.digest())

    def test_cold_process_resume_retains_context_moments_and_sampler(self):
        state = self.state(sampler="iid_with_replacement")
        for _ in range(7):
            state.advance(self.x, self.y)
        before_context = state.vector().copy()
        state.select_context("current")
        np.testing.assert_array_equal(state.vector(), before_context)
        uninterrupted = state.clone()
        expected_marks = [uninterrupted.advance(self.x, self.new_y)["marks"] for _ in range(13)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state.save(root / "checkpoint")
            (root / "expected.json").write_text(json.dumps({"bindings": self.bindings,
                                                          "contexts": self.contexts}))
            np.savez(root / "data.npz", x=self.x, y=self.new_y)
            program = """
import json, sys
from pathlib import Path
import numpy as np
from cell_field_state import CellTrainingState
p=Path(sys.argv[1]); e=json.loads((p/'expected.json').read_text())
s=CellTrainingState.load(p/'checkpoint', e['bindings'], expected_contexts=e['contexts'])
with np.load(p/'data.npz', allow_pickle=False) as data:
    marks=[s.advance(data['x'], data['y'])['marks'] for _ in range(13)]
s.save(p/'continued')
print(json.dumps({'marks':marks, 'digest':s.digest()}))
"""
            result = subprocess.run([sys.executable, "-c", program, str(root)],
                                    cwd=Path(__file__).parent, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), {"marks": expected_marks,
                                                        "digest": uninterrupted.digest()})
            loaded = CellTrainingState.load(root / "continued", self.bindings,
                                            expected_contexts=self.contexts)
            np.testing.assert_array_equal(loaded.vector(), uninterrupted.vector())

    def test_parameters_alone_do_not_resume_the_same_training_dynamics(self):
        complete = self.state()
        for _ in range(12):
            complete.advance(self.x, self.y)
        reset = CellTrainingState(complete.head, bindings=self.bindings,
                                 contexts=self.contexts, active_context="old")
        self.assertEqual(reset.head.digest(), complete.head.digest())
        complete.advance(self.x, self.y)
        reset.advance(self.x, self.y)
        self.assertNotEqual(reset.head.digest(), complete.head.digest())

    def test_pure_transition_and_explicit_marks_do_not_consume_rng(self):
        state = self.state(sampler="iid_with_replacement")
        digest, vector = state.digest(), state.vector()
        marks = np.array([0, 3, 7, 9, 12, 17, 19])
        pure = state.transition_vector(vector, state.step_count, self.x, self.y, marks)
        self.assertEqual(state.digest(), digest)
        clone, rng_before = state.clone(), state.rng.bit_generator.state
        receipt = clone.advance(self.x, self.y, indices=marks)
        np.testing.assert_array_equal(clone.vector(), pure)
        np.testing.assert_array_equal(state.vector(), vector)
        self.assertEqual(clone.rng.bit_generator.state, rng_before)
        self.assertEqual(receipt["marks"], marks.tolist())
        self.assertEqual(receipt["mark_origin"], "external")

    def test_paired_controls_share_moments_on_the_first_transition(self):
        left, right = self.state(), self.state()
        n = left.parameter_count
        mask = np.zeros(n, dtype=bool)
        mask[-2:] = True
        delta = np.zeros(n)
        delta[-2:] = [0.01, -0.01]
        left.advance(self.x, self.y, indices=[0, 1, 8, 9])
        right.advance(self.x, self.y, indices=[0, 1, 8, 9], intervention=delta, mask=mask)
        np.testing.assert_array_equal(left.vector()[n:], right.vector()[n:])
        np.testing.assert_allclose(right.parameter_vector(), left.parameter_vector() + delta,
                                   rtol=0, atol=0)

    def test_context_and_mask_failure_leave_complete_state_unchanged(self):
        state = self.state(sampler="iid_with_replacement")
        initial = state.digest()
        changed = self.x.copy()
        changed[0, 0] += 0.01
        for features, labels in ((changed, self.y), (self.x, self.new_y)):
            with self.assertRaises(ValueError):
                state.advance(features, labels)
            self.assertEqual(state.digest(), initial)
        with self.assertRaises(ValueError):
            state.select_context("future")
        with self.assertRaises(ValueError):
            state.advance(self.x, self.y, intervention=np.ones(state.parameter_count),
                          mask=np.zeros(state.parameter_count, dtype=bool))
        self.assertEqual(state.digest(), initial)

    def test_frozen_binding_views_cannot_change_the_optimizer_contract(self):
        state = self.state()
        initial = state.digest()
        state.protocol["learning_rate"] = 1.0
        state.bindings["encoder"] = "different"
        state.contexts["old"] = "0" * 64
        self.assertEqual(state.digest(), initial)

    def test_checkpoint_rejects_wrong_identity_protocol_and_corruption(self):
        state = self.state()
        state.advance(self.x, self.y)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "checkpoint"
            state.save(target)
            with self.assertRaises(ValueError):
                CellTrainingState.load(target, {**self.bindings, "encoder": "new"})
            with self.assertRaises(ValueError):
                CellTrainingState.load(target, self.bindings, {"learning_rate": 0.01})
            with self.assertRaises(ValueError):
                CellTrainingState.load(target, self.bindings, expected_contexts={})
            with self.assertRaises(ValueError):
                CellTrainingState.load(target, self.bindings, expected_state_digest="0" * 64)
            metadata = target / "manifest.json"
            original = metadata.read_bytes()
            altered = json.loads(original)
            altered["step_count"] += 1
            metadata.write_text(json.dumps(altered))
            with self.assertRaises(ValueError):
                CellTrainingState.load(target, self.bindings)
            metadata.write_bytes(original)
            with (target / "state.npz").open("ab") as stream:
                stream.write(b"unexpected")
            with self.assertRaises(ValueError):
                CellTrainingState.load(target, self.bindings)


if __name__ == "__main__":
    unittest.main()
