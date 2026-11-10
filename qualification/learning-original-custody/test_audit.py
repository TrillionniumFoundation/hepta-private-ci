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
            'source_task_id': 'task-A',
            'next_task_id': 'task-B',
            'baseline_bundle': 'a' * 64,
            'selected_bundle': 'b' * 64,
            'decision': 'adopt',
            'operator_custody': {'trainer': 'organization-1', 'evaluator': 'organization-2', 'holdout': 'organization-3'},
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
                'operation_id': 'op-1',
                'task_id': 'task-B' if stage == 'next_use' else 'task-A',
                'bundle_sha256': 'b' * 64,
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

    def test_different_task_and_version_bound(self):
        self.record['next_task_id'] = 'task-A'
        self.record['original_receipts']['next_use']['bundle_sha256'] = 'a' * 64
        issues = self.check()['issues']
        self.assertIn('next_task_not_distinct', issues)
        self.assertIn('wrong_consumed_version:next_use', issues)

    def test_corrupt_original_bytes(self):
        (self.root / 'evaluation.receipt').write_bytes(b'changed')
        self.assertIn('receipt_bytes_mismatch:evaluation', self.check()['issues'])

    def test_absent_failure_cost_or_attempt(self):
        self.record['attempts'] = self.record['attempts'][:1]
        self.assertIn('attempt_inventory_mismatch', self.check()['issues'])

    def test_unknown_is_not_success(self):
        self.record['attempts'][2]['state'] = 'unknown'
        self.assertIn('unresolved_attempts', self.check()['issues'])

    def test_unsafe_path_rejected(self):
        self.record['original_receipts']['training']['file'] = '../secret'
        self.assertIn('unsafe_receipt_path:training', self.check()['issues'])

    def test_invalid_malformed_inventory_is_hold_not_crash(self):
        self.record['admitted_attempt_ids'] = [['invalid']]
        self.assertIn('attempt_inventory_invalid', self.check()['issues'])

    def test_unchanged_bytes_not_candidate_adopt(self):
        self.record['selected_bundle'] = self.record['baseline_bundle']
        self.assertIn('selection_version_mismatch', self.check()['issues'])


if __name__ == '__main__':
    unittest.main()
