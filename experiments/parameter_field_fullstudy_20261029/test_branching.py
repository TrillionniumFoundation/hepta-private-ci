"""Complete-state tests with a three-parameter toy; no corpus or scientific bank."""

from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch

from . import branching
from .branching import StudyAdapter, codec, dynamics_identity, full_current_feature, state_difference, strict
from ..multimodal_output_portfolio.field_bridge_v3_20261027.training_common import Costs


class Toy(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.config = {"synthetic_engineering_fixture": True, "input_width": 2}
        self.linear = torch.nn.Linear(2, 1)
        self.frozen_bias = torch.nn.Parameter(torch.tensor([.2]), requires_grad=False)
        self.register_buffer("offset", torch.tensor([.1]))

    def forward(self, x):
        return self.linear(x) + self.frozen_bias + self.offset


class CompleteStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.protocol = json.loads(Path(branching.learning.__file__).with_name("PROTOCOL.json").read_text())

    def setUp(self):
        self.rng_before = (torch.get_rng_state(), random.getstate(), np.random.get_state())
        torch.manual_seed(1731)
        random.seed(1731)
        np.random.seed(1731)
        model = Toy().eval()
        original = deepcopy(model).eval().requires_grad_(False)
        observer = deepcopy(model).eval().requires_grad_(False)
        optimizer = torch.optim.SGD([p for p in model.parameters() if p.requires_grad], lr=.03, momentum=.9)
        context = SimpleNamespace(
            seed=17, protocol=deepcopy(self.protocol), costs=Costs(),
            probe=[{"fixture": "probe", "values": np.asarray([.3])}],
            guard=[{"fixture": "guard", "values": np.asarray([.4])}],
            baseline_guard={"source_ids": [("synthetic:a", "synthetic:b")],
                            "output_sha256": ["a" * 64],
                            "values": {"reward": np.asarray([.25], dtype=np.float64)}},
            corpus=SimpleNamespace(manifest={"synthetic": True}), original=original,
            observers={"reward": observer})
        binding = {"study_id": "synthetic-complete-state-tests", "proposal_sha256": "1" * 64,
                   "source_freeze_sha256": "2" * 64, "runtime_sha256": codec.digest(strict.runtime_descriptor()),
                   "prospective_protocol_sha256": "3" * 64, "global_resource_limits_sha256": "4" * 64}
        self.adapter = StudyAdapter(context, model, optimizer, binding)
        self.toy_step(2)

    def tearDown(self):
        torch.set_rng_state(self.rng_before[0])
        random.setstate(self.rng_before[1])
        np.random.set_state(self.rng_before[2])

    def toy_step(self, action):
        model, optimizer = self.adapter.model, self.adapter.optimizer
        x = torch.randn(2, 2)
        target = torch.tensor([[random.random()], [float(np.random.random())]])
        optimizer.zero_grad(set_to_none=True)
        ((model(x) - target).square().mean() * (action + 1)).backward()
        optimizer.step()
        with torch.no_grad():
            model.offset.add_(torch.rand(1) * .01)
        self.adapter.context.costs.add("synthetic_gradient_microsteps")

    def versions(self):
        return {k: v._version for k, v in itertools.chain(
            self.adapter.model.named_parameters(), self.adapter.model.named_buffers())}

    def test_complete_literal_restore_replays_all_rng_and_sgd(self):
        raw, digest = self.adapter.seal()
        state = codec.loads(raw, digest, len(raw))
        self.assertNotIn("frozen_bias", state["parameters"])
        self.assertTrue(state["optimizer"]["state"])
        self.toy_step(3)
        expected = codec.dumps(self.adapter.capture())
        draws = (torch.rand(3).numpy(), random.random(), np.random.random(3))
        charged = self.adapter.context.costs.snapshot()["synthetic_gradient_microsteps"]
        self.adapter.restore(raw, digest)
        self.assertEqual(codec.dumps(self.adapter.capture()), raw)
        self.toy_step(3)
        self.assertEqual(codec.dumps(self.adapter.capture()), expected)
        np.testing.assert_array_equal(torch.rand(3).numpy(), draws[0])
        self.assertEqual(random.random(), draws[1])
        np.testing.assert_array_equal(np.random.random(3), draws[2])
        self.assertEqual(self.adapter.context.costs.snapshot()["synthetic_gradient_microsteps"], charged + 1)

    def test_all_action_orderings_start_from_the_same_complete_parent(self):
        raw, digest = self.adapter.seal()
        reference = {}
        for order in itertools.permutations(range(4)):
            for action in order:
                self.adapter.restore(raw, digest)
                self.toy_step(action)
                observed = codec.dumps(self.adapter.capture())
                if action in reference:
                    self.assertEqual(observed, reference[action])
                else:
                    reference[action] = observed
        self.assertEqual(len(set(reference.values())), 4)

    def test_none_gradient_and_zero_gradient_are_distinct_and_restore_exactly(self):
        parameter = next(p for p in self.adapter.model.parameters() if p.requires_grad)
        parameter.grad = None
        none_raw, none_sha = self.adapter.seal()
        none_state = self.adapter.capture()
        parameter.grad = torch.zeros_like(parameter)
        zero_state = self.adapter.capture()
        difference = state_difference(none_state, zero_state)
        self.assertFalse(difference["reference_tail_state_equal"])
        self.assertIn("gradients", difference["different_components"])
        self.assertIsNotNone(difference["gradients"]["first_different_tensor"])
        self.adapter.restore(none_raw, none_sha)
        self.assertIsNone(parameter.grad)

    def assert_rejected_before_write(self, record):
        before = codec.dumps(self.adapter.capture())
        versions = self.versions()
        raw = codec.dumps(record)
        with self.assertRaises(ValueError):
            self.adapter.restore(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(codec.dumps(self.adapter.capture()), before)
        self.assertEqual(self.versions(), versions)

    def test_hash_or_future_tape_tamper_is_rejected_before_write(self):
        raw, digest = self.adapter.seal()
        versions = self.versions()
        with self.assertRaises(ValueError):
            self.adapter.restore(raw, "0" * 64)
        self.assertEqual(self.versions(), versions)
        record = self.adapter.capture()
        record["remaining_schedule"][0]["adapt_seed"] += 1
        self.assert_rejected_before_write(record)

    def test_malformed_momentum_is_rejected_before_any_tensor_write(self):
        original = self.adapter.capture()
        index = next(iter(original["optimizer"]["state"]))
        value = original["optimizer"]["state"][index]["momentum_buffer"]
        for replacement in (np.zeros(value.size + 1, dtype=value.dtype),
                            value.astype(np.float64), np.full_like(value, np.nan)):
            with self.subTest(shape=replacement.shape, dtype=str(replacement.dtype)):
                record = deepcopy(original)
                record["optimizer"]["state"][index]["momentum_buffer"] = replacement
                self.assert_rejected_before_write(record)

    def test_recorded_trainability_and_cursor_inventory_cannot_be_ignored(self):
        record = self.adapter.capture()
        name = next(iter(record["requires_grad"]))
        record["requires_grad"][name] = not record["requires_grad"][name]
        self.assert_rejected_before_write(record)
        record = self.adapter.capture()
        record["cursor"]["undeclared_future_information"] = 1
        self.assert_rejected_before_write(record)

    def test_policy_feature_excludes_future_tape_rng_and_controller_identity(self):
        record = self.adapter.capture()
        field = np.arange(12, dtype=np.float64)
        original = full_current_feature(record, field)
        changed = deepcopy(record)
        changed["remaining_schedule"][0]["adapt_seed"] += 99
        changed["rng"]["torch_cpu"][0] ^= 1
        changed["cursor"]["schedule_id"] += 10
        changed["cursor"]["path_kind"] = "unseen_policy"
        changed["history"] = [{"arbitrary_future_label": 99}]
        np.testing.assert_array_equal(full_current_feature(changed, field), original)
        name = next(iter(changed["parameters"]))
        changed["parameters"][name].flat[0] += .5
        self.assertFalse(np.array_equal(full_current_feature(changed, field), original))

    def test_momentum_presence_and_history_identity_are_not_conflated(self):
        record = self.adapter.capture()
        index = next(iter(record["optimizer"]["state"]))
        record["optimizer"]["state"][index]["momentum_buffer"].fill(0.)
        absent = deepcopy(record)
        del absent["optimizer"]["state"][index]["momentum_buffer"]
        self.assertFalse(np.array_equal(full_current_feature(record, np.zeros(12)),
                                       full_current_feature(absent, np.zeros(12))))
        changed = deepcopy(record)
        changed["history"] = [{"field": [0.] * 12, "action": 2, "accepted": True,
                               "scheduled_microsteps": 48}]
        first, second = dynamics_identity(record), dynamics_identity(changed)
        self.assertEqual(first["dynamics"], second["dynamics"])
        self.assertNotEqual(first["controller_history"], second["controller_history"])

    def test_guard_receipt_advances_clock_even_when_rejected(self):
        with patch.object(branching.learning, "guarded_block", return_value={"accepted": False}):
            receipt = self.adapter.transition(2)
        self.assertEqual(self.adapter.clock, 48)
        self.assertEqual(receipt["remaining_steps"], 240)
        self.assertEqual(receipt["logical_clock"], 48)
        self.assertFalse(receipt["accepted"])
        with patch.object(branching.learning, "guarded_block", side_effect=RuntimeError("toy failure")):
            with self.assertRaises(RuntimeError):
                self.adapter.transition(2)
        self.assertEqual(self.adapter.clock, 48)


if __name__ == "__main__":
    unittest.main()
