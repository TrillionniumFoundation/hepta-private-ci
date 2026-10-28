"""Regression tests for causal inference, feedback separation and cost accounting."""

import json
import math
from pathlib import Path
import tempfile
import unittest

from experiments.adaptive_neuron_v2.learning.kernel import initial_raw
from experiments.adaptive_neuron_v2.learning.network import (
    initialize,
    model_payload as neural_payload,
)
from .audit import account_records
from .common import charge, model_payload, sha, write
from .reference import Reference
from .run import verify_checkpoint


class OwnerContracts(unittest.TestCase):
    def setUp(self):
        self.parameters = initialize(910001)
        self.raw = initial_raw()
        self.model = model_payload(
            neural_payload(self.parameters, self.raw, "first_passage", "1" * 64)
        )
        self.initial = {"sequence": 0, "balance": 16.0, "price": 0.02, "head": "1" * 64}

    def test_raw_belief_has_exact_likelihood_and_zero_neural_work(self):
        reference = Reference(
            self.model,
            (0.75, 0.04, 8),
            {"readout": "raw_belief_dp", "credit": "live"},
            self.initial,
        )
        result = reference.observe(1)
        self.assertAlmostEqual(result["logit"], math.log(3))
        self.assertAlmostEqual(result["immediate"], 0.5)
        self.assertEqual(result["actual_snn_cell_updates"], 0)
        self.assertEqual(result["spikes"], 0)
        self.assertEqual(result["actual_work"], 1.0)

    def test_insufficient_next_quote_stops_before_another_observation(self):
        reference = Reference(
            self.model,
            (0.6, 0.01, 8),
            {"readout": "raw_belief_dp", "credit": "off"},
            {**self.initial, "balance": 2.0},
        )
        result = reference.observe(1)
        self.assertTrue(result["budget_forced_abstention"])
        self.assertEqual(result["action"], "abstain")
        self.assertEqual(reference.work, 1.0)
        with self.assertRaises(ValueError):
            reference.observe(1)
        self.assertEqual(reference.work, 1.0)

    def test_credit_price_changes_boundary_without_extra_neural_input(self):
        low = Reference(
            self.model,
            (0.6, 0.01, 8),
            {"readout": "snn", "credit": "off"},
            self.initial,
        )
        high = Reference(
            self.model,
            (0.6, 0.01, 8),
            {"readout": "snn", "credit": "live"},
            {**self.initial, "price": 0.08},
        )
        a, b = low.observe(1), high.observe(1)
        self.assertEqual(a["logit"], b["logit"])
        self.assertEqual(a["state_after"]["neural"], b["state_after"]["neural"])
        self.assertGreater(a["continuation"], b["continuation"])
        self.assertEqual(high.price, 0.08)
        settled = high.settle(3.0, 1.0)
        self.assertNotEqual(settled["price"], high.price)
        self.assertEqual(high.price, 0.08, "Within-episode price must remain frozen")

    def test_surrogate_parameters_do_not_become_runtime_hazard_or_price(self):
        changed = json.loads(json.dumps(self.model))
        changed["neural"]["surrogate"].update(mu=-1.0, sigma=1.8, **{"lambda": 0.9})
        a = Reference(
            self.model,
            (0.6, 0.01, 8),
            {"readout": "snn", "credit": "live"},
            self.initial,
        )
        b = Reference(
            changed, (0.6, 0.01, 8), {"readout": "snn", "credit": "live"}, self.initial
        )
        self.assertEqual(a.observe(1), b.observe(1))

    def test_checkpoint_binding_rejects_changed_task_weights(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            write(
                checkpoint,
                {
                    "arm": "fixed_theta",
                    "development_only": True,
                    "parameters": {
                        key: value.tolist() for key, value in self.parameters.items()
                    },
                    "raw_theta": self.raw.tolist(),
                },
            )
            model = model_payload(
                neural_payload(
                    self.parameters, self.raw, "first_passage", sha(checkpoint)
                )
            )
            profile = root / "model.json"
            write(profile, model)
            verify_checkpoint(profile, checkpoint)
            model["neural"]["weights"][0][0] += 0.1
            altered = root / "altered.json"
            write(altered, model)
            with self.assertRaisesRegex(ValueError, "task-trained checkpoint"):
                verify_checkpoint(altered, checkpoint)

    def test_torn_account_is_not_treated_as_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "account.jsonl"
            path.write_bytes(b'{"payload_json":"{}","record_digest":"bad"}')
            with self.assertRaisesRegex(ValueError, "torn"):
                account_records(path)

    def test_retry_old_timings_are_not_charged_as_another_transition(self):
        old = {
            "native_transition_executed": False,
            "execution_micros": 100,
            "model_latency_micros": 60,
            "journal_bytes_written": 464,
            "actual_snn_cell_updates": 0,
            "actual_resource_work": 0,
        }
        cost = charge(
            [{"response": {"ok": True, "result": old, "physical_rpc_micros": 2}}]
        )
        self.assertEqual(cost["physical_rpc_micros"], 2)
        self.assertEqual(cost["owner_ticks"], 0)
        self.assertEqual(cost["native_tick_micros"], 0)
        self.assertEqual(cost["journal_bytes_written"], 0)
        self.assertEqual(cost["actual_resource_work"], 0)


if __name__ == "__main__":
    unittest.main()
