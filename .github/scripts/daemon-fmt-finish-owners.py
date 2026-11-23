"""Observe two immutable sources; this diagnostic does not grant daemon postimage permissions."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
R=Path.cwd()
OUT=Path(os.environ["RUNNER_TEMP"])/"final-format"
OUT.mkdir(exist_ok=True)
REFS={'before':'e4be1e972707f5c376033fd59e18fb4f260da891','after':'97a379c5a347f0e66c5ed9a0cbd38303d1f92cb5'}
BASE='b8e8c6e82abc1479c573f61a5e17d28d581e6cad'
def run(args,**kwargs):
 return subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**kwargs)
def git(*args):
 return subprocess.check_output(['git',*args]).decode().strip()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(name,b): (OUT/name).write_bytes(b)
def cmd(name,argv,**kwargs):
 start=time.monotonic()
 result=run(argv,**kwargs)
 save(name+'.log',result.stdout);return [result.returncode, time.monotonic()-start]
files=git('diff','--name-only',*REFS.values()).splitlines()
assert len(files)==12 and all(p.startswith('codex-rs/') and p.endswith('.rs')for p in files)
reports={}
for arm,ref in REFS.items():
 subprocess.run(['git','checkout','--quiet','--detach',ref],check=True)
 assert git('status','--porcelain','--untracked-files=all')==''
 row={'ref':ref,'parsed':{},'source_blobs':{}}
 for p in files:
  a=run(['rustc','+1.96.0','-Zunpretty=normal','--edition=2024',p],env={**os.environ,'RUSTC_BOOTSTRAP':'1'})
  assert a.returncode==0, (p,a.stdout)
  row['parsed'][p]=sha(a.stdout);row['source_blobs'][p]=git('hash-object',p)
 row['context_owner_check']=cmd(arm+'-context',['python3','scripts/context-compiler-truth.py'])
 assert row['context_owner_check'][0]==1 and b'source identity policy' in (OUT/(arm+'-context.log')).read_bytes()
 cargo=['cargo','+1.96.0','metadata','--no-deps','--format-version=1']
 a=run(cargo,cwd=R/'codex-rs');assert a.returncode==0,a.stdout
 packages=json.loads(a.stdout)['packages'];row['workspace_package_count']=len(packages)
 assert not any(p['name']=='codex-hepta-memory-federation-wire' for p in packages)
 row['wire_own_manifest']=cmd(arm+'-wire',cargo+['--manifest-path','hepta-memory-federation-wire/Cargo.toml'],cwd=R/'codex-rs')
 assert row['wire_own_manifest'][0]!=0 and b'believes it' in (OUT/(arm+'-wire.log')).read_bytes()
 src='codex-rs/hepta-supervisor/src/qualification_fault.rs';dest=OUT/(arm+'-original-supervisor-test')
 row['standalone_fault_compile']=cmd(arm+'-fault-compile',['rustc','+1.96.0','--edition=2024','--test',src,'-o',str(dest)])
 assert row['standalone_fault_compile'][0]==0
 row['standalone_fault_test']=cmd(arm+'-fault-test',[str(dest),'--test-threads=1'])
 assert row['standalone_fault_test'][0]==0 and b'1 passed;' in (OUT/(arm+'-fault-test.log')).read_bytes()
 dest.unlink()
 row['standalone_fault_with_qualification_compile']=cmd(arm+'-fault-feature-compile',['rustc','+1.96.0','--edition=2024','--crate-type=lib','--cfg','feature="qualification"',src,'-o',str(dest)])
 assert row['standalone_fault_with_qualification_compile'][0]==0;dest.unlink()
 assert git('status','--porcelain','--untracked-files=all')==''
 reports[arm]=row
save('paired-source.json',(json.dumps(reports,indent=2)+'\n').encode())
assert sorted(k for k,v in reports['before']['parsed'].items()if reports['after']['parsed'][k]!=v)==sorted(['codex-rs/hepta-memory-federation-wire/src/codec.rs','codex-rs/hepta-memory-federation-wire/src/protocol.rs','codex-rs/hepta-supervisor/src/qualification_fault.rs'])
