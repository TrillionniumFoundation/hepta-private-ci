import sys,os,json,io,resource,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from common import *
from live_control import Clock
from control_channel import FrameReader
from contracts import ContractError
from live_delivery import GuardedDelivery
from policy_backend import PolicyBackend
from route_contract import POLICY
from cost import Budget
from verify_fault import verify_fault
import numpy as np
role=sys.argv[1]
if role not in ('producer','recover'):raise ValueError('fixed role')
checks=[];refusals=[];failures=[]
def check(n,v):
 if not v:raise AssertionError(n)
 checks.append(n)
manifest=json.loads((FOLDER/'CONTROL_MANIFEST.json').read_bytes());clock=Clock(manifest,os.environ['CONTROL_PIN'],os.environ['CONTROL_EPOCH'])
if inst(SESSION)!=manifest['root_instance']:raise ValueError('root before models')
clock.live();all_inputs()
def arrays(k):
 with np.load(io.BytesIO(read(k)),allow_pickle=False)as z:return {n:z[n].copy()for n in z.files}
ca=arrays('content');aa=arrays('actor');payload,artifact,raw=expected()
backend=PolicyBackend(ca,aa,FREEZE,{'completed_export_sha256':sha(read('complete')),'content_sha256':CFG['inputs']['content']['sha256'],'actor_full_sha256':CFG['inputs']['actor']['sha256']})
check('artifact_exact',canonical(backend.checkpoint_payload())==canonical(payload))
reader=FrameReader(int(sys.argv[2]))if role=='producer'else None
budget=Budget(OUT,total_ns=2_000_000_000,byte_cap=16*2**20,rss_cap=256*2**20)
d=GuardedDelivery(backend,artifact,SESSION,budget,clock,reader)
limits={'CPU':resource.getrlimit(resource.RLIMIT_CPU),'AS':resource.getrlimit(resource.RLIMIT_AS),'FSIZE':resource.getrlimit(resource.RLIMIT_FSIZE)}
if role=='producer':
 write('REQUEST.json',raw,True);write('ARTIFACT.json',payload)
 a,g=d.start(raw,POLICY);a,record=d.publish(a,g,stop_after=2)
 expected_route=json.loads(read('old_route'));expected_route['artifact_sha256']=artifact;expected_route['request_identity_sha256']=sha(canonical(a.identity))
 check('real_reference_route_wire',a.wire==read('old_wire')and a.route==expected_route)
 check('acked_known_prefix',a.phase=='generated'and a.next_index==2 and a.session.spent=={'controller':1,'generator':1,'output_bytes':8227})
 before=inventory();write('FAULT_BEFORE.json',before)
 ready={'pid':os.getpid(),'freeze':FREEZE,'record':record,'artifact_sha256':artifact,'wire_sha256':sha(a.wire),'route_sha256':sha(canonical(a.route)),'root_instance':inst(SESSION),'lock_instance':inst(SESSION/'.hepta-writer.lock'),'before_ref':file_ref(FOLDER/'FAULT_BEFORE.json')}
 write('READY.json',ready)
 try:d.await_cancel(a,record)
 except ContractError as e:
  check('exact_active_channel_failure',str(e)=='control channel fault; no further output');failures.append({'name':'active_EOF','error':str(e)})
 else:raise AssertionError('EOF not observed')
 fault=json.loads((SESSION/ready['record']['namespace']/'control-fault.json').read_bytes())
 check('precise_fault_no_cancel',fault['error']=='ChannelEOF: EOF before control frame'and fault['disposition']=='unknown_no_automatic_replay'and d.control_ack is None and a.phase=='generated')
 summary=verify_fault(ready,manifest,clock,before);write('PRODUCER_FAULT_VERIFIED.json',summary)
 after=inventory();write('FAULT_AFTER.json',after)
 check('only_fault_record_added',len(after)==len(before)+1 and all(after[k]==v for k,v in before.items()))
 check('one_real_work_retained',backend.work['allocation_restores']==2 and backend.work['serving_calls']==backend.work['serving_actor_predictions']==1 and backend.work['optimizer_steps']==backend.work['reference_calls']==0 and d.work['generator_attempts']==1 and d.work['generated_wire_bytes']==len(a.wire)and d.work['published_local_bytes']==8227)
 check('model_unchanged',canonical(backend.checkpoint_payload())==canonical(payload));all_inputs();check('inputs_unchanged',True)
 work=backend.work;delivery=d.work;d.close();os.close(reader.fd)
 write('PRODUCER_RESULT.json',{'checks':checks,'refusals':refusals,'failures':failures,'work':work,'delivery_work':delivery,'limits':limits,'known_prefix_bytes':8227,'fault_ref':file_ref(SESSION/ready['record']['namespace']/'control-fault.json')})
 raise SystemExit(0)
ready=json.loads((FOLDER/'READY.json').read_bytes());before=json.loads((FOLDER/'FAULT_BEFORE.json').read_bytes());handoff=json.loads((FOLDER/'HANDOFF.json').read_bytes())
summary=verify_fault(ready,manifest,clock,before)
check('joint_handoff_exact',canonical(handoff)==canonical(summary))
a,record=d.restore(ready['record'],raw,POLICY)
check('audit_midpoint_only',a.phase=='generated'and a.next_index==2 and a.session.spent=={'controller':1,'generator':1,'output_bytes':8227})
prior=inventory();write('RECOVER_BEFORE.json',prior);live_before=clock.live()
try:d.publish(a,record)
except ContractError as e:
 check('exact_controlfault_not_readonly_or_expiry',str(e)=='control effect unknown; supervisor disposition required');refusals.append({'name':'control_fault_recovery','error':str(e)})
else:raise AssertionError('faulted prefix resumed')
live_after=clock.live();after=inventory();write('RECOVER_AFTER.json',after)
check('live_refusal_no_write',live_before<=live_after<manifest['deadline_ns']and prior==after)
check('zero_recovery_inference',backend.work['allocation_restores']==2 and backend.work['serving_calls']==backend.work['serving_actor_predictions']==backend.work['optimizer_steps']==0)
check('model_unchanged',canonical(backend.checkpoint_payload())==canonical(payload))
for name,model,original in [('CONTENT_AFTER.npz',backend.content,ca),('ACTOR_AFTER.npz',backend.actor,aa)]:
 data=model.to_arrays(include_optimizer=True)
 if set(data)!=set(original)or any(not np.array_equal(v,original[k])for k,v in data.items()):raise AssertionError('full arrays')
 b=io.BytesIO();np.savez(b,**data);write(name,b.getvalue(),True)
for mode in ('text','image'):write('FINAL-'+mode+'.part',a.session.prefix(mode),True)
all_inputs();check('inputs_unchanged',True)
work=backend.work;delivery=d.work;d.close()
write('RECOVERY_RESULT.json',{'checks':checks,'refusals':refusals,'work':work,'delivery_work':delivery,'limits':limits,'live_before_ns':live_before,'live_after_ns':live_after,'deadline_ns':manifest['deadline_ns'],'spent':a.session.spent})
