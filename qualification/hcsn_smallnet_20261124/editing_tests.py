"""Functional and failure-boundary checks for label-free weight programs."""

from copy import deepcopy
import unittest

import torch
from torch import nn

from .editing import interface_program, propose, tensor_digest


class _BranchedModel(nn.Module):
    """All three direct-input branches matter, including a controller."""

    def __init__(self, width=8, seed=1):
        super().__init__()
        generator = torch.Generator().manual_seed(seed)
        self.writer = nn.Linear(6, width, dtype=torch.float64)
        self.drive = nn.Linear(6, 1, dtype=torch.float64)
        self.boundary = nn.Linear(6, 1, dtype=torch.float64)
        self.readout = nn.Linear(width, 2, dtype=torch.float64)
        self.register_buffer("protected_physics", torch.tensor([.2, .4], dtype=torch.float64))
        with torch.no_grad():
            for value in self.parameters():
                value.copy_(torch.randn(value.shape, generator=generator, dtype=value.dtype) * .3)

    def forward(self, x):
        hidden = (self.writer(x) + self.drive(x).tanh() - self.boundary(x).tanh()).tanh()
        return self.readout(hidden)


class EditingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.model = _BranchedModel()
        generator = torch.Generator().manual_seed(17)
        self.x = torch.randn(3, 5, 6, generator=generator, dtype=torch.float64)
        self.matrix = torch.eye(6, dtype=torch.float64)
        self.matrix[0, 0], self.matrix[1, 1] = 1.5, .75
        self.matrix[2, 3] = .2
        self.offset = torch.tensor([.1, -.2, 0., .3, 0., -.1], dtype=torch.float64)

    def test_unidentified_capability_abstains_and_preserves_complete_bytes(self):
        before = tensor_digest(self.model.state_dict())
        candidate, report = propose(self.model, rule={"kind": "delay_xor_capability"})
        self.assertEqual(report["status"], "ABSTAIN")
        self.assertEqual(tensor_digest(candidate), before)
        self.assertEqual(tensor_digest(self.model.state_dict()), before)
        self.assertEqual(report["protocol"]["label_accesses"], 0)
        candidate["readout.weight"].zero_()
        self.assertEqual(tensor_digest(self.model.state_dict()), before)

    def test_class_rule_matches_exact_declared_output_permutation(self):
        before = self.model(self.x).detach()
        candidate, report = propose(self.model, rule={"kind": "class_permutation",
            "old_to_new": [1, 0], "scope": "replacement_label_schema"})
        after_model = deepcopy(self.model)
        after_model.load_state_dict(candidate)
        self.assertEqual(report["status"], "CANDIDATE")
        torch.testing.assert_close(after_model(self.x), before[..., [1, 0]], rtol=1e-14, atol=1e-14)
        self.assertTrue(torch.equal(candidate["writer.weight"], self.model.writer.weight))
        self.assertTrue(torch.equal(candidate["protected_physics"], self.model.protected_physics))

    def test_old_and_new_unobserved_label_schemas_are_refused(self):
        for extra in ({}, {"scope": "replacement_label_schema", "preserve_original_labels": True},
                      {"scope": "replacement_label_schema", "simultaneous_old_and_new": True}):
            candidate, report = propose(self.model, rule={"kind": "class_permutation",
                                                          "old_to_new": [1, 0], **extra})
            self.assertEqual(report["status"], "ABSTAIN")
            self.assertEqual(tensor_digest(candidate), tensor_digest(self.model.state_dict()))

    def test_class_mask_and_norm_bounds_refuse_atomically(self):
        rule = {"kind": "class_permutation", "old_to_new": [1, 0], "scope": "replacement_label_schema"}
        for kwargs in ({"editable_names": ("readout.weight",)}, {"max_l2": 0.}, {"max_linf": 0.}):
            candidate, report = propose(self.model, rule=rule, **kwargs)
            self.assertEqual(report["status"], "ABSTAIN")
            self.assertEqual(report["changed_scalar_count"], 0)
            self.assertEqual(tensor_digest(candidate), tensor_digest(self.model.state_dict()))

    def test_identity_class_rule_is_keep(self):
        candidate, report = propose(self.model, rule={"kind": "class_permutation",
            "old_to_new": [0, 1], "scope": "replacement_label_schema"})
        self.assertEqual(report["status"], "KEEP")
        self.assertEqual(tensor_digest(candidate), tensor_digest(self.model.state_dict()))

    def test_affine_input_program_preserves_complete_nonlinear_function(self):
        source = tensor_digest(self.model.state_dict())
        candidate, report = interface_program(self.model.state_dict(),
            ["writer", "drive", "boundary"], {"matrix": self.matrix, "offset": self.offset})
        migrated = deepcopy(self.model)
        migrated.load_state_dict(candidate)
        encoded = self.x @ self.matrix.T + self.offset
        torch.testing.assert_close(migrated(encoded), self.model(self.x), atol=1e-13, rtol=1e-13)
        self.assertEqual(report["status"], "CANDIDATE")
        self.assertEqual(report["cost"]["linear_system_solves"], 3)
        self.assertEqual(report["protocol"]["network_forward_calls"], 0)
        self.assertEqual(tensor_digest(self.model.state_dict()), source)
        self.assertTrue(torch.equal(candidate["readout.weight"], self.model.readout.weight))

    def test_missing_controller_branch_is_detectable_by_required_function_check(self):
        candidate, _ = interface_program(self.model.state_dict(), ["writer", "drive"],
                                        {"matrix": self.matrix, "offset": self.offset})
        migrated = deepcopy(self.model)
        migrated.load_state_dict(candidate)
        error = (migrated(self.x @ self.matrix.T + self.offset) - self.model(self.x)).abs().max()
        self.assertGreater(float(error), 1e-4)

    def test_input_domain_failures_return_original_without_partial_writes(self):
        source = tensor_digest(self.model.state_dict())
        singular = self.matrix.clone()
        singular[0] = singular[1]
        ill = torch.diag(torch.tensor([1e-12, 1., 1., 1., 1., 1.], dtype=torch.float64))
        for matrix, bounds in ((singular, {}), (ill, {}), (self.matrix, {"max_l2": .001})):
            candidate, report = interface_program(self.model.state_dict(), ["writer", "drive", "boundary"],
                                                  {"matrix": matrix, "offset": self.offset}, **bounds)
            self.assertEqual(report["status"], "ABSTAIN")
            self.assertEqual(tensor_digest(candidate), source)

    def test_missing_bias_refuses_nonzero_offset_but_accepts_linear_map(self):
        model = nn.Module()
        model.input = nn.Linear(6, 4, bias=False, dtype=torch.float64)
        for offset, status in ((self.offset, "ABSTAIN"), (torch.zeros_like(self.offset), "CANDIDATE")):
            candidate, report = interface_program(model.state_dict(), ["input"],
                                                  {"matrix": self.matrix, "offset": offset})
            self.assertEqual(report["status"], status)
            if status == "ABSTAIN":
                self.assertEqual(tensor_digest(candidate), tensor_digest(model.state_dict()))

    def test_program_reruns_on_distinct_checkpoints_not_a_copied_delta(self):
        paths = ["writer", "drive", "boundary"]
        transform = {"matrix": self.matrix, "offset": self.offset}
        first, _ = interface_program(self.model.state_dict(), paths, transform)
        delta = {key: first[key] - value for key, value in self.model.state_dict().items()}
        other = _BranchedModel(seed=237)
        rerun, receipt = interface_program(other.state_dict(), paths, transform)
        migrated, copied = deepcopy(other), deepcopy(other)
        migrated.load_state_dict(rerun)
        copied.load_state_dict({key: value + delta[key] for key, value in other.state_dict().items()})
        encoded = self.x @ self.matrix.T + self.offset
        torch.testing.assert_close(migrated(encoded), other(self.x), atol=1e-13, rtol=1e-13)
        self.assertGreater(float((copied(encoded) - other(self.x)).abs().max()), 1e-4)
        self.assertNotEqual(receipt["source_digest"], tensor_digest(self.model.state_dict()))

    def test_malformed_contracts_raise_before_mutation(self):
        before = tensor_digest(self.model.state_dict())
        with self.assertRaises(ValueError):
            propose(self.model, rule={"kind": "class_permutation", "old_to_new": [0, 0],
                                      "scope": "replacement_label_schema"})
        with self.assertRaises(ValueError):
            interface_program(self.model.state_dict(), ["writer", "writer"], self.matrix)
        with self.assertRaises(ValueError):
            interface_program(self.model.state_dict(), ["writer"], torch.eye(3))
        with self.assertRaises(ValueError):
            propose(self.model, max_l2=float("inf"))
        self.assertEqual(tensor_digest(self.model.state_dict()), before)

    def test_nonfinite_constructed_candidate_refuses_with_json_safe_receipt(self):
        import json
        model = nn.Module()
        model.input = nn.Linear(2, 1, dtype=torch.float32)
        with torch.no_grad():
            model.input.weight.fill_(torch.finfo(torch.float32).max)
            model.input.bias.zero_()
        original = tensor_digest(model.state_dict())
        candidate, receipt = interface_program(model.state_dict(), ["input"], torch.eye(2) * .5)
        self.assertEqual(receipt["status"], "ABSTAIN")
        self.assertEqual(receipt["reason"], "nonfinite_constructed_candidate")
        self.assertIsNone(receipt["proposed_delta_l2"])
        self.assertEqual(tensor_digest(candidate), original)
        json.dumps(receipt, allow_nan=False)


