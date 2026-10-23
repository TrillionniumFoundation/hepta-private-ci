"""Converged input admission between the finite Bellman controller and its policy snapshot.

The local hashes are integrity markers, not authorization to run a real model.
"""
import unittest

from portfolio import Allocation, Config, State, execute
from snapshot_policy import (compile_optimal_snapshot, current_source_digest,
                             export_snapshot_bytes, load_snapshot_bytes,
                             rollout_snapshot)


class CompiledProfileAdmissionTests(unittest.TestCase):
    def test_online_compiled_seed_contract_matches_generator(self):
        cfg = Config(horizon=1)
        initial = State((2, 2, 2, 2), 4)
        digest = current_source_digest()
        snapshot = compile_optimal_snapshot(initial, cfg, digest)
        for seed in (None, True, 0.5, -1, 2**63, "7", []):
            with self.subTest(seed=repr(seed)):
                with self.assertRaisesRegex(ValueError, "random seed"):
                    rollout_snapshot(snapshot, cfg, digest, seed)
                with self.assertRaisesRegex(ValueError, "replay seed"):
                    execute(initial, cfg, seed)
        for seed in (0, 7, 2**63 - 1):
            with self.subTest(seed=seed):
                result = rollout_snapshot(snapshot, cfg, digest, seed)
                expected = execute(initial, cfg, seed)
                self.assertEqual(result["outputs"], expected["outputs"])
                self.assertEqual(result["paid_units"], expected["spent"])

    def test_mutable_state_and_actions_never_enter_policy_or_cache(self):
        for levels in ([0, 0, 0, 0], (0, 0, 0, 0)):
            if type(levels) is list:
                with self.assertRaisesRegex(ValueError, "portfolio state"):
                    State(levels, 12)
        with self.assertRaisesRegex(ValueError, "allocation"):
            Allocation([0, 0, 0, 0])
        self.assertEqual(hash(State((0, 0, 0, 0), 12)),
                         hash(State((0, 0, 0, 0), 12)))

    def test_canonical_cold_snapshot_survives_stricter_profile_contract(self):
        cfg = Config(horizon=2, activation_cost=1, risk_aversion=1.0)
        initial = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        compiled = compile_optimal_snapshot(initial, cfg, digest)
        reopened = load_snapshot_bytes(export_snapshot_bytes(compiled), cfg, initial)
        self.assertEqual(compiled.policy_sha256, reopened.policy_sha256)
        for seed in (0, 1, 29, 2**63 - 1):
            online = rollout_snapshot(reopened, cfg, digest, seed)
            oracle = execute(initial, cfg, seed)
            self.assertEqual(online["outputs"], oracle["outputs"])
            self.assertEqual(online["paid_units"], oracle["spent"])
            self.assertEqual(online["external_fixture_loss"],
                             oracle["external_fixture_loss"])

    def test_absurd_physical_profile_never_reaches_solver(self):
        for values in (
            {"unit_cost": 10**400},
            {"activation_cost": 10**400},
            {"emission_cost_each": 1.1},
            {"sync_penalty": 1_000_001},
            {"cost_shadow_price": float("nan")},
        ):
            with self.subTest(values=str(values)[:60]):
                with self.assertRaisesRegex(ValueError, "control profile"):
                    Config(**values)


if __name__ == "__main__":
    unittest.main()
