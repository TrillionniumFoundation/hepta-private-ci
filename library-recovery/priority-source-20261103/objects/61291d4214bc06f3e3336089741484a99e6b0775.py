from pathlib import Path
import ast,re,yaml,json
ROOT=Path(__file__).resolve().parent
A=Path('/workspace/shared/windows-permission-queue-probe/.github/workflows/bazel.yml')
B=ROOT/'candidate/.github/workflows/bazel.yml'
a=yaml.safe_load(A.read_text());b=yaml.safe_load(B.read_text())
old='refs/heads/dot/windows-permission-queue-probe-20261006'
new='refs/heads/dot/windows-permission-queue-controls-20261006'
def condition(expr,event,ref,selector='',reusable=False):
 text=expr.removeprefix('${{').removesuffix('}}').strip()
 for x,y in [('github.event_name','event'),('github.ref','ref'),('inputs.qualification-group','selector'),('inputs.reusable-call','reusable')]:text=text.replace(x,y)
 text=re.sub(r'\btrue\b','True',text).replace('always()','True').replace('&&',' and ').replace('||',' or ')
 text=re.sub(r'!(?!=)',' not ',text).strip();tree=ast.parse(text,mode='eval')
 assert all(isinstance(n,(ast.Expression,ast.BoolOp,ast.And,ast.Or,ast.UnaryOp,ast.Not,ast.Compare,ast.Eq,ast.NotEq,ast.Name,ast.Load,ast.Constant)) for n in ast.walk(tree))
 return bool(eval(compile(tree,'<routing>','eval'),{'__builtins__':{}},dict(event=event,ref=ref,selector=selector,reusable=reusable)))

def selected(workflow,event,ref,selector='',reusable=False):
 return {k for k,v in workflow['jobs'].items() if condition(v.get('if','True'),event,ref,selector,reusable)}

assert b[True]['push']=={'branches':[new.removeprefix('refs/heads/')]}
assert b[True]['workflow_dispatch']==a[True]['workflow_dispatch']
assert b[True]['workflow_call']==a[True]['workflow_call']
assert b['permissions']==a['permissions']
assert selected(b,'push',new)=={'fixed-windows-platform'}
assert selected(a,'push',old)=={'fixed-windows-platform'}
checks=2
for event in ('push','pull_request','workflow_dispatch'):
 for ref in (old,new,'refs/heads/main','refs/heads/unrelated'):
  assert selected(a,event,ref,reusable=True)==selected(b,event,ref,reusable=True);checks+=1
for ref in (old,new,'refs/heads/main','refs/heads/unrelated'):
 for selector in ('','full','linux-supervisor','windows-platform','invalid'):
  assert selected(a,'workflow_dispatch',ref,selector)==selected(b,'workflow_dispatch',ref,selector);checks+=1
for name in a['jobs']:
 x=a['jobs'][name].copy();y=b['jobs'][name].copy();x.pop('if',None);y.pop('if',None);assert x==y
assert b['concurrency']['group']==a['concurrency']['group'].replace(old,new).replace('::diagnostic-permission-queue-push','::diagnostic-permission-queue-controls-push')
print(json.dumps({'routing_cases':checks,'ordinary_job_payloads':'unchanged','new_push_jobs':['fixed-windows-platform']}))
