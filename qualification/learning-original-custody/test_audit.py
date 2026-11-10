"""Synthetic negatives only: they are not independent learning evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from audit import STAGES, inspect


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.record = {
            'schema': 'hepta-original-learning-custody-precheck-v1',
            'source_head': 'a' * 40,
            'operation_id': 'op-1',
            'next_operation_id': 'op-2',
            'source_task_id': 'task-A',
            'next_task_id': 'task-B',
            'baseline_bundle': 'a' * 64,
            'selected_bundle': 'b' * 64,
            'decision': 'adopt',
            'operator_custody': {'trainer': 'organization-1', 'evaluator': 'organization-2',
                                 'holdout': 'organization-3', 'selector': 'organization-4',
                                 'observer': 'organization-5'},
            'admitted_attempt_ids': ['train', 'eval', 'delivery'],
            'attempts': [
                {'id': 'train', 'state': 'completed', 'cost_usd': '1.2'},
                {'id': 'eval', 'state': 'failed', 'cost_usd': '0.5'},
                {'id': 'delivery', 'state': 'cancelled', 'cost_usd': '0.3'},
            ],
            'original_receipts': {},
        }
        for stage in STAGES:
            p = self.root / (stage + '.receipt')
            p.write_bytes(stage.encode())
            self.record['original_receipts'][stage] = {
                'file': p.name,
                'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                'operation_id': 'op-2' if stage == 'next_use' else 'op-1',
                'learning_operation_id': 'op-1' if stage == 'next_use' else None,
                'next_operation_id': 'op-2' if stage == 'learning_next_use' else None,
                'next_task_id': 'task-B' if stage == 'learning_next_use' else None,
                'task_id': 'task-B' if stage == 'next_use' else 'task-A',
                'bundle_sha256': 'b' * 64,
                'selection_digest': 'c' * 64 if stage in ('selection', 'learning_next_use') else None,
            }

    def check(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps(self.record))
        return inspect(manifest)

    def test_complete_byte_precheck_is_still_hold(self):
        result = self.check()
        self.assertEqual(result['integrity'], 'PASS')
        self.assertEqual(result['status'], 'HOLD')
        self.assertFalse(result['owner_authenticated'])
        self.assertFalse(result['benefit_established'])
        self.assertEqual(result['declared_attempt_cost_usd'], '2.0')

    def test_different_keys_do_not_erase_same_operator(self):
        self.record['operator_custody']['evaluator'] = 'organization-1'
        self.assertIn('same_operator_multiple_roles', self.check()['issues'])

    def trainer_no_update(self):
        self.record['decision'] = 'no_update'
        self.record['no_update_origin'] = 'trainer'
        self.record['selected_bundle'] = self.record['baseline_bundle']
        self.record['operator_custody'].pop('evaluator')
        self.record['operator_custody'].pop('holdout')
        self.record['original_receipts'].pop('evaluation')
        self.record['original_receipts'].pop('proposal')
        for entry in self.record['original_receipts'].values():
            entry['bundle_sha256'] = self.record['selected_bundle']

    def test_original_trainer_no_update_never_synthesizes_evaluation(self):
        self.trainer_no_update()
        result = self.check()
        self.assertEqual(result['integrity'], 'PASS')
        self.assertEqual(result['status'], 'HOLD')
        self.assertEqual(result['receipt_bytes_required'], 8)
        self.assertFalse(result['owner_authenticated'])

    def test_trainer_no_update_rejects_forged_evaluation_stage(self):
        self.trainer_no_update()
        self.record['original_receipts']['evaluation'] = {
            'file': 'evaluation.receipt', 'sha256': hashlib.sha256(b'evaluation').hexdigest(),
            'operation_id': 'op-1', 'task_id': 'task-A'
        }
        self.assertIn('receipt_coverage', self.check()['issues'])

    def test_trainer_no_update_requires_selector_and_observer(self):
        self.trainer_no_update()
        self.record['operator_custody']['selector'] = 'organization-1'
        self.assertIn('same_operator_multiple_roles', self.check()['issues'])
        self.record['operator_custody']['selector'] = 'organization-4'
        self.record['operator_custody'].pop('observer')
        self.assertIn('operator_custody_missing', self.check()['issues'])

    def test_evaluator_no_update_requires_original_evaluation(self):
        self.record['decision'] = 'no_update'
        self.record['no_update_origin'] = 'evaluation'
        self.record['selected_bundle'] = self.record['baseline_bundle']
        self.record['original_receipts'].pop('proposal')
        self.record['original_receipts'].pop('evaluation')
        self.assertIn('receipt_coverage', self.check()['issues'])


    def test_adoption_requires_original_proposal(self):
        self.record['original_receipts'].pop('proposal')
        issues = self.check()['issues']
        self.assertIn('receipt_coverage', issues)
        self.assertIn('missing_receipt:proposal', issues)

    def test_evaluator_no_update_skips_unexecuted_proposal(self):
        self.record['decision'] = 'no_update'
        self.record['no_update_origin'] = 'evaluation'
        self.record['selected_bundle'] = self.record['baseline_bundle']
        self.record['original_receipts'].pop('proposal')
        for entry in self.record['original_receipts'].values():
            entry['bundle_sha256'] = self.record['selected_bundle']
        result = self.check()
        self.assertEqual(result['integrity'], 'PASS')
        self.assertEqual(result['receipt_bytes_required'], 9)
        self.assertEqual(result['status'], 'HOLD')
        self.record['original_receipts']['proposal'] = {
            'file': 'proposal.receipt',
            'sha256': hashlib.sha256(b'proposal').hexdigest(),
            'operation_id': 'op-1', 'task_id': 'task-A'
        }
        self.assertIn('receipt_coverage', self.check()['issues'])

    def test_proposal_no_update_requires_original_proposal(self):
        self.record['decision'] = 'no_update'
        self.record['no_update_origin'] = 'proposal'
        self.record['selected_bundle'] = self.record['baseline_bundle']
        for entry in self.record['original_receipts'].values():
            entry['bundle_sha256'] = self.record['selected_bundle']
        result = self.check()
        self.assertEqual(result['integrity'], 'PASS')
        self.assertEqual(result['receipt_bytes_required'], 10)
        self.assertEqual(result['status'], 'HOLD')
        self.record['original_receipts'].pop('proposal')
        self.assertIn('missing_receipt:proposal', self.check()['issues'])

    def test_original_learning_next_use_cannot_be_omitted_or_replaced_by_consumer(self):
        # LearningIterationReceiptV1::record() pins the learning operation.
        # The next ordinary task's receipt uses its own different operation.
        self.record['original_receipts'].pop('learning_next_use')
        issues = self.check()['issues']
        self.assertIn('receipt_coverage', issues)
        self.assertIn('missing_receipt:learning_next_use', issues)

    def test_terminal_learning_next_use_has_original_operation_and_consumer_link(self):
        entry = self.record['original_receipts']['learning_next_use']
        entry['operation_id'] = 'op-2'
        self.assertIn('foreign_operation:learning_next_use', self.check()['issues'])
        entry['operation_id'] = 'op-1'
        entry['next_operation_id'] = 'foreign-op'
        self.assertIn('learning_next_use_unbound_to_consumer_operation', self.check()['issues'])
        entry['next_operation_id'] = 'op-2'
        entry['next_task_id'] = 'task-A'
        self.assertIn('learning_next_use_unbound_to_consumer_task', self.check()['issues'])

    def test_trainer_no_update_still_requires_terminal_learning_receipt(self):
        self.trainer_no_update()
        result = self.check()
        self.assertEqual(result['integrity'], 'PASS')
        self.assertEqual(result['receipt_bytes_required'], 8)
        self.record['original_receipts'].pop('learning_next_use')
        self.assertIn('missing_receipt:learning_next_use', self.check()['issues'])

    def test_no_update_origin_must_be_explicit(self):
        self.record['decision'] = 'no_update'
        self.record['selected_bundle'] = self.record['baseline_bundle']
        self.assertIn('no_update_origin', self.check()['issues'])

    def test_adoption_rejects_no_update_origin(self):
        self.record['no_update_origin'] = 'trainer'
        self.assertIn('no_update_origin_not_applicable', self.check()['issues'])

    def test_different_task_and_version_bound(self):
        self.record['next_task_id'] = 'task-A'
        self.record['original_receipts']['next_use']['bundle_sha256'] = 'a' * 64
        issues = self.check()['issues']
        self.assertIn('next_task_not_distinct', issues)
        self.assertIn('wrong_consumed_version:next_use', issues)

    def test_next_operation_and_learning_lineage(self):
        self.record['next_operation_id'] = 'op-1'
        self.assertIn('next_operation_not_distinct', self.check()['issues'])
        self.record['next_operation_id'] = 'op-2'
        self.record['original_receipts']['next_use']['learning_operation_id'] = 'foreign-op'
        self.assertIn('next_use_unbound_to_learning', self.check()['issues'])

    def test_corrupt_original_bytes(self):
        (self.root / 'evaluation.receipt').write_bytes(b'changed')
        self.assertIn('receipt_bytes_mismatch:evaluation', self.check()['issues'])

    def test_absent_failure_cost_or_attempt(self):
        self.record['attempts'] = self.record['attempts'][:1]
        self.assertIn('attempt_inventory_mismatch', self.check()['issues'])

    def test_extreme_finite_decimal_cost_fails_closed(self):
        # Decimal accepts this finite literal; default-context addition
        # overflows. No supplied manifest may crash the HOLD-only audit.
        self.record['attempts'][0]['cost_usd'] = '1e999999999'
        result = self.check()
        self.assertEqual(result['integrity'], 'FAIL')
        self.assertIn('attempt_cost:0', result['issues'])
        self.assertEqual(result['declared_attempt_cost_usd'], '0.8')

    def test_high_precision_cost_cannot_silently_round(self):
        self.record['attempts'][0]['cost_usd'] = '0.123456789012345678901234567891'
        result = self.check()
        self.assertEqual(result['integrity'], 'FAIL')
        self.assertIn('attempt_cost:0', result['issues'])

    def test_small_failed_attempt_cost_cannot_be_lost_in_sum(self):
        self.record['attempts'][0]['cost_usd'] = '9999999999999999999999999999'
        self.record['attempts'][1]['cost_usd'] = '0.01'
        result = self.check()
        self.assertEqual(result['integrity'], 'FAIL')
        self.assertIn('attempt_cost:1', result['issues'])

    def test_selection_must_bind_adopted_and_retained_versions(self):
        self.record['original_receipts']['selection']['bundle_sha256'] = 'a' * 64
        self.assertIn('wrong_consumed_version:selection', self.check()['issues'])
        self.trainer_no_update()
        self.record['original_receipts']['selection']['bundle_sha256'] = 'b' * 64
        self.assertIn('wrong_consumed_version:selection', self.check()['issues'])

    def test_terminal_next_use_must_reference_original_selection_digest(self):
        self.record['original_receipts']['learning_next_use']['selection_digest'] = 'd' * 64
        self.assertIn('terminal_selection_unbound', self.check()['issues'])

    def test_selection_digest_is_mandatory_and_well_formed(self):
        self.record['original_receipts']['selection'].pop('selection_digest')
        self.assertIn('invalid_selection_digest:selection', self.check()['issues'])
        self.record['original_receipts']['selection']['selection_digest'] = 'c' * 64
        self.record['original_receipts']['learning_next_use']['selection_digest'] = 'bad'
        self.assertIn('invalid_selection_digest:learning_next_use', self.check()['issues'])

    def test_unknown_is_not_success(self):
        self.record['attempts'][2]['state'] = 'unknown'
        self.assertIn('unresolved_attempts', self.check()['issues'])

    def test_unsafe_path_rejected(self):
        self.record['original_receipts']['training']['file'] = '../secret'
        self.assertIn('unsafe_receipt_path:training', self.check()['issues'])

    def test_invalid_malformed_inventory_is_hold_not_crash(self):
        self.record['admitted_attempt_ids'] = [['invalid']]
        self.assertIn('attempt_inventory_invalid', self.check()['issues'])

    def test_unhashable_attempt_state_is_hold_not_exception(self):
        self.record['attempts'][0]['state'] = ['completed']
        self.assertIn('attempt_state:0', self.check()['issues'])

    def test_unchanged_bytes_not_candidate_adopt(self):
        self.record['selected_bundle'] = self.record['baseline_bundle']
        self.assertIn('selection_version_mismatch', self.check()['issues'])


    def test_duplicate_top_level_operation_rejected_before_byte_check(self):
        manifest = self.root / 'manifest.json'
        original = json.dumps(self.record)
        forged = original.replace('"operation_id": "op-1"',
                                  '"operation_id": "foreign", "operation_id": "op-1"', 1)
        self.assertNotEqual(forged, original)
        manifest.write_text(forged)
        result = inspect(manifest)
        self.assertEqual(result['integrity'], 'FAIL')
        self.assertIn('bad_manifest:ValueError', result['issues'])

    def test_duplicate_nested_receipt_metadata_rejected(self):
        manifest = self.root / 'manifest.json'
        original = json.dumps(self.record)
        forged = original.replace('"task_id": "task-A"',
                                  '"task_id": "task-A", "task_id": "foreign"', 1)
        self.assertNotEqual(forged, original)
        manifest.write_text(forged)
        self.assertIn('bad_manifest:ValueError', inspect(manifest)['issues'])

    def test_nonfinite_json_constant_rejected(self):
        manifest = self.root / 'manifest.json'
        self.record['extra'] = float('nan')
        manifest.write_text(json.dumps(self.record))
        self.assertIn('bad_manifest:ValueError', inspect(manifest)['issues'])

    def test_manifest_reader_never_uses_unbounded_read_bytes(self):
        from unittest import mock
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps(self.record))
        with mock.patch.object(Path, 'read_bytes',
                               side_effect=AssertionError('unbounded read')):
            result = inspect(manifest)
        self.assertEqual(result['integrity'], 'PASS')
        self.assertEqual(result['status'], 'HOLD')

    def test_oversized_sparse_receipt_rejected_on_open_descriptor(self):
        from audit import MAX_RECEIPT_BYTES
        # Sparse file avoids allocating 64 MiB while exercising fstat after
        # the open; no receipt bytes are hashed for this stage.
        with (self.root / 'training.receipt').open('wb') as stream:
            stream.truncate(MAX_RECEIPT_BYTES + 1)
        result = self.check()
        self.assertIn('receipt_unreadable:training', result['issues'])
        self.assertEqual(result['receipt_bytes_matched'], len(STAGES) - 1)
        self.assertEqual(result['status'], 'HOLD')

    def test_manifest_size_bounded_before_parsing(self):
        from audit import MAX_MANIFEST_BYTES
        manifest = self.root / 'manifest.json'
        manifest.write_bytes(b' ' * (MAX_MANIFEST_BYTES + 1))
        self.assertIn('bad_manifest:ValueError', inspect(manifest)['issues'])

if __name__ == '__main__':
    unittest.main()
