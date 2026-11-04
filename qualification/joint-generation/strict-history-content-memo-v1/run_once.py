import os,sys,json,resource,signal,time,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
resource.setrlimit(resource.RLIMIT_CPU,(6,6));resource.setrlimit(resource.RLIMIT_AS,(256*2**20,256*2**20));resource.setrlimit(resource.RLIMIT_FSIZE,(2*2**20,2*2**20));signal.alarm(60)
for n,h in json.loads((ROOT/'FREEZE.json').read_text()).items():
 if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h:raise ValueError('freeze')
OUT=ROOT/'RUN_ONCE';OUT.mkdir();start=time.monotonic()
def limit():
 resource.setrlimit(resource.RLIMIT_CPU,(4,4));signal.alarm(45);os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
with (OUT/'stdout').open('xb') as out,(OUT/'stderr').open('xb') as err:
 p=subprocess.Popen([sys.executable,'-I','-B',str(ROOT/'worker.py')],stdout=out,stderr=err,preexec_fn=limit)
 pid,status,u=os.wait4(p.pid,0);p.returncode=os.waitstatus_to_exitcode(status)
r={'complete_wait':True,'exit_code':p.returncode,'raw_wait_status':status,'whole_child_CPU_seconds':u.ru_utime+u.ru_stime,'user_CPU_seconds':u.ru_utime,'system_CPU_seconds':u.ru_stime,'wall_seconds':time.monotonic()-start,'max_rss_kib':u.ru_maxrss,'source_freeze_sha256':hashlib.sha256((ROOT/'FREEZE.json').read_bytes()).hexdigest(),'result_sha256':hashlib.sha256((OUT/'RESULT.json').read_bytes()).hexdigest() if (OUT/'RESULT.json').exists() else None,'automatic_retry':False,'outer_CPU_prefix_seconds':time.process_time(),'outer_final_tail':'unknown_nonzero','preparation_review_and_history':'additional_nonzero','scope':'stdlib fresh-bytes content memo only; NOT strict256 admission','limits':{'child_CPU_seconds':4,'outer_CPU_seconds':6,'AS_MiB':256,'file_MiB':2,'child_wall_alarm_seconds':45,'outer_wall_alarm_seconds':60}}
(OUT/'WAIT4_RECEIPT.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps(r));raise SystemExit(0 if p.returncode==0 else 1)
