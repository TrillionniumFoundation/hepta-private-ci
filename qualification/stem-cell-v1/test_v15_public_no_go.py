"""Source-only negative tests, not newly executed pretrained model trials."""
import copy
import unittest
import v15_public_no_go as g


def sample():
    c=dict(schema=g.SCHEMA,original_dataset_sha256=g.CORPUS,original_reader_sha256=g.MODEL,
           cases=16,independent_retrospective_source_families=4,
           actual_pretrained_reader_requests=64,actual_model_forwards=123,
           per_arm={arm:dict(cases=16,publisher_annotated_witness_delivered=16 if arm=='annotated_witness' else 0,
               publisher_target_exact_casefold=0,publisher_target_substring=1 if arm=='annotated_witness' else 0,
               syntactic_citations=1,invalid_citations=0,abstention_literal=0,
               input_tokens=500,output_tokens=200) for arm in g.ARMS},
           per_source_family={f'conv-{k}':dict(cases=4,answers_changed_retrieved_to_witness=1) for k in (47,48,49,50)})
    c.update(publisher_witness_not_independently_human_verified=True,
             source_annotation_informed_candidate_selection=True,
             reference_reader_not_executed=True,real_future_source_windows=0,
             semantic_task_accuracy_independently_verified=None,
             citation_semantic_entailment_independently_verified=None,
             official_hf_operator_parity_verified=False,equivalent_total_lifecycle_compute=False,
             v6_seed41_retention_fixed=False,causal_stem_utility_verified=False,
             stem_winner_verified=False,production_authorized=False,decision='HOLD_NO_GO')
    return c

class TestV15Negative(unittest.TestCase):
    def setUp(self):self.p=sample()
    def deny(self):
        with self.assertRaises(ValueError):g.review(self.p)
    def test_valid_never_promotes(self):
        out=g.review(self.p);self.assertFalse(out['stem_selection_permitted'])
    def test_missing_arm(self):self.p['per_arm'].pop('none');self.deny()
    def test_fake_human_judge(self):self.p['publisher_witness_not_independently_human_verified']=False;self.deny()
    def test_fake_reference(self):self.p['reference_reader_not_executed']=False;self.deny()
    def test_fake_future(self):self.p['real_future_source_windows']=2;self.deny()
    def test_fake_task_accuracy(self):self.p['semantic_task_accuracy_independently_verified']=0.90;self.deny()
    def test_false_production(self):self.p['production_authorized']=True;self.deny()
    def test_wrong_model_sha(self):self.p['original_reader_sha256']='a'*64;self.deny()
    def test_missing_request(self):self.p['actual_pretrained_reader_requests']=63;self.deny()
    def test_fake_forward(self):self.p['actual_model_forwards']=12;self.deny()
    def test_broken_witness_lesion(self):self.p['per_arm']['witness_lesion']['publisher_annotated_witness_delivered']=1;self.deny()
    def test_omitted_family(self):self.p['per_source_family'].pop('conv-47');self.deny()
    def test_label_denominator(self):self.p['per_arm']['retrieved']['cases']=15;self.deny()
    def test_bogus_exact_without_substring(self):self.p['per_arm']['retrieved']['publisher_target_exact_casefold']=2;self.deny()
    def test_negative_count(self):self.p['per_arm']['none']['output_tokens']=-1;self.deny()
    def test_int_bool_confusion(self):self.p['per_arm']['retrieved']['input_tokens']=True;self.deny()
    def test_false_source_independence(self):self.p['independent_retrospective_source_families']=829;self.deny()
    def test_unverified_stem_claim(self):self.p['stem_winner_verified']=True;self.deny()

if __name__=='__main__':unittest.main()
