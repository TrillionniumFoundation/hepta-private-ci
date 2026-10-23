import gc
import time
import unittest
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
            self.assertEqual(chosen['outputs'], oracle['outputs'])
            self.assertEqual(chosen['paid_units'], oracle['spent'])
            self.assertEqual(chosen['external_fixture_loss'],
                             oracle['external_fixture_loss'])
            self.assertEqual(chosen['actions'],
                             tuple(row['allocation'] for row in oracle['records']))
        self.assertEqual(policy.policy_sha256,
                         compile_optimal_snapshot(initial, cfg, digest).policy_sha256)

    def test_unseen_state_or_mismatched_profile_must_not_fallback_to_oracle(self):
        cfg = Config(horizon=2)
        initial = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        snap = compile_optimal_snapshot(initial, cfg, digest)
        with self.assertRaisesRegex(ValueError, 'source or initial'):
            compile_optimal_snapshot(initial, cfg, '0'*64)
        with self.assertRaisesRegex(ValueError, 'scope mismatch'):
            snap.choose(initial, cfg, digest, 'PRODUCTION')
        with self.assertRaisesRegex(ValueError, 'scope mismatch'):
            snap.choose(initial, Config(horizon=1), digest, 'FINITE_SYNTHETIC_DENY_ALL')
        with self.assertRaisesRegex(ValueError, 'scope mismatch'):
            snap.choose(initial, cfg, 'a'*64, 'FINITE_SYNTHETIC_DENY_ALL')
        with self.assertRaisesRegex(ValueError, 'uncovered'):
            snap.choose(State((2, 0, 2, 0), 12), cfg, digest,
                        'FINITE_SYNTHETIC_DENY_ALL')

    def test_runtime_has_no_solver_calls_after_compilation(self):
        from unittest.mock import patch
        cfg = Config(horizon=2)
        initial = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        snap = compile_optimal_snapshot(initial, cfg, digest)
        with patch.object(Controller, 'solve', side_effect=AssertionError('online solve')):
            for seed in range(16):
                self.assertEqual(set(rollout_snapshot(snap, cfg, digest, seed)['outputs']),
                                 {'text', 'audio', 'image', 'video'})

    def test_compiled_lookup_runs_without_repeated_full_search(self):
        cfg = Config(horizon=2)
        initial = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        snap = compile_optimal_snapshot(initial, cfg, digest)
        self.assertGreater(dict(snap.offline_work)['expanded_states'], len(snap.entries))
        before = time.perf_counter_ns()
        for _ in range(1000):
            snap.choose(initial, cfg, digest, 'FINITE_SYNTHETIC_DENY_ALL')
        after = time.perf_counter_ns()
        self.assertGreater(after, before)

if __name__ == '__main__': unittest.main()

class SnapshotLimitTests(unittest.TestCase):
    def test_offline_expansion_and_transition_caps_fail_closed(self):
        from unittest.mock import patch
        cfg = Config(horizon=2)
        initial = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        with patch('snapshot_policy.MAX_OFFLINE_STATES', 1):
            with self.assertRaisesRegex(ValueError, 'expansion cap'):
                compile_optimal_snapshot(initial, cfg, digest)
        with patch('snapshot_policy.MAX_OFFLINE_TRANSITIONS', 2):
            with self.assertRaisesRegex(ValueError, 'branch cap'):
                compile_optimal_snapshot(initial, cfg, digest)

    def test_snapshot_is_bound_to_configuration_and_code_source(self):
        cfg = Config(horizon=1)
        initial = State((2, 2, 0, 0), 12)
        digest = current_source_digest()
        snap = compile_optimal_snapshot(initial, cfg, digest)
        with self.assertRaises(TypeError):
            snap._choices[initial] = (None, float('nan'))
        changed = Config(horizon=1, cost_shadow_price=0.2)
        with self.assertRaisesRegex(ValueError, 'scope mismatch'):
            snap.choose(initial, changed, digest, 'FINITE_SYNTHETIC_DENY_ALL')
        with self.assertRaisesRegex(ValueError, 'invalid committed random seed'):
            rollout_snapshot(snap, cfg, digest, True)
        self.assertTrue(dict(snap.offline_work)['evaluated_branches'] > 0)
        self.assertGreaterEqual(dict(snap.offline_work)['maximum_states'],
                                dict(snap.offline_work)['expanded_states'])

    def test_initial_state_cannot_claim_existing_active_cells(self):
        cfg = Config()
        with self.assertRaisesRegex(ValueError, 'source or initial'):
            compile_optimal_snapshot(State((0, 0, 0, 0), 12,
                                           active_mask=1), cfg,
                                     current_source_digest())

class SnapshotPersistenceTests(unittest.TestCase):
    def test_export_and_cold_reload_from_canonical_bytes(self):
        from snapshot_policy import export_snapshot_bytes, load_snapshot_bytes
        cfg = Config(horizon=2)
        initial = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        compiled = compile_optimal_snapshot(initial, cfg, digest)
        original_bytes = export_snapshot_bytes(compiled)
        recovered = load_snapshot_bytes(original_bytes, cfg, initial)
        self.assertEqual(compiled.policy_sha256, recovered.policy_sha256)
        self.assertEqual(len(compiled.entries), len(recovered.entries))
        for seed in range(32):
            self.assertEqual(rollout_snapshot(compiled, cfg, digest, seed),
                             rollout_snapshot(recovered, cfg, digest, seed))

    def test_corrupted_bytes_are_not_accepted_as_a_valid_snapshot(self):
        from snapshot_policy import export_snapshot_bytes, load_snapshot_bytes
        cfg = Config(horizon=1)
        initial = State((0, 1, 2, 1), 12)
        raw = export_snapshot_bytes(compile_optimal_snapshot(
            initial, cfg, current_source_digest()))
        with self.assertRaises(ValueError):
            load_snapshot_bytes(raw.replace(b'policy_sha256', b'policy_sha257'), cfg, initial)
        with self.assertRaises(ValueError):
            load_snapshot_bytes(raw, Config(horizon=2), initial)
        with self.assertRaises(ValueError):
            load_snapshot_bytes(raw + b' ', cfg, initial)
        with self.assertRaises(ValueError):
            load_snapshot_bytes(b'', cfg, initial)

    def test_reload_requires_all_reachable_generation_outcomes(self):
        from snapshot_policy import export_snapshot_bytes, load_snapshot_bytes
        from hashlib import sha256
        import json
        cfg = Config(horizon=2)
        initial = State((0, 0, 0, 0), 12)
        original = compile_optimal_snapshot(initial, cfg, current_source_digest())
        payload = json.loads(export_snapshot_bytes(original))['payload']
        self.assertGreater(len(payload['entries']), 1)
        payload['entries'].pop()
        # Even a recomputed UNAUTHENTICATED digest must not bypass coverage.
        compact = lambda x: json.dumps(x, sort_keys=True,
                                      separators=(',', ':'),
                                      allow_nan=False).encode()
        envelope = {'payload': payload,
                    'policy_sha256': sha256(compact(payload)).hexdigest()}
        with self.assertRaisesRegex(ValueError, 'missing reachable outcome|missing initial state'):
            load_snapshot_bytes(compact(envelope), cfg, initial)
