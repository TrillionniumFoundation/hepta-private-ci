"""Synthetic record-verifier controls; no ELF execution or native test credit."""
from pathlib import Path
import copy
import hashlib
import json
import tempfile
import unittest

import fd_gate_evidence
import nextest_fd_runner as runner


class ExactTargetControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / 'target'
        self.target.mkdir()
        self.directory = self.root / 'records'
        self.directory.mkdir()
        self.config_path = self.root / 'config.json'
        self.mapping = dict(runner.NEURAL_RUNTIME_CASE_TARGETS)
        self.names = sorted(self.mapping)
        self.config = {
            'schema': 'hepta-nextest-fd-runner-v2', 'gate': 'neural-runtime-input',
            'target': str(self.target), 'crate': None, 'directory': str(self.directory),
            'selected_names': self.names, 'predicate': None,
            'expected_case_targets': self.mapping,
            'source': {'scope': 'synthetic utility records only'},
            'coordinator': {'pid': 1, 'start_ticks': 'synthetic'},
        }
        self.records = []
        for index, name in enumerate(self.names):
            target = self.mapping[name]
            executable = self.target / (target + '-0123456789abcdef')
            raw = b'\x7fELF-not-executed-utility-fixture-' + str(index).encode()
            executable.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            retained = self.directory / (digest + '.elf')
            retained.write_bytes(raw)
            self.records.append({
                'schema': self.config['schema'], 'status': 'pre_exec_fd_bound',
                'phase': 'run', 'gate': self.config['gate'],
                'source': self.config['source'], 'coordinator': self.config['coordinator'],
                'runner_sha256': fd_gate_evidence.digest(runner.__file__),
                'coordinator_descendant_verified': True,
                'pre_exec_fd_identity_verified': True,
                'observed_selected_tests': [name], 'exact_test': name,
                'pid': 100 + index, 'start_ticks': str(index + 1),
                'argv': [str(executable), '--exact', name, '--nocapture'],
                'actual_executable': str(executable), 'expected_binary_target': target,
                'retained_copy': str(retained), 'sha256': digest, 'bytes': len(raw),
            })

    def tearDown(self):
        self.temp.cleanup()

    def verify(self, records=None, cases=None, declared=None):
        self.config_path.write_text(json.dumps(self.config))
        for path in self.directory.glob('*.json'):
            path.unlink()
        for index, original in enumerate(self.records if records is None else records):
            record = copy.deepcopy(original)
            record['capture_config_sha256'] = fd_gate_evidence.digest(self.config_path)
            (self.directory / (str(index) + '.json')).write_text(json.dumps(record))
        return fd_gate_evidence.verify(
            self.config_path, runner.__file__,
            [(name, 'ok') for name in self.names] if cases is None else cases,
            [2] if declared is None else declared,
        )

    def test_two_exact_targets_have_independent_case_and_image_bindings(self):
        result = self.verify()
        self.assertEqual(result['errors'], [])
        self.assertTrue(result['per_case_bijection_verified'])
        self.assertEqual(set(result['actual_images_by_target']), set(self.mapping.values()))
        self.assertEqual(len(result['unique_actual_elf_sha256']), 2)

    def test_swapped_or_extra_target_refuses_credit(self):
        records = copy.deepcopy(self.records)
        for index, record in enumerate(records):
            other = self.records[1 - index]
            for key in ('actual_executable', 'expected_binary_target', 'retained_copy', 'sha256', 'bytes'):
                record[key] = other[key]
            record['argv'][0] = record['actual_executable']
        self.assertTrue(self.verify(records)['errors'])
        records = copy.deepcopy(self.records)
        records[0]['actual_executable'] = str(self.target / 'unlisted_target-0123456789abcdef')
        records[0]['argv'][0] = records[0]['actual_executable']
        self.assertTrue(self.verify(records)['errors'])

    def test_missing_extra_or_duplicate_case_refuses_credit(self):
        self.assertTrue(self.verify(self.records[:1])['errors'])
        duplicate = copy.deepcopy(self.records[0])
        duplicate['pid'] += 10
        self.assertTrue(self.verify(self.records + [duplicate])['errors'])
        cases = [(name, 'ok') for name in self.names] + [(self.names[0], 'ok')]
        self.assertTrue(self.verify(self.records + [duplicate], cases)['errors'])
        extra = copy.deepcopy(self.records[0])
        extra['exact_test'] = 'unlisted_case'
        extra['observed_selected_tests'] = ['unlisted_case']
        extra['argv'][2] = 'unlisted_case'
        self.assertTrue(self.verify(self.records + [extra], cases + [('unlisted_case', 'ok')])['errors'])

    def test_original_single_binary_and_other_gates_do_not_gain_multi_target_scope(self):
        self.config['gate'] = 'dispatcher'
        self.assertTrue(self.verify()['errors'])
        self.config['schema'] = 'hepta-nextest-fd-runner-v1'
        self.assertTrue(self.verify()['errors'])
        del self.config['expected_case_targets']
        self.config['crate'] = self.mapping[self.names[0]]
        self.assertIsNone(runner.fixed_case_targets(self.config))
        self.assertTrue(self.verify()['errors'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
