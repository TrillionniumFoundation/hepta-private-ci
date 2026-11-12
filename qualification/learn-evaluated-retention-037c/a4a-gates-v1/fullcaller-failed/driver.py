from pathlib import Path
from datetime import datetime,timezone
import ast,fcntl,gzip,hashlib,json,os,subprocess,sys,textwrap
repo=Path('/home/qian-qi/hepta-learn-caller-20261112-037c-a4a1b5eb')
records=Path('/home/qian-qi/hepta-learn-037c-evidence/fullcaller-a4a1b5eb6cb4-v1')
source='a4a1b5eb6cb45fc1182564e6b81026a2a2acf609'
tree='e09e7fb338e5f9a37fccfd4f05a8d5c222d7c0da'
key='learn-037c-fullcaller-a4a1b5eb6cb4-v1'
records.mkdir(mode=0o700,exist_ok=False)
def now(): return datetime.now(timezone.utc).isoformat()
def save(name,value):
 with (records/name).open('x') as f: json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
def git(root,*words): return subprocess.check_output(['git','--no-optional-locks',*words],cwd=root)
def identity(root):
 return {'commit':git(root,'rev-parse','HEAD').decode().strip(),'tree':git(root,'rev-parse','HEAD^{tree}').decode().strip(),'dirty':git(root,'status','--porcelain=v1','--untracked-files=all').decode()}
