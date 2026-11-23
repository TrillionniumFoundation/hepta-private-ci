import hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
root=Path.cwd();temp=Path(os.environ['RUNNER_TEMP']);ev=temp/'fixture-pair-evidence';builds=ev/'bridge-cargo-artifacts.jsonl'
refs={'base':'c12ee03f3185d5a13949faca54f066dfd634e509','candidate':'40ea7f9e18acc0203731e0f715386f73b59423c1'}
fixture='qualification/hcsn_training/native_fixture.rs'
signed_rows=[json.loads(l) for l in (ev/'signed-artifacts.jsonl').read_text().splitlines()]
assert signed_rows[-1]=={'reason':'build-finished','success':True}
signed=[r for r in signed_rows if r.get('reason')=='compiler-artifact' and r['target']['name']=='hcsn_signed_worker' and r['profile']['test']]
assert len(signed)==1;binary=Path(signed[0]['executable']).resolve(strict=True)
def digest(p):
 h=hashlib.sha256()
 with p.open('rb')as f:
  while b:=f.read(1048576): h.update(b)
 return h.hexdigest()
def git(*args):return subprocess.check_output(['git',*args],text=True).strip()
assert git('diff','--name-only',*refs.values())==fixture
rustc=subprocess.check_output(['rustup','which','rustc'],cwd=root/'codex-rs',text=True).strip()
data={'refs':refs,'rustc_sha256':digest(Path(rustc)), 'signed_worker_sha256':digest(binary),'cases':[]}
for arm,ref in refs.items():
 subprocess.run(['git','checkout','--quiet','--detach',ref],check=True)
 assert git('status','--porcelain')==''
 input_sha=digest(root/fixture)
 for backend in ['value_kernel','population_grid','population_age']:
  target=temp/f'fixture-{arm}-{backend}';case=ev/f'{arm}-{backend}';case.mkdir()
  command=[sys.executable,'-m','qualification.hcsn_training.verify_bridge','--rust-workspace','codex-rs','--rustc',rustc,
           '--cargo-artifacts',str(builds),'--signed-worker-executable',str(binary),'--backend',backend,'--output',str(target)]
  start=time.monotonic()
  with (case/'driver.log').open('wb')as log: r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
  row={'arm':arm,'source':ref,'fixture_git_blob':git('hash-object',fixture),'fixture_sha256':input_sha,'backend':backend,'code':r.returncode,'wall_s':time.monotonic()-start}
  for n in ['result.json','failure.json','processes.jsonl','native-build.json','reference.json','resumed.json','native-plan.stderr','native-compile.stderr','native-clock-commit.stderr','signed-taskflow-real-worker.stdout','signed-taskflow-real-worker.stderr']:
   if (target/n).is_file():shutil.copyfile(target/n,case/n)
  if r.returncode:
   for p in target.glob('*.stderr'):
    if p.stat().st_size:shutil.copyfile(p,case/p.name)
  if (target/'native-build.json').is_file():
   b=json.loads((target/'native-build.json').read_text());assert b['source_sha256']==input_sha and b['rustc_sha256']==data['rustc_sha256']
   row['native_fixture_elf_sha256']=b['executable_sha256']
  if r.returncode==0:
   res=json.loads((target/'result.json').read_text()); assert res['status']=='passed' and res['signed_taskflow'] and res['supervised'] and res['backend']==backend
  data['cases'].append(row);(ev/'pair.json').write_text(json.dumps(data,indent=2)+'\n')
 assert git('status','--porcelain')==''
assert len(data['cases'])==6 and all(r['code']==0 for r in data['cases'])
