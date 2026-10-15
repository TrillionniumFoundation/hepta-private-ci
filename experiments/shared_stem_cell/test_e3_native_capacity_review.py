"""Independent stdlib synthetic source/score fault tests, no pretrained outcomes."""
import copy
import unittest
import e3_native_capacity_review as m
H='a'*64


def case():
 rows=[];combined=[];labels=[]
 for i in range(64):
  ident=f'{i:064x}';group=f'{i+1000:064x}';source=f'{i+2000:064x}'
  p0=[0.5,0.2,0.2,0.1];p1=[0.2,0.5,0.2,0.1]
  rows.append({'id':ident,'group':group,'source_input_sha256':source,
               'text_only_probabilities':p0[:], 'joint_text_image_probabilities':p1[:]})
  combined.append({'id':ident,'group':group,'source_input_sha256':source,
                   'arms':{'text_only':p0[:]}})
  labels.append({'id':ident,'group':group,'split':'test','label':1})
 receipt={'schema':m.RECEIPT,'model':{'repo':m.MODEL[0],'revision':m.MODEL[1],
             'pipeline_digest':H},'source_sha256':H,
          'heads_complete_trainable_params_each':769,'train_steps_each':80,
          'train_examples':96,'test_examples':64,'initial_same_head_digest':H,
          'text_trained_head_digest':H,'joint_trained_head_digest':H,
          'same_initialization':True,'identical_optimizer_schedule':True,
          'held_labels_visible_during_fit':False,'cost_matched':False,
          'production_accepted':False,'authority':'DENY_ALL','rows':rows}
 original={'schema':m.FIVE,'authority':'DENY_ALL','production_accepted':False,
          'stem_winner':None,'human_visual_necessity_adjudicated':False,
          'cohort':'historical_scienceqa_test_not_future',
          'source_sha256':H,'cases':combined}
 return [receipt,original,labels]

class Result(unittest.TestCase):
 def test_good(self):
  q=m.score(*case());self.assertEqual(q['joint_correct'],64)
  self.assertEqual(q['text_only_correct'],0)
  self.assertIsNone(q['stem_winner'])
 def test_unverified_model(self):
  x=case();x[0]['model']['revision']='b'*40
  with self.assertRaises(m.CapacityReviewError):m.score(*x)
 def test_mismatched_case_id(self):
  x=case();x[0]['rows'][0]['id']='b'*64
  with self.assertRaises(m.CapacityReviewError):m.score(*x)
 def test_wrong_label_group(self):
  x=case();x[2][0]['group']='b'*64
  with self.assertRaises(m.CapacityReviewError):m.score(*x)
 def test_missing_label(self):
  x=case();x[2].pop()
  with self.assertRaises(m.CapacityReviewError):m.score(*x)
 def test_duplicate_head_input(self):
  x=case();x[0]['rows'][1]['id']=x[0]['rows'][0]['id']
  with self.assertRaises(m.CapacityReviewError):m.score(*x)
 def test_bad_probability(self):
  x=case();x[0]['rows'][1]['joint_text_image_probabilities']=[True,0,0,0]
  with self.assertRaises(m.CapacityReviewError):m.score(*x)
 def test_fake_promotion(self):
  x=case();x[0]['production_accepted']=True
  with self.assertRaises(m.CapacityReviewError):m.score(*x)
 def test_source_diff(self):
  x=case();x[0]['source_sha256']='b'*64
  with self.assertRaises(m.CapacityReviewError):m.score(*x)
 def test_wrong_budget(self):
  x=case();x[0]['train_steps_each']=0
  with self.assertRaises(m.CapacityReviewError):m.score(*x)
 def test_wrong_output_id(self):
  x=case();x[0]['rows'][0]['source_input_sha256']='0'*64
  with self.assertRaises(m.CapacityReviewError):m.score(*x)

if __name__=='__main__':unittest.main()
