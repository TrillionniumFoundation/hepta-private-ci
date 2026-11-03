import sys,os,json,time,signal,fcntl
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from common import *
from owned_process import spawn,poll as child_poll,wait as child_wait,cleanup
from live_control import Clock
from verify_control import verify
from verify_fault import verify_fault
lock=open(sys.argv[1],'rb');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def timeout(signum,frame):raise TimeoutError('supervisor wall deadline')
signal.signal(signal.SIGALRM,timeout)
FOLDER.mkdir();SESSION.mkdir();root_instance=inst(SESSION)
owned=[];receipts=[];events=[];error=None;complete=False;fds=set();checks=[]
def check(n,v):
 if not v:raise AssertionError(n)
 checks.append(n)
def closefd(fd):
 if fd in fds:os.close(fd);fds.remove(fd)
def launch(role,passed=(),closed=()):
 with(FOLDER/(role+'.stdout')).open('xb')as f,(FOLDER/(role+'.stderr')).open('xb')as e:
  env=os.environ.copy();env['CONTROL_EPOCH']=manifest['run_epoch'];env['CONTROL_PIN']=pin
  return spawn([sys.executable,'-I','-B',str(ROOT/'worker.py'),role]+[str(x)for x in passed],f.fileno(),e.fileno(),role=role,alarm_seconds=30,env=env,owned=owned,events=events,pass_fds=passed,close_fds=closed)
def poll(p):return child_poll(p,receipts,events)
def wait(p):return child_wait(p,receipts,events)
try:
 all_inputs();origin=time.monotonic_ns();write('CLOCK.json',{'origin_ns':origin,'deadline_ns':origin+45_000_000_000});payload,artifact,raw=expected();r=json.loads(raw)
 manifest={'schema':'local-live-control-v1','run_epoch':os.urandom(16).hex(),'origin_ns':origin,'deadline_ns':r['deadline_ns'],'request_sha256':sha(raw),'artifact_sha256':artifact,'namespace':sha(canonical({'objective_id':r['objective_id'],'run_id':r['run_id']})),'source_freeze':FREEZE,'root_instance':root_instance};pin=sha(canonical(manifest));write('CONTROL_MANIFEST.json',manifest);clock=Clock(manifest,pin,manifest['run_epoch'])
 cr,cw=os.pipe();fds.update((cr,cw));p=launch('producer',(cr,),(cw,));closefd(cr)
 while not(FOLDER/'READY.json').exists():
  if poll(p):raise ValueError('producer failed before midpoint')
  time.sleep(.005)
 ready=json.loads((FOLDER/'READY.json').read_bytes())
 if ready['pid']!=p.pid or ready['freeze']!=FREEZE or ready['before_ref']!=file_ref(FOLDER/'FAULT_BEFORE.json'):raise ValueError('READY external pins')
 before=json.loads((FOLDER/'FAULT_BEFORE.json').read_bytes())
 midpoint=verify(ready,root_instance,clock);write('MIDPOINT_VERIFIED.json',midpoint)
 if before!=inventory():raise ValueError('before-close exact inventory')
 # No bytes written to this command pipe; child has no writer copy.
 close_begin=time.monotonic_ns();closefd(cw);close_complete=time.monotonic_ns()
 write('CLOSE_EVENT.json',{'close_begin_ns':close_begin,'close_complete_ns':close_complete,'sent_command_bytes':0,'scope':'local sole-writer close,not remote transport or cancel'})
 if wait(p)!=0:raise ValueError('producer unexpected fault outcome')
 events.append({'event':'producer_reaped_before_fault_verify','pid':p.pid,'monotonic_ns':time.monotonic_ns()})
 producer=json.loads((FOLDER/'PRODUCER_RESULT.json').read_bytes());summary=verify_fault(ready,manifest,clock,before)
 check('joint_fault_bound_known_result',summary['known_generator_result']is True and summary['confirmed_cancel']is False and summary['known_prefix_bytes']==8227 and summary['fault_ref']==producer['fault_ref'])
 check('close_observation_partial_order',close_begin<=close_complete and close_begin<=summary['fault']['observed_ns']<manifest['deadline_ns'])
 write('HANDOFF.json',summary)
 q=launch('recover')
 if wait(q)!=0:raise ValueError('recovery failed')
 recovery=json.loads((FOLDER/'RECOVERY_RESULT.json').read_bytes())
 check('specific_fault_refusal_while_live',recovery['refusals']==[{'name':'control_fault_recovery','error':'control effect unknown; supervisor disposition required'}]and recovery['live_after_ns']<manifest['deadline_ns']and recovery['work']['serving_calls']==0)
 for v in (producer,recovery):
  if v['limits']!={'CPU':[2,2],'AS':[256*2**20]*2,'FSIZE':[2*2**20]*2}:raise ValueError('worker limits')
 n=len(checks)+len(producer['checks'])+len(recovery['checks']);nf=len(producer['refusals'])+len(recovery['refusals']);ne=len(producer['failures'])
 if n!=20 or nf!=1 or ne!=1:raise ValueError('fixed counts')
 if producer['work']['allocation_restores']!=2 or recovery['work']['allocation_restores']!=2 or producer['work']['serving_calls']!=1:raise ValueError('work counts')
 all_inputs();out={'status':'PASS_REAL_PREFIX_ACTIVE_CHANNEL_EOF_FAIL_CLOSED','checks':n,'refusals':nf,'expected_active_control_failures':ne,'supervisor_checks':checks,'producer_work':producer['work'],'recovery_work':recovery['work'],'new_allocations':4,'new_inferences':1,'new_Adam':0,'events':events,'role_receipts':receipts,'source_freeze_sha256':FREEZE,'close_begin_ns':close_begin,'close_complete_ns':close_complete,'fault_observed_ns':summary['fault']['observed_ns'],'deadline_ns':manifest['deadline_ns'],'fault_ref':summary['fault_ref'],'known_prefix_bytes':8227,'scope':'known generated result and prefix,unknown control disposition;no cancel confirmed,no new inference on recovery;instrumented actual output boundary,not all disconnect cases'}
 (OUT/'RESULT.json').write_bytes(canonical(out));complete=True
except BaseException as e:error=type(e).__name__+': '+str(e)
finally:
 signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(15)
 for fd in list(fds):closefd(fd)
 cleanup(owned,receipts,events);lock.close()
 with(OUT/'ROLE_RECEIPTS.json').open('xb')as f:f.write(canonical({'complete':complete,'error':error,'receipts':receipts,'events':events,'cleanup_boundary':'own registered fork and sole-writer pipe closure;hard ancestor/kernel/storage failure outside guarantee'}))
if error:print(error,file=sys.stderr)
raise SystemExit(0 if complete else 1)
