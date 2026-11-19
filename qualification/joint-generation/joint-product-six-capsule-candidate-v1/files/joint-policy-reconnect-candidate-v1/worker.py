import sys,os,json,copy,io,signal,resource
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from common import *
import numpy as np
from policy_backend import PolicyBackend
from route_contract import POLICY
from content_input import convert
from guarded_delivery import GuardedDelivery
from contracts import ContractError
from cost import Budget
from attempt import parts
from verify_midpoint import verify
role=sys.argv[1]
if role not in ('producer','recover'):raise ValueError('fixed role')
checks=[];refusals=[]
def check(name,ok):
 if not ok:raise AssertionError(name)
 checks.append(name)
def arrays(k):
 with np.load(io.BytesIO(read(k)),allow_pickle=False)as z:return {n:z[n].copy()for n in z.files}
all_inputs()
if role=='recover':
 h=json.loads((FOLDER/'HANDOFF.json').read_bytes())
 if inst(SESSION)!=h['root_instance']or inst(SESSION/'.hepta-writer.lock')!=h['lock_instance']:raise ValueError('handoff inode mismatch before model restore/lease')
ca=arrays('content');aa=arrays('actor');expected_payload,artifact,raw=expected()
backend=PolicyBackend(ca,aa,FREEZE,{'completed_export_sha256':sha(read('complete')),'content_sha256':CFG['inputs']['content']['sha256'],'actor_full_sha256':CFG['inputs']['actor']['sha256']})
check('current_full_artifact_exact',canonical(backend.checkpoint_payload())==canonical(expected_payload))
budget=Budget(OUT,total_ns=2_000_000_000,byte_cap=16*2**20,rss_cap=256*2**20)
d=GuardedDelivery(backend,artifact,SESSION,budget)
limits={'CPU':resource.getrlimit(resource.RLIMIT_CPU),'AS':resource.getrlimit(resource.RLIMIT_AS),'FSIZE':resource.getrlimit(resource.RLIMIT_FSIZE)}
if role=='producer':
 write('REQUEST.json',raw,True);write('ARTIFACT.json',expected_payload)
 a,g=d.start(raw,POLICY,now=2);a,record=d.publish(a,g,now=2,stop_after=2)
 oldroute=json.loads(read('old_route'));oldroute['artifact_sha256']=artifact;oldroute['request_identity_sha256']=sha(canonical(a.identity))
 check('one_real_route_exact_historical_reference',a.wire==read('old_wire')and a.route==oldroute)
 check('midpoint_acked_prefix',a.phase=='generated'and a.next_index==2 and a.session.spent=={'controller':1,'generator':1,'output_bytes':8227}and len(a.session.prefix('text'))==35 and len(a.session.prefix('image'))==8192)
 w=backend.work
 check('one_serving_no_reference_or_training',w['allocation_restores']==2 and w['serving_calls']==w['serving_actor_predictions']==w['serving_encoded_rows']==w['serving_prefix_J']==1 and w['serving_final_updates']=={'T':0,'I':1,'J':0}and w['reference_calls']==w['reference_actor_predictions']==w['optimizer_steps']==w['fresh_models']==0)
 check('serving_no_model_state_change',canonical(backend.checkpoint_payload())==canonical(expected_payload))
 ready={'pid':os.getpid(),'freeze':FREEZE,'record':record,'artifact_sha256':artifact,'wire_sha256':sha(a.wire),'route_sha256':sha(canonical(a.route)),'root_instance':inst(SESSION),'lock_instance':inst(SESSION/'.hepta-writer.lock'),'checks':checks,'refusals':refusals,'work':w,'delivery_work':d.work,'limits':limits}
 write('READY.json',ready)
 while True:signal.pause()
ready=json.loads((FOLDER/'READY.json').read_bytes());handoff=json.loads((FOLDER/'HANDOFF.json').read_bytes())
verified=verify(ready,inst(SESSION))
check('exact_external_handoff',handoff==verified)
check('same_root_and_lock_inode',inst(SESSION)==handoff['root_instance']and inst(SESSION/'.hepta-writer.lock')==handoff['lock_instance'])
changed=json.loads(raw);changed['streams'][0]['payload']['pixels'][0][0]=[0.,0.,0.];changed=canonical(changed);write('CONFLICTING_REQUEST.json',changed,True)
bound=convert(changed,expected_artifact_sha256=artifact,sequence=POLICY,now_ns=2)
check('conflicting_payload_valid_same_logical_namespace',changed!=raw and bound.run_spec.run_id==CFG['new_run_id']and bound.run_spec.objective_id==json.loads(raw)['objective_id'])
for name,value in [('duplicate',raw),('conflicting',changed)]:
 before=inventory();write(name+'-before.json',before)
 try:d.start(value,POLICY,now=2)
 except ContractError as e:
  if str(e)!='logical request already claimed/conflicting payload; no generator retry':raise
  refusals.append({'name':name,'error':str(e)})
 else:raise AssertionError('request reran')
 after=inventory();write(name+'-after.json',after)
 check(name+'_namespace_refusal_no_write',before==after)
check('duplicates_no_policy_inference',backend.work['serving_calls']==backend.work['serving_actor_predictions']==backend.work['serving_encoded_rows']==0)
a,record=d.restore(handoff['record'],raw,POLICY,now=2)
check('restored_midpoint_exact',a.phase=='generated'and a.next_index==2 and sha(canonical(a.route))==handoff['route_sha256'])
a,final=d.publish(a,record,now=2)
check('complete_saved_output_no_recompute',a.phase=='complete'and a.next_index==6 and a.wire==read('old_wire')and a.session.spent=={'controller':1,'generator':1,'output_bytes':34808}and sha(canonical(a.route))==handoff['route_sha256'])
for mode in ('text','image'):write('FINAL-'+mode+'.part',a.session.prefix(mode),True)
write('FINAL_ROUTE.json',a.route);write('FINAL_WIRE.json',a.wire,True)
w=backend.work
check('recovery_only_two_allocations_zero_inference',w['allocation_restores']==2 and all(v==0 for k,v in w.items()if k not in ('allocation_restores','serving_final_updates'))and w['serving_final_updates']=={'T':0,'I':0,'J':0})
check('recovery_full_artifact_unchanged',canonical(backend.checkpoint_payload())==canonical(expected_payload))
for n,model,original in [('CONTENT_AFTER.npz',backend.content,ca),('ACTOR_AFTER.npz',backend.actor,aa)]:
 data=model.to_arrays(include_optimizer=True)
 if set(data)!=set(original)or any(not np.array_equal(v,original[k])for k,v in data.items()):raise AssertionError('full model arrays')
 b=io.BytesIO();np.savez(b,**data);write(n,b.getvalue(),True)
all_inputs();check('all_original_pins_unchanged',True)
delivery_work=d.work;d.close()
write('RECOVERY_RESULT.json',{'status':'PASS_RECONNECTED_ROUTE_PREFIX','pid':os.getpid(),'freeze':FREEZE,'checks':checks,'refusals':refusals,'work':w,'delivery_work':delivery_work,'final':final,'limits':limits,'spent':a.session.spent,'remaining_pieces_published':4,'new_output_bytes':delivery_work['published_local_bytes'],'same_root_instance':inst(SESSION),'same_lock_instance':inst(SESSION/'.hepta-writer.lock'),'scope':'two cold restores counted,zero new policy/model inference; literal clock,local prefix not client ack'})
