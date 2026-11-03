import sys,os,json,io,signal,resource,time,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from common import *
from live_control import Clock
from control_channel import FrameReader,send
from policy_backend import PolicyBackend
from live_delivery import GuardedDelivery
from contracts import ContractError
from route_contract import POLICY
from cost import Budget
from verify_control import verify_ack
import numpy as np
role=sys.argv[1]
if role not in ('producer','recover'):raise ValueError('fixed role')
checks=[];refusals=[]
def check(n,v):
 if not v:raise AssertionError(n)
 checks.append(n)
def refused(n,fn,expected):
 before=inventory()
 try:fn()
 except ContractError as e:
  if str(e)!=expected:raise
  refusals.append({'name':n,'error':str(e)})
 else:raise AssertionError(n)
 check(n+'_no_write',before==inventory())
manifest=json.loads((FOLDER/'CONTROL_MANIFEST.json').read_bytes())
clock=Clock(manifest,os.environ['CONTROL_PIN'],os.environ['CONTROL_EPOCH'])
if inst(SESSION)!=manifest['root_instance']:raise ValueError('clock root before models')
clock.live();all_inputs()
def arrays(k):
 with np.load(io.BytesIO(read(k)),allow_pickle=False)as z:return {n:z[n].copy()for n in z.files}
ca=arrays('content');aa=arrays('actor');payload,artifact,raw=expected()
backend=PolicyBackend(ca,aa,FREEZE,{'completed_export_sha256':sha(read('complete')),'content_sha256':CFG['inputs']['content']['sha256'],'actor_full_sha256':CFG['inputs']['actor']['sha256']})
check('full_artifact_exact',canonical(backend.checkpoint_payload())==canonical(payload))
reader=FrameReader(int(sys.argv[2]))if role=='producer'else None
ackfd=int(sys.argv[3])if role=='producer'else None
budget=Budget(OUT,total_ns=2_000_000_000,byte_cap=16*2**20,rss_cap=256*2**20)
d=GuardedDelivery(backend,artifact,SESSION,budget,clock,reader)
limits={'CPU':resource.getrlimit(resource.RLIMIT_CPU),'AS':resource.getrlimit(resource.RLIMIT_AS),'FSIZE':resource.getrlimit(resource.RLIMIT_FSIZE)}
if role=='producer':
 write('REQUEST.json',raw,True);write('ARTIFACT.json',payload)
 a,g=d.start(raw,POLICY);a,record=d.publish(a,g,stop_after=2)
 oldroute=json.loads(read('old_route'));oldroute['artifact_sha256']=artifact;oldroute['request_identity_sha256']=sha(canonical(a.identity))
 check('real_route_and_wire_reference',a.route==oldroute and a.wire==read('old_wire'))
 check('ack2_before_external_cancel',a.phase=='generated'and a.next_index==2 and a.session.spent=={'controller':1,'generator':1,'output_bytes':8227})
 ready={'pid':os.getpid(),'freeze':FREEZE,'record':record,'artifact_sha256':artifact,'wire_sha256':sha(a.wire),'route_sha256':sha(canonical(a.route)),'root_instance':inst(SESSION),'lock_instance':inst(SESSION/'.hepta-writer.lock'),'checks':list(checks),'work':backend.work,'limits':limits}
 # Audit-only restore tested before any cancellation marker exists; no message sent yet.
 view,view_record=d.restore(record,raw,POLICY)
 write('READONLY_BEFORE.json',inventory())
 refused('readonly_await_before_cancel',lambda:d.await_cancel(view,view_record),'live-control recovered view is read-only')
 refused('readonly_replay_before_cancel',lambda:d.replay_control(view,view_record,clock.command()),'live-control recovered view is read-only')
 write('READONLY_AFTER.json',inventory())
 write('READY.json',ready)
 a,final=d.await_cancel(a,record)
 check('external_cancel_terminal',a.phase=='cancelled'and a.next_index==2 and a.session.spent['output_bytes']==8227)
 packet=d.control_ack;write('ACK_PACKET.json',packet)
 send_result=send(ackfd,packet,time.monotonic_ns()+2_000_000_000)
 check('one_call_no_training',backend.work['allocation_restores']==2 and backend.work['serving_calls']==backend.work['serving_actor_predictions']==1 and backend.work['optimizer_steps']==backend.work['reference_calls']==0)
 check('artifact_unchanged',canonical(backend.checkpoint_payload())==canonical(payload))
 # Duplicate acknowledgement remains idempotent, with persistent evidence.
 before=inventory();write('DUPLICATE_BEFORE.json',before)
 _,same=d.replay_control(a,final,clock.command());after=inventory();write('DUPLICATE_AFTER.json',after)
 check('duplicate_same_disposition_no_write',same==final and before==after)
 bad=clock.command();bad['sequence']=2
 refused('conflicting_duplicate',lambda:d.replay_control(a,final,bad),'control command identity/schema mismatch')
 write('PRODUCER_RESULT.json',{'checks':checks,'refusals':refusals,'work':backend.work,'delivery_work':d.work,'send_result':send_result,'limits':limits,'final':final})
 os.close(reader.fd);os.close(ackfd)
 while True:signal.pause()
ready=json.loads((FOLDER/'READY.json').read_bytes());packet=json.loads((FOLDER/'ACK_PACKET.json').read_bytes());handoff=json.loads((FOLDER/'HANDOFF.json').read_bytes())
verified=verify_ack(packet,ready,clock)
check('externally_pinned_ack',handoff['packet']==packet and handoff['root_instance']==verified['root_instance']and handoff['lock_instance']==verified['lock_instance'])
a,record=d.restore(ready['record'],raw,POLICY)
check('old_midpoint_load_only',a.phase=='generated'and a.next_index==2)
write('ROLLBACK_BEFORE.json',inventory())
refused('cancelled_frontier',lambda:d.publish(a,record),'namespace terminal, older acknowledgement may not advance')
write('ROLLBACK_AFTER.json',inventory())
check('no_new_inference',backend.work['allocation_restores']==2 and backend.work['serving_calls']==backend.work['serving_actor_predictions']==backend.work['optimizer_steps']==0)
check('preserved_two_tickets_prefix',a.session.spent=={'controller':1,'generator':1,'output_bytes':8227})
check('full_artifact_unchanged',canonical(backend.checkpoint_payload())==canonical(payload))
for name,model,original in [('CONTENT_AFTER.npz',backend.content,ca),('ACTOR_AFTER.npz',backend.actor,aa)]:
 data=model.to_arrays(include_optimizer=True)
 if set(data)!=set(original)or any(not np.array_equal(v,original[k])for k,v in data.items()):raise AssertionError('full arrays')
 b=io.BytesIO();np.savez(b,**data);write(name,b.getvalue(),True)
for mode in ('text','image'):write('FINAL-'+mode+'.part',a.session.prefix(mode),True)
all_inputs();check('original_inputs_unchanged',True)
work=backend.work;delivery_work=d.work;d.close()
write('RECOVERY_RESULT.json',{'checks':checks,'refusals':refusals,'work':work,'delivery_work':delivery_work,'limits':limits,'spent':a.session.spent})
