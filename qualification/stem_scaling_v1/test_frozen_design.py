"""Synthetic pre-registered design and strict original-case completeness tests."""
import copy, hashlib, json, tempfile, unittest
from pathlib import Path
from scaling_frontier import SCHEMA as SRC
import frozen_design as f


def fixture():
 baseline={'logical_cells':1024,'active_cells':4,'reasoning_depth':2,
           'train_rows':128,'compute_budget_ns':1000000}
 provenance={'arm':'shared_sparse','seed':41,'source_sha256':'a'*64,
             'held_label_sha256':'b'*64,'evaluator_sha256':'c'*64,
             'stem_sha256':'d'*64,'independent_source_groups':4,'total':16}
 ids={'baseline':'p5:baseline'}
 for axis,levels in f.LEVELS.items():
  for level in levels:
   if level != baseline[axis]:ids[f'{axis}={level}']=f'p5:{axis}:{level}'
 design={'schema':f.SCHEMA,'authority_posture':'DENY_ALL',
         'production_accepted':False,'teacher_equivalence_certified':False,
         'baseline':baseline,'provenance':provenance,'trial_ids':ids}
 rows=[]
 for name,shape in f.expected(design).items():
  rows.append({**shape,'correct':11 if name=='p5:baseline' else 12,
               'training_cpu_ns':123000,'inference_cpu_ns':456000,
               'encoder_forwards':16,'peak_rss_bytes':12345678,
               'physical_work_observed':True,'independent_score_receipt':True})
 return design,{'schema':SRC,'authority_posture':'DENY_ALL',
                'production_accepted':False,'teacher_equivalence_certified':False,
                'rows':rows}

class TestFrozenDesign(unittest.TestCase):
 def test_five_axes_reuse_one_common_baseline_without_creating_new_sources(self):
  d,o=fixture();out=f.audit(d,o)
  self.assertEqual(out['original_design_points'],16)
  self.assertEqual(len(out['five_complete_one_axis_curves']),5)
  self.assertEqual(out['original_independent_source_groups'],4)
  self.assertFalse(out['independent_teacher_equivalence_certified'])
  self.assertFalse(out['ten_t_hundred_t_extrapolation_permitted'])

 def test_missing_or_extra_original_trial_denied(self):
  for kind in ('missing','extra'):
   d,o=fixture()
   if kind=='missing':o['rows'].pop()
   else:o['rows'].append(dict(o['rows'][0],trial_id='unexpected'))
   with self.subTest(kind=kind),self.assertRaises(ValueError):f.audit(d,o)

 def test_forged_source_held_label_or_model_denied(self):
  for field in ('source_sha256','held_label_sha256','evaluator_sha256','stem_sha256'):
   d,o=fixture();o['rows'][5][field]='e'*64
   with self.subTest(field=field),self.assertRaises(ValueError):f.audit(d,o)

 def test_change_one_unregistered_resource_axis_denied(self):
  for axis in f.AXES:
   d,o=fixture();o['rows'][0][axis]=f.LEVELS[axis][0] if o['rows'][0][axis]!=f.LEVELS[axis][0] else f.LEVELS[axis][1]
   with self.subTest(axis=axis),self.assertRaises(ValueError):f.audit(d,o)

 def test_cherry_pick_only_positive_last_level_denied(self):
  d,o=fixture();o['rows']=[r for r in o['rows'] if r['correct']>11]
  with self.assertRaises(ValueError):f.audit(d,o)

 def test_after_the_fact_changed_trial_map_and_duplication_denied(self):
  d,o=fixture();d['trial_ids']['baseline']='fake-posthoc-win'
  with self.assertRaises(ValueError):f.audit(d,o)
  d,o=fixture();d['trial_ids']['baseline']=d['trial_ids']['logical_cells=64']
  with self.assertRaises(ValueError):f.expected(d)

 def test_deny_production_or_teacher_claim(self):
  for key,value in [('authority_posture','ALLOW'),('production_accepted',True),
                    ('teacher_equivalence_certified',True)]:
   d,o=fixture();d[key]=value
   with self.subTest(key=key),self.assertRaises(ValueError):f.expected(d)

 def test_duplicate_json_and_nonfinite_rejected(self):
  with tempfile.TemporaryDirectory() as temp:
   from scaling_frontier import load
   p=Path(temp)/'bad.json'
   for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}'):
    p.write_bytes(raw)
    with self.assertRaises(ValueError):load(p)

 def test_exact_design_sha_required_and_create_only_output(self):
  d,o=fixture()
  with tempfile.TemporaryDirectory() as temp:
   from unittest.mock import patch
   from sys import argv
   root=Path(temp);design=root/'design.json';original=root/'original.json';out=root/'out.json'
   design.write_bytes((json.dumps(d,sort_keys=True,separators=(',',':'))+'\n').encode())
   original.write_text(json.dumps(o))
   cmd=['demo','--frozen-design',str(design),'--expected-design-sha256',
        hashlib.sha256(design.read_bytes()).hexdigest(),'--original-observations',str(original),
        '--output',str(out)]
   with patch('sys.argv',cmd):f.main()
   self.assertEqual(json.loads(out.read_text())['original_design_points'],16)
   with patch('sys.argv',cmd),self.assertRaises(ValueError):f.main()

if __name__=='__main__':unittest.main()
