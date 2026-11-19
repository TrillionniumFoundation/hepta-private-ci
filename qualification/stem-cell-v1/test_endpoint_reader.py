"""Synthetic tensor checks; no real training/evaluation examples are consumed."""
import copy
import inspect
import unittest
from unittest.mock import patch

import torch
from torch.nn import functional as F

from bridge_reader import build_reader
from endpoint_reader import (EndpointBranch, build_endpoint_reader, endpoint_identity,
    load_bridge_warmup, public_value_permutation)
from token_reader import _normalize
from token_reader_training import parameter_digest


def fixture():
    generator = torch.Generator().manual_seed(8102)
    facts = torch.randn(2, 4, 5, 384, generator=generator)
    question = torch.randn(2, 3, 384, generator=generator)
    candidate = torch.randn(2, 2, 384, generator=generator)
    mask = torch.ones(2, 4, 5, dtype=torch.bool)
    mask[:, 1, -2:] = False
    return (facts, question, candidate, mask, torch.ones(2, 3, dtype=torch.bool),
            torch.ones(2, 2, dtype=torch.bool))


class EndpointReaderTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.features = fixture()
        self.bridge = build_reader("bridge", 41).eval().requires_grad_(False)
        self.bridge.training_source_groups = ("synthetic-fixture-source",)
        with torch.no_grad():
            self.bridge.fact_bridge.output.weight.copy_(torch.eye(32) * .1)
            self.bridge.head[2].bias.add_(.03)

    def test_common_warmup_tensors_predictions_and_caller_rng_are_preserved(self):
        digest = parameter_digest(self.bridge)
        rng = torch.random.get_rng_state().clone()
        models = {arm: load_bridge_warmup(self.bridge, arm, seed=41)
                  for arm in ("bridge", "endpoint", "broken", "local")}
        self.assertTrue(torch.equal(rng, torch.random.get_rng_state()))
        self.assertEqual(parameter_digest(self.bridge), digest)
        for arm, model in models.items():
            for name, value in self.bridge.state_dict().items():
                self.assertTrue(torch.equal(model.state_dict()[name], value), (arm, name))
            self.assertFalse(model.training)
            self.assertTrue(all(not p.requires_grad for p in model.parameters()))
            self.assertEqual(model.training_source_groups, self.bridge.training_source_groups)
            for steps in (1, 3, 8):
                self.assertTrue(torch.equal(model(*self.features, steps=steps),
                                            self.bridge(*self.features, steps=steps)), (arm, steps))
            self.assertEqual(endpoint_identity(model)["added_parameter_count"], 0 if arm == "bridge" else 4160)
        self.assertEqual(parameter_digest(models["endpoint"]), parameter_digest(models["broken"]))
        branch = models["endpoint"].endpoint_branch
        local = models["local"].head.endpoint_local
        for left, right in ((branch.input, local.input), (branch.match, local.hidden1),
                            (branch.value, local.hidden2), (branch.output, local.output)):
            self.assertTrue(torch.equal(left.weight, right.weight))

    def test_added_parameters_have_finite_real_gradients_after_output_update(self):
        for arm in ("endpoint", "broken", "local"):
            model = load_bridge_warmup(self.bridge, arm, seed=41).train().requires_grad_(True)
            common = set(self.bridge.state_dict())
            original = copy.deepcopy(model.state_dict())
            optimizer = torch.optim.SGD(model.parameters(), lr=.05)
            for _ in range(4):
                optimizer.zero_grad(set_to_none=True)
                F.cross_entropy(model(*self.features, steps=3), torch.tensor([0, 1])).backward()
                optimizer.step()
            for name, parameter in model.named_parameters():
                if name not in common:
                    self.assertIsNotNone(parameter.grad, (arm, name))
                    self.assertTrue(torch.isfinite(parameter.grad).all(), (arm, name))
                    self.assertGreater(parameter.grad.abs().sum().item(), 0, (arm, name))
                    self.assertFalse(torch.equal(parameter, original[name]), (arm, name))

    def test_slots_depend_only_on_public_fact_tokens_and_model_calls_exclude_labels(self):
        model = load_bridge_warmup(self.bridge, "endpoint", seed=41)
        captured = []
        original = model.endpoint_branch.endpoints

        def observe(evidence, mask):
            captured.append(evidence.detach().clone())
            return original(evidence, mask)

        with patch.object(model.endpoint_branch, "endpoints", side_effect=observe):
            model.prepare(*self.features)
            changed = list(self.features)
            changed[1], changed[2] = -changed[1], changed[2] * 2
            model.prepare(*changed)
        self.assertTrue(torch.equal(captured[0], captured[1]))
        expected = F.layer_norm(model.project(_normalize(self.features[0])), (32,))
        self.assertTrue(torch.equal(captured[0], expected))
        parameters = inspect.signature(model.forward).parameters
        self.assertNotIn("targets", parameters)
        self.assertNotIn("evidence_targets", parameters)
        with self.assertRaises(TypeError):
            model(*self.features, labels=torch.tensor([0, 1]))

    def test_broken_changes_only_payload_correspondence_and_uses_no_padding(self):
        torch.manual_seed(3)
        evidence = torch.randn(2, 4, 5, 32)
        facts, mask = self.features[0], self.features[3]
        real = EndpointBranch(32)
        with torch.no_grad():
            real.output.weight.copy_(torch.eye(32))
        broken = copy.deepcopy(real)
        broken.broken = True
        permutation = public_value_permutation(facts, mask)
        self.assertTrue(all(permutation[row, fact] != fact for row in range(2) for fact in range(4)))
        self.assertTrue(torch.equal(real.endpoints(evidence, mask)[0], broken.endpoints(evidence, mask)[0]))
        self.assertFalse(torch.equal(real(evidence, mask, permutation), broken(evidence, mask, permutation)))
        padded = facts.clone()
        padded[~mask] = 10000
        self.assertTrue(torch.equal(permutation, public_value_permutation(padded, mask)))
        self.assertTrue(torch.equal(permutation, public_value_permutation(facts, mask)))

    def test_masks_and_distinct_fact_permutation_are_respected(self):
        for arm in ("endpoint", "broken", "local"):
            model = load_bridge_warmup(self.bridge, arm, seed=41)
            with torch.no_grad():
                output = model.head.endpoint_local.output if arm == "local" else model.endpoint_branch.output
                output.weight.copy_(torch.eye(32))
            expected = model(*self.features, steps=3)
            changed = list(self.features)
            changed[0] = changed[0].clone()
            changed[0][~changed[3]] = 10000
            torch.testing.assert_close(expected, model(*changed, steps=3))
            permutation = torch.tensor([2, 0, 3, 1])
            changed = list(self.features)
            changed[0], changed[3] = changed[0][:, permutation], changed[3][:, permutation]
            torch.testing.assert_close(expected, model(*changed, steps=3))
            changed = list(self.features)
            changed[0] = torch.cat((changed[0], torch.randn(2, 1, 5, 384) * 10000), 1)
            changed[3] = torch.cat((changed[3], torch.zeros(2, 1, 5, dtype=torch.bool)), 1)
            torch.testing.assert_close(expected, model(*changed, steps=3))
            changed[3] = torch.zeros_like(changed[3])
            result = model(*changed, steps=3, return_attention=True)
            self.assertTrue(torch.isfinite(result["logits"]).all())
            self.assertLessEqual(result["state"].abs().max().item(), 1)
            self.assertTrue(torch.equal(result["attentions"][-1], torch.zeros(2, 5)))

    def test_zero_one_fact_and_hash_tie_boundaries_are_explicit(self):
        branch = EndpointBranch(32)
        with torch.no_grad():
            branch.output.weight.copy_(torch.eye(32))
        evidence = torch.randn(2, 4, 5, 32)
        mask = torch.zeros(2, 4, 5, dtype=torch.bool)
        mask[1, 2] = True
        permutation = public_value_permutation(self.features[0], mask)
        for broken in (False, True):
            branch.broken = broken
            self.assertTrue(torch.equal(branch(evidence, mask, permutation), torch.zeros(2, 4, 32)))
        facts = self.features[0].clone()
        facts[:, 1:] = facts[:, :1]
        tied_mask = torch.ones_like(self.features[3])
        tied = public_value_permutation(facts, tied_mask)
        self.assertEqual(tied.tolist(), [[1, 2, 3, 0], [1, 2, 3, 0]])
        self.assertIn("tie", endpoint_identity(load_bridge_warmup(self.bridge, "broken", seed=41))["hash_tie_limit"])

    def test_local_control_is_only_a_head_path_and_checkpoint_roundtrip_is_strict(self):
        local = load_bridge_warmup(self.bridge, "local", seed=41)
        with torch.no_grad():
            local.head.endpoint_local.output.weight.copy_(torch.eye(32))
        self.assertTrue(torch.equal(local.prepare(*self.features)["relations"],
                                    self.bridge.prepare(*self.features)["relations"]))
        for arm in ("bridge", "endpoint", "broken", "local"):
            model = load_bridge_warmup(self.bridge, arm, seed=41)
            restored = build_endpoint_reader(arm, 9)
            restored.load_state_dict(model.state_dict(), strict=True)
            self.assertEqual(endpoint_identity(restored), endpoint_identity(model))
            self.assertEqual(parameter_digest(restored), parameter_digest(model))
        with self.assertRaisesRegex(ValueError, "frozen"):
            load_bridge_warmup(build_reader("bridge", 41), "endpoint", seed=41)
        with self.assertRaisesRegex(ValueError, "registered"):
            build_endpoint_reader("other", 41)


if __name__ == "__main__":
    unittest.main()
