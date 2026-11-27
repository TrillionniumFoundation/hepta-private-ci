import os,sys,json,time,resource,signal,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from owned_process import spawn,wait,cleanup
# Enforce OUTER self-limit too; descendants inherit without hard-limit elevation.
for r,n in [(resource.RLIMIT_CPU,2),(resource.RLIMIT_AS,256*2**20),(resource.RLIMIT_FSIZE,2*2**20)]:resource.setrlimit(r,(n,n))
def deadline(signum,frame):raise TimeoutError('outer wall deadline')
signal.signal(signal.SIGALRM,deadline);signal.alarm(90)
if len(sys.argv)!=2:raise ValueError('existing benchmark lock required')
lock=Path(sys.argv[1]).resolve(strict=True)
for n,h in json.loads((ROOT/'FREEZE.json').read_bytes()).items():
 if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h:raise ValueError('freeze')
OUT=ROOT/'RUN_ONCE';OUT.mkdir();start=time.monotonic()
os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
env=os.environ.copy()
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):env[k]='1'
p=None;pid=None;u=None;error=None;reaped=False;owned=[];process_receipts=[];events=[]
children_before=resource.getrusage(resource.RUSAGE_CHILDREN)
try:
 with (OUT/'supervisor.stdout').open('xb')as f,(OUT/'supervisor.stderr').open('xb')as e:
  p=spawn([sys.executable,'-I','-B',str(ROOT/'supervise.py'),str(lock)],f.fileno(),e.fileno(),role='supervisor',alarm_seconds=60,env=env,owned=owned,events=events)
  wait(p,process_receipts,events)
except BaseException as e:
 error=type(e).__name__+': '+str(e)
 signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(15)
 cleanup(owned,process_receipts,events)
if owned and owned[0].pid is not None:p=owned[0];pid=p.pid;u=p.usage;reaped=p.reaped
children_after=resource.getrusage(resource.RUSAGE_CHILDREN)
whole=(u.ru_utime+u.ru_stime)if u is not None else ((children_after.ru_utime-children_before.ru_utime)+(children_after.ru_stime-children_before.ru_stime))
rss=u.ru_maxrss if u is not None else children_after.ru_maxrss
r={'outer_limits':{'CPU':resource.getrlimit(resource.RLIMIT_CPU),'AS':resource.getrlimit(resource.RLIMIT_AS),'FSIZE':resource.getrlimit(resource.RLIMIT_FSIZE)},'complete_wait':reaped,'pid':pid,'exit_code':p.returncode if p is not None else None,'runner_error':error,'outer_owned_events':events,'outer_process_receipts':process_receipts,'wall_limits_seconds':{'supervisor':60,'workers':30,'outer_initial':90,'handled_failure_cleanup':15},'failure_boundary':'SIGALRM deferred until shared fork ownership registered, even if spawn never returns to caller; exec failure tracked exit127. Hard parent death/kernel stalls/cleanup or disk failure may still prevent descendant receipts/cost' ,'source_freeze_sha256':hashlib.sha256((ROOT/'FREEZE.json').read_bytes()).hexdigest(),'whole_reaped_subtree_CPU_seconds':whole,'largest_reaped_process_RSS_kib':rss,'wall_seconds':time.monotonic()-start,'retry':False,'outer_tail':'unknown_not_zero','inventory':{str(x.relative_to(OUT)):{'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()}for x in sorted(OUT.rglob('*'))if x.is_file()}}
roles=json.loads((OUT/'ROLE_RECEIPTS.json').read_bytes())if(OUT/'ROLE_RECEIPTS.json').exists()else{}
r['role_receipts_complete']=roles.get('complete')is True and len(roles.get('receipts',[]))==2
r['sum_worker_CPU_seconds']=sum(v['CPU_seconds']for v in roles.get('receipts',[]))
r['complete_supervisor_CPU_seconds']=whole-r['sum_worker_CPU_seconds']if r['role_receipts_complete']else None
r['automatic_next_run_authorized']=False
r['outer_prefix_CPU_seconds']=time.process_time();r['known_CPU_lower_bound_seconds']=whole+r['outer_prefix_CPU_seconds'];r['final_retained_bytes']=0;r['terminal_budget_pass']=False
base=sum(v['bytes']for v in r['inventory'].values());ok=reaped and error is None and p.returncode==0 and r['role_receipts_complete']and r['complete_supervisor_CPU_seconds']>=-1e-9 and whole<=5 and rss*1024<=256*2**20 and len(r['inventory'])+1<=100 and all(v['bytes']<=2*2**20 for v in r['inventory'].values())
for _ in range(20):
 raw=json.dumps(r,indent=2,sort_keys=True).encode()+b'\n';size=base+len(raw);passed=ok and size<=16*2**20 and len(raw)<=65536
 if r['final_retained_bytes']==size and r['terminal_budget_pass']==passed:break
 r['final_retained_bytes']=size;r['terminal_budget_pass']=passed
else:raise ValueError('fixed point')
(OUT/'OUTER_WAIT4_RECEIPT.json').write_bytes(raw)
if sum(x.stat().st_size for x in OUT.rglob('*')if x.is_file())!=size:raise ValueError('retained')
print(json.dumps({k:r[k]for k in ['exit_code','terminal_budget_pass','whole_reaped_subtree_CPU_seconds','final_retained_bytes']}))
raise SystemExit(0 if passed else 1)
