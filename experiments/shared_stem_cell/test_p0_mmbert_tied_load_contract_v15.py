"""Strict model-free adversarial tests: never claims physical model success."""
from __future__ import annotations
import unittest
from p0_mmbert_tied_load_contract_v15 import Invalid, require_alias_only_loading_report as accept


class AliasLoadingContractTests(unittest.TestCase):
    def test_no_missing_is_not_a_model_pass(self):
        o=accept({'missing_keys': []})
        self.assertFalse(o['actual_pretrained_tensor_bytes_verified'])
        self.assertFalse(o['production_accepted'])
        self.assertEqual(o['authority'],'DENY_ALL')

    def test_one_decoder_alias_is_structurally_allowed(self):
        self.assertEqual(accept({'missing_keys':['decoder.weight']})['missing_tied_aliases'],['decoder.weight'])

    def test_one_input_alias_is_structurally_allowed(self):
        self.assertEqual(accept({'missing_keys':['model.embeddings.tok_embeddings.weight']})['missing_tied_aliases'],['model.embeddings.tok_embeddings.weight'])

    def test_both_tied_aliases_are_allowed_only_pending_physical_proof(self):
        o=accept({'missing_keys':['model.embeddings.tok_embeddings.weight','decoder.weight']})
        self.assertEqual(len(o['missing_tied_aliases']),2)
        self.assertTrue(o['needs_full_tensor_comparison'])
        self.assertFalse(o['actual_pretrained_tensor_bytes_verified'])

    def test_one_random_non_tied_parameter_refused(self):
        for key in ('decoder.bias','model.layers.0.weight','model.embeddings.LayerNorm.weight'):
            with self.subTest(key=key),self.assertRaises(Invalid):accept({'missing_keys':[key]})

    def test_tied_and_nontied_refused(self):
        with self.assertRaises(Invalid):accept({'missing_keys':['decoder.weight','encoder.attention.bias']})

    def test_tied_duplicates_refused(self):
        with self.assertRaises(Invalid):accept({'missing_keys':['decoder.weight','decoder.weight']})

    def test_missing_report_wrong_shape_refused(self):
        for info in (None,[],{'missing_keys':'decoder.weight'},{'missing_keys':None},{'missing_keys':set()}):
            with self.subTest(info=str(info)),self.assertRaises(Invalid):accept(info)

    def test_unexpected_or_mismatch_always_refused(self):
        for key in ('unexpected_keys','mismatched_keys','error_msgs'):
            with self.subTest(key=key),self.assertRaises(Invalid):accept({key:['bad.weight']})

    def test_nonempty_tied_unexpected_also_refused(self):
        with self.assertRaises(Invalid):accept({'unexpected_keys':['decoder.weight']})

    def test_unknown_fields_refused(self):
        with self.assertRaises(Invalid):accept({'ignored_keys':['encoder.layer']})

    def test_bad_names_refused(self):
        for name in ('','foo/bar','a\nsecret','../bad','x:y',42):
            with self.subTest(name=str(name)),self.assertRaises(Invalid):accept({'missing_keys':[name]})

    def test_nonbool_actual_verified_stays_false(self):
        for keys in ([],['decoder.weight'],['decoder.weight','model.embeddings.tok_embeddings.weight']):
            o=accept({'missing_keys':keys})
            self.assertIs(o['actual_pretrained_tensor_bytes_verified'],False)


if __name__=='__main__':unittest.main()
