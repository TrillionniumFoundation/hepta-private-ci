"""Physical-forward tests on small synthetic fixtures, never scientific holdout."""

from dataclasses import replace
import unittest

import torch

from .data import generate_sources
from .models import make_model
from .pft_interventions import (
    ARMS,
    forward_interventions,
    permutation,
    route_messages,
    tensors_identity,
)


class MessageInterventionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        torch.manual_seed(913)
        self.model = make_model(
            dict(neurons=8, boundary="qvi", features="value_risk", precision="mixed")
        )
        self.batch = generate_sources(
            (999000,), per_source=4, namespace="unit-test-only"
        )
        self.order = permutation(8, 913)

    def test_intact_tick_resume_matches_original_forward_and_weights(self):
        state = self.model.initial_state(
            4, initial_margin=self.batch.initial_margin[:, None]
        )
        with torch.no_grad():
            expected = self.model(self.batch.x, state=state)
        before = tensors_identity(self.model.state_dict())
        actual, audit = forward_interventions(
            self.model, self.batch, self.order, chunk=4
        )
        torch.testing.assert_close(actual["intact"], expected, atol=1e-6, rtol=1e-6)
        self.assertEqual(before, audit["parent_after_sha256"])
        self.assertEqual(audit["initial_and_final_clock"], [0, 12])
        self.assertEqual(
            audit["forwarded_signed_message_squared_norm_by_tick"]["deleted"],
            [0.0] * 12,
        )

    def test_delete_removes_input_path_with_identical_physical_initial_state(self):
        same_margin = torch.full_like(self.batch.initial_margin, 0.6)
        batch = replace(self.batch, initial_margin=same_margin)
        actual, _ = forward_interventions(self.model, batch, self.order, chunk=4)
        deleted = actual["deleted"]
        torch.testing.assert_close(
            deleted, deleted[:, :1].expand_as(deleted), atol=0, rtol=0
        )
        self.assertGreater(float((actual["intact"] - deleted).abs().max()), 1e-8)

    def test_shuffle_preserves_message_values_and_role_partition(self):
        values = torch.arange(48).reshape(2, 3, 8).double()
        changed = route_messages(values, "shuffled", self.order)
        for start in (0, 4):
            torch.testing.assert_close(
                changed[..., start : start + 4].sort().values,
                values[..., start : start + 4].sort().values,
            )
        self.assertFalse(torch.equal(changed, values))
        self.assertTrue(bool((self.order != torch.arange(8)).all()))
        torch.testing.assert_close(values, torch.arange(48).reshape(2, 3, 8).double())

    def test_shuffling_zero_messages_is_noop_but_original_path_is_active(self):
        zero = torch.zeros(4, 3, 8, dtype=torch.float64)
        torch.testing.assert_close(route_messages(zero, "shuffled", self.order), zero)
        actual, audit = forward_interventions(
            self.model, self.batch, self.order, chunk=4
        )
        self.assertGreater(
            float((actual["shuffled"] - actual["intact"]).abs().max()), 1e-8
        )
        for hashes in audit["initial_state_sha256_by_chunk_arm"]:
            self.assertEqual(len(set(hashes)), 1)
        self.assertTrue(audit["all_finite"])

    def test_batch_partition_does_not_change_any_arm(self):
        full, _ = forward_interventions(self.model, self.batch, self.order, chunk=4)
        split, _ = forward_interventions(self.model, self.batch, self.order, chunk=2)
        for arm in ARMS:
            torch.testing.assert_close(full[arm], split[arm], atol=1e-6, rtol=1e-6)

    def test_cross_role_permutation_is_rejected_before_forward(self):
        order = self.order.roll(4)
        with self.assertRaisesRegex(ValueError, "preserve sender/receiver"):
            forward_interventions(self.model, self.batch, order, chunk=4)


if __name__ == "__main__":
    unittest.main()
