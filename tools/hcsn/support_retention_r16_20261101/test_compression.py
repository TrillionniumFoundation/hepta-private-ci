"""Behavioral regressions for declared support and packed execution semantics."""

import unittest

import numpy as np

from ..addressed_decision_r15_20261101.planner import BeliefMemory
from .compression import AnchoredPackedMemory, BlockLaw, PackedBeliefMemory, pack, unpack


class CompressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.law = BlockLaw()

    def test_vertices_and_sparse_mixtures_keep_support_and_observation_law(self):
        rng = np.random.default_rng(160101)
        states = np.r_[np.eye(40), rng.dirichlet(np.ones(40), 64)]
        projected = self.law.project(states, "block")
        self.assertTrue(np.all(projected[states > 0] > 0))
        np.testing.assert_allclose(pack(projected), pack(states), rtol=0, atol=2e-16)
        for matrix in (self.law.E_read, self.law.E_refresh, self.law.reward):
            np.testing.assert_allclose(projected @ matrix, states @ matrix, rtol=0, atol=8e-16)

    def test_old_mean_failure_is_preserved_and_block_handles_erasure(self):
        belief = np.zeros(40)
        belief[0], belief[32] = .75, .25
        self.assertEqual(float(self.law.project(belief, "mean") @ self.law.E_read[:, 4]), 0.)
        memory = PackedBeliefMemory(self.law, [0, 1, 2, 3])
        memory.packed[0] = pack(belief)
        memory.observe(0, 4, "read")
        expected = np.zeros(8)
        expected[4] = 1.
        np.testing.assert_array_equal(memory.packed[0], expected)

    def test_packed_matches_expanded_projected_execution(self):
        expanded = BeliefMemory(self.law, [0, 1, 2, 3], projection="block")
        expanded.beliefs = self.law.project(expanded.beliefs, "block")
        packed = PackedBeliefMemory(self.law, [0, 1, 2, 3])
        for index, dt in enumerate((0., .001, .07, .23, .91, 2.4)):
            expanded.advance(dt)
            packed.advance(dt)
            if dt:
                token = index % 4
                expanded.observe(index % 4, token, "refresh")
                packed.observe(index % 4, token, "refresh")
            expanded.write((index + 1) % 4, index % 4)
            packed.write((index + 1) % 4, index % 4)
            np.testing.assert_allclose(packed.beliefs, expanded.beliefs, rtol=0, atol=2e-15)
        self.assertEqual(packed.packed.nbytes, 256)
        self.assertEqual(packed.operations, expanded.operations)

    def test_checkpoint_preserves_state_and_rejects_mutation(self):
        memory = PackedBeliefMemory(self.law, [0, 1, 2, 3])
        memory.advance(.37)
        restored = PackedBeliefMemory.restore(self.law, memory.checkpoint())
        self.assertEqual(memory.checkpoint(), restored.checkpoint())
        payload = memory.checkpoint()
        payload["packed"][0][0] += .1
        with self.assertRaises(ValueError):
            PackedBeliefMemory.restore(self.law, payload)

    def test_zero_time_and_impossible_observation(self):
        memory = PackedBeliefMemory(self.law, [0, 1, 2, 3])
        checkpoint = memory.checkpoint()
        memory.advance(0.)
        self.assertEqual(checkpoint, memory.checkpoint())
        with self.assertRaisesRegex(ValueError, "Impossible observation"):
            memory.observe(0, 4, "read")

    def test_unrepresentable_support_is_rejected_without_floor(self):
        p = np.zeros(8)
        p[0], p[4] = np.nextafter(0., 1.), 1.
        with self.assertRaisesRegex(ValueError, "unrepresentable"):
            unpack(p)

    def test_anchored_time_splitting_and_restart(self):
        whole = AnchoredPackedMemory(self.law, [0, 1, 2, 3])
        split = AnchoredPackedMemory(self.law, [0, 1, 2, 3])
        for index, duration in enumerate((.3, .61, 1.5)):
            whole.advance(duration)
            for _ in range(7):
                split.advance(duration / 7)
            np.testing.assert_allclose(whole.beliefs, split.beliefs, rtol=0, atol=2e-15)
            whole.observe(index, index, "refresh")
            split.observe(index, index, "refresh")
            whole.write((index + 1) % 4, (index + 2) % 4)
            split.write((index + 1) % 4, (index + 2) % 4)
            whole = AnchoredPackedMemory.restore(self.law, whole.checkpoint())
            split = AnchoredPackedMemory.restore(self.law, split.checkpoint())
            np.testing.assert_allclose(whole.packed, split.packed, rtol=0, atol=2e-15)
        self.assertEqual(whole.packed.nbytes + whole.anchor_times.nbytes + 8, 296)


if __name__ == "__main__":
    unittest.main()
