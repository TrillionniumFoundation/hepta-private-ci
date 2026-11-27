"""Negative-boundary execution samples; no Torch/GPU/pretrained efficacy."""
import copy
import hashlib
import json
import unittest
from group_abort_trace_audit import audit_abort


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def fixture():
    row = dict(execution_status='callback_failed', success=False, valid_execution=False,
               execution_mode='ndu', steps=1, verifier_calls=1,
               search_formula_work=103, prediction=2)
    trace = [dict(kind='propose', call=1, status='completed', elapsed_ns=5,
                  output_digest=digest('C')),
             dict(kind='verify', call=2, status='completed', elapsed_ns=5,
                  output_digest=digest([False, 'unsupported_dependency'])),
             dict(kind='value', call=3, status='failed', elapsed_ns=12,
                  error_type='ValueError')]
    record = dict(calls=3, trace=trace, proposed_candidates=['C'],
                  verifier_statuses=['unsupported_dependency'],
                  workspace_bindings=[dict(step=1)], final_candidate='C',
                  ndu_decisions=[])
    return row, record


class AbortAuditTests(unittest.TestCase):
    def test_real_negative_callback_is_preserved(self):
        row, record = fixture()
        self.assertEqual(audit_abort(row, record, 1, 'dependency')['outcome'], 'failed')
    def test_failed_episode_never_promotes(self):
        row, record = fixture()
        row['success'] = True
        with self.assertRaises(ValueError):
            audit_abort(row, record, 1, 'dependency')
    def test_completed_verifier_is_checked_against_public_evidence(self):
        row, record = fixture()
        record['trace'][1]['output_digest'] = digest([True, 'supported'])
        with self.assertRaisesRegex(ValueError, 'verifier'):
            audit_abort(row, record, 1, 'dependency')
    def test_no_reordered_callback_prefix(self):
        row, record = fixture()
        record['trace'][0], record['trace'][1] = record['trace'][1], record['trace'][0]
        with self.assertRaises(ValueError):
            audit_abort(row, record, 1, 'dependency')
    def test_no_unpaid_verification(self):
        row, record = fixture()
        row['verifier_calls'] = 0
        with self.assertRaises(ValueError):
            audit_abort(row, record, 1, 'dependency')
    def test_post_valuation_controller_failure_is_negative(self):
        row, record = fixture()
        record['trace'][2]['status'] = 'completed'
        record['trace'][2]['output_digest'] = digest('value')
        del record['trace'][2]['error_type']
        self.assertEqual(audit_abort(row, record, 1, 'dependency')['outcome'], 'failed')


if __name__ == '__main__':
    unittest.main()