def execute(name,command,cwd,env=None):
 started=now();digest=hashlib.sha256();size=0
 with (records/(name+'.raw.log')).open('xb',buffering=0) as f:
  p=subprocess.Popen(command,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  print(json.dumps({'phase':name,'command':command if name!='original-workflow' else ['python3','extracted-original-workflow.py'],'pid':p.pid,'started_at':started}),flush=True)
  while True:
   chunk=os.read(p.stdout.fileno(),65536)
   if not chunk: break
   f.write(chunk);digest.update(chunk);size+=len(chunk);sys.stdout.buffer.write(chunk);sys.stdout.buffer.flush()
  status=p.wait();p.stdout.close();os.fsync(f.fileno())
 observed={'returncode':status,'started_at':started,'finished_at':now(),'log_bytes':size,'log_sha256':digest.hexdigest(),'controller_kill':False}
 save(name+'.json',observed)
 return status
def snapshot(label):
 rows=[]
 names=git(repo,'ls-files','-z')+git(repo,'ls-files','--others','--exclude-standard','-z')
 for raw in sorted(set(names.split(b'\0'))-{b''}):
  rel=os.fsdecode(raw);p=repo/rel
  if not p.exists() and not p.is_symlink(): rows.append({'path':rel,'missing':True});continue
  data=os.fsencode(os.readlink(p)) if p.is_symlink() else p.read_bytes()
  rows.append({'path':rel,'mode':'120000' if p.is_symlink() else ('100755' if p.stat().st_mode&0o111 else '100644'),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()})
 encoded=json.dumps(rows,sort_keys=True,separators=(',',':')).encode()
 with gzip.open(records/(label+'.files.json.gz'),'xb') as f: f.write(encoded)
 value={**identity(repo),'file_count':len(rows),'inventory_sha256':hashlib.sha256(encoded).hexdigest()}
 save(label+'.json',value);print(json.dumps({'snapshot':label,**value}),flush=True)
 return value
result={'kind':'original-full-caller-proof','request_key':key,'source':source,'tree':tree,'repo':str(repo),'started_at':now(),'qualification':False}
save('started.json',result);before=None;status=1;gate_lock=None;metadata_before=None
try:
 if not repo.is_dir(): raise RuntimeError('handed-off cc22 source worktree missing')
 previous=Path('/home/qian-qi/hepta-learn-037c-evidence/final-gates-8faf92e260e1-v2')
 prior=json.loads((previous/'result.json').read_text())
 prior_caller=json.loads((previous/'fullcaller-gate.json').read_text())
 if prior.get('source')!='8faf92e260e118508fc62f4f38f3816db24cd4cc' or 'fullcaller' not in prior.get('phase_exit_codes',{}) or not prior_caller.get('actual_process_exit_observed') or prior.get('old_caller_before')!=prior.get('old_caller_after'):
  raise RuntimeError('old fullcaller has no complete preserved terminal observation')
 source_records=Path('/home/qian-qi/hepta-learn-037c-evidence/source-a4a1b5eb6cb4-v1')
 prepared=json.loads((source_records/'result.json').read_text())
 prepared_exec=json.loads((source_records/'source-closure.json').read_text())
 if prepared.get('source')!=source or prepared.get('tree')!=tree or prepared.get('before')!=prepared.get('after') or not prepared.get('execution',{}).get('actual_process_exit_observed') or prepared_exec.get('source_sha')!=source or prepared_exec.get('tested_sha')!=source:
  raise RuntimeError('cc22 original source gate has no complete exact terminal observation')
 if hashlib.sha256((source_records/'result.json').read_bytes()).hexdigest()!='fd283e2847c6dde06ffb6f0a97bfeb2ab250e92f7ff1eb89d8b4dd9471cf3294' or hashlib.sha256((source_records/'source-closure.json').read_bytes()).hexdigest()!='6d7ca8638ca69aeaf89833681cd672637a09c961d234d9d354b983a903a26c50':
  raise RuntimeError('final source result or execution original bytes differ')
 if prepared.get('status')!='passed' or prepared.get('exit_code')!=0 or prepared.get('execution',{}).get('returncode')!=0 or prepared.get('execution',{}).get('outer_controller_kill') is not False or prepared.get('after',{}).get('file_count')!=15230 or prepared.get('after',{}).get('inventory_sha256')!='29f9e6135150109dd4b4072b9e8f7851e34b7ab499bfa622e16e698a88468573':
  raise RuntimeError('final source gate did not pass with the exact complete unchanged input inventory')
 if prepared_exec.get('status')!='passed' or any(prepared_exec.get(k)!=0 for k in ('exit_code','command_exit_code','returncode','observed_failed_tests')) or prepared_exec.get('observed_passed_tests')!=504 or prepared_exec.get('timed_out') is not False or prepared_exec.get('output_limit_exceeded') is not False:
  raise RuntimeError('final complete 504-case original source execution is not an observed PASS')
 save('prerequisite-observations.json',{'old_terminal':prior,'old_caller_execution':prior_caller,'cc22_source_terminal':prepared,'cc22_source_execution':prepared_exec})
 lock_path=records.parent/'caller-gates-a4a1b5eb6cb4.lock'
 gate_lock=lock_path.open('x+b')
 fcntl.flock(gate_lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 save('exclusive-gate-lock.json',{'path':str(lock_path),'pid':os.getpid(),'held':'exclusive nonblocking'})
 def repository_metadata():
  paths={name:Path(git(repo,'rev-parse','--path-format=absolute','--git-path',name).decode().strip()) for name in ('config','config.worktree','info/sparse-checkout')}
  states={name:{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None} for name,path in paths.items()}
  lock_paths={name:Path(git(repo,'rev-parse','--path-format=absolute','--git-path',name).decode().strip()) for name in ('index.lock','HEAD.lock','config.lock','shallow.lock')}
  locks={str(path):path.exists() for path in lock_paths.values()}
  if any(locks.values()): raise RuntimeError('active git lock at caller boundary')
  return {'metadata':states,'locks':locks}
 metadata_before=repository_metadata()
 save('metadata-before.json',metadata_before)
 if identity(repo)!={'commit':source,'tree':tree,'dirty':''}: raise RuntimeError('caller checkout is not exact clean source')
 before=snapshot('source-before')
 full_rows=json.loads(gzip.decompress((records/'source-before.files.json.gz').read_bytes()))
 source_rows=[{k:v for k,v in row.items() if k!='blob'} for row in full_rows]
 source_encoded=json.dumps(source_rows,sort_keys=True,separators=(',',':')).encode()
 if len(full_rows)!=15230 or hashlib.sha256(source_encoded).hexdigest()!=prepared['after']['inventory_sha256'] or source_encoded!=gzip.decompress((source_records/'source-after.files.json.gz').read_bytes()):
  raise RuntimeError('separate caller checkout differs from every original passed source byte')
 save('source-byte-admission.json',{'file_count':len(full_rows),'source_gate_inventory_sha256':hashlib.sha256(source_encoded).hexdigest(),'caller_inventory_sha256':before['inventory_sha256'],'all_original_source_bytes_equal':True})
 env=dict(os.environ)
 env.update(GITHUB_WORKSPACE=str(repo),RUNNER_TEMP=str(records),SOURCE_SHA=source,TESTED_SHA=source,HEPTA_CI_LANE='source-head',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(repo/'scripts'))
 workflow=repo/'.github/workflows/hepta-daemon-learning-native.yml'
 raw=workflow.read_bytes()
 selected=raw.decode().split('      - name: Verify the full caller inventory and retain original execution\n',1)[1]
 program=textwrap.dedent(selected.split("          python3 - <<'PY'\n",1)[1].split('          PY\n',1)[0])
 ast.parse(program)
 if 'for phase, timeout in (("self-test", 300), ("verify", 4800)):' not in program: raise RuntimeError('original full caller budgets differ')
 if hashlib.sha256(program.encode()).hexdigest()!='b7738faad5d06f584c4fe1dddf70db8d6f210427293c7e17aceb72d047d8c7dd': raise RuntimeError('original caller workflow program bytes differ')
 (records/'extracted-original-workflow.py').write_text(program)
 disk=os.statvfs(str(repo))
 save('environment.json',{'python':sys.version,'uid':os.getuid(),'gid':os.getgid(),'workflow_sha256':hashlib.sha256(raw).hexdigest(),'program_sha256':hashlib.sha256(program.encode()).hexdigest(),'cargo_lock_sha256':hashlib.sha256((repo/'codex-rs/Cargo.lock').read_bytes()).hexdigest(),'environment':{k:env.get(k) for k in ('PATH','GITHUB_WORKSPACE','RUNNER_TEMP','SOURCE_SHA','TESTED_SHA','HEPTA_CI_LANE','PYTHONDONTWRITEBYTECODE','PYTHONPATH','LANG','LC_ALL')},'available_disk_bytes':disk.f_bavail*disk.f_frsize,'mem_available':next(l for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))})
 status=execute('original-workflow',[sys.executable,'-c',program],repo,env)
 result['status']='passed' if status==0 else 'failed'
except Exception as e:
 result.update(status='failed',error=type(e).__name__+': '+str(e))
finally:
 if before is not None:
  try:
   after=snapshot('source-after');result.update(before=before,after=after)
   if before!=after: result.update(status='failed',source_identity_changed=True);status=status or 1
  except Exception as e: result.update(status='failed',retention_error=type(e).__name__+': '+str(e));status=status or 1
 if metadata_before is not None:
  try:
   metadata_after=repository_metadata();save('metadata-after.json',metadata_after)
   result.update(metadata_before=metadata_before,metadata_after=metadata_after)
   if metadata_before!=metadata_after: result.update(status='failed',metadata_changed=True);status=status or 1
  except Exception as e: result.update(status='failed',metadata_retention_error=type(e).__name__+': '+str(e));status=status or 1
 if gate_lock is not None: fcntl.flock(gate_lock.fileno(),fcntl.LOCK_UN);gate_lock.close()
 result.update(finished_at=now(),exit_code=status)
 save('result.json',result);print(json.dumps({'caller_result':result}),flush=True)
raise SystemExit(status)
