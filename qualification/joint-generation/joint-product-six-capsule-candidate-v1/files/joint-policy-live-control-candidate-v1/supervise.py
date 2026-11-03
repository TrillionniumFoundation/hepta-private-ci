import sys,os,json,time,signal,resource,fcntl,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from common import *
from owned_process import spawn,poll as child_poll,wait as child_wait,kill_owned,cleanup
from verify_control import verify,verify_ack
from control_channel import FrameReader,send
from live_control import Clock
from qualify_controls import qualify
lock=open(sys.argv[1],'rb');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def timeout(signum,frame):raise TimeoutError('supervisor wall deadline')
signal.signal(signal.SIGALRM,timeout)
FOLDER.mkdir();SESSION.mkdir();root_instance=inst(SESSION)
owned=[];receipts=[];events=[];error=None;complete=False;fds=set()
def closefd(fd):
 if fd in fds:os.close(fd);fds.remove(fd)
def launch(role,passed=(),closed=()):
 with(FOLDER/(role+'.stdout')).open('xb')as f,(FOLDER/(role+'.stderr')).open('xb')as e:
  args=[sys.executable,'-I','-B',str(ROOT/'worker.py'),role]+[str(x)for x in passed]
  env=os.environ.copy();env['CONTROL_EPOCH']=manifest['run_epoch'];env['CONTROL_PIN']=clock.pin
  return spawn(args,f.fileno(),e.fileno(),role=role,alarm_seconds=30,env=env,owned=owned,events=events,pass_fds=passed,close_fds=closed)
def poll(p):return child_poll(p,receipts,events)
def wait(p):return child_wait(p,receipts,events)
def until(path,p):
 while not path.exists():
  if poll(p):raise ValueError('producer exited before checkpoint')
  time.sleep(.005)
