"""Strict mmBERT no-random-parameter loader tests; no real weights loaded."""
import unittest
from p0_mmbert_missing_keys_v14 import Invalid, fail_unverified_pretrained_missing_keys


class FixedModelLoadFailureTests(unittest.TestCase):
    def test_success_without_missing_weight_still_requires_all_bytes(self):
        r=fail_unverified_pretrained_missing_keys({"missing_keys":[], "error_msgs":[]})
        self.assertTrue(r['complete_checkpoint_byte_verification_still_required'])
        self.assertEqual(r['authority'],'DENY_ALL')

    def test_one_tied_alias_only_may_proceed_to_exact_source_bytes(self):
        for name in ('decoder.weight','model.embeddings.tok_embeddings.weight'):
            with self.subTest(name=name):
                r=fail_unverified_pretrained_missing_keys({'missing_keys':[name]})
                self.assertEqual(r['allowed_single_tied_missing_alias'],name)

    def test_two_missing_aliases_are_still_denied(self):
        with self.assertRaisesRegex(Invalid,'non-tied pretrained'):
            fail_unverified_pretrained_missing_keys({
                'missing_keys':['decoder.weight','model.embeddings.tok_embeddings.weight']})

    def test_non_alias_missing_is_refused_with_bounded_key_names(self):
        with self.assertRaisesRegex(Invalid,'decoder.bias'):
            fail_unverified_pretrained_missing_keys({'missing_keys':['decoder.bias']})

    def test_unexpected_mismatch_and_model_loader_error_denied(self):
        for key in ('unexpected_keys','mismatched_keys','error_msgs'):
            with self.subTest(key=key),self.assertRaises(Invalid):
                fail_unverified_pretrained_missing_keys({key:['fault']})

    def test_bogus_non_string_or_giant_missing_report_denied(self):
        for bad in (None,2,[None],['x']*513):
            with self.subTest(bad=str(bad)[:30]),self.assertRaises(Invalid):
                fail_unverified_pretrained_missing_keys({'missing_keys':bad})

    def test_diagnostic_does_not_echo_untrusted_unbounded_key_text(self):
        s='prefix.'+'S'*150+'SECRET'
        try:
            fail_unverified_pretrained_missing_keys({'missing_keys':[s]})
        except Invalid as error:
            self.assertNotIn('SECRET',str(error))
            self.assertIn('missing_name_set_sha256=',str(error))
        else: self.fail('must fail closed')

if __name__=='__main__':unittest.main()
