"""Synthetic-only CPU Head and source-contract tests; no model weights downloaded."""
import copy,tempfile,unittest
from pathlib import Path
import e1_public_triplet_real_cpu as e

def panel():
 cases=[]
 for split,n in e.SPLITS.items():
  for i in range(n):
   txt='synthetic public task '+split+' '+str(i)+' category '+('world' if i%2==0 else 'sports')
   joint={'state':txt,'question':'Which category does the news report describe?','options':['world','sports']}
   src=e.sha(txt.encode())
   cases.append({'case_id':src[:24],'split':split,'label':i%2,'label_name':'world' if i%2==0 else 'sports',
                 'source_digest':src,'group_id':src,'joint_input_digest':e.sha(e.canonical(joint)),'joint_input':joint})
 return {'schema':'hepta.stem.agnews-binary-capability-panel.v1','dataset':'szhuggingface/ag_news',
  'dataset_commit_prefix':'98c5322','dataset_file_sha256':dict(e.SOURCE_FILES),'label_mapping':{'world':0,'sports':1},
  'case_count':224,'cross_sectional_not_future':True,'production_promotion':'DENY_ALL','cases':cases}

class Tests(unittest.TestCase):
 def test_pinned_panel_passes_mechanism_only(self):
  obj=panel()
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'panel.json';p.write_bytes(e.canonical(obj))
   self.assertEqual(e.load_panel(p)[1],e.sha(e.canonical(obj)))
 def deny_source(self,change):
  obj=panel();change(obj)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'panel.json';p.write_bytes(e.canonical(obj))
   with self.assertRaises((e.Invalid,ValueError,TypeError)):e.load_panel(p)
 def test_reject_source_file_sha_drift(self):self.deny_source(lambda p:p['dataset_file_sha256'].update(train='f'*64))
 def test_reject_modified_text(self):self.deny_source(lambda p:p['cases'][0]['joint_input'].update(state='tampered'))
 def test_reject_label_type(self):self.deny_source(lambda p:p['cases'][0].update(label=True))
 def test_reject_wrong_question(self):self.deny_source(lambda p:p['cases'][0]['joint_input'].update(question='new question'))
 def test_reject_duplicate_source(self):self.deny_source(lambda p:p['cases'].__setitem__(1,copy.deepcopy(p['cases'][0])))
 def test_reject_missing_case(self):self.deny_source(lambda p:p['cases'].pop())
 def test_actual_torch_optimizer_changes_only_learned_head(self):
  import torch
  torch.set_num_threads(1);obj=panel()
  for name,(key,revision,width) in e.MODELS.items():
   vectors={c['case_id']:[((int(c['case_id'][:4],16)%99)-50)/100]*width for c in obj['cases']}
   report=e.fit_heads(obj,name,vectors)
   self.assertEqual(report['steps'],40)
   self.assertLessEqual(report['head_parameter_count'],2048)
   self.assertEqual(len(report['controls']['learned_head']['predictions']),96)
   self.assertNotEqual(report['controls']['frozen_head']['head_sha256'],report['controls']['learned_head']['head_sha256'])
   self.assertFalse(report['training_test_labels_accessed'])
 def test_changing_test_labels_does_not_change_head_or_predictions(self):
  import torch
  torch.set_num_threads(1);obj=panel();width=e.MODELS['granite_97m_r2'][2]
  vectors={c['case_id']:[((int(c['case_id'][:4],16)%99)-50)/100]*width for c in obj['cases']}
  first=e.fit_heads(obj,'granite_97m_r2',vectors)
  changed=copy.deepcopy(obj)
  for c in changed['cases']:
   if c['split']=='test':c['label']=1-c['label']
  second=e.fit_heads(changed,'granite_97m_r2',vectors)
  self.assertEqual(first['controls'],second['controls'])
 def test_incomplete_feature_bank_denied(self):
  with self.assertRaises(e.Invalid):e.fit_heads(panel(),'granite_97m_r2',{})
 def test_wrong_feature_width_denied(self):
  obj=panel()
  with self.assertRaises(e.Invalid):e.fit_heads(obj,'granite_97m_r2',{c['case_id']:[0.] for c in obj['cases']})
 def test_zero_optimizer_budget_denied(self):
  obj=panel()
  with self.assertRaises(e.Invalid):e.fit_heads(obj,'granite_97m_r2',{c['case_id']:[0.]*384 for c in obj['cases']},steps=0)

if __name__=='__main__':unittest.main()
