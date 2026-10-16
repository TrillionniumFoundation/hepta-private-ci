"""V18 source-only synthetic mechanics tests; no pretrained model outcomes claimed."""
import copy
from hashlib import sha256
import unittest

from v18_factorial_original_reader import SCHEMA, ARMS, ALL_ARMS, READER_SHA, TOKEN_SHA, digest, htext
from v18_independent_original_review import recount,compare_repeat,score_original_answers

class FakeTokenizer:
    def encode(self,s):
        return [ord(x) for x in s]
    def decode(self,ids):
        return ''.join(chr(v) for v in ids)


def data():
    tok=FakeTokenizer();v17={'requests':{},'cases':[]};cases=[];requests={};older={};answers={};starts=[]
    for i in range(32):
        fam=('conv-47','conv-48','conv-49','conv-50')[i//8]
        cid=f'{fam}/q{i%8}';body_changed=i<29;cohort='literal_in_annotated_source' if i%8<4 else 'not_literal_in_annotated_source'
        ids=['a','b','c'];old_rids=[]
        for ar in ('formatted_full','formatted_focused'):
            rid=htext('baseline:'+cid+ar);old_rids.append(rid)
            v17['requests'][rid]={'case_id':cid,'family':fam,'source_ids':ids}
            older[rid]={'case_id':cid,'source_ids':ids,'answer_text':'abc'}
        cross={}
        for arm in ARMS:
            # Last three have no actual source-shortening, so prompts match original V17
            if not body_changed:
                rid=old_rids[1 if arm=='full_focus_heading' else 0]
                cross[arm]={'request_id':rid,'reused_v17':True}
            else:
                prompt='new:'+cid+arm
                rid=htext(prompt)
                requests[rid]={'case_id':cid,'arm':arm,'source_ids':ids,'prompt':prompt}
                cross[arm]={'request_id':rid,'reused_v17':False}
        cases.append({'case_id':cid,'family':fam,'cohort':cohort,
                      'cross_arms':cross,'full_full_heading':old_rids[0],
                      'focused_focus_heading':old_rids[1]})
    v17_raw={'plan_sha256':digest(v17),'model_sha256':READER_SHA,'requests':64,
             'production_authorized':False,'raw_answers':older}
    plan={'schema':SCHEMA+'.source-only-plan','v17_plan_sha256':digest(v17),
          'reader_weights_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
          'publisher_gold_available_to_producer':False,'production_authorized':False,
          'new_requests':requests,'novel_physical_requests':58,
          'question_count':32,'changed_source_cases':29,'reused_unchanged_model_requests':6,
          'max_new_tokens':24,'cases':cases}
    for rid,row in requests.items():
        ids=[ord(c) for c in 'abc']
        answers[rid]={'case_id':row['case_id'],'arm':row['arm'],'source_ids':row['source_ids'],
                      'answer_text':'abc','answer_sha256':htext('abc'),'output_ids':ids,
                      'input_tokens':len(tok.encode(row['prompt'])),'output_tokens':3,'cpu_seconds':0.1}
        starts.append({'request_id':rid,'plan_sha256':digest(plan),
                       'input_tokens':len(tok.encode(row['prompt'])),
                       'input_ids_sha256':digest(tok.encode(row['prompt']))})
    physical={'schema':SCHEMA+'.original-physical-answers','plan_sha256':digest(plan),
              'model_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
              'requests':58,'pretrained_model_executed':True,'official_HF_parity':False,
              'reference_reader_executed':False,'independently_human_reviewed':False,
              'production_authorized':False,'model_forwards':58*4,'raw_answers':answers}
    return plan,physical,starts,v17,v17_raw,tok

class V18ReviewContracts(unittest.TestCase):
    def setUp(self):
        self.plan,self.model,self.starts,self.v17,self.old,self.tok=data()
    def validate(self):return recount(self.plan,self.model,self.starts,self.v17,self.old,self.tok)
    def test_exact_pass_no_promotion(self):
        r,grid=self.validate();self.assertEqual(r['new_original_requests'],58)
        self.assertEqual(r['total_factorial_case_arm_slots'],128)
        self.assertEqual(len(grid),32);self.assertFalse(r['production_authorized'])
    def test_full_equal_case_reuse(self):
        _,g=self.validate();self.assertEqual(g['conv-50/q7']['full_focus_heading']['answer_text'],'abc')
    def test_mutated_plan_stays_rejected(self):
        self.plan['production_authorized']=True
        with self.assertRaises(ValueError):self.validate()
    def test_missing_model_output_rejected(self):
        self.model['raw_answers'].pop(next(iter(self.model['raw_answers'])))
        with self.assertRaises(ValueError):self.validate()
    def test_extra_attempt_rejected(self):
        self.starts.append(self.starts[0])
        with self.assertRaises(ValueError):self.validate()
    def test_changed_original_prompt_rejected(self):
        rid=next(iter(self.plan['new_requests']))
        self.plan['new_requests'][rid]['prompt']='different'
        with self.assertRaises(ValueError):self.validate()
    def test_swapped_source_ids_rejected(self):
        rid=next(iter(self.model['raw_answers']))
        self.model['raw_answers'][rid]['source_ids']=['a','c','b']
        with self.assertRaises(ValueError):self.validate()
    def test_changed_raw_answer_rejected(self):
        rid=next(iter(self.model['raw_answers']))
        self.model['raw_answers'][rid]['answer_text']='wrong'
        with self.assertRaises(ValueError):self.validate()
    def test_bool_token_rejected(self):
        rid=next(iter(self.model['raw_answers']))
        self.model['raw_answers'][rid]['output_ids']=[True]
        with self.assertRaises(ValueError):self.validate()
    def test_forwards_must_be_physical(self):
        self.model['model_forwards']+=1
        with self.assertRaises(ValueError):self.validate()
    def test_false_hf_parity_refused(self):
        self.model['official_HF_parity']=True
        with self.assertRaises(ValueError):self.validate()
    def test_reused_v17_missing_refused(self):
        rid=next(iter(self.old['raw_answers']))
        self.old['raw_answers'].pop(rid)
        with self.assertRaises(ValueError):self.validate()
    def test_duplicate_case_refused(self):
        self.plan['cases'][-1]=self.plan['cases'][0]
        with self.assertRaises(ValueError):self.validate()
    def test_repeat_identical(self):
        z=compare_repeat(self.plan,self.model,copy.deepcopy(self.model))
        self.assertTrue(z['real_model_answers_reproduced'])
    def test_repeat_changed_answer(self):
        n=copy.deepcopy(self.model)
        next(iter(n['raw_answers'].values()))['answer_text']='bad'
        with self.assertRaises(ValueError):compare_repeat(self.plan,self.model,n)
    def test_literal_scores_not_semantic(self):
        _,grid=self.validate()
        originals=[]
        for name in ('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44','conv-47','conv-48','conv-49','conv-50'):
            qa=[{'answer':'abc'} for _ in range(8)]
            if name=='conv-50':qa[-1]['answer']=None
            originals.append({'sample_id':name,'qa':qa})
        score=score_original_answers(self.plan,grid,originals)
        self.assertEqual(score['cohort_counts']['literal_in_annotated_source']['full_full_heading']['substring'],16)
        self.assertEqual(score['independent_human_judgments'],0)
        self.assertIsNone(score.get('semantic_correctness'))
        self.assertFalse(score['production_authorized'])
    def test_label_owner_missing_row(self):
        _,grid=self.validate()
        originals=[{'sample_id':z,'qa':[{'answer':'abc'} for _ in range(8)]}
          for z in ('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44','conv-47','conv-48','conv-49','conv-50')]
        originals[0]['sample_id']='foreign'
        with self.assertRaises(ValueError):score_original_answers(self.plan,grid,originals)

if __name__=='__main__':unittest.main()
