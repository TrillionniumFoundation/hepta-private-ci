import os,sys,json,time,resource,subprocess,signal,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
# Enforce OUTER self-limit too; descendants inherit without hard-limit elevation.
for r,n in [(resource.RLIMIT_CPU,5),(resource.RLIMIT_AS,256*2**20),(resource.RLIMIT_FSIZE,2*2**20)]:resource.setrlimit(r,(n,n))
def deadline(signum,frame):raise TimeoutError('outer wall deadline')
signal.signal(signal.SIGALRM,deadline);signal.alarm(75)
if len(sys.argv)!=2:raise ValueError('existing benchmark lock required')
lock=Path(sys.argv[1]).resolve(strict=True)
for n,h in json.loads((ROOT/'FREEZE.json').read_bytes()).items():
 if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h:raise ValueError('freeze')
OUT=ROOT/'RUN_ONCE';OUT.mkdir();start=time.monotonic()
def limits():
 signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(45);os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
 for r,n in [(resource.RLIMIT_CPU,5),(resource.RLIMIT_AS,256*2**20),(resource.RLIMIT_FSIZE,2*2**20)]:resource.setrlimit(r,(n,n))
env=os.environ.copy()
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):env[k]='1'
p=None;pid=None;u=None;error=None;reaped=False
children_before=resource.getrusage(resource.RUSAGE_CHILDREN)
def poll_own():
 global pid,status,u,reaped
 # Never block wait4 with alarm masked. Commit ownership bookkeeping before
 # unmasking a pending deadline, so a reaped/reused numeric PID is not killed.
 previous=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGALRM})
 try:
  got,st,usage=os.wait4(p.pid,os.WNOHANG)
  if got:
   pid,status,u=got,st,usage;p.returncode=os.waitstatus_to_exitcode(st);reaped=True
  return bool(got)
 finally:signal.pthread_sigmask(signal.SIG_SETMASK,previous)
try:
 with (OUT/'supervisor.stdout').open('xb')as f,(OUT/'supervisor.stderr').open('xb')as e:
  p=subprocess.Popen([sys.executable,'-I','-B',str(ROOT/'qualify.py'),str(lock)],stdout=f,stderr=e,preexec_fn=limits,env=env)
  while not poll_own():time.sleep(.01)
except BaseException as e:
 error=type(e).__name__+': '+str(e)
 # Own unreaped Popen only. Reserve bounded cleanup wall time, never retry.
 signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(15)
 if p is not None and not reaped:
  try:os.kill(p.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  pid,status,u=os.wait4(p.pid,0);reaped=True;p.returncode=os.waitstatus_to_exitcode(status)
children_after=resource.getrusage(resource.RUSAGE_CHILDREN)
whole=(u.ru_utime+u.ru_stime)if u is not None else ((children_after.ru_utime-children_before.ru_utime)+(children_after.ru_stime-children_before.ru_stime))
rss=u.ru_maxrss if u is not None else children_after.ru_maxrss
r={'outer_limits':{'CPU':resource.getrlimit(resource.RLIMIT_CPU),'AS':resource.getrlimit(resource.RLIMIT_AS),'FSIZE':resource.getrlimit(resource.RLIMIT_FSIZE)},'complete_wait':reaped,'pid':pid,'exit_code':p.returncode if p is not None else None,'runner_error':error,'wall_limits_seconds':{'child':45,'outer_initial':75,'handled_failure_cleanup':15},'failure_boundary':'handled exceptions after successful Popen attempt own-child kill/reap; outer hard kill/cleanup or disk failure may prevent receipts; failed spawn may have internally reaped work without individual PID receipt','source_freeze_sha256':hashlib.sha256((ROOT/'FREEZE.json').read_bytes()).hexdigest(),'whole_reaped_subtree_CPU_seconds':whole,'largest_reaped_process_RSS_kib':rss,'wall_seconds':time.monotonic()-start,'retry':False,'outer_tail':'unknown_not_zero','inventory':{str(x.relative_to(OUT)):{'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()}for x in sorted(OUT.rglob('*'))if x.is_file()}}
r['automatic_next_run_authorized']=False
r['outer_prefix_CPU_seconds']=time.process_time();r['known_CPU_lower_bound_seconds']=whole+r['outer_prefix_CPU_seconds'];r['final_retained_bytes']=0;r['terminal_budget_pass']=False
base=sum(v['bytes']for v in r['inventory'].values());ok=reaped and error is None and p.returncode==0 and whole<=5 and rss*1024<=256*2**20 and len(r['inventory'])+1<=100 and all(v['bytes']<=2*2**20 for v in r['inventory'].values())
for _ in range(20):
 raw=json.dumps(r,indent=2,sort_keys=True).encode()+b'\n';size=base+len(raw);passed=ok and size<=16*2**20 and len(raw)<=65536
 if r['final_retained_bytes']==size and r['terminal_budget_pass']==passed:break
 r['final_retained_bytes']=size;r['terminal_budget_pass']=passed
else:raise ValueError('fixed point')
(OUT/'OUTER_WAIT4_RECEIPT.json').write_bytes(raw)
if sum(x.stat().st_size for x in OUT.rglob('*')if x.is_file())!=size:raise ValueError('retained')
print(json.dumps({k:r[k]for k in ['exit_code','terminal_budget_pass','whole_reaped_subtree_CPU_seconds','final_retained_bytes']}))
raise SystemExit(0 if passed else 1)
