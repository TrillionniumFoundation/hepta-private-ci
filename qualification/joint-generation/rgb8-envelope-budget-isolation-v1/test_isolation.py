import copy,hashlib,json,unittest
import numpy as np
import legacy_multimodal_contract as old
import multimodal_contract as new
from contracts import ContractError
import serve
OBSERVATIONS=[]
ARTIFACT='a'*64

def fixture(words='blue cross right',mode='greedy',reverse=False):
 streams=[{'stream_id':'instruction','modality':'text','timing':{'clock_id':'capture:1','sync_group':'clip:1','start_ns':100,'end_ns':100000100},'payload':{'encoding':'utf-8','text':words}}, {'stream_id':'source','modality':'image','timing':{'clock_id':'capture:1','sync_group':'clip:1','start_ns':100,'end_ns':100000100},'payload':{'dtype':'float32','color_space':'RGB','pixels':np.linspace(0,1,192).reshape(8,8,3)}}]
 if reverse:streams.reverse()
 return {'schema':new.SCHEMA,'objective_id':'scene-transform-v1','run_id':'alias:literal','artifact_sha256':ARTIFACT,'budget':{'compute_units':5000,'input_bytes':65536,'output_bytes':4096},'deadline_ns':10**18,'decoding':{'mode':mode,'seed':42 if mode=='sample' else 0},'outputs':['text','image'],'streams':streams,'sync_tolerance_ns':0}

def env(module,**kw):return module.MediaEnvelope.parse(fixture(**kw),now_ns=1)
def adapt(module,e,**kw):return module.to_legacy_request(e,expected_artifact_sha256=kw.get('artifact',ARTIFACT),now_ns=kw.get('now',1))

def budget(e):return dict(vars(e.budget))
class IsolationTests(unittest.TestCase):
 def test_preserved_old_alias(self):
  for field in ('compute_units','output_bytes'):
   e=env(old);before=budget(e);r=adapt(old,e)
   self.assertIs(r['budget'],vars(e.budget));r['budget'][field]+=1
   self.assertEqual(getattr(e.budget,field),before[field]+1)
   OBSERVATIONS.append({'case':'legacy_alias','field':field,'before':before,'after':budget(e),'identity_alias':True})
 def test_new_bidirectional_and_sibling_isolation(self):
  for field in ('compute_units','output_bytes'):
   for direction in ('request_to_envelope','envelope_to_request'):
    e=env(new);before=budget(e);a=adapt(new,e);b=adapt(new,e)
    self.assertIsNot(a['budget'],vars(e.budget));self.assertIsNot(a['budget'],b['budget'])
    fresh=None
    if direction=='request_to_envelope':
     a['budget'][field]+=1;self.assertEqual(budget(e),before);self.assertEqual(b['budget'],before)
    else:
     # Deliberate local mutation of the test object's __dict__, NOT an authority attack.
     vars(e.budget)[field]+=1
     self.assertEqual(a['budget'],before);self.assertEqual(b['budget'],before)
     c=adapt(new,e);self.assertEqual(c['budget'][field],before[field]+1);fresh=dict(c['budget'])
    OBSERVATIONS.append({'case':'fixed_isolation','field':field,'direction':direction,'before':before,'envelope_after':budget(e),'request_a_after':dict(a['budget']),'request_b_after':dict(b['budget']),'fresh_request_after':fresh,'passed':True})
 def test_request_and_real_encoder_parity(self):
  for words in ('keep keep keep','blue cross right'):
   for mode in ('greedy','sample'):
    for reverse in (False,True):
     a=adapt(old,env(old,words=words,mode=mode,reverse=reverse));b=adapt(new,env(new,words=words,mode=mode,reverse=reverse))
     self.assertEqual(a,b)
     la,xa=serve.encode_request(a,include_low=False);lb,xb=serve.encode_request(b,include_low=False)
     self.assertIsNone(la);self.assertIsNone(lb);self.assertEqual(xa.shape,(1,202));self.assertTrue(np.array_equal(xa,xb))
     expected=np.r_[np.eye(4)[0 if words.startswith('keep') else 3],np.eye(3)[0 if words.startswith('keep') else 2],np.eye(3)[0 if words.startswith('keep') else 2]]
     self.assertTrue(np.array_equal(xb[0,-10:],expected))
     OBSERVATIONS.append({'case':'parity','words':words,'mode':mode,'reversed_stream_order':reverse,'feature_sha256':hashlib.sha256(xb.astype('<f8').tobytes()).hexdigest(),'request_sha256':hashlib.sha256(json.dumps(b,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
 def test_rejection_before_callback_and_no_budget_change(self):
  for module in (old,new):
   for case in ('artifact','expired','missing_text','geometry','unknown_word','output_profile'):
    value=fixture();kwargs={}
    if case=='artifact':kwargs['artifact']='b'*64
    elif case=='expired':kwargs['now']=10**18
    elif case=='missing_text':value['streams']=value['streams'][1:]
    elif case=='geometry':value['streams'][1]['payload']['pixels']=np.zeros((16,16,3))
    elif case=='unknown_word':value['streams'][0]['payload']['text']='purple cross right'
    elif case=='output_profile':value['outputs']=['text']
    e=module.MediaEnvelope.parse(value,now_ns=1);before=budget(e)
    with self.assertRaises(ContractError):adapt(module,e,**kwargs)
    self.assertEqual(budget(e),before)
    OBSERVATIONS.append({'case':'expected_refusal','module':module.__name__,'reason':case,'budget_unchanged':True})
 def test_actual_dispatch_callback_isolation(self):
  for module in (old,new):
   e=env(module);before=budget(e);calls=[]
   def callback(request):
    calls.append(request);request['budget']['output_bytes']+=1;return 'local-callback-only'
   result=module.dispatch(e,callback,expected_artifact_sha256=ARTIFACT,now_ns=1)
   self.assertEqual(result,'local-callback-only');self.assertEqual(len(calls),1)
   self.assertEqual(e.budget.output_bytes,before['output_bytes']+(module is old))
   OBSERVATIONS.append({'case':'dispatch_callback','module':module.__name__,'callback_calls':1,'envelope_changed':module is old})
