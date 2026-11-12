from pathlib import Path
from datetime import datetime,timezone
import gzip,hashlib,json,os,subprocess,sys
repo=Path('/home/qian-qi/hepta-learn-caller-20261112-037c-726af8f4')
records=Path('/home/qian-qi/hepta-learn-037c-evidence/source-726af8f4a345-v1')
source='726af8f4a345a2ffb148b971f3fa16c71436862d'
tree='04c2cd46be5833568491ae02ca299f16ef622f7d'
key='learn-037c-source-726af8f4a345-v1'
records.mkdir(mode=0o700,exist_ok=False)
def now(): return datetime.now(timezone.utc).isoformat()
def save(n,v):
 with (records/n).open('x') as f: json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
def git(*a): return subprocess.check_output(['git','--no-optional-locks',*a],cwd=repo)
def snapshot(label):
 rows=[]
 for raw in sorted(set((git('ls-files','-z')+git('ls-files','--others','--exclude-standard','-z')).split(b'\0'))-{b''}):
  rel=os.fsdecode(raw);p=repo/rel
  if not p.exists() and not p.is_symlink(): rows.append({'path':rel,'missing':True});continue
  data=os.fsencode(os.readlink(p)) if p.is_symlink() else p.read_bytes()
  rows.append({'path':rel,'mode':'120000' if p.is_symlink() else ('100755' if p.stat().st_mode&0o111 else '100644'),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
 encoded=json.dumps(rows,sort_keys=True,separators=(',',':')).encode()
 with gzip.open(records/(label+'.files.json.gz'),'xb') as f: f.write(encoded)
 v={'commit':git('rev-parse','HEAD').decode().strip(),'tree':git('rev-parse','HEAD^{tree}').decode().strip(),'dirty':git('status','--porcelain=v1','--untracked-files=all').decode(),'file_count':len(rows),'inventory_sha256':hashlib.sha256(encoded).hexdigest()}
 save(label+'.json',v);print(json.dumps({'snapshot':label,**v}),flush=True);return v
result={'kind':'original-source-closure-gate','source':source,'tree':tree,'request_key':key,'started_at':now(),'qualification':False}
save('started.json',result);before=None;status=1
try:
 before=snapshot('source-before')
 if before['commit']!=source or before['tree']!=tree or before['dirty']: raise RuntimeError('source gate requires exact clean frozen source')
 env=dict(os.environ);env.update(SOURCE_SHA=source,TESTED_SHA=source,HEPTA_CI_LANE='source-head',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(repo/'scripts'))
 command=['python3','scripts/hepta_ci_exec.py','--timeout-seconds','600','--minimum-tests','1','--output',str(records/'source-closure.json'),'--','python3','-m','unittest','discover','-s','qa/b4-no-bypass','-p','*source_closure.py','-v']
 save('invocation.json',{'command':command,'cwd':str(repo),'request_key':key,'environment':{k:env.get(k) for k in ('SOURCE_SHA','TESTED_SHA','HEPTA_CI_LANE','PYTHONDONTWRITEBYTECODE','PYTHONPATH','PATH')},'python':sys.version,'uid':os.getuid()})
 digest=hashlib.sha256();size=0
 with (records/'driver.raw.log').open('xb',buffering=0) as f:
  p=subprocess.Popen(command,cwd=repo,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  print(json.dumps({'phase':'original-source-closure','pid':p.pid,'command':command}),flush=True)
  while True:
   chunk=os.read(p.stdout.fileno(),65536)
   if not chunk: break
   f.write(chunk);digest.update(chunk);size+=len(chunk);sys.stdout.buffer.write(chunk);sys.stdout.buffer.flush()
  status=p.wait();p.stdout.close();os.fsync(f.fileno())
 result.update(status='passed' if status==0 else 'failed',execution={'returncode':status,'driver_log_bytes':size,'driver_log_sha256':digest.hexdigest(),'actual_process_exit_observed':True,'outer_controller_kill':False})
except Exception as e: result.update(status='failed',error=type(e).__name__+': '+str(e))
finally:
 if before is not None:
  try:
   after=snapshot('source-after');result.update(before=before,after=after)
   if before!=after: result.update(status='failed',source_identity_changed=True);status=status or 1
  except Exception as e: result.update(status='failed',retention_error=type(e).__name__+': '+str(e));status=status or 1
 result.update(finished_at=now(),exit_code=status);save('result.json',result);print(json.dumps({'source_gate_result':result}),flush=True)
raise SystemExit(status)
