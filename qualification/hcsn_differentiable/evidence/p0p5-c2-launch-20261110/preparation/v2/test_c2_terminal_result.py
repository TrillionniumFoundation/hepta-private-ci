"""Terminal-artifact failure fixtures only: opaque bytes, no models or optimization."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from c2_controller import cost_totals, terminal_result_gate
from c2_io import identity, sha


class TerminalResultTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='explicit-c2-terminal-metadata-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.parent_dir = self.root / 'parent-campaign/synthetic-hcsn'
        self.parent_dir.mkdir(parents=True)
        self.output = self.root / 'child'
        self.output.mkdir()
        self.path = self.output / 'result.json'
        self.prior = {'epochs': [{'epoch': 1}, {'epoch': 2}], 'episodes_train': 5,
            'effective_batch_size': 2, 'main_updates': 7, 'memorization': {'passed': True},
            'model_configuration': {'explicit_opaque_fixture': True}, 'source_before': {'fixture.py': 'a'*64}}
        (self.parent_dir / 'result.json').write_text(json.dumps(self.prior))
        self.parent = {'name': self.parent_dir.name, 'seed': 101, 'learning_rate': .003,
            'result_sha256': sha(self.parent_dir / 'result.json'), 'whole_process_wall_seconds': 14374.0}
        self.contract = {'parent_campaign': str(self.parent_dir.parent),
            'maximum_epochs': 200, 'cumulative_active_wall_seconds': 43200}
        self.process = {'name': self.parent_dir.name, 'returncode': 0, 'hard_timeout_sent': False,
            'process_started': True, 'whole_process_wall_seconds': 2.0,
            'attempt_wrapper_wall_seconds': 2.1, 'child_cpu_seconds': .5}
        self.result = {'schema': 'hcsn-c2-soft-wall-continuation-v1', 'production_execution': True,
            'confirmation_access': False, 'arm': 'hcsn', 'seed': 101, 'learning_rate': .003,
            'parent': str(self.parent_dir), 'parent_outer': self.parent,
            'parent_report': identity(self.parent_dir / 'result.json'),
            'model_configuration': self.prior['model_configuration'], 'status': 'completed_development',
            'source_and_parent_inputs_unchanged': True, 'common_and_physical_weights_unchanged': True,
            'source_before': self.prior['source_before'], 'source_after': self.prior['source_before'],
            'parent_retained_epochs': 2, 'cumulative_epochs_completed': 3,
            'retained_main_updates_at_resume': 6, 'logical_main_updates': 9, 'new_main_updates': 3,
            'actual_executed_main_updates_logged_all_phases': 10,
            'epochs': [{'epoch': 3, 'complete': True}], 'parent_full_outer_wall_charged': 14374.0,
            'cumulative_active_wall_cap_seconds': 43200, 'stop_reason': 'epoch_cap_not_convergence',
            'training_adequacy_established': False}
        for filename, field in [('development_logits.pt', 'selected_development_logits'),
                ('events.jsonl', 'events'), ('resume-start.pt', 'resume_start_checkpoint'),
                ('RESUME-START.json', 'resume_start_receipt')]:
            # These bytes exercise only the gate's file identity checks. They
            # are explicitly not serialized models, logits or a native result.
            (self.output / filename).write_bytes(b'opaque synthetic identity fixture\n')
            self.result[field] = identity(self.output / filename)
        for filename, field in [('last.pt', 'last_checkpoint_sha256'), ('best.pt', 'best_checkpoint_sha256')]:
            (self.output / filename).write_bytes(b'opaque synthetic identity fixture\n')
            self.result[field] = sha(self.output / filename)

    def write(self, value=None):
        self.path.write_text(json.dumps(self.result if value is None else value))

    def gate(self, process=None):
        return terminal_result_gate(self.process if process is None else process, self.path, self.parent, self.contract)

    def assert_failed_charged(self, row):
        self.assertEqual(row['status'], 'failed_terminal_evidence')
        self.assertFalse(row['terminal_evidence_complete'])
        for name in ('whole_process_wall_seconds', 'attempt_wrapper_wall_seconds', 'child_cpu_seconds', 'returncode'):
            self.assertEqual(row[name], self.process[name])
        totals = cost_totals([row], [row['name']])
        self.assertFalse(totals['attempt_terminal_evidence_complete'])
        self.assertEqual(totals['incomplete_terminal_evidence_names'], [row['name']])
        self.assertEqual(totals['sum_exact_per_child_cpu_seconds'], .5)
        self.assertEqual(totals['sum_attempt_outer_wall_seconds'], 2.0)
        self.assertTrue(totals['attempt_cost_accounting_complete'])

    def test_exit_zero_missing_result_is_failed_with_all_cost_retained(self):
        self.assert_failed_charged(self.gate())

    def test_exit_zero_malformed_json_is_failed_with_all_cost_retained(self):
        self.path.write_text('{"truncated":')
        self.assert_failed_charged(self.gate())

    def test_exit_zero_wrong_identity_fields_are_rejected(self):
        for field, value in [('seed', 307), ('learning_rate', .001), ('parent', '/another-parent'),
                ('parent_outer', {}), ('parent_report', {}), ('model_configuration', {}),
                ('production_execution', False), ('confirmation_access', True), ('schema', 'other')]:
            with self.subTest(field=field):
                row = copy.deepcopy(self.result)
                row[field] = value
                self.write(row)
                self.assert_failed_charged(self.gate())

    def test_exit_zero_wrong_success_state_or_changed_source_is_rejected(self):
        for field, value in [('status', 'budget_exhausted'), ('source_and_parent_inputs_unchanged', False),
                ('common_and_physical_weights_unchanged', False), ('training_adequacy_established', True)]:
            with self.subTest(field=field):
                row = copy.deepcopy(self.result)
                row[field] = value
                self.write(row)
                self.assert_failed_charged(self.gate())

    def test_exit_zero_missing_or_modified_success_artifact_is_rejected(self):
        self.write()
        artifact = self.output / 'resume-start.pt'
        raw = artifact.read_bytes()
        artifact.unlink()
        self.assert_failed_charged(self.gate())
        artifact.write_bytes(raw + b'changed')
        self.assert_failed_charged(self.gate())

    def test_exit_zero_cannot_refund_discarded_updates_or_parent_wall(self):
        for field, value in [('actual_executed_main_updates_logged_all_phases', 9),
                ('parent_full_outer_wall_charged', 14000), ('epochs', [])]:
            with self.subTest(field=field):
                row = copy.deepcopy(self.result)
                row[field] = value
                self.write(row)
                self.assert_failed_charged(self.gate())

    def test_consistent_success_with_artifacts_is_completed_without_adequacy_credit(self):
        self.write()
        row = self.gate()
        self.assertEqual(row['status'], 'completed', row.get('terminal_evidence_error'))
        self.assertTrue(row['terminal_evidence_complete'])
        self.assertFalse(row['adequate'])
        self.assertTrue(cost_totals([row], [row['name']])['attempt_terminal_evidence_complete'])

    def test_identified_nonzero_failure_remains_failed_and_fully_charged(self):
        result = copy.deepcopy(self.result)
        result['status'] = 'budget_exhausted'
        self.write(result)
        process = dict(self.process, returncode=2)
        row = self.gate(process)
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['fit_status'], 'budget_exhausted')
        self.assertTrue(row['terminal_evidence_complete'])
        self.assertEqual(row['child_cpu_seconds'], .5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
