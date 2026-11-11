"""Reject semantically ambiguous or non-finite C2 terminal reports despite valid byte hashes."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from c2_controller import terminal_result_gate
from c2_io import identity


class StrictTerminalJsonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.name = 'hcsn-s101-lr0.001'
        self.parent = self.root / 'parents' / self.name
        self.parent.mkdir(parents=True)
        self.result = self.root / 'newfit' / 'result.json'
        self.result.parent.mkdir()
        self.prior = {'model_configuration': {'arm': 'hcsn'}, 'source_before': {}}
        self.contract = {'parent_campaign': str(self.parent.parent)}
        self.row = {'name': self.name, 'returncode': 1, 'hard_timeout_sent': False}

    def verify(self, *, replace_result=None, replace_prior=None):
        parent_raw = json.dumps(self.prior).encode()
        if replace_prior:
            parent_raw = replace_prior(parent_raw)
        (self.parent / 'result.json').write_bytes(parent_raw)
        parent_info = {'name': self.name, 'seed': 101, 'learning_rate': 0.001,
                       'result_sha256': hashlib.sha256(parent_raw).hexdigest()}
        result = {
            'schema': 'hcsn-c2-soft-wall-continuation-v1',
            'production_execution': True, 'confirmation_access': False,
            'arm': 'hcsn', 'seed': 101, 'learning_rate': 0.001,
            'parent': str(self.parent), 'parent_outer': parent_info,
            'parent_report': identity(self.parent / 'result.json'),
            'model_configuration': {'arm': 'hcsn'},
            'status': 'failed', 'training_adequacy_established': False,
        }
        raw = json.dumps(result).encode()
        if replace_result:
            raw = replace_result(raw)
        self.result.write_bytes(raw)
        return terminal_result_gate(self.row, self.result, parent_info, self.contract)

    def test_control_plain_valid_failure_receipt_is_accepted(self):
        row = self.verify()
        self.assertTrue(row['terminal_evidence_complete'], row.get('terminal_evidence_error'))

    def test_duplicate_top_level_terminal_status_is_rejected(self):
        def mutate(raw):
            return raw.replace(b'"status": "failed"',
                               b'"status": "completed_development", "status": "failed"')
        self.assertFalse(self.verify(replace_result=mutate)['terminal_evidence_complete'])

    def test_duplicate_nested_model_key_is_rejected(self):
        def mutate(raw):
            return raw.replace(b'"model_configuration": {"arm": "hcsn"}',
                               b'"model_configuration": {"arm": "hcsn", "arm": "hcsn"}')
        self.assertFalse(self.verify(replace_result=mutate)['terminal_evidence_complete'])

    def test_nonfinite_nan_result_is_rejected(self):
        self.assertFalse(self.verify(replace_result=lambda raw:
            raw[:-1] + b', "ignored": NaN}')['terminal_evidence_complete'])

    def test_nonfinite_overflow_result_is_rejected(self):
        self.assertFalse(self.verify(replace_result=lambda raw:
            raw[:-1] + b', "ignored": 1e999}')['terminal_evidence_complete'])

    def test_duplicate_original_parent_key_is_rejected(self):
        def mutate(raw):
            return raw.replace(b'{"arm": "hcsn"}',
                               b'{"arm": "hcsn", "arm": "hcsn"}')
        self.assertFalse(self.verify(replace_prior=mutate)['terminal_evidence_complete'])

    def test_nonobject_terminal_root_is_rejected(self):
        self.assertFalse(self.verify(replace_result=lambda _: b'[]')['terminal_evidence_complete'])


if __name__ == '__main__':
    unittest.main()
