"""Synthetic reconstruction integrity tests; no A bank or scientific kernels."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from . import replay_terminals as replay


class ToyAdapter:
    def __init__(self, corrupt=False):
        self.record, self.restores, self.corrupt = None, 0, corrupt

    def restore(self, raw, sha):
        self.record = replay.codec.loads(raw, sha, len(raw))
        self.restores += 1

    def capture(self):
        record = deepcopy(self.record)
        if self.corrupt:
            record['parameters']['weight'][0] += 1.
        return record


def state():
    return {'parameters': {'weight': np.asarray([.2, -.3], dtype=np.float32)},
            'buffers': {}, 'optimizer': {'kind': 'SGD', 'state': {'momentum': np.asarray([1., 2.], dtype=np.float32)}},
            'gradients': {'weight': None}, 'rng': {'toy': np.asarray([1, 4], dtype=np.uint8)},
            'immutable': {'source': 'fixed'}, 'remaining_schedule': [],
            'cursor': {'clock': 288, 'path_kind': 'baseline'}, 'history': [{'already_observed': True}]}


def transaction():
    return {'start': 0, 'end': 48, 'action_index': 1, 'schedule_id': 6000,
            'accepted': True, 'guard_delta': .125, 'guard_values': [.25, .5],
            'guard_output_sha256': ['a' * 64, 'b' * 64],
            'before': {'parameters': 'c' * 64}, 'candidate': {'parameters': 'd' * 64},
            'after': {'parameters': 'd' * 64}, 'first_gradient': {'loss': 1.25},
            'last_gradient': {'loss': 1.1}, 'logical_clock': 48, 'remaining_steps': 240,
            'resources': {'scheduled_gradient_microsteps': 48, 'elapsed_ns': 100}}


class EvidenceComparisonTests(unittest.TestCase):
    def test_complete_grid_requires_96768_extra_steps_and_576_terminals(self):
        keys = replay.expected_parent_keys()
        self.assertEqual(len(keys), 48)
        self.assertEqual(len(set(keys)), 48)
        self.assertEqual(sum(4 * (288 - clock) for _, _, clock in keys), 32256)
        self.assertEqual(3 * len(keys) * 4, 576)
        self.assertEqual(3 * sum(4 * (288 - clock) for _, _, clock in keys), 96768)
        self.assertEqual(replay.REGISTRATION['scheduled_gradient_microsteps_total'], 96768)

    def test_all_deterministic_guard_and_gradient_fields_are_checked(self):
        original = transaction()
        timed = deepcopy(original)
        timed['resources']['elapsed_ns'] = 999999
        self.assertTrue(replay.compare_receipt(original, timed)['equal'])
        changes = {'accepted': False, 'guard_delta': .126, 'guard_values': [.25, .4],
                   'guard_output_sha256': ['f' * 64, 'b' * 64], 'last_gradient': {'loss': 1.2},
                   'remaining_steps': 239}
        for key, value in changes.items():
            changed = deepcopy(original)
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                replay.compare_receipt(original, changed)
        changed = deepcopy(original)
        changed['new_unfrozen_field'] = 1
        with self.assertRaisesRegex(ValueError, 'inventory'):
            replay.compare_receipt(original, changed)

    def test_parameter_equality_cannot_hide_optimizer_rng_or_history_changes(self):
        original = state()
        identity = replay.dynamics_identity(original)
        self.assertTrue(replay.compare_identity(identity, identity, 'Terminal')['equal'])
        variants = []
        momentum = deepcopy(original)
        momentum['optimizer']['state']['momentum'][0] += 1.
        variants.append(momentum)
        rng = deepcopy(original)
        rng['rng']['toy'][0] ^= 1
        variants.append(rng)
        history = deepcopy(original)
        history['history'].append({'other_observation': 3})
        variants.append(history)
        for changed in variants:
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                replay.compare_identity(identity, replay.dynamics_identity(changed), 'Terminal')


class LiteralArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.costs = replay.Costs()
        self.budget = replay.ReplayBudget(self.root, self.costs)
        # Only engineering metadata is written; this simulates budget states, not science.
        self.stat = SimpleNamespace(f_bavail=10 ** 12, f_frsize=1, f_favail=100000)
        self.patch = patch.object(replay.os, 'statvfs', return_value=self.stat)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_compressed_bytes_and_live_complete_state_restore_are_verified(self):
        raw = replay.codec.dumps(state())
        adapter = ToyAdapter()
        target = self.root / 'terminal.bin.gz'
        artifact = replay.persist_terminal(adapter, raw, target, self.budget, self.costs)
        self.assertEqual(replay.read_terminal(target, artifact), raw)
        self.assertEqual(replay.codec.dumps(adapter.capture()), raw)
        self.assertEqual(adapter.restores, 1)
        self.assertEqual(self.costs.values['R_literal_terminal_restores_verified'], 1)
        self.assertTrue(artifact['reconstructed_after_original_run'])
        self.assertFalse(artifact['original_terminal_tensor_previously_archived'])
        target.write_bytes(target.read_bytes() + b'tamper')
        with self.assertRaisesRegex(ValueError, 'archive bytes'):
            replay.read_terminal(target, artifact)

    def test_live_restoration_mismatch_does_not_produce_verified_evidence(self):
        with self.assertRaisesRegex(ValueError, 'live terminal restore'):
            replay.persist_terminal(ToyAdapter(corrupt=True), replay.codec.dumps(state()),
                                    self.root / 'bad.bin.gz', self.budget, self.costs)
        self.assertNotIn('R_literal_terminal_restores_verified', self.costs.values)

    def test_pending_bytes_and_gradient_caps_stop_before_write(self):
        with self.assertRaisesRegex(ValueError, 'raw evidence cap'):
            self.budget.check(replay.REGISTRATION['global_raw_cap_bytes'] + 1)
        self.costs.add('scheduled_gradient_microsteps', 32257)
        with self.assertRaisesRegex(ValueError, 'physical gradient ceiling'):
            self.budget.write(self.root / 'blocked', b'toy')
        self.assertFalse((self.root / 'blocked').exists())
        self.costs.values['scheduled_gradient_microsteps'] = 0
        self.stat.f_bavail = replay.REGISTRATION['allocatable_reserve_bytes'] - 1
        with self.assertRaisesRegex(ValueError, 'reserve exhausted'):
            self.budget.write(self.root / 'blocked', b'toy')
        self.assertFalse((self.root / 'blocked').exists())

    def test_exclusive_evidence_write_never_overwrites_a_prior_terminal(self):
        target = self.root / 'existing'
        self.budget.write(target, b'first')
        with self.assertRaises(FileExistsError):
            self.budget.write(target, b'second')
        self.assertEqual(target.read_bytes(), b'first')

    def test_separate_protocol_is_exact_and_hash_bound(self):
        path = self.root / 'PROTOCOL_R.json'
        protocol = {'schema': replay.PROTOCOL_SCHEMA, 'execution_ready': True,
                    'registration': deepcopy(replay.REGISTRATION), 'source_stage_A_protocol_sha256': 'a' * 64}
        path.write_text(json.dumps(protocol))
        freeze = {'protocol_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        replay.validate_protocol(protocol, freeze, path)
        with self.assertRaisesRegex(ValueError, 'protocol bytes'):
            replay.validate_protocol(protocol, {'protocol_sha256': '0' * 64}, path)
        protocol['registration']['new_source_roles'] = ['qualification_task']
        with self.assertRaisesRegex(ValueError, 'exact reconstruction design'):
            replay.validate_protocol(protocol, freeze, path)


if __name__ == '__main__':
    unittest.main()