try:
 all_inputs();origin=time.monotonic_ns();write('CLOCK.json',{'origin_ns':origin,'deadline_ns':origin+45_000_000_000})
 payload,artifact,raw=expected();r=json.loads(raw)
 manifest={'schema':'local-live-control-v1','run_epoch':os.urandom(16).hex(),'origin_ns':origin,'deadline_ns':r['deadline_ns'],'request_sha256':sha(raw),'artifact_sha256':artifact,'namespace':sha(canonical({'objective_id':r['objective_id'],'run_id':r['run_id']})),'source_freeze':FREEZE,'root_instance':root_instance}
 write('CONTROL_MANIFEST.json',manifest);clock=Clock(manifest,sha(canonical(manifest)),manifest['run_epoch'])
 controls=qualify(clock);write('CONTROL_NEGATIVES.json',controls)
 cr,cw=os.pipe();ar,aw=os.pipe();fds.update((cr,cw,ar,aw))
 p=launch('producer',(cr,aw),(cw,ar));closefd(cr);closefd(aw)
 until(FOLDER/'READY.json',p);ready=json.loads((FOLDER/'READY.json').read_bytes())
 if ready['pid']!=p.pid or ready['freeze']!=FREEZE:raise ValueError('producer PID/freeze')
 midpoint=verify(ready,root_instance,clock);write('MIDPOINT_VERIFIED.json',midpoint)
 events.append({'event':'midpoint_verified','pid':p.pid,'monotonic_ns':time.monotonic_ns()})
 command=clock.command();sent=send(cw,command,min(manifest['deadline_ns'],time.monotonic_ns()+2_000_000_000));write('COMMAND_SENT.json',{'command':command,**sent})
 packet=FrameReader(ar).read(min(manifest['deadline_ns'],time.monotonic_ns()+5_000_000_000));received=time.monotonic_ns()
 verification=verify_ack(packet,ready,clock)
 if not sent['send_begin_ns']<=packet['ack']['observed_ns']<=packet['ack']['intent_return_ns']<=packet['ack']['ack_pre_send_ns']<=received or not sent['send_begin_ns']<=sent['write_complete_ns']<=received:raise ValueError('causal timestamp partial order')
 write('ACK_RECEIVED.json',{'packet':packet,'received_ns':received});write('HANDOFF.json',verification)
 events.append({'event':'cancel_ack_verified','pid':p.pid,'monotonic_ns':time.monotonic_ns()})
 until(FOLDER/'PRODUCER_RESULT.json',p)
 producer=json.loads((FOLDER/'PRODUCER_RESULT.json').read_bytes())
 # Corrupt only a detached acknowledgement pin, never the original records.
 bad=copy.deepcopy(packet);bad['ack_record']['sha256']='0'*64;write('BAD_ACK.json',bad);before=inventory();write('BAD_ACK_BEFORE.json',before)
 try:verify_ack(bad,ready,clock)
 except ValueError as e:bad_error=str(e)
 else:raise AssertionError('corrupt ACK accepted')
 if bad_error!='ACK ref mismatch' or before!=inventory():raise ValueError('bad ACK refusal reason/state')
 write('BAD_ACK_AFTER.json',inventory())
 closefd(cw);closefd(ar)
 if poll(p):raise ValueError('producer not live before kill')
 kill_owned(p)
 if wait(p)!=-9:raise ValueError('producer ownkill')
 q=launch('recover')
 if wait(q)!=0:raise ValueError('recovery failed')
 result=json.loads((FOLDER/'RECOVERY_RESULT.json').read_bytes());finalverify=verify_ack(packet,ready,clock)
 if finalverify['known_prefix_bytes']!=8227 or (SESSION/manifest['namespace']/'piece-02-intent.json').exists():raise ValueError('cancel advanced')
 for v in (producer,result):
  if v['limits']!={'CPU':[2,2],'AS':[256*2**20]*2,'FSIZE':[2*2**20]*2}:raise ValueError('worker limits')
 if producer['work']['allocation_restores']!=2 or result['work']['allocation_restores']!=2 or result['work']['serving_calls']!=0:raise ValueError('work')
 checks=len(producer['checks'])+len(result['checks'])+len(controls['checks'])+2
 refs=len(producer['refusals'])+len(result['refusals'])+len(controls['refusals'])+1
 if checks!=22 or refs!=14:raise ValueError('frozen counts')
 all_inputs()
 out={'status':'PASS_LOCAL_ASYNC_CANCEL_BOUNDARY','checks':checks,'refusals':refs,'producer_work':producer['work'],'recovery_work':result['work'],'new_model_restores':4,'new_selective_serving_calls':1,'new_Actor_predictions':1,'new_encoded_rows':1,'new_optimizer_steps':0,'events':events,'role_receipts':receipts,'source_freeze_sha256':FREEZE,'root_instance':root_instance,'manifest_sha256':clock.pin,'clock_epoch':manifest['run_epoch'],'bad_ack_error':bad_error,'control_negative_checks':controls,'partial_order':{'send':sent,'observed_ns':packet['ack']['observed_ns'],'intent_return_ns':packet['ack']['intent_return_ns'],'ack_pre_send_ns':packet['ack']['ack_pre_send_ns'],'ack_received_ns':received},'scope':'one instrumented safe-boundary asynchronous local cancellation; not production owner auth, remote client ACK, hard realtime or actual reboot; no kernel preemption'}
 (OUT/'RESULT.json').write_bytes(canonical(out));complete=True
except BaseException as e:error=type(e).__name__+': '+str(e)
finally:
 signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(15)
 for fd in list(fds):closefd(fd)
 cleanup(owned,receipts,events);lock.close()
 with(OUT/'ROLE_RECEIPTS.json').open('xb')as f:f.write(canonical({'complete':complete,'error':error,'receipts':receipts,'events':events,'cleanup_boundary':'owned fork registration, explicit pipe end closure; hard ancestor/kernel/storage failures remain outside guarantee'}))
if error:print(error,file=sys.stderr)
raise SystemExit(0 if complete else 1)
