"""Synthetic reference ZIP audit: historical claims never become production no-change."""
import copy,hashlib,io,json,unittest
from unittest.mock import patch
from zipfile import ZipFile
import e1_public_laya_reference as e
import e1_public_triplet_real_cpu as trial
from test_e1_public_triplet_review import fixture
def build_zip(panel):
 d=trial.sha(trial.canonical(panel))
 rows=[]
 for case in panel['cases']:
  if case['split'] not in ('calibration','test'):continue
  rows.append({'case_id':case['case_id'],'source_digest':case['source_digest'],
               'joint_input_digest':case['joint_input_digest'],'split':case['split'],
               'prob_sports':.75 if case['label'] else .25})
 report={'schema':'hepta.stem.agnews-physical-arm.v1','panel_digest':d,
         'arm_id':'laya421_frozen','production_promotion':'DENY_ALL',
         'cross_sectional_not_future':True,'rows':rows}
 receipt={'panel_digest':d}
 return {'stem-laya-physical-arm.json':json.dumps(report,sort_keys=True).encode(),
         'stem-agnews-source.json':json.dumps(receipt,sort_keys=True).encode()}
def archive(files):
 b=io.BytesIO()
 with ZipFile(b,'w') as z:
  for name,data in files.items():z.writestr(name,data)
 return b.getvalue()
class TestArchive(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.root=fixture()
 def attempt(self,fn=None,valid=False):
  panel,reports=copy.deepcopy(self.root);files=build_zip(panel)
  if fn:fn(panel,reports,files)
  raw=archive(files)
  with patch.object(e,'ZIP_SHA',hashlib.sha256(raw).hexdigest()):
   if valid:
    result=e.compare(panel,reports,raw)
    self.assertEqual(result['laya_test_cases'],64)
    self.assertFalse(result['historical_reference_is_production_no_change'])
    self.assertFalse(result['production_promotion_permitted'])
   else:
    with self.assertRaises((e.Invalid,KeyError,ValueError,TypeError)):e.compare(panel,reports,raw)
 def test_mechanism_only(self):self.attempt(valid=True)
 def test_missing_pretrained_candidate(self):self.attempt(lambda p,r,f:r.pop('mmbert_small'))
 def test_wrong_source_hash(self):
  self.attempt(lambda p,r,f:f.__setitem__('stem-agnews-source.json',b'{"panel_digest":"'+b'f'*64+b'"}'))
 def test_tampered_source_case(self):
  def bad(p,r,f):
   value=json.loads(f['stem-laya-physical-arm.json']);value['rows'][0]['case_id']='wrong'
   f['stem-laya-physical-arm.json']=json.dumps(value).encode()
  self.attempt(bad)
 def test_wrong_trained_head_panel(self):self.attempt(lambda p,r,f:r['granite_97m_r2'].update(public_panel_sha256='f'*64))
 def test_false_production(self):self.attempt(lambda p,r,f:r['granite_97m_r2'].update(production_promotion_permitted=True))
 def test_duplicate_zip_entry(self):
  p,r=copy.deepcopy(self.root);files=build_zip(p);raw=io.BytesIO()
  with ZipFile(raw,'w') as z:
   for name,data in files.items():z.writestr(name,data)
   z.writestr('stem-agnews-source.json',b'{}')
  with patch.object(e,'ZIP_SHA',hashlib.sha256(raw.getvalue()).hexdigest()):
   with self.assertRaises(e.Invalid):e.compare(p,r,raw.getvalue())
 def test_mismatched_archive_sha(self):
  p,r=copy.deepcopy(self.root)
  with self.assertRaises(e.Invalid):e.compare(p,r,archive(build_zip(p)))
if __name__=='__main__':unittest.main()
