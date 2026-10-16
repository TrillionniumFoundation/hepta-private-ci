"""Model-free contract checks; actual pretrained forward is hosted-only."""
from __future__ import annotations
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from types import SimpleNamespace
from p0_mmbert_original_physical_probe_v15 import Invalid, checked_observation, SCHEMA, safe_failure_code, main


def fake():
    return SimpleNamespace(
      pretrained_weight_receipt={'actual_local_full_tied_embedding_checkpoint_verified':True,
                                 'complete_table_sha256':'a'*64,'authority':'DENY_ALL'},
      complete_weight_receipt={'all_serialized_pretrained_tensor_bytes_verified':True,
                               'whole_pretrained_state_sha256':'b'*64,
                               'source_tensor_count':137,'authority':'DENY_ALL'})

class PhysicalProofContractTests(unittest.TestCase):
    def test_complete_mock_structural_receipt_only(self):
        r=checked_observation(fake())
        self.assertEqual(r['source_tensor_count'],137)
        self.assertNotIn('production_accepted',r)
        self.assertNotIn('original_checkpoint_qualified',r)

    def test_false_preflight_denied(self):
        with self.assertRaises(Invalid):checked_observation(fake(),original_preflight=False)

    def test_false_tied_table_denied(self):
        x=fake();x.pretrained_weight_receipt['actual_local_full_tied_embedding_checkpoint_verified']=False
        with self.assertRaises(Invalid):checked_observation(x)

    def test_false_complete_tensor_check_denied(self):
        x=fake();x.complete_weight_receipt['all_serialized_pretrained_tensor_bytes_verified']=False
        with self.assertRaises(Invalid):checked_observation(x)

    def test_wrong_tensor_count_denied(self):
        x=fake();x.complete_weight_receipt['source_tensor_count']=136
        with self.assertRaises(Invalid):checked_observation(x)

    def test_empty_source_digest_denied(self):
        x=fake();x.complete_weight_receipt['whole_pretrained_state_sha256']=''
        with self.assertRaises(Invalid):checked_observation(x)

    def test_invalid_table_digest_denied(self):
        x=fake();x.pretrained_weight_receipt['complete_table_sha256']='c'*63+'/'
        with self.assertRaises(Invalid):checked_observation(x)

    def test_missing_original_report_denied(self):
        with self.assertRaises(Invalid):checked_observation(SimpleNamespace())

    def test_lifted_production_authority_denied(self):
        x=fake();x.complete_weight_receipt['authority']='PRODUCTION'
        with self.assertRaises(Invalid):checked_observation(x)

    def test_known_tied_storage_failure_is_classified(self):
        self.assertEqual(safe_failure_code(ValueError(
            'token embedding and pretrained MLM decoder are not tied at 384D')),
            'tied_table_storage_not_shared')

    def test_loaded_extra_state_names_are_classified(self):
        self.assertEqual(safe_failure_code(Invalid(
            'model contains unverified or newly initialized saved weights')),
            'runtime_state_contains_extra_tensor')

    def test_loaded_tensor_byte_failure_omits_key_name(self):
        self.assertEqual(safe_failure_code(Invalid(
            'loaded model parameter is not the pretrained source: model.block.secret')),
            'serialized_tensor_bytes_mismatch')

    def test_unknown_exception_never_surfaces_secret_path(self):
        secret='secret/token/permission?x=xyz'
        out=safe_failure_code(ValueError(secret))
        self.assertEqual(out,'unclassified_strict_failure')
        self.assertNotIn(secret,out)

    def test_error_on_non_exception_stays_bounded(self):
        self.assertEqual(safe_failure_code('arbitrary message'),
                         'unclassified_strict_failure')

    def test_failure_entrypoint_prints_only_sanitized_code(self):
        import json
        stream=StringIO()
        with patch('sys.argv',['probe','--compact-checkout','/unavailable',
                               '--output','/no/output.json']), \
             patch('p0_mmbert_original_physical_probe_v15.run_original',
                   side_effect=Invalid('model contains unverified or newly initialized saved weights')):
            with redirect_stdout(stream),self.assertRaises(SystemExit) as ctx:
                main()
        self.assertEqual(ctx.exception.code,1)
        report=json.loads(stream.getvalue())
        self.assertEqual(report['failure_code'],'runtime_state_contains_extra_tensor')
        self.assertFalse(report['original_checkpoint_qualified'])
        self.assertFalse(report['production_accepted'])
        self.assertNotIn('initialized randomly',stream.getvalue())

    def test_no_task_data_or_label_owner_access_in_source(self):
        from pathlib import Path
        p=Path(__file__).with_name('p0_mmbert_original_physical_probe_v15.py')
        t=p.read_text()
        self.assertIn('Original fixed pretrained mmBERT parameter-integrity probe.',t)
        self.assertNotIn('owner-only',t)
        self.assertNotIn('heldout_labels',t)

if __name__=='__main__':unittest.main()
