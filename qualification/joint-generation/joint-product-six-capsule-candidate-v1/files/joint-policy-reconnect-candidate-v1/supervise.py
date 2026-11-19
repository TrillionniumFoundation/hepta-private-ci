import sys,os,json,time,signal,resource,fcntl
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from common import *
from owned_process import spawn,poll as child_poll,wait as child_wait,kill_owned,cleanup
from verify_midpoint import verify
from attempt import Attempt,parts
from content_input import convert
from route_contract import POLICY
lock=open(sys.argv[1],'rb');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def timeout(signum,frame):raise TimeoutError('supervisor wall deadline')
signal.signal(signal.SIGALRM,timeout) # inherited60s timer is not restarted after imports
FOLDER.mkdir();SESSION.mkdir();root_instance=inst(SESSION)
owned=[];receipts=[];events=[];error=None;complete=False

def launch(role):
 with(FOLDER/(role+'.stdout')).open('xb')as f,(FOLDER/(role+'.stderr')).open('xb')as e:
  return spawn([sys.executable,'-I','-B',str(ROOT/'worker.py'),role],f.fileno(),e.fileno(),role=role,alarm_seconds=30,env=os.environ.copy(),owned=owned,events=events)
def poll(p):return child_poll(p,receipts,events)
def wait(p):return child_wait(p,receipts,events)
try:
 all_inputs();p=launch('producer')
 while not(FOLDER/'READY.json').exists():
  if poll(p):raise ValueError('producer exited before READY')
  time.sleep(.01)
 ready=json.loads((FOLDER/'READY.json').read_bytes())
 if ready['pid']!=p.pid or ready['freeze']!=FREEZE:raise ValueError('producer PID/freeze')
 handoff=verify(ready,root_instance)
 events.append({'event':'midpoint_independently_verified','pid':p.pid,'monotonic_ns':time.monotonic_ns()})
 write('HANDOFF.json',handoff);events.append({'event':'handoff_persisted','pid':p.pid,'monotonic_ns':time.monotonic_ns()})
 if poll(p):raise ValueError('holder no longer live')
 kill_owned(p)
 if wait(p)!=-9:raise ValueError('producer ownkill')
 q=launch('recover')
 if wait(q)!=0:raise ValueError('recovery failed')
 result=json.loads((FOLDER/'RECOVERY_RESULT.json').read_bytes());payload,artifact,raw=expected();ref=result['final'];ns=handoff['namespace']
 if ref['namespace']!=ns or ref['name']!='piece-05-ack.json':raise ValueError('final fixedslot')
 path=SESSION/ns/ref['name']
 if file_ref(path)!={k:ref[k]for k in ('bytes','sha256')}:raise ValueError('final external pin')
 bound=convert(raw,expected_artifact_sha256=artifact,sequence=POLICY,now_ns=2)
 a=Attempt.load(path,raw_request=raw,sequence=POLICY,expected_spec=bound.run_spec,expected_file_sha256=ref['sha256'],now=2)
 wire=read('old_wire');expected_prefix={m:b''for m in ('text','image')}
 for mode,b in parts(wire):expected_prefix[mode]+=b
 if a.phase!='complete'or a.next_index!=6 or a.wire!=wire or sha(canonical(a.route))!=handoff['route_sha256']or a.session.spent!={'controller':1,'generator':1,'output_bytes':34808}:raise ValueError('complete state')
 if any(a.session.prefix(m)!=expected_prefix[m]or(FOLDER/('FINAL-'+m+'.part')).read_bytes()!=expected_prefix[m]for m in expected_prefix):raise ValueError('final exact prefixes')
 if (FOLDER/'FINAL_WIRE.json').read_bytes()!=wire or (FOLDER/'FINAL_ROUTE.json').read_bytes()!=canonical(a.route):raise ValueError('final wire/route')
 if inst(SESSION)!=root_instance or inst(SESSION/'.hepta-writer.lock')!=handoff['lock_instance']:raise ValueError('same root/lock')
 checks=len(ready['checks'])+len(result['checks']);refs=len(ready['refusals'])+len(result['refusals'])
 if checks!=17 or refs!=2 or result['new_output_bytes']!=26581 or result['remaining_pieces_published']!=4:raise ValueError('counts/output deltas')
 for v in (ready,result):
  if v['limits']!={'CPU':[2,2],'AS':[256*2**20]*2,'FSIZE':[2*2**20]*2}:raise ValueError('worker limits')
 all_inputs()
 out={'status':'PASS_ROUTE_PROCESS_RECONNECT_NO_INFERENCE_REPLAY','checks':checks,'refusals':refs,'producer_work':ready['work'],'recovery_work':result['work'],'new_model_restores':4,'new_selective_serving_calls':1,'new_Actor_predictions':1,'new_encoded_rows':1,'new_optimizer_steps':0,'events':events,'role_receipts':receipts,'source_freeze_sha256':FREEZE,'root_instance':root_instance,'lock_instance':handoff['lock_instance'],'handoff':handoff,'final_record':ref,'historical_reference':'V2 successful full route/output already paid; not fresh uninterrupted baseline','scope':'real process death after acked midpoint,2namespace refusals and saved remainder; literalclock/localprefix not remote client ack or owner auth; no new unknown model injection'}
 (OUT/'RESULT.json').write_bytes(canonical(out));complete=True
except BaseException as e:error=type(e).__name__+': '+str(e)
finally:
 signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(15)
 cleanup(owned,receipts,events)
 lock.close()
 with(OUT/'ROLE_RECEIPTS.json').open('xb')as f:f.write(canonical({'complete':complete,'error':error,'receipts':receipts,'events':events,'cleanup_boundary':'fork PID retained in shared preallocated ownership before unmask; exec failure tracked exit127; hard parent death/kernel stalls/cleanup/disk failure remain limits'}))
if error:print(error,file=sys.stderr)
raise SystemExit(0 if complete else 1)
