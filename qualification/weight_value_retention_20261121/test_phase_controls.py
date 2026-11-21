"""Synthetic files only: no real model, teacher, public dataset, or optimizer."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from data_contract import FITS, HEAD_IDS, pin, read, save
import run_confirmation as confirmation
from public_sampling import public_world, seed_for
from supervise import command_for


def rewrite(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, allow_nan=False) + '\n')


def fixture(root):
    main = root / 'main' / 'output'
    main.mkdir(parents=True)
    anchor = save(root / 'synthetic_model.json', {'synthetic': True})
    arrays = save(root / 'synthetic_arrays.json', {'not_real_arrays': True})
    protocol_sha = '1' * 64
    stamp = lambda second: f'2026-01-01T00:00:{second:02d}+00:00'
    phases = {}
    for name, second in [('GEN', 1), ('SELECT', 2), ('TRAIN_AUDIT', 5)]:
        phases[name] = save(main / (name + '.json'), dict(phase=name,
            protocol_sha256=protocol_sha, started_utc=stamp(second),
            completed_utc=stamp(second), arrays_pin=arrays))
    row = dict(models={'KEEP': {'model_pin': anchor}}, candidate_slots={n: {} for n in HEAD_IDS},
        family_choice={f: 'KEEP' for f in ('Q', 'B', 'G', 'T')}, global_choice='KEEP',
        graph_manifest_pin=arrays, hidden_pin=arrays, diagnostic_models={},
        phase_records=phases, SELECT_record_pin=phases['SELECT'], restore_pin=anchor)
    fits = {str(f): json.loads(json.dumps(row)) for f in FITS}
    selection = save(main / 'selection.json', dict(protocol_sha256=protocol_sha,
        created_utc=stamp(3), fits=fits))
    diagnostic = save(main / 'diagnostic.json', dict(candidate_selection_seal_pin=selection,
        created_utc=stamp(4), fits={str(f): {'models': {}} for f in FITS}))
    result = dict(status='COMPLETED', protocol_sha256=protocol_sha, source_inputs_unchanged=True,
        fits=fits, candidate_selection_seal_pin=selection, diagnostic_seal_pin=diagnostic,
        completed_utc=stamp(6))
    result_pin = save(main / 'RESULTS.json', result)
    process = dict(schema='hepta-value-process-receipt-v1', phase='main', status='COMPLETED',
        returncode=0, wall_timeout=False, error=None, protocol_and_entry_unchanged=True,
        result_pin=result_pin, protocol_pin={'sha256': protocol_sha}, CPU_hard_seconds=150,
        CPU_soft_seconds=145, child_CPU_seconds=1.0, address_space_bytes=536870912,
        affinity=[7], threads=1, wall_seconds=240, child_wall_seconds=2.0,
        entry_pin=pin(Path(confirmation.__file__).with_name('run_main.py')),
        supervisor_pin=pin(Path(confirmation.__file__).with_name('supervise.py')),
        completed_utc=stamp(7))
    save(main.parent / 'PROCESS.json', process)
    return main, protocol_sha, result, process


def reseal_result(main, result, process):
    rewrite(main / 'RESULTS.json', result)
    process['result_pin'] = pin(main / 'RESULTS.json')
    rewrite(main.parent / 'PROCESS.json', process)


class PhaseControls(unittest.TestCase):
    def test_complete_files_and_failed_process_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            main, sha, result, process = fixture(Path(tmp))
            self.assertEqual(confirmation.completed_main(main, sha)[0]['status'], 'COMPLETED')
            process['status'] = 'FAILED_OR_UNKNOWN'
            rewrite(main.parent / 'PROCESS.json', process)
            with self.assertRaises(ValueError):
                confirmation.completed_main(main, sha)

    def test_missing_audit_rejected_even_with_candidate_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            main, sha, result, process = fixture(Path(tmp))
            del result['fits']['11']['phase_records']['TRAIN_AUDIT']
            reseal_result(main, result, process)
            with self.assertRaisesRegex(ValueError, 'required completed phase'):
                confirmation.completed_main(main, sha)

    def test_changed_sealed_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main, sha, _, _ = fixture(root)
            rewrite(root / 'synthetic_model.json', {'synthetic': 'modified'})
            with self.assertRaisesRegex(ValueError, 'source pin changed'):
                confirmation.completed_main(main, sha)

    def test_audit_before_seal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            main, sha, result, process = fixture(Path(tmp))
            audit = read(main / 'TRAIN_AUDIT.json')
            audit['started_utc'] = '2026-01-01T00:00:01+00:00'
            rewrite(main / 'TRAIN_AUDIT.json', audit)
            for row in result['fits'].values():
                row['phase_records']['TRAIN_AUDIT'] = pin(main / 'TRAIN_AUDIT.json')
            reseal_result(main, result, process)
            with self.assertRaisesRegex(ValueError, 'AUDIT began before'):
                confirmation.completed_main(main, sha)

    def test_collision_is_terminal_after_one_entropy_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main, sha, result, _ = fixture(root)
            output = root / 'confirmation'
            protocol = {'_sha256': sha, 'known_schedule_hashes': [], 'schedule_fields': ['duration'],
                'public_domains': {'iid': {}, 'ood': {}, 'prior_distances': []}}
            with patch.object(confirmation.os, 'urandom', return_value=b'x' * 32) as entropy:
                with patch.object(confirmation, 'public_world', return_value={'duration': [1]}) as draw:
                    with self.assertRaisesRegex(ValueError, 'resampling forbidden'):
                        confirmation.confirmation_worlds(output, protocol, result,
                            pin(main / 'RESULTS.json'), SimpleNamespace(validate_public=lambda public: None))
            self.assertEqual(entropy.call_count, 1)
            self.assertEqual(draw.call_count, 2)
            failed = read(output / 'CONF_FAILED_COLLISION.json')
            self.assertFalse(failed['replacement_permitted'])
            self.assertEqual(len(failed['generated_current_group']), 1)
            self.assertFalse((output / 'CONF_WORLDS_FROZEN.json').exists())

    def test_seed_domains_and_supervisor_routing(self):
        values = [seed_for(b'x' * 32, seal, fit, domain)
                  for seal in ('a' * 64, 'b' * 64) for fit in (11, 23) for domain in ('iid', 'ood')]
        self.assertEqual(len(set(values)), 8)
        domain = dict(durations=[0.1, 0.2], drives=[-1., 1.], reliabilities=[0.7, 0.9],
                      prices=[0.01, 0.02], delays=[1, 2], latency_price=0.01,
                      repair_price=0.02, failure_probability=0.1)
        first = public_world(np.random.Generator(np.random.PCG64(values[0])), domain, [1., 2.], 'synthetic')
        second = public_world(np.random.Generator(np.random.PCG64(values[0])), domain, [1., 2.], 'synthetic')
        self.assertEqual(first, second)
        self.assertEqual((first['deadline'], first['target_tick']), (6, 6))
        with self.assertRaises(ValueError):
            command_for('main', 'protocol', 'out', main='forbidden')
        with self.assertRaises(ValueError):
            command_for('reader', 'protocol', 'out', main='main')
        command = command_for('reader', 'protocol', 'out', main='main', confirmation='conf')
        self.assertIn('--confirmation', command)


if __name__ == '__main__':
    unittest.main()
