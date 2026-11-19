import sys,os,json,io,resource,time,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from common import *
from output_budget_verifier import verify as inspect
from output_budget_pure import POLICY
role=sys.argv[1]
if role not in ('producer','recover'):raise ValueError('fixed role')
checks=[];refusals=[]
def check(n,v):
 if not v:raise AssertionError(n)
 checks.append(n)
def refused(name,fn,expected=None):
 try:fn()
 except ValueError as e:
  if expected is not None and str(e)!=expected:raise AssertionError((name,str(e)))
  refusals.append({'name':name,'error':str(e)})
 else:raise AssertionError(name+' accepted')
limits={'CPU':resource.getrlimit(resource.RLIMIT_CPU),'AS':resource.getrlimit(resource.RLIMIT_AS),'FSIZE':resource.getrlimit(resource.RLIMIT_FSIZE)}
all_inputs()
def load_case(name):
 payload,artifact,raw=case_expected(name);manifest,pin=case_manifest(name)
 if inst(SESSION)!=manifest['root_instance']:raise ValueError('root instance')
 ns=manifest['namespace'];p=SESSION/ns/'reserved.json';rr={'namespace':ns,'name':'reserved.json',**file_ref(p)}
 rejected=SESSION/ns/'output-budget-rejected.json'
 args=[raw,payload,FREEZE,manifest,pin,manifest['run_epoch'],p.read_bytes(),rr,rejected.read_bytes()if rejected.exists()else None,read('old_wire'),read('old_route')]
 return args
if role=='producer':
 import numpy as np
 from policy_backend import PolicyBackend
 from live_control import Clock
 from live_delivery import GuardedDelivery
 from live_core import KnownOutputBudgetRejection,UncertainEffect
 from cost import Budget
 def arrays(k):
  with np.load(io.BytesIO(read(k)),allow_pickle=False)as z:return {n:z[n].copy()for n in z.files}
 class ObservedBackend(PolicyBackend):
  def serve_bound(self,*args):
   self.last_return=None
   wire,route=super().serve_bound(*args);self.last_return=(wire,json.loads(canonical(route)));return wire,route
 ca=arrays('content');aa=arrays('actor');payload,artifact,_=case_expected('known')
 backend=ObservedBackend(ca,aa,FREEZE,{'completed_export_sha256':sha(read('complete')),'content_sha256':CFG['inputs']['content']['sha256'],'actor_full_sha256':CFG['inputs']['actor']['sha256']})
 check('artifact_exact',canonical(backend.checkpoint_payload())==canonical(payload));write('ARTIFACT.json',payload)
 budget=Budget(OUT,total_ns=2_000_000_000,byte_cap=8*2**20,rss_cap=256*2**20);cases={}
 for name in ('known','uncommitted'):
  payload,artifact,raw=case_expected(name);manifest,pin=case_manifest(name);clock=Clock(manifest,pin,manifest['run_epoch']);write(name+'-REQUEST.json',raw,True)
  d=GuardedDelivery(backend,artifact,SESSION,budget,clock,None)
  try:d.start(raw,POLICY,fault=None if name=='known'else'rejection_before_write')
  except KnownOutputBudgetRejection as e:
   check(name+'_typed_outcome',name=='known');outcome={'kind':'known_rejected','record':e.record,'error':str(e)}
  except UncertainEffect as e:
   check(name+'_typed_outcome',name=='uncommitted'and str(e)=='output rejection not committed'and type(e.__cause__)is OSError and str(e.__cause__)=='injected rejection failure before temp creation');outcome={'kind':'unknown','record':e.record,'error':str(e)}
  else:raise AssertionError('output unexpectedly admitted')
  args=load_case(name);summary=inspect(*args);write(name+'-AUDIT.json',summary)
  wire,route=backend.last_return;expected_route=json.loads(read('old_route'));expected_route['artifact_sha256']=artifact;expected_route['request_identity_sha256']=sha(canonical(json.loads(args[6])['payload']['identity']))
  check(name+'_returned_reference_exact',wire==read('old_wire')and route==expected_route)
  write(name+'-RETURNED.wire',wire,True);write(name+'-RETURNED-route.json',route)
  check(name+'_disk_scope',len(list((SESSION/manifest['namespace']).iterdir()))==(3 if name=='known'else 2))
  check(name+'_returned_cost',d.work['generator_attempts']==1 and d.work['generated_wire_bytes']==34884 and d.work['published_local_bytes']==0)
  before=inventory();write(name+'-DYNAMIC-BEFORE.json',before)
  # Actual public admission retry must fail on existing namespace, never rerun model.
  calls=backend.work['serving_calls'];refused(name+'_duplicate',lambda:d.start(raw,POLICY),'logical request already claimed/conflicting payload; no generator retry')
  if name=='known':
   old,ref=d.restore(args[7],raw,POLICY)
   check('reserved_view_still_indeterminate',old.phase=='indeterminate')
   refused('known_old_frontier',lambda:d.publish(old,ref),'output budget rejection terminal; no publication or replay')
  after=inventory();write(name+'-DYNAMIC-AFTER.json',after)
  check(name+'_dynamic_no_write_or_infer',before==after and backend.work['serving_calls']==calls)
  cases[name]={'outcome':outcome,'summary':summary,'delivery_work':d.work};d.close()
 check('two_actual_serves',backend.work['allocation_restores']==2 and backend.work['serving_calls']==backend.work['serving_actor_predictions']==2 and backend.work['reference_calls']==backend.work['optimizer_steps']==0)
 for name,model,original in [('CONTENT_AFTER.npz',backend.content,ca),('ACTOR_AFTER.npz',backend.actor,aa)]:
  data=model.to_arrays(include_optimizer=True)
  check(name+'_unchanged',set(data)==set(original)and all(np.array_equal(v,original[k])for k,v in data.items()))
  b=io.BytesIO();np.savez(b,**data);write(name,b.getvalue(),True)
 all_inputs();check('inputs_unchanged',True)
 write('PRODUCER_RESULT.json',{'checks':checks,'refusals':refusals,'cases':cases,'work':backend.work,'limits':limits})
else:
 check('no_backend_modules',not any(n in sys.modules for n in ('numpy','policy_backend','live_core','live_delivery')))
 before=inventory();write('RECOVERY-BEFORE.json',before);summaries={}
 for name in ('known','uncommitted'):
  args=load_case(name);s=inspect(*args);summaries[name]=s
  check(name+'_exact_prior_audit',s==json.loads((FOLDER/(name+'-AUDIT.json')).read_bytes()))
 # Detached well-shaped semantic mutations; original journal never written.
 args=load_case('known');value=json.loads(args[8]);bad=copy.deepcopy(value);bad['allowed_output_bytes']+=1
 write('BAD-allowed.json',bad);mut=list(args);mut[8]=canonical(bad);refused('wrong_allowed',lambda:inspect(*mut),'rejection allowed output budget binding')
 bad=copy.deepcopy(value);bad['reserved_record']['namespace']='f'*64
 write('BAD-reserved.json',bad);mut=list(args);mut[8]=canonical(bad);refused('wrong_reserved_identity',lambda:inspect(*mut),'rejection reserved reference binding')
 after=inventory();write('RECOVERY-AFTER.json',after);check('read_only_inventory',before==after)
 all_inputs();check('inputs_unchanged',True)
 write('RECOVERY_RESULT.json',{'checks':checks,'refusals':refusals,'summaries':summaries,'limits':limits,'work':{'allocation_restores':0,'serving_calls':0,'optimizer_steps':0},'scope':'structural readonly classification,not runtime replay or owner authority'})
