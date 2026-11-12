from pathlib import Path
from datetime import datetime,timezone
import ast,fcntl,hashlib,json,os,subprocess,sys
PARENT=Path('/home/qian-qi/hepta-learn-caller-20261112-037c-8faf92e2')
REPO=Path('/home/qian-qi/hepta-learn-source-20261112-037c-374aa919')
RECORDS=Path('/home/qian-qi/hepta-learn-037c-evidence/source-preparation-374aa919931e-v1')
SOURCE_RECORDS=Path('/home/qian-qi/hepta-learn-037c-evidence/source-374aa919931e-v1')
SOURCE='374aa919931e8ee5446b4ccdc49e651b7848cc5d'
TREE='981c4675a6579dfd9748046d3d01a2268f11c36f'
OLD_SOURCE='8faf92e260e118508fc62f4f38f3816db24cd4cc'
OLD_TREE='d26b9398ffe6ed269c1d018a7e4e043bbe0a2b9d'
KEY='learn-037c-source-preparation-374aa919931e-v1'
SOURCE_PROGRAM="from pathlib import Path\nfrom datetime import datetime,timezone\nimport gzip,hashlib,json,os,subprocess,sys\nrepo=Path('/home/qian-qi/hepta-learn-source-20261112-037c-374aa919')\nrecords=Path('/home/qian-qi/hepta-learn-037c-evidence/source-374aa919931e-v1')\nsource='374aa919931e8ee5446b4ccdc49e651b7848cc5d'\ntree='981c4675a6579dfd9748046d3d01a2268f11c36f'\nkey='learn-037c-source-374aa919931e-v1'\nrecords.mkdir(mode=0o700,exist_ok=False)\ndef now(): return datetime.now(timezone.utc).isoformat()\ndef save(n,v):\n with (records/n).open('x') as f: json.dump(v,f,indent=2,sort_keys=True);f.write('\\n')\ndef git(*a): return subprocess.check_output(['git','--no-optional-locks',*a],cwd=repo)\ndef snapshot(label):\n rows=[]\n for raw in sorted(set((git('ls-files','-z')+git('ls-files','--others','--exclude-standard','-z')).split(b'\\0'))-{b''}):\n  rel=os.fsdecode(raw);p=repo/rel\n  if not p.exists() and not p.is_symlink(): rows.append({'path':rel,'missing':True});continue\n  data=os.fsencode(os.readlink(p)) if p.is_symlink() else p.read_bytes()\n  rows.append({'path':rel,'mode':'120000' if p.is_symlink() else ('100755' if p.stat().st_mode&0o111 else '100644'),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})\n encoded=json.dumps(rows,sort_keys=True,separators=(',',':')).encode()\n with gzip.open(records/(label+'.files.json.gz'),'xb') as f: f.write(encoded)\n v={'commit':git('rev-parse','HEAD').decode().strip(),'tree':git('rev-parse','HEAD^{tree}').decode().strip(),'dirty':git('status','--porcelain=v1','--untracked-files=all').decode(),'file_count':len(rows),'inventory_sha256':hashlib.sha256(encoded).hexdigest()}\n save(label+'.json',v);print(json.dumps({'snapshot':label,**v}),flush=True);return v\nresult={'kind':'original-source-closure-gate','source':source,'tree':tree,'request_key':key,'started_at':now(),'qualification':False}\nsave('started.json',result);before=None;status=1\ntry:\n before=snapshot('source-before')\n if before['commit']!=source or before['tree']!=tree or before['dirty']: raise RuntimeError('source gate requires exact clean frozen source')\n env=dict(os.environ);env.update(SOURCE_SHA=source,TESTED_SHA=source,HEPTA_CI_LANE='source-head',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(repo/'scripts'))\n command=['python3','scripts/hepta_ci_exec.py','--timeout-seconds','600','--minimum-tests','1','--output',str(records/'source-closure.json'),'--','python3','-m','unittest','discover','-s','qa/b4-no-bypass','-p','*source_closure.py','-v']\n save('invocation.json',{'command':command,'cwd':str(repo),'request_key':key,'environment':{k:env.get(k) for k in ('SOURCE_SHA','TESTED_SHA','HEPTA_CI_LANE','PYTHONDONTWRITEBYTECODE','PYTHONPATH','PATH')},'python':sys.version,'uid':os.getuid()})\n digest=hashlib.sha256();size=0\n with (records/'driver.raw.log').open('xb',buffering=0) as f:\n  p=subprocess.Popen(command,cwd=repo,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)\n  print(json.dumps({'phase':'original-source-closure','pid':p.pid,'command':command}),flush=True)\n  while True:\n   chunk=os.read(p.stdout.fileno(),65536)\n   if not chunk: break\n   f.write(chunk);digest.update(chunk);size+=len(chunk);sys.stdout.buffer.write(chunk);sys.stdout.buffer.flush()\n  status=p.wait();p.stdout.close();os.fsync(f.fileno())\n result.update(status='passed' if status==0 else 'failed',execution={'returncode':status,'driver_log_bytes':size,'driver_log_sha256':digest.hexdigest(),'actual_process_exit_observed':True,'outer_controller_kill':False})\nexcept Exception as e: result.update(status='failed',error=type(e).__name__+': '+str(e))\nfinally:\n if before is not None:\n  try:\n   after=snapshot('source-after');result.update(before=before,after=after)\n   if before!=after: result.update(status='failed',source_identity_changed=True);status=status or 1\n  except Exception as e: result.update(status='failed',retention_error=type(e).__name__+': '+str(e));status=status or 1\n result.update(finished_at=now(),exit_code=status);save('result.json',result);print(json.dumps({'source_gate_result':result}),flush=True)\nraise SystemExit(status)\n"
SOURCE_PROGRAM_SHA='be64d0e6bd88e924038d56e4d172fb872a5dc31086f1b520ed710bbf023bb018'
RECORDS.mkdir(mode=0o700,exist_ok=False)
def now(): return datetime.now(timezone.utc).isoformat()
def save(n,v):
 with (RECORDS/n).open('x') as f:
  json.dump(v,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
def sha(p):
 if not p.exists(): return None
 if p.is_symlink() or not p.is_file(): raise RuntimeError('identity file must be regular')
 return hashlib.sha256(p.read_bytes()).hexdigest()
def git(root,*args):
 return subprocess.check_output(['git','--no-optional-locks',*args],cwd=root)
def gitpath(root,name):
 return Path(git(root,'rev-parse','--path-format=absolute','--git-path',name).decode().strip())
def identity(root):
 return {
  'head':git(root,'rev-parse','HEAD').decode().strip(),
  'tree':git(root,'rev-parse','HEAD^{tree}').decode().strip(),
  'status':git(root,'status','--porcelain=v1','--untracked-files=all').decode(),
  'diff_sha256':hashlib.sha256(git(root,'diff','--binary')).hexdigest(),
  'common_dir':git(root,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip(),
  'config_sha256':sha(gitpath(root,'config')),
  'worktree_config_sha256':sha(gitpath(root,'config.worktree')),
  'index_sha256':sha(gitpath(root,'index')),
  'sparse_path':str(gitpath(root,'info/sparse-checkout')),
  'sparse_sha256':sha(gitpath(root,'info/sparse-checkout')),
  'cargo_lock_sha256':sha(root/'codex-rs/Cargo.lock'),
 }
def locks(root):
 found={str(gitpath(root,n)):gitpath(root,n).exists() for n in ('index.lock','HEAD.lock','config.lock','shallow.lock')}
 if any(found.values()): raise RuntimeError('active Git lock prevents isolated preparation')
 return found
def execute(name,args,cwd):
 started=now();digest=hashlib.sha256();size=0
 with (RECORDS/(name+'.raw.log')).open('xb',buffering=0) as f:
  p=subprocess.Popen(args,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  print(json.dumps({'phase':name,'pid':p.pid,'started_at':started,'command':args}),flush=True)
  while True:
   b=os.read(p.stdout.fileno(),65536)
   if not b: break
   f.write(b);digest.update(b);size+=len(b);sys.stdout.buffer.write(b);sys.stdout.buffer.flush()
  status=p.wait();p.stdout.close();os.fsync(f.fileno())
 observed={'command':args,'cwd':str(cwd),'started_at':started,'finished_at':now(),'returncode':status,'log_bytes':size,'log_sha256':digest.hexdigest(),'actual_process_exit_observed':True,'outer_controller_kill':False}
 save(name+'.json',observed)
 return status
result={'kind':'isolated-exact-source-gate-only','source':SOURCE,'tree':TREE,'request_key':KEY,'repo':str(REPO),'parent_repo':str(PARENT),'source_records':str(SOURCE_RECORDS),'started_at':now(),'qualification':False}
save('started.json',result)
before=None;prepared=None;status=1;lock=None
try:
 if not (PARENT/'.git').is_dir() or (PARENT/'.git').is_symlink(): raise RuntimeError('parent must be the confirmed independent clone')
 before=identity(PARENT);save('parent-before.json',before);save('parent-locks-before.json',locks(PARENT))
 if before['head']!=OLD_SOURCE or before['tree']!=OLD_TREE or before['status'] or before['sparse_sha256'] is not None:
  raise RuntimeError('confirmed old parent source differs')
 if before['common_dir']!=str(PARENT/'.git'): raise RuntimeError('unexpected shared common Git directory')
 if git(PARENT,'remote','get-url','origin').decode().strip()!='https://github.com/TrillionniumFoundation/hepta-private-ci.git': raise RuntimeError('parent origin differs')
 if REPO.exists() or SOURCE_RECORDS.exists(): raise RuntimeError('new source or records path already exists')
 disk=os.statvfs(str(PARENT))
 save('preparation-environment.json',{'python':sys.version,'uid':os.getuid(),'available_disk_bytes':disk.f_bavail*disk.f_frsize,'git_version':git(PARENT,'--version').decode().strip(),'source_program_sha256':SOURCE_PROGRAM_SHA,'command_scope':'source closure only; original budget 600 seconds; no caller or Rust'})
 if disk.f_bavail*disk.f_frsize<1024**3: raise RuntimeError('insufficient disk for isolated worktree')
 lock_path=RECORDS.parent/'object-prep-374aa919931e.lock'
 lock=lock_path.open('x+b');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 save('object-preparation-lock.json',{'path':str(lock_path),'held':'exclusive nonblocking','pid':os.getpid(),'created_at':now()})
 if execute('source-fetch',['git','fetch','--filter=blob:none','--no-tags','--no-write-fetch-head','origin',SOURCE],PARENT):
  raise RuntimeError('additive exact source fetch failed')
 if git(PARENT,'rev-parse',SOURCE+'^{tree}').decode().strip()!=TREE: raise RuntimeError('exact source tree differs')
 if execute('source-worktree',['git','worktree','add','--detach',str(REPO),SOURCE],PARENT):
  raise RuntimeError('isolated detached worktree creation failed')
 parent_prepared=identity(PARENT);save('parent-after-preparation.json',parent_prepared)
 if parent_prepared!=before: raise RuntimeError('parent identity changed during preparation')
 save('parent-locks-after-preparation.json',locks(PARENT))
 prepared=identity(REPO);save('prepared-source.json',prepared);save('source-locks-before.json',locks(REPO))
 if prepared['head']!=SOURCE or prepared['tree']!=TREE or prepared['status'] or prepared['sparse_sha256'] is not None:
  raise RuntimeError('new source must be exact clean non-sparse checkout')
 fcntl.flock(lock.fileno(),fcntl.LOCK_UN);lock.close();lock=None
 if hashlib.sha256(SOURCE_PROGRAM.encode()).hexdigest()!=SOURCE_PROGRAM_SHA: raise RuntimeError('source driver payload hash differs')
 ast.parse(SOURCE_PROGRAM)
 path=RECORDS/'source-driver.py'
 with path.open('x') as f: f.write(SOURCE_PROGRAM);f.flush();os.fsync(f.fileno())
 status=execute('source-gate',[sys.executable,str(path)],REPO)
 after=identity(REPO);save('final-source.json',after);save('source-locks-after.json',locks(REPO))
 if after!=prepared: raise RuntimeError('source or Cargo.lock identity changed')
 result.update(status='passed' if status==0 else 'failed',source_gate_exit_code=status)
except Exception as e:
 status=1;result.update(status='failed',error=type(e).__name__+': '+str(e))
finally:
 if before is not None:
  try:
   after=identity(PARENT);save('parent-after.json',after);save('parent-locks-after.json',locks(PARENT))
   result.update(parent_before=before,parent_after=after)
   if after!=before: status=1;result.update(status='failed',parent_changed=True)
  except Exception as e:
   status=1;result.update(status='failed',retention_error=type(e).__name__+': '+str(e))
 if lock is not None: fcntl.flock(lock.fileno(),fcntl.LOCK_UN);lock.close()
 result.update(finished_at=now(),exit_code=status)
 save('result.json',result);print(json.dumps({'exact_source_gate_result':result}),flush=True)
raise SystemExit(status)
