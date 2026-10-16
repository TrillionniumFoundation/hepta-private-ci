"""Source-only strict mmBERT report alias gate; real model efficacy not inferred."""
from __future__ import annotations
import unittest
from e1_mmbert_tied_loader import require_verified_alias_only_loading_info, Invalid

ALIAS=('decoder.weight','model.embeddings.tok_embeddings.weight')


class V15OriginalAliasReport(unittest.TestCase):
    def test_no_missing_original_tensors(self):
        self.assertEqual(require_verified_alias_only_loading_info({'missing_keys':[],
                          'unexpected_keys':[],'mismatched_keys':[],'error_msgs':[]}),())

    def test_any_single_registered_alias(self):
        for missing in ALIAS:
            with self.subTest(alias=missing):
                self.assertEqual(require_verified_alias_only_loading_info({'missing_keys':[missing]}),(missing,))

    def test_dual_reported_aliases_are_only_provisional_not_model_acceptance(self):
        for missing in ([ALIAS[0],ALIAS[1]],[ALIAS[1],ALIAS[0]]):
            # The physical tied-table and COMPLETE source-weight checks occur
            # subsequently; this inventory parser alone cannot qualify a model.
            self.assertEqual(require_verified_alias_only_loading_info({'missing_keys':missing}),ALIAS)

    def test_genuine_missing_weight_denied(self):
        for missing in (['decoder.bias'],['model.layers.0.q_proj.weight'],[ALIAS[0],'mlm.head.bias']):
            with self.subTest(keys=missing), self.assertRaises(Invalid):
                require_verified_alias_only_loading_info({'missing_keys':missing})

    def test_malformed_or_duplicate_tied_reports_denied(self):
        for missing in (None,'decoder.weight',[ALIAS[0],ALIAS[0]], [ALIAS[0],ALIAS[1],ALIAS[0]],[None]):
            with self.subTest(keys=missing), self.assertRaises(Invalid):
                require_verified_alias_only_loading_info({'missing_keys':missing})
        with self.assertRaises(Invalid):require_verified_alias_only_loading_info({})
        with self.assertRaises(Invalid):require_verified_alias_only_loading_info([])

    def test_nonempty_or_malformed_failure_fields_denied(self):
        for k,value in (('unexpected_keys',['extra.weight']), ('mismatched_keys',[('bad',(2,),(1,))]),
                        ('error_msgs',['load-failure']),('error_msgs',None),('unexpected_keys','')):
            with self.subTest(field=k), self.assertRaises(Invalid):
                require_verified_alias_only_loading_info({'missing_keys':[],k:value})

if __name__=='__main__':unittest.main()
