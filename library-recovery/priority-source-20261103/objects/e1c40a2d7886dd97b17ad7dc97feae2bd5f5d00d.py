from pathlib import Path
import ast,hashlib,json,re,subprocess,yaml
ROOT=Path(__file__).resolve().parent
BASE=Path('/workspace/shared/platform-nine-leaf-69d')
CANDIDATE=ROOT/'candidate'
a=yaml.safe_load((BASE/'.github/workflows/bazel.yml').read_text())
b=yaml.safe_load((CANDIDATE/'.github/workflows/bazel.yml').read_text())
old='refs/heads/dot/platform-leaf-qualification-20261006'
new='refs/heads/dot/platform-windows-qualification-20261006'
assert b[True]['push']=={'branches':['dot/platform-windows-qualification-20261006']}
assert b[True]['workflow_dispatch']==a[True]['workflow_dispatch']
assert b[True]['workflow_call']==a[True]['workflow_call']
assert b['permissions']==a['permissions']

def condition(expr,event,ref,selector='',reusable=False):
 text=expr.removeprefix('${{').removesuffix('}}').strip()
 for x,y in [('github.event_name','event'),('github.ref','ref'),('inputs.qualification-group','selector'),('inputs.reusable-call','reusable')]:text=text.replace(x,y)
 text=re.sub(r'\btrue\b','True',text).replace('always()','True').replace('&&',' and ').replace('||',' or ')
 text=re.sub(r'!(?!=)',' not ',text).strip();tree=ast.parse(text,mode='eval')
 assert all(isinstance(n,(ast.Expression,ast.BoolOp,ast.And,ast.Or,ast.UnaryOp,ast.Not,ast.Compare,ast.Eq,ast.NotEq,ast.Name,ast.Load,ast.Constant)) for n in ast.walk(tree))
 return bool(eval(compile(tree,'<routing>','eval'),{'__builtins__':{}},dict(event=event,ref=ref,selector=selector,reusable=reusable)))

def selected(workflow,event,ref,selector='',reusable=False):
 return {k for k,v in workflow['jobs'].items() if condition(v.get('if','True'),event,ref,selector,reusable)}
checks=[]
assert selected(b,'push',new)=={'fixed-windows-platform'}
assert selected(a,'push',old)=={'fixed-linux-supervisor','fixed-windows-platform'}
for event in ('push','pull_request','workflow_dispatch'):
 for ref in (old,new,'refs/heads/main','refs/heads/unrelated'):
  assert selected(a,event,ref,reusable=True)==selected(b,event,ref,reusable=True)
  checks.append(dict(event=event,ref=ref,reusable=True))
for ref in (old,new,'refs/heads/main','refs/heads/unrelated'):
 for selector in ('','full','linux-supervisor','windows-platform','invalid'):
  assert selected(a,'workflow_dispatch',ref,selector)==selected(b,'workflow_dispatch',ref,selector)
  checks.append(dict(event='workflow_dispatch',ref=ref,selector=selector))
assert '::diagnostic-windows-push' in b['concurrency']['group']
assert '::diagnostic-platform-push' not in b['concurrency']['group']
assert b['jobs']['fixed-windows-platform']['env']['TESTED_SHA']=='${{ github.sha }}'
for name in a['jobs']:
 x=a['jobs'][name].copy();y=b['jobs'][name].copy();x.pop('if',None);y.pop('if',None)
 if name=='fixed-windows-platform':
  oldsteps=x.pop('steps');newsteps=y.pop('steps');assert len(oldsteps)==len(newsteps)
  for os,ns in zip(oldsteps,newsteps):
   if os.get('name') in ('Run fixed ACL/helper native targets','Run fixed Core/Queue native targets'):
    os=os.copy();ns=ns.copy();before=os.pop('run');after=ns.pop('run')
    assert after.strip().endswith(before)
    assert after.splitlines()[0]=='export HEPTA_BAZEL_BASH="$(cygpath -w "$BASH")"'
   assert os==ns
 assert x==y
paths=['.github/workflows/bazel.yml','scripts/hepta_fixed_bazel.py','scripts/test_hepta_fixed_bazel.py'];chunks=[]
for rel in paths:
 p=BASE/rel;q=CANDIDATE/rel;v=subprocess.run(['git','diff','--no-index','--full-index','--',str(p),str(q)],capture_output=True,text=True);assert v.returncode==1
 chunks.append(v.stdout.replace('a'+str(p),'a/'+rel).replace('b'+str(q),'b/'+rel))
patch=''.join(chunks);(ROOT/'git-bash-and-windows-only.patch').write_text(patch)
result={'base_source':'dc36dcf5d0fca0d44bed8c31aa31b7c07002dcbf','base_tree':'7c5f57443016cca05a02f4f0133b59029d2a6b4d','planned_new_branch':new.removeprefix('refs/heads/'),'changed_paths':paths,'patch_sha256':hashlib.sha256(patch.encode()).hexdigest(),'routing_cases':len(checks)+2,'source_tests':'14/14 pass; no native Windows execution','current_linux_run':'37404705271 remains on original branch; no ref update there','published':False}
(ROOT/'manifest.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
