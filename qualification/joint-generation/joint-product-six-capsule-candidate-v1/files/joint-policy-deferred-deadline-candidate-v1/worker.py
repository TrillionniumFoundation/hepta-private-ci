import sys,os,json,time,io,resource
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from common import *
from live_control import Clock
from control_channel import FrameReader
from contracts import ContractError
role=sys.argv[1]
if role not in ('producer','recover'):raise ValueError('fixed role')
checks=[];refusals=[]
def check(name,ok):
 if not ok:raise AssertionError(name)
 checks.append(name)
manifest=json.loads((FOLDER/'CONTROL_MANIFEST.json').read_bytes());clock=Clock(manifest,os.environ['CONTROL_PIN'],os.environ['CONTROL_EPOCH'])
if inst(SESSION)!=manifest['root_instance']:raise ValueError('root epoch before any model')
limits={'CPU':resource.getrlimit(resource.RLIMIT_CPU),'AS':resource.getrlimit(resource.RLIMIT_AS),'FSIZE':resource.getrlimit(resource.RLIMIT_FSIZE)}
if role=='recover':
 before=inventory();write('RECOVER_BEFORE.json',before)
 try:clock.live()
 except ContractError as e:
  check('exact_expiry_before_model',str(e)=='live deadline expired');refusals.append({'name':'expired_recovery','error':str(e)})
 else:raise AssertionError('expired epoch renewed')
 after=inventory();write('RECOVER_AFTER.json',after)
 check('expiry_no_write',before==after)
 check('original_deadline_unchanged',manifest==json.loads((FOLDER/'CONTROL_MANIFEST.json').read_bytes()))
 write('RECOVERY_RESULT.json',{'checks':checks,'refusals':refusals,'allocation_restores':0,'serving_calls':0,'optimizer_steps':0,'limits':limits,'observed_ns':clock.last,'deadline_ns':manifest['deadline_ns'],'scope':'expired live refusal before backend imports/construction,not cancelled-frontier test'})
 raise SystemExit(0)
clock.live();all_inputs()
import numpy as np
from policy_backend import PolicyBackend
from live_delivery import GuardedDelivery
from route_contract import POLICY
from cost import Budget
releasefd=int(sys.argv[2]);reader=FrameReader(releasefd)
class DelayedBackend(PolicyBackend):
 def serve_bound(self,pixels,sequence,identity):
  wire,route=super().serve_bound(pixels,sequence,identity)
  computed=time.monotonic_ns()
  if computed>=manifest['deadline_ns']:raise ValueError('fixed computed-before-deadline precondition failed')
  wr=write('RETURN_WIRE.json',wire,True);rr=write('RETURN_ROUTE.json',route)
  diag={'schema':'known-compute-return-v1','pid':os.getpid(),'freeze':FREEZE,'manifest_sha256':clock.pin,'identity':identity,'computed_ns':computed,'deadline_ns':manifest['deadline_ns'],'wire_ref':wr,'route_ref':rr,'work':self.work,'root_instance':inst(SESSION),'lock_instance':inst(SESSION/'.hepta-writer.lock')}
  dr=write('RETURN_READY.json',diag)
  message=reader.read(computed+6_000_000_000)
  expected={'schema':'deadline-release-v1','manifest_sha256':clock.pin,'request_sha256':manifest['request_sha256'],'diagnostic_sha256':dr['sha256'],'deadline_ns':manifest['deadline_ns']}
  if canonical(message)!=canonical(expected):raise ValueError('release binding')
  observed=time.monotonic_ns()
  if observed<manifest['deadline_ns']:raise ValueError('release before original deadline')
  os.close(releasefd)
  write('RETURN_RELEASED.json',{'observed_ns':observed,'return_ns':time.monotonic_ns(),'release':message,'scope':'delayed original return,not delayed mathematical computation'})
  return wire,route

def arrays(k):
 with np.load(io.BytesIO(read(k)),allow_pickle=False)as z:return {n:z[n].copy()for n in z.files}
ca=arrays('content');aa=arrays('actor');payload,artifact,raw=expected()
backend=DelayedBackend(ca,aa,FREEZE,{'completed_export_sha256':sha(read('complete')),'content_sha256':CFG['inputs']['content']['sha256'],'actor_full_sha256':CFG['inputs']['actor']['sha256']})
check('artifact_exact',canonical(backend.checkpoint_payload())==canonical(payload))
budget=Budget(OUT,total_ns=2_000_000_000,byte_cap=16*2**20,rss_cap=256*2**20)
d=GuardedDelivery(backend,artifact,SESSION,budget,clock,None)
write('REQUEST.json',raw,True);write('ARTIFACT.json',payload)
a,final=d.start(raw,POLICY)
check('late_return_deadline_cancel',a.phase=='cancelled'and a.next_index==0 and clock.last>=manifest['deadline_ns'])
oldroute=json.loads(read('old_route'));oldroute['artifact_sha256']=artifact;oldroute['request_identity_sha256']=sha(canonical(a.identity))
check('known_wire_route_exact',a.wire==read('old_wire')and a.route==oldroute)
check('two_tickets_zero_prefix',a.session.spent=={'controller':1,'generator':1,'output_bytes':0}and all(a.session.prefix(x)==b''for x in ('text','image')))
check('returned_bytes_charged',d.work['generator_attempts']==1 and d.work['generated_wire_bytes']==len(a.wire)and d.work['published_local_bytes']==0)
check('models_unchanged',canonical(backend.checkpoint_payload())==canonical(payload))
for name,model,original in [('CONTENT_AFTER.npz',backend.content,ca),('ACTOR_AFTER.npz',backend.actor,aa)]:
 data=model.to_arrays(include_optimizer=True)
 if set(data)!=set(original)or any(not np.array_equal(v,original[k])for k,v in data.items()):raise AssertionError('full arrays')
 b=io.BytesIO();np.savez(b,**data);write(name,b.getvalue(),True)
packet=d.control_ack;write('DEADLINE_PACKET.json',packet)
all_inputs();check('inputs_unchanged',True)
work=backend.work;delivery=d.work;d.close()
write('PRODUCER_RESULT.json',{'checks':checks,'refusals':refusals,'work':work,'delivery_work':delivery,'limits':limits,'packet':packet,'final':final,'request_deadline_ns':manifest['deadline_ns']})