class RealModelTransferTests(unittest.TestCase):
    """Small fixtures verify the mapping contracts, not learning or speedups."""

    def test_complete_transfer_suite_on_real_population_state(self):
        from .model import ModelConfig, SmallHCSN
        from .transfer_suite import run_transfers
        torch.set_num_threads(1)
        torch.manual_seed(471)
        model = SmallHCSN(ModelConfig(neurons=8, boundary_mode="fixed", feature_normalization="population"))
        generator = torch.Generator().manual_seed(719)
        inputs = .25 * torch.randn(3, 2, 6, generator=generator, dtype=torch.float64)

        def initial(subject, batch):
            margins = torch.linspace(.6, 1.2, batch * subject.config.neurons,
                                     dtype=subject.reset_absolute.dtype,
                                     device=subject.reset_absolute.device)
            return subject.initial_state(batch, margins.reshape(batch, subject.config.neurons))

        report = run_transfers(model, inputs, initial)
        self.assertTrue(report["all_positive_controls_passed"], repr(report["panels"]))
        self.assertTrue(report["source_unchanged"])
        self.assertEqual(report["cost"]["attempted_forward_calls"], 7)
        self.assertFalse(report["classification"]["views_are_independent_training_runs"])
        self.assertFalse(report["classification"]["population_sign_symmetry_claimed"])

    def test_population_mapping_refuses_unknown_fields_and_cross_role_orders(self):
        from .model import ModelConfig, SmallHCSN
        from .transfer_suite import permute_model_state
        model = SmallHCSN(ModelConfig(neurons=8, boundary_mode="fixed"))
        source = model.state_dict()
        with self.assertRaises(ValueError):
            permute_model_state(source, [4, 1, 2, 3, 0, 5, 6, 7], 8)
        with self.assertRaises(ValueError):
            permute_model_state(source, [0., 1., 2., 3., 4., 5., 6., 7.], 8)
        with self.assertRaises(ValueError):
            permute_model_state({**source, "new_neuron_buffer": torch.ones(8)}, list(range(8)), 8)


if __name__ == "__main__":
    unittest.main()
