"""V16 source-only negative-publication adversarial contracts."""
import copy
import unittest
from v16_public_no_go import check
from v16_literal_witness_reader import SCHEMA,GROUPS,ARMS,HELD,READER_SHA,CORPUS_SHA


def fixture():
    arr={g:{a:dict(cases=16,publisher_witness_delivered=16 if a=='witness' else 0,
        literal_target_substring=0,input_tokens=100,output_tokens=10) for a in ARMS} for g in GROUPS}
    report=dict(schema=SCHEMA+'.sanitized-historical-literal-diagnostic',retrospective_question_count=32,
        actual_original_reader_requests=128,unique_original_source_families=4,
        original_model_sha256=READER_SHA,original_dataset_sha256=CORPUS_SHA,
        cohorts_selected_using_publisher_answers=True,literal_occurrence_does_not_establish_semantic_sufficiency=True,
        independently_human_verified_sufficiency=False,independent_semantic_answer_correctness=None,
        reference_reader_actual_calls=0,prospective_calendar_windows=0,official_HF_operator_parity=False,
        full_lifecycle_cost_matched=False,stem_winner_verified=False,v6_seed41_retention_fixed=False,
        production_authorized=False,decision='HOLD_NO_GO',actual_model_forwards=2500,
        per_cohort_arm=arr,per_original_family={f:{g:{'cases':4} for g in GROUPS} for f in HELD})
    bytes_=dict(schema=SCHEMA+'.independent-private-recount',verified_requests=128,
                model_forward_calls=2500,semantic_accuracy=None,source_sufficiency_human_verified=False,
                reference_reader_executed=False,production_authorized=False)
    gold=dict(schema=SCHEMA+'.independent-original-source-recount',question_count=32,source_roots=4,
              answer_dependent_historical_cohort=True,independently_verified_semantics=False,
              stronger_reader_executed=False,production_authorized=False,status='RECOUNT_PASS_NO_GO',
              literal_substring_hit_per_arm={g:{a:0 for a in ARMS} for g in GROUPS})
    repeat=dict(schema=SCHEMA+'.original-independent-process-repeat',
         matched_exact_original_request_outputs=128,first_physical_forwards=2500,
         second_physical_forwards=2500,original_first_answer_sha256='a'*64,
         original_model_hf_parity_verified=False,independent_semantic_accuracy=None,
         stronger_reference_reader_executed=False,production_authorized=False,
         result='PHYSICAL_BYTES_REPEATABLE_ONLY')
    report['original_answer_journal_sha256']='a'*64
    return report,bytes_,gold,repeat


class PublicContracts(unittest.TestCase):
    def setUp(self):self.r,self.b,self.g,self.p=fixture()
    def reject(self,change):
        vals=[copy.deepcopy(v) for v in (self.r,self.b,self.g,self.p)]
        change(*vals[:3])
        with self.assertRaises(ValueError):check(*vals)
    def test_independent_repeat_refuses_changed_text(self):
        from v16_repeat_review import compare
        first=dict(schema=SCHEMA+'.actual-original-reader-results',plan_sha256='a'*64,
           model_sha256=READER_SHA,tokenizer_sha256='b'*64,reader_config_sha256='c'*64,
           requests=128,model_forwards=3000,stronger_reference_reader_executed=False,
           human_verified_sufficiency=False,independent_semantic_correctness=None,
           hf_operator_tokenizer_parity=False,production_authorized=False,
           execution_cpu_seconds=12,execution_wall_seconds=10,
           raw_answers={str(i):dict(case_id=str(i),arm='witness',source_ids=['s'],
                 answer_text='a',answer_sha256='d'*64,token_ids=[1],input_tokens=8,output_tokens=1)
                 for i in range(128)})
        second=copy.deepcopy(first)
        self.assertEqual(compare(first,second)['matched_exact_original_request_outputs'],128)
        second['raw_answers']['0']['answer_text']='changed'
        with self.assertRaises(ValueError):compare(first,second)
    def test_fake_repeat_forward_counter(self):
        mutated=copy.deepcopy(self.p);mutated['second_physical_forwards']=1
        with self.assertRaises(ValueError):check(self.r,self.b,self.g,mutated)
    def test_fake_repeat_semantics(self):
        mutated=copy.deepcopy(self.p);mutated['independent_semantic_accuracy']=1.
        with self.assertRaises(ValueError):check(self.r,self.b,self.g,mutated)
    def test_nominal_no_go(self):self.assertEqual(check(self.r,self.b,self.g,self.p)['production_authorized'],False)
    def test_fake_semantics(self):self.reject(lambda r,b,g:r.__setitem__('independent_semantic_answer_correctness',True))
    def test_fake_human(self):self.reject(lambda r,b,g:r.__setitem__('independently_human_verified_sufficiency',True))
    def test_fake_reader(self):self.reject(lambda r,b,g:r.__setitem__('reference_reader_actual_calls',128))
    def test_future(self):self.reject(lambda r,b,g:r.__setitem__('prospective_calendar_windows',2))
    def test_wrong_model(self):self.reject(lambda r,b,g:r.__setitem__('original_model_sha256','f'*64))
    def test_missing_cohort(self):self.reject(lambda r,b,g:r['per_cohort_arm'].pop(GROUPS[0]))
    def test_missing_arm(self):self.reject(lambda r,b,g:r['per_cohort_arm'][GROUPS[0]].pop('lesion'))
    def test_wrong_witness(self):self.reject(lambda r,b,g:r['per_cohort_arm'][GROUPS[1]]['retrieved'].__setitem__('publisher_witness_delivered',1))
    def test_wrong_family_denominator(self):self.reject(lambda r,b,g:r['per_original_family'][HELD[0]][GROUPS[0]].__setitem__('cases',6))
    def test_wrong_frame_count(self):self.reject(lambda r,b,g:b.__setitem__('model_forward_calls',2499))
    def test_gold_mismatch(self):self.reject(lambda r,b,g:g['literal_substring_hit_per_arm'][GROUPS[0]].__setitem__('witness',1))
    def test_model_selection(self):self.reject(lambda r,b,g:r.__setitem__('stem_winner_verified',True))
    def test_old_retention_fake(self):self.reject(lambda r,b,g:r.__setitem__('v6_seed41_retention_fixed',True))
    def test_future_independence_false(self):self.reject(lambda r,b,g:g.__setitem__('independently_verified_semantics',True))
    def test_authorization(self):self.reject(lambda r,b,g:r.__setitem__('production_authorized',True))

if __name__=='__main__':unittest.main()
