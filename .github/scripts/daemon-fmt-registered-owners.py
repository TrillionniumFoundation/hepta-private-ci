from pathlib import Path
import gzip,hashlib,json,os,subprocess,sys,types
D=Path(os.environ['RUNNER_TEMP'])/'expanded-format';D.mkdir(exist_ok=True)
ROOT=Path.cwd();BASE='b8e8c6e82abc1479c573f61a5e17d28d581e6cad';OLD='c12ee03f3185d5a13949faca54f066dfd634e509';NEW='e4be1e972707f5c376033fd59e18fb4f260da891'
def gt(*s):return subprocess.check_output(['git',*s])
def module(ref,n):
 p=str(ROOT/'scripts/format.py');m=types.ModuleType(n);m.__file__=p;sys.modules[n]=m;exec(compile(gt('show',ref+':scripts/format.py'),p,'exec'),m.__dict__);return m
def snapshot(paths):
 return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()for p in paths}
assert gt('rev-parse','HEAD').decode().strip()==NEW
before=module(OLD,'old_fmt');after=module(NEW,'new_fmt')
scope=after.changed_paths(BASE)
op=gt('diff','--name-only','--diff-filter=ACDMRT','--no-renames','-z',BASE,OLD,'--')
original=[p for p in op.decode().split('\0')if p and((ROOT/p).is_file()or Path(p).name in {'pyproject.toml','ruff.toml','.ruff.toml','rustfmt.toml','.rustfmt.toml'})]
old=before.rust_configuration_scope(original);new=after.rust_configuration_scope(scope)
assert old==new and len(new)==4219
arch=after.retained_rust.INVENTORY['archived'];active=after.retained_rust.INVENTORY['maintained_builders'];registered=set(arch)|set(active)
assert set(arch).isdisjoint(active) and len(arch)==37 and len(active)==7 and registered<=set(new)
for p in new:
 if p not in registered:
  a=before.rust_file_command(p,check=False);b=after.rust_file_command(p,check=False);assert a.args==b.args and a.cwd==b.cwd,p
groups=after.scoped_formatter_groups(scope,check=False,base=BASE)
planned=[Path(c.args[-1]).relative_to(ROOT).as_posix()for g in groups if g.name=='Rust' for c in g.commands]
assert planned==new
data0=snapshot(sorted(registered)+list(after.retained_rust.INVENTORY['companions']));rows=[]
for mode in (True,False):
 for p in sorted(registered):
  c=after.rust_file_command(p,check=mode)
  if p in arch:assert c.args[0]==sys.executable and c.args[1].endswith('hepta_retained_rust.py')
  else:assert c.args[0]=='rustfmt' and ('--check' in c.args)==mode and c.args[c.args.index('--edition')+1]=='2024'
  proc=subprocess.run(c.args,cwd=c.cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  rows.append({'path':p,'check_mode':mode,'tool':c.args[:2],'exit':proc.returncode,'out':proc.stdout})
  assert proc.returncode==0,(p,proc.stdout)
assert data0==snapshot(data0)
assert gt('status','--porcelain','--untracked-files=all')==b''
(D/'original-rust.json.gz').write_bytes(gzip.compress(json.dumps(new).encode(),mtime=0))
(D/'actual-44.json').write_text(json.dumps(rows,indent=2)+'\n')
(D/'scope.json').write_text(json.dumps({'candidate':NEW,'old':OLD,'base':BASE,'changed_paths_original':len(original),'changed_paths_candidate':len(scope),'added':sorted(set(scope)-set(original)),'removed':sorted(set(original)-set(scope)),'original_rust_list_identical':len(new),'other_commands_unchanged':len(new)-len(registered),'verified_immutable':len(arch),'maintained':len(active),'checked_commands':len(rows),'physical_digests_before_and_after':data0},indent=2)+'\n')
