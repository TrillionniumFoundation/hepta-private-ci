"""Adversarial audit fixtures, distinct from registered scientific trajectories."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from .audit import execution_gates, validate_roster


class AuditAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads(
            Path(__file__).with_name("PROTOCOL.json").read_text()
        )
        self.model = {
            key: self.protocol[key]
            for key in (
                "dt",
                "mu",
                "sigma",
                "rho",
                "killing_rate",
                "payoff_cost",
                "running_cost",
            )
        }
        low, high, count = self.protocol["state_grid"]
        self.model.update(
            {
                "schema": "hepta.free-boundary.readout.v1",
                "transition_kind": "survival_weighted_gaussian_bins",
                "states": [low + i * (high - low) / (count - 1) for i in range(count)],
                "value": [[] for _ in range(self.protocol["horizon"] + 1)],
            }
        )
        starts = [
            min(range(count), key=lambda i: abs(self.model["states"][i] - x))
            for x in self.protocol["starts"]
        ]
        self.index = {
            "complete": True,
            "episodes": [
                {
                    "case": f"{arm}.s{state}.n{seed}",
                    "arm": arm,
                    "initial_state": state,
                    "seed": seed,
                }
                for state in starts
                for seed in self.protocol["noise_seeds"]
                for arm in self.protocol["arms"]
            ],
        }

    def test_complete_registered_roster_is_admitted(self):
        validate_roster(self.index, self.protocol, self.model)

    def test_dropping_whole_context_cannot_hide_behind_complete_flag(self):
        self.index["episodes"] = self.index["episodes"][3:]
        with self.assertRaisesRegex(ValueError, "roster"):
            validate_roster(self.index, self.protocol, self.model)

    def test_duplicate_context_cannot_replace_missing_context(self):
        self.index["episodes"][-3:] = deepcopy(self.index["episodes"][:3])
        with self.assertRaisesRegex(ValueError, "roster"):
            validate_roster(self.index, self.protocol, self.model)

    def test_changed_drift_profile_cannot_retain_registered_starts(self):
        self.model["mu"] += 0.1
        with self.assertRaisesRegex(ValueError, "parameter changed: mu"):
            validate_roster(self.index, self.protocol, self.model)

    def test_exact_parity_with_all_native_fallback_does_not_pass(self):
        arms = {
            arm: {
                "applied_readout_count": 0,
                "applied_actions": {},
                "all_native_fallback": True,
            }
            for arm in self.protocol["arms"]
        }
        gates = execution_gates(arms, 56, 56)
        self.assertTrue(gates["all_registered_paths_match_exact_dp"])
        self.assertFalse(gates["every_arm_applied_readout"])
        self.assertFalse(gates["candidate_stop_and_continue_exercised"])
        self.assertFalse(gates["no_arm_all_native_fallback"])


if __name__ == "__main__":
    unittest.main()
