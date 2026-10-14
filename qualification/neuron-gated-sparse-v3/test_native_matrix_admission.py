#!/usr/bin/env python3
"""Research source-only negative tests: do not attest a Cell Owner or a Rust run."""
from __future__ import annotations

from argparse import Namespace
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from run_native_physical_matrix import (
    independently_recheck_a0_for_native_use,
    require_two_fresh_processes_identical,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class StrictNativeStudyAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.selected = self.root / 'frozen-v1.safetensors'
        self.selected.write_bytes(b'UNSELECTED_SYNTHETIC_TEST_BYTES')
        self.selected_hash = digest(self.selected.read_bytes())
        self.receipt = {
            'cell_id': 'fixture-research-cell',
            'no_change_v1_selected_sha256': self.selected_hash,
            'evidence_class': 'SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION',
            'a0_registry_sha256': digest(b'registry'),
            'a0_host_id': 'fixture-host',
            'a0_checkpoint_digest_claimed': digest(b'checkpoint'),
            'a0_generation_claimed': 19,
        }
        self.claim = {
            'selected_v1': self.selected,
            'selected_v1_sha256': self.selected_hash,
            'a0_evidence_root': self.root,
            'a0_trusted_public_key': self.root / 'test-key.pem',
            'a0_expected_host_id': 'fixture-host',
        }
        self.signed_format = {
            'evidence_class': 'SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION',
            **{k:self.receipt[k] for k in (
                'a0_registry_sha256','a0_host_id',
                'a0_checkpoint_digest_claimed','a0_generation_claimed')},
        }

    def recheck(self, *, canary=False, **changed):
        options = dict(self.claim)
        options.update(changed)
        with patch('run_native_physical_matrix.require_selected_owner_a0',
                   return_value=self.signed_format):
            return independently_recheck_a0_for_native_use(
                self.receipt, synthetic_canary=canary, **options)

    def test_non_synthetic_replay_requires_fresh_a0(self):
        with self.assertRaisesRegex(ValueError, 'fresh signed A0'):
            independently_recheck_a0_for_native_use(
                self.receipt, synthetic_canary=False)

    def test_explicit_synthetic_canary_has_no_owner_and_denies_mixed_args(self):
        result=independently_recheck_a0_for_native_use(
            self.receipt, synthetic_canary=True)
        self.assertFalse(result['a0_rechecked'])
        with self.assertRaisesRegex(ValueError, 'synthetic canary'):
            self.recheck(canary=True)

    def test_signed_format_recheck_still_disclaims_host_attestation(self):
        result=self.recheck()
        self.assertTrue(result['a0_rechecked'])
        self.assertFalse(result['live_host_execution_independently_attested'])

    def test_stale_registry_or_checkpoint_fails(self):
        for field in ('a0_registry_sha256','a0_host_id',
                      'a0_checkpoint_digest_claimed','a0_generation_claimed'):
            with self.subTest(field=field):
                changed=dict(self.signed_format)
                changed[field]=digest(b'changed') if field.endswith('sha256') or field.endswith('digest_claimed') else 'different'
                with patch('run_native_physical_matrix.require_selected_owner_a0',
                           return_value=changed):
                    with self.assertRaisesRegex(ValueError,'A0 owner evidence drift'):
                        independently_recheck_a0_for_native_use(
                            self.receipt, synthetic_canary=False, **self.claim)

    def test_frozen_selected_v1_sha_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError,'selected V1 baseline digest'):
            self.recheck(selected_v1_sha256=digest(b'changed'))

    def test_changed_selected_v1_bytes_rejected(self):
        self.selected.write_bytes(b'REPLACED_SYNTHETIC_WEIGHT_BYTES')
        with self.assertRaisesRegex(ValueError,'physical SHA256 mismatch'):
            self.recheck()

    def test_replay_rejects_bad_a0_age(self):
        for age in (0,-1,86_401,True):
            with self.subTest(age=age):
                with self.assertRaisesRegex(ValueError,'freshness cap'):
                    self.recheck(a0_max_age_seconds=age)


class CrossProcessNumericAgreementTests(unittest.TestCase):
    def test_exact_native_frontier_and_head_logit_comparison(self):
        first={
            'arm':'v3', 'ndu_eligible':False, 'production_qualification':False,
            'frontier':[{'sequence':1,'checkpoint_sha256':digest(b'one'),
                         'activation_q24':[1,2,3],
                         'quantized_head_logit_q24':123}],
        }
        require_two_fresh_processes_identical(first,dict(first),arm='v3',cap=2048)
        for field, changed in (
            ('checkpoint_sha256',digest(b'different')),
            ('quantized_head_logit_q24',124),
            ('activation_q24',[1,2,4]),
        ):
            with self.subTest(field=field):
                second={'arm':'v3','ndu_eligible':False,'production_qualification':False,
                        'frontier':[dict(first['frontier'][0])]}
                second['frontier'][0][field]=changed
                with self.assertRaisesRegex(ValueError,'independent-process'):
                    require_two_fresh_processes_identical(first,second,arm='v3',cap=2048)
        second={'arm':'v3','ndu_eligible':True,'production_qualification':False,
                'frontier':first['frontier']}
        with self.assertRaisesRegex(ValueError,'independent-process'):
            require_two_fresh_processes_identical(first,second,arm='v3',cap=2048)


if __name__=='__main__':
    unittest.main()
