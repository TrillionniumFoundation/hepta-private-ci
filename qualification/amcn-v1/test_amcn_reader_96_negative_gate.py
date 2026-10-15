import copy
import json
from pathlib import Path
import unittest

from amcn_reader_96_negative_gate import verify

ORIGINAL=json.loads(Path(__file__).with_name('ORIGINAL_READER_96_PRIVATE_RECOUNT.json').read_text())

class HistoricalSourceOnlyDenial(unittest.TestCase):
    def test_verbatim_original_NO_GO(self):
        outcome=verify(ORIGINAL)
        self.assertEqual(outcome['reader_no_evidence_nonabstentions'],20)
        self.assertFalse(outcome['citation_entailment_independently_judged'])
        self.assertFalse(outcome['production_accepted'])

    def test_reduced_original_calls_refused(self):
        v=copy.deepcopy(ORIGINAL);v['original_attempts_recounted']=95
        with self.assertRaises(ValueError):verify(v)

    def test_forged_no_evidence_abstention_refused(self):
        v=copy.deepcopy(ORIGINAL);v['no_evidence_literal_abstention_outputs']=20
        with self.assertRaises(ValueError):verify(v)

    def test_wrong_source_sha_refused(self):
        v=copy.deepcopy(ORIGINAL);v['original_model_sha256']='0'*64
        with self.assertRaises(ValueError):verify(v)

    def test_forged_semantic_entailment_refused(self):
        v=copy.deepcopy(ORIGINAL);v['independent_human_semantic_entailment']=1.0
        with self.assertRaises(ValueError):verify(v)

    def test_forged_official_hf_parity_refused(self):
        v=copy.deepcopy(ORIGINAL);v['tokenizer_official_HF_parity_verified']=True
        with self.assertRaises(ValueError):verify(v)

    def test_missing_original_citation_group_refused(self):
        v=copy.deepcopy(ORIGINAL);del v['cohort_stats']['long']
        with self.assertRaises(ValueError):verify(v)

    def test_miscounted_original_citation_denied(self):
        v=copy.deepcopy(ORIGINAL);v['cohort_stats']['verbatim']['citation_tag_count']+=1
        with self.assertRaises(ValueError):verify(v)

    def test_false_future_denied(self):
        v=copy.deepcopy(ORIGINAL);v['future_calendar_windows']=2
        with self.assertRaises(ValueError):verify(v)

    def test_selected_model_claim_denied(self):
        v=copy.deepcopy(ORIGINAL);v['production_accepted']=True
        with self.assertRaises(ValueError):verify(v)

if __name__=='__main__':unittest.main()
