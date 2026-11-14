import sys,os,json,time,signal,fcntl,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from common import *
from owned_process import spawn,poll as child_poll,wait as child_wait,cleanup
from control_channel import send
from live_control import Clock
from verify_expired import verify,verify_records,expected_identity,read_records
lock=open(sys.argv[1],'rb');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def timeout(signum,frame):raise TimeoutError('supervisor wall deadline')
signal.signal(signal.SIGALRM,timeout)
FOLDER.mkdir();SESSION.mkdir();root_instance=inst(SESSION)
owned=[];receipts=[];events=[];error=None;complete=False;fds=set();checks=[];refusals=[]
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
 all_inputs();origin=time.monotonic_ns();write('CLOCK.json',{'origin_ns':origin,'deadline_ns':origin+3_000_000_000})
 payload,artifact,raw=expected();r=json.loads(raw)
 manifest={'schema':'local-live-control-v1','run_epoch':os.urandom(16).hex(),'origin_ns':origin,'deadline_ns':r['deadline_ns'],'request_sha256':sha(raw),'artifact_sha256':artifact,'namespace':sha(canonical({'objective_id':r['objective_id'],'run_id':r['run_id']})),'source_freeze':FREEZE,'root_instance':root_instance};pin=sha(canonical(manifest));write('CONTROL_MANIFEST.json',manifest)
 cr,cw=os.pipe();fds.update((cr,cw));p=launch('producer',(cr,),(cw,));closefd(cr)
 while not(FOLDER/'RETURN_READY.json').exists():
  if poll(p):raise ValueError('producer failed before original model returned')
  time.sleep(.005)
 diag=json.loads((FOLDER/'RETURN_READY.json').read_bytes())
 identity=expected_identity(raw,payload,FREEZE)
 for key,name in [('wire_ref','RETURN_WIRE.json'),('route_ref','RETURN_ROUTE.json')]:
  ref=diag[key]
  if ref!={'name':name,**file_ref(FOLDER/name)}:raise ValueError('diagnostic exact ref')
 expected_route=json.loads(read('old_route'));expected_route['artifact_sha256']=artifact;expected_route['request_identity_sha256']=sha(canonical(identity))
 check('computed_identity_before_deadline',diag['pid']==p.pid and diag['freeze']==FREEZE and diag['manifest_sha256']==pin and diag['identity']==identity and diag['root_instance']==root_instance and diag['lock_instance']==inst(SESSION/'.hepta-writer.lock')and origin<=diag['computed_ns']<manifest['deadline_ns']and diag['deadline_ns']==manifest['deadline_ns'])
 check('known_original_result_exact', (FOLDER/'RETURN_WIRE.json').read_bytes()==read('old_wire')and(FOLDER/'RETURN_ROUTE.json').read_bytes()==canonical(expected_route))
 write('RETURN_VERIFIED.json',{'diagnostic_ref':file_ref(FOLDER/'RETURN_READY.json'),'verified_ns':time.monotonic_ns(),'computed_ns':diag['computed_ns'],'deadline_ns':manifest['deadline_ns']})
 while time.monotonic_ns()<manifest['deadline_ns']+20_000_000:
  if poll(p):raise ValueError('producer exited before release')
  time.sleep(.005)
 release={'schema':'deadline-release-v1','manifest_sha256':pin,'request_sha256':manifest['request_sha256'],'diagnostic_sha256':file_ref(FOLDER/'RETURN_READY.json')['sha256'],'deadline_ns':manifest['deadline_ns']}
 sent=send(cw,release,time.monotonic_ns()+1_000_000_000);write('RELEASE_SENT.json',{'message':release,**sent});closefd(cw)
 if wait(p)!=0:raise ValueError('producer terminal failure')
 events.append({'event':'producer_reaped_before_terminal_verify','pid':p.pid,'monotonic_ns':time.monotonic_ns()})
 producer=json.loads((FOLDER/'PRODUCER_RESULT.json').read_bytes());packet=json.loads((FOLDER/'DEADLINE_PACKET.json').read_bytes());returned=json.loads((FOLDER/'RETURN_RELEASED.json').read_bytes())
 check('release_return_past_original_deadline',sent['send_begin_ns']>=manifest['deadline_ns']+20_000_000 and returned['release']==release and returned['observed_ns']>=sent['send_begin_ns'] and returned['return_ns']>=returned['observed_ns'])
 final=verify(manifest,pin,manifest['run_epoch'],raw,payload,FREEZE,SESSION,packet,read('old_wire'),json.loads(read('old_route')));write('TERMINAL_VERIFIED.json',final)
 check('terminal_known_cancel_zero_output',final['phase']=='cancelled'and final['output_bytes']==0)
 # Detach all input evidence for semantic negatives; no original journal rewrites.
 records=read_records(SESSION,manifest['namespace'])
 def negative(name,m,pp,rr,expected_error):
  before=inventory();write(name+'-BEFORE.json',before)
  write(name+'-INPUT.json',{'manifest':m,'packet':pp,'records':{k:v.hex()for k,v in rr.items()}})
  try:verify_records(m,sha(canonical(m)),manifest['run_epoch'],raw,payload,FREEZE,root_instance,pp,rr,read('old_wire'),json.loads(read('old_route')))
  except ValueError as e:
   if str(e)!=expected_error:raise
   refusals.append({'name':name,'error':str(e)})
  else:raise AssertionError(name)
  after=inventory();write(name+'-AFTER.json',after);check(name+'_original_inventory_unchanged',before==after)
 def rebind_observation(rr,pp):
  ob=rr['control-observed.json'];pp['ack']['observed_record'].update(bytes=len(ob),sha256=sha(ob));rr['control-ack.json']=canonical(pp['ack']);pp['ack_record'].update(bytes=len(rr['control-ack.json']),sha256=sha(rr['control-ack.json']))
 rr=dict(records);pp=copy.deepcopy(packet);ob=json.loads(rr['control-observed.json']);ob['message']['reason']='user_cancel';rr['control-observed.json']=canonical(ob);pp['ack']['command_sha256']=sha(canonical(ob['message']));rebind_observation(rr,pp)
 negative('WRONG_REASON',manifest,pp,rr,'deadline command binding')
 m=copy.deepcopy(manifest);m['deadline_ns']+=1_000_000_000
 negative('RENEWED_DEADLINE',m,copy.deepcopy(packet),dict(records),'manifest request/source/root binding')
 rr=dict(records);pp=copy.deepcopy(packet);ob=json.loads(rr['control-observed.json']);ob['prior_record']['sha256']='0'*64;rr['control-observed.json']=canonical(ob);rebind_observation(rr,pp)
 negative('BAD_GENERATED_REF',manifest,pp,rr,'generated record binding')
 q=launch('recover')
 if wait(q)!=0:raise ValueError('expired recovery failed')
 recovery=json.loads((FOLDER/'RECOVERY_RESULT.json').read_bytes())
 for v in (producer,recovery):
  if v['limits']!={'CPU':[2,2],'AS':[256*2**20]*2,'FSIZE':[2*2**20]*2}:raise ValueError('worker limits')
 if producer['work']['allocation_restores']!=2 or producer['work']['serving_calls']!=1 or recovery['allocation_restores']!=0 or recovery['serving_calls']!=0:raise ValueError('work counts')
 n=len(checks)+len(producer['checks'])+len(recovery['checks']);nf=len(refusals)+len(recovery['refusals'])
 if n!=17 or nf!=4:raise ValueError('frozen counts')
 all_inputs();out={'status':'PASS_REAL_RESULT_DELAYED_RETURN_DEADLINE_CANCEL','checks':n,'refusals':nf,'supervisor_checks':checks,'supervisor_refusals':refusals,'producer_work':producer['work'],'recovery_work':{k:recovery[k]for k in ('allocation_restores','serving_calls','optimizer_steps')},'new_Adam':0,'new_allocations':2,'new_inferences':1,'events':events,'role_receipts':receipts,'deadline_ns':manifest['deadline_ns'],'computed_ns':diag['computed_ns'],'release':sent,'return_observed_ns':returned['observed_ns'],'return_sample_ns':returned['return_ns'],'source_freeze_sha256':FREEZE,'scope':'delayed return after actual math,not natural slow compute/preemption; expired recovery refuses before models; old refs are saved controls,no new references'}
 (OUT/'RESULT.json').write_bytes(canonical(out));complete=True
except BaseException as e:error=type(e).__name__+': '+str(e)
finally:
 signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(15)
 for fd in list(fds):closefd(fd)
 cleanup(owned,receipts,events);lock.close()
 with(OUT/'ROLE_RECEIPTS.json').open('xb')as f:f.write(canonical({'complete':complete,'error':error,'receipts':receipts,'events':events,'cleanup_boundary':'registered own fork and explicit pipe ends; hard ancestor death/kernel/storage remain limits'}))
if error:print(error,file=sys.stderr)
raise SystemExit(0 if complete else 1)
