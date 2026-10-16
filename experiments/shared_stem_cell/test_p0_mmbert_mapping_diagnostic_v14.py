"""Model-free strict integrity regressions, NOT original pretrained efficacy."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from p0_mmbert_mapping_diagnostic_v14 import (
    Invalid, REVISION, SCHEMA, inspect_key_mapping, names, write_create_only)


class DiagnosticTests(unittest.TestCase):
    def report(self, info=None, runtime=None, source=None):
        return inspect_key_mapping(info or {'missing_keys': []},
                                   runtime or ['model.layer.weight','decoder.weight'],
                                   source or ['model.layer.weight','decoder.weight'])

    def test_original_complete_names_are_observational_only(self):
        r=self.report()
        self.assertEqual(r['schema'],SCHEMA)
        self.assertEqual(r['non_tied_missing_count'],0)
        self.assertFalse(r['production_accepted'])
        self.assertFalse(r['actual_original_weights_compared_by_this_diagnostic'])
        self.assertEqual(r['authority'],'DENY_ALL')

    def test_non_tied_model_key_reported_not_admitted(self):
        r=self.report({'missing_keys':['decoder.bias']})
        self.assertEqual(r['non_tied_missing_loader_keys'],['decoder.bias'])
        self.assertTrue(r['strict_loader_would_refuse_non_tied_missing'])
        self.assertFalse(r['production_accepted'])

    def test_tied_alias_is_not_claimed_non_tied(self):
        r=self.report({'missing_keys':['decoder.weight']})
        self.assertEqual(r['non_tied_missing_count'],0)
        self.assertIn('decoder.weight',r['missing_loader_keys'])
        self.assertFalse(r['production_accepted'])

    def test_source_vs_state_mismatch_preserved(self):
        r=self.report(runtime=['model.layer.weight','decoder.weight'],
                      source=['model.layer.weight','decoder.bias'])
        self.assertEqual(r['runtime_only_state_keys'],['decoder.weight'])
        self.assertEqual(r['source_only_saved_keys'],['decoder.bias'])

    def test_missing_and_unexpected_both_preserved(self):
        r=self.report({'missing_keys':['decoder.bias'],
                       'unexpected_keys':['old.classifier.weight']})
        self.assertEqual(r['unexpected_loader_keys'],['old.classifier.weight'])

    def test_changed_original_revision_fails(self):
        with self.assertRaises(Invalid):
            inspect_key_mapping({}, ['model.w'], ['model.w'],revision='f'*40)

    def test_non_dict_loading_report_fails(self):
        with self.assertRaises(Invalid):inspect_key_mapping([],['a'],['a'])

    def test_empty_source_fails(self):
        with self.assertRaises(Invalid):inspect_key_mapping({},['a'],[])

    def test_empty_model_fails(self):
        with self.assertRaises(Invalid):inspect_key_mapping({},[],['a'])

    def test_duplicate_tensor_name_fails(self):
        with self.assertRaises(Invalid):names(['a','a'])

    def test_control_chars_and_paths_refused(self):
        for t in ('token\nsecret', 'a/b', 'http://secret', '../x','a\x00b',''):
            with self.subTest(t=t), self.assertRaises(Invalid):names([t])

    def test_unbounded_inventory_fails(self):
        with self.assertRaises(Invalid):names([f'a{i}' for i in range(8193)])

    def test_reject_string_instead_of_list(self):
        with self.assertRaises(Invalid):names('decoder.bias')

    def test_reject_nonstring(self):
        with self.assertRaises(Invalid):names([42])

    def test_invalid_mismatched_key_fails(self):
        with self.assertRaises(Invalid):self.report({'mismatched_keys':['bad\nsecret']})

    def test_contradictory_loader_names_fails(self):
        with self.assertRaises(Invalid):self.report({'missing_keys':['a'], 'unexpected_keys':['a']})

    def test_finite_create_only_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'r.json'
            write_create_only(p,self.report())
            self.assertEqual(json.loads(p.read_text())['authority'],'DENY_ALL')
            with self.assertRaises(FileExistsError):write_create_only(p,{'broken':True})

    def test_symlink_destination_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'l.json';p.symlink_to(Path(tmp)/'out.json')
            with self.assertRaises(FileExistsError):write_create_only(p,{})

    def test_nan_report_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):write_create_only(Path(tmp)/'x',{'score':float('nan')})

    def test_shape_tuple_diagnostic_names_only(self):
        r=self.report({'mismatched_keys':[('model.w',[384,384],[256,256])]})
        self.assertEqual(r['mismatched_loader_keys'],['model.w'])
        self.assertNotIn('384',repr(r))

    def test_runtime_diagnostic_is_not_extra_admission(self):
        r=self.report({'missing_keys':['norm.bias']})
        for key in ('production_accepted','real_source_task_efficacy_proved',
                    'independent_publisher_or_hardware_attestation'):
            self.assertFalse(r[key])


if __name__ == '__main__':unittest.main()
