"""All inputs here are SYNTHETIC protocol fixtures; no real model claims."""
import copy, hashlib, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import e22_answer_sensitivity as e


def fixture():
 rows=[]
 for g, sizes in enumerate(((2,4),(3,5),(4,5),(4,6))):
  source=hashlib.md5(str(g).encode()).hexdigest()
  for q,count in enumerate(sizes):
   for a in range(count):
    base=.23+.13*a
    rows.append({'task_id':hashlib.md5(str((g,q,a)).encode()).hexdigest(),
     'source_group':source,'question_slot':q,'candidate_id':a,
     'original_v1_candidate':a==0,'probs':{
       'conditioned':base,'mean_pool_query_fused':base+.01,'no_evidence':.48,
       'no_query':.6,'learned_linear_5':base,'learned_gated_3':base+.02}})
 return ({'schema':e.SCHEMA,'authority':'DENY_ALL','production_accepted':False,
  'source_archive_sha256':e.SOURCE_SHA,'e15_head':e.E15_HEAD,
  'real_pretrained_forwards_new':0,'held_human_labels_opened':False,
  'source_group_count':4,'question_count':8,'candidate_count':33,'rows':rows},
  {r['task_id']:r['candidate_id']%2 for r in rows})


def original_score(b,y):
 truth=e.score_from_labels(b,y)
 return {'schema':'hepta.e21.original-human-question-level-review.v1',
  'authority':'DENY_ALL','original_source_and_merge_scores_reconciled':True,
  'method_results':truth}

class E22(unittest.TestCase):
 def test_eight_original_noquery_invariance(self):
  b,y=fixture();s=e.analyze(b)
  self.assertEqual(len(s['questions']),8)
  self.assertEqual(sum(r['candidate_count'] for r in s['questions']),33)
  self.assertTrue(all(q['arms']['no_query']['exact_invariant'] for q in s['questions']))
  result=e.review(b,s,y,original_score(b,y))
  self.assertEqual(result['models']['no_query']['complete_human_questions'],0)
  self.assertFalse(result['system2_admitted'])

 def test_near_equal_prob_is_not_exactly_equal(self):
  b,y=fixture();b['rows'][1]['probs']['no_query']+=1e-12
  s=e.analyze(b);self.assertEqual(sum(q['arms']['no_query']['exact_invariant'] for q in s['questions']),7)
  self.assertEqual(sum(q['arms']['no_query']['threshold_invariant'] for q in s['questions']),8)
  self.assertTrue(e.review(b,s,y,original_score(b,y))['original_e21_independent_human_scores_reconciled'])

 def test_promotion_and_label_leak_denied(self):
  for key,value in (('production_accepted',True),('held_human_labels_opened',True),
                    ('real_pretrained_forwards_new',False),('labels',{})):
   b,_=fixture();b[key]=value
   with self.subTest(key=key),self.assertRaises(ValueError):e.analyze(b)

 def test_wrong_original_e21_scores_and_false_score(self):
  b,y=fixture();s=e.analyze(b);z=original_score(b,y)
  z['method_results']['no_query']['correct']+=1
  with self.assertRaises(ValueError):e.review(b,s,y,z)

 def test_single_truth_class_is_not_mixed_question(self):
  b,y=fixture();s=e.analyze(b)
  with self.assertRaises(ValueError):e.review(b,s,{k:0 for k in y},original_score(b,y))

 def test_stale_sealed_prelabel_and_missing_candidate_denied(self):
  b,y=fixture();s=e.analyze(b)
  changed=copy.deepcopy(b);changed['rows'][0]['probs']['conditioned']+=.1
  with self.assertRaises(ValueError):e.review(changed,s,y,original_score(b,y))
  changed=copy.deepcopy(b);changed['rows'].pop()
  with self.assertRaises(ValueError):e.analyze(changed)

 def test_changed_answer_id_denied(self):
  b,y=fixture();b['rows'][1]['candidate_id']=0
  with self.assertRaises(ValueError):e.analyze(b)

 def test_strict_duplicate_and_nonfinite_json(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'bad.json'
   for v in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}'):
    p.write_bytes(v)
    with self.assertRaises(ValueError):e.read(p)

 def test_cli_blind_create_once_exact_prelabel_sha(self):
  b,y=fixture()
  with tempfile.TemporaryDirectory() as d:
   src=Path(d)/'src.json';out=Path(d)/'sealed.json'
   src.write_bytes(e.encoded(b))
   args=['run','--mode','blind','--e21-blind',str(src),'--sha256',
         hashlib.sha256(src.read_bytes()).hexdigest(),'--out',str(out)]
   with patch.object(sys,'argv',args):e.main()
   self.assertEqual(e.read(out),e.analyze(b))
   with patch.object(sys,'argv',args),self.assertRaises(ValueError):e.main()

if __name__=='__main__':unittest.main()
