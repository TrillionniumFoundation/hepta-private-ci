"""A compiled policy must exactly replay the costly Oracle without online solving."""
import time
import unittest
from unittest.mock import patch

from portfolio import Config, Controller, State, execute
from snapshot_policy import (compile_optimal_snapshot, current_source_digest,
                             rollout_snapshot)


class SnapshotPolicyTests(unittest.TestCase):
    def test_compiled_policy_matches_exact_oracle_for_all_128_draws(self):
        cfg = Config(horizon=3, risk_aversion=0.0, activation_cost=1,
                     cost_shadow_price=0.02)
        initial = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        policy = compile_optimal_snapshot(initial, cfg, digest)
        self.assertGreater(len(policy.entries), 1)
        for seed in range(128):
            oracle = execute(initial, cfg, seed)
            chosen = rollout_snapshot(policy, cfg, digest, seed)
            self.assertEqual(chosen["outputs"], oracle["outputs"])
            self.assertEqual(chosen["paid_units"], oracle["spent"])
            self.assertEqual(chosen["external_fixture_loss"],
                             oracle["external_fixture_loss"])
            self.assertEqual(chosen["actions"],
                             tuple(row["allocation"] for row in oracle["records"]))
        self.assertEqual(policy.policy_sha256,
                         compile_optimal_snapshot(initial, cfg, digest).policy_sha256)

    def test_unseen_state_or_mismatched_profile_must_not_fallback_to_oracle(self):
        cfg = Config(horizon=2)
        initial = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        snap = compile_optimal_snapshot(initial, cfg, digest)
        with self.assertRaisesRegex(ValueError, "source or initial"):
            compile_optimal_snapshot(initial, cfg, "0" * 64)
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            snap.choose(initial, cfg, digest, "PRODUCTION")
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            snap.choose(initial, Config(horizon=1), digest, "FINITE_SYNTHETIC_DENY_ALL")
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            snap.choose(initial, cfg, "a" * 64, "FINITE_SYNTHETIC_DENY_ALL")
        with self.assertRaisesRegex(ValueError, "uncovered"):
            snap.choose(State((2, 0, 2, 0), 12), cfg, digest,
                        "FINITE_SYNTHETIC_DENY_ALL")

    def test_runtime_has_no_solver_calls_after_compilation(self):
        cfg = Config(horizon=2)
        initial = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        snap = compile_optimal_snapshot(initial, cfg, digest)
        with patch.object(Controller, "solve", side_effect=AssertionError("online solve")):
            for seed in range(16):
                self.assertEqual(set(rollout_snapshot(snap, cfg, digest, seed)["outputs"]),
                                 {"text", "audio", "image", "video"})

    def test_compiled_lookup_runs_without_repeated_full_search(self):
        cfg = Config(horizon=2)
        initial = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        snap = compile_optimal_snapshot(initial, cfg, digest)
        self.assertGreater(dict(snap.offline_work)["expanded_states"], len(snap.entries))
        before = time.perf_counter_ns()
        for _ in range(1000):
            snap.choose(initial, cfg, digest, "FINITE_SYNTHETIC_DENY_ALL")
        after = time.perf_counter_ns()
        self.assertGreater(after, before)


if __name__ == "__main__":
    unittest.main()
