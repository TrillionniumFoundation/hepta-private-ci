"""Stdlib-only synthetic ABI *contract* tests, NOT a real HF model import.

The hosted V17 step separately uses the real pinned 5.19 LoadStateDictInfo.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest

from p0_hf519_loading_report_abi_v17 import (
    Invalid, PINNED_VERSION, REPORT_TYPES, SCHEMA, TIED_ALIASES,
    verify_report_abi, write_new)
from p0_mmbert_tied_load_contract_v15 import (
    Invalid as ContractInvalid, require_alias_only_loading_report)


@dataclass
class FakeSourceShapedInfo:
    missing_keys: set
    unexpected_keys: set
    mismatched_keys: set
    error_msgs: list
    conversion_errors: dict
    skipped_pp_keys: set

    def to_dict(self):
        return {'missing_keys':self.missing_keys, 'unexpected_keys':self.unexpected_keys,
                'mismatched_keys':self.mismatched_keys, 'error_msgs':self.error_msgs}


def make_fake(*, missing_keys=(), unexpected_keys=(), mismatched_keys=(),
              error_msgs=(), conversion_errors=None):
    return FakeSourceShapedInfo(
        set(missing_keys), set(unexpected_keys), set(mismatched_keys), list(error_msgs),
        {} if conversion_errors is None else dict(conversion_errors), set()).to_dict()


class UpstreamSourceShapeMechanism(unittest.TestCase):
    def test_real_contract_accepts_empty_pinned_sets_without_approval(self):
        report = verify_report_abi(make_fake, require_alias_only_loading_report, ContractInvalid)
        self.assertEqual(report['schema'], SCHEMA)
        self.assertEqual(report['installed_transformers_required_version'], '5.19.0')
        self.assertEqual(report['observed_report_collection_kinds'],
                         {'missing_keys':'set','unexpected_keys':'set',
                          'mismatched_keys':'set','error_msgs':'list'})
        self.assertEqual(report['strict_denial_cases_tested'],5)
        for name in ('actual_model_weights_loaded_by_this_probe',
                     'complete_original_tensor_byte_comparison_by_this_probe',
                     'model_selected','production_accepted','full_four_stem_efficacy_proven'):
            self.assertIs(report[name],False)
        self.assertEqual(report['authority'],'DENY_ALL')

    def test_source_types_exact_and_nonempty_tensor_names_not_exported(self):
        self.assertEqual(PINNED_VERSION,'5.19.0')
        self.assertIs(REPORT_TYPES['missing_keys'],set)
        self.assertIs(REPORT_TYPES['unexpected_keys'],set)
        self.assertIs(REPORT_TYPES['mismatched_keys'],set)
        self.assertIs(REPORT_TYPES['error_msgs'],list)
        body=json.dumps(verify_report_abi(make_fake,require_alias_only_loading_report,ContractInvalid))
        self.assertNotIn('decoder.weight',body)
        self.assertNotIn('private.name',body)

    def test_unexpected_list_instead_of_source_set_fails_abi_only(self):
        def fake(**kw):
            d=make_fake(**kw);d['unexpected_keys']=list(d['unexpected_keys']);return d
        with self.assertRaises(Invalid):
            verify_report_abi(fake,require_alias_only_loading_report,ContractInvalid)

    def test_missing_field_report_fails(self):
        def fake(**kw):
            d=make_fake(**kw);d.pop('mismatched_keys');return d
        with self.assertRaises(Invalid):
            verify_report_abi(fake,require_alias_only_loading_report,ContractInvalid)

    def test_extra_field_report_fails(self):
        def fake(**kw):
            d=make_fake(**kw);d['secret_tensor']='not a field';return d
        with self.assertRaises(Invalid):
            verify_report_abi(fake,require_alias_only_loading_report,ContractInvalid)

    def test_nonempty_clean_loading_report_fails(self):
        def fake(**kw):
            d=make_fake(**kw);d['missing_keys'].add('random.not_serialized');return d
        with self.assertRaises(Invalid):
            verify_report_abi(fake,require_alias_only_loading_report,ContractInvalid)

    def test_validator_false_success_cannot_claim_verified_weights(self):
        def bad_verifier(_):
            return {'needs_full_tensor_comparison':False,'actual_pretrained_tensor_bytes_verified':True,
                    'production_accepted':True,'authority':'GRANTED','missing_tied_aliases':[]}
        with self.assertRaises(Invalid):
            verify_report_abi(make_fake,bad_verifier,ContractInvalid)

    def test_unexpected_nonempty_set_remains_rejected(self):
        with self.assertRaises(ContractInvalid):
            require_alias_only_loading_report(make_fake(unexpected_keys={'unmapped.weight'}))
        with self.assertRaises(ContractInvalid):
            require_alias_only_loading_report(make_fake(mismatched_keys={('w',(1,),(2,))}))
        with self.assertRaises(ContractInvalid):
            require_alias_only_loading_report(make_fake(error_msgs=['unsafe']))

    def test_non_tied_missing_remains_rejected(self):
        with self.assertRaises(ContractInvalid):
            require_alias_only_loading_report(make_fake(missing_keys={'different.weight'}))
        for alias in TIED_ALIASES:
            allowed=require_alias_only_loading_report(make_fake(missing_keys={alias}))
            self.assertIs(allowed['actual_pretrained_tensor_bytes_verified'],False)
            self.assertIs(allowed['production_accepted'],False)

    def test_missing_conversion_errors_in_upstream_to_dict_is_not_a_model_pass(self):
        a=make_fake()
        b=make_fake(conversion_errors={'private.key':'error'})
        self.assertEqual(a,b)
        self.assertIs(verify_report_abi(make_fake,require_alias_only_loading_report,
                                        ContractInvalid)['complete_original_tensor_byte_comparison_by_this_probe'],False)

    def test_receipt_create_once_and_reject_symlink_or_overwrite(self):
        report=verify_report_abi(make_fake,require_alias_only_loading_report,ContractInvalid)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'result.json';write_new(p,report)
            self.assertEqual(json.loads(p.read_text()),report)
            with self.assertRaises(FileExistsError):write_new(p,report)
            link=Path(d)/'link.json';link.symlink_to(Path(d)/'missing')
            with self.assertRaises(FileExistsError):write_new(link,report)

    def test_unbounded_receipt_and_nan_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Invalid):
                write_new(Path(d)/'oversize.json',{'payload':'x'*4500})
            with self.assertRaises(ValueError):
                write_new(Path(d)/'nonfinite.json',{'bad':float('nan')})


if __name__ == '__main__':
    unittest.main()
