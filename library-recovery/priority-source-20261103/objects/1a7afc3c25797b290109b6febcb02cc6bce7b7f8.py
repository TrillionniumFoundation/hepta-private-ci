"""Read-only routing checks for the one-file branch-scoped trigger proposal."""
from pathlib import Path
import ast
import hashlib
import json
import re
import subprocess
import yaml

ROOT = Path(__file__).resolve().parent
BASE = Path('/workspace/shared/platform-nine-leaf-69d/.github/workflows/bazel.yml')
CANDIDATE = ROOT / 'candidate/.github/workflows/bazel.yml'
a = yaml.safe_load(BASE.read_text())
b = yaml.safe_load(CANDIDATE.read_text())
assert b[True]['push'] == {'branches': ['dot/platform-leaf-qualification-20261006']}
assert b[True]['workflow_dispatch'] == a[True]['workflow_dispatch']
assert a[True]['workflow_call'] is None
assert b[True]['workflow_call']['inputs'] == {'reusable-call': {'description': 'Preserve ordinary qualification when invoked by a caller workflow', 'type': 'boolean', 'default': True}}
assert b[True]['workflow_dispatch']['inputs']['qualification-group']['default'] == 'full'
assert a.keys() == b.keys()
for key in a.keys() - {True, 'jobs', 'concurrency'}: assert a[key] == b[key]
assert set(a['jobs']) == set(b['jobs'])
for name, before in a['jobs'].items():
    after = b['jobs'][name].copy(); before = before.copy()
    after.pop('if', None); before.pop('if', None)
    assert before == after, name


def condition(expression, event, ref, selector, reusable=False):
    text = expression.removeprefix('${{').removesuffix('}}').strip()
    for old, new in [('github.event_name','event'), ('github.ref','ref'), ('inputs.qualification-group','selector'), ('inputs.reusable-call','reusable')]:
        text = text.replace(old, new)
    text = re.sub(r'\btrue\b', 'True', text)
    text = text.replace('always()', 'True').replace('&&',' and ').replace('||',' or ')
    text = re.sub(r'!(?!=)', ' not ', text).strip()
    tree = ast.parse(text, mode='eval')
    allowed = (ast.Expression,ast.BoolOp,ast.And,ast.Or,ast.UnaryOp,ast.Not,ast.Compare,ast.Eq,ast.NotEq,ast.Name,ast.Load,ast.Constant)
    assert all(isinstance(node,allowed) for node in ast.walk(tree))
    assert {node.id for node in ast.walk(tree) if isinstance(node,ast.Name)} <= {'event','ref','selector','reusable'}
    return bool(eval(compile(tree,'<checked-routing>','eval'),{'__builtins__':{}},{'event':event,'ref':ref,'selector':selector,'reusable':reusable}))

ordinary = set(a['jobs']) - {'fixed-linux-supervisor','fixed-windows-platform','reject-unknown-diagnostic'}
checks=[]
branch='refs/heads/dot/platform-leaf-qualification-20261006'
for event in ('push','pull_request','workflow_dispatch'):
    selectors = ('','full','linux-supervisor','windows-platform','invalid') if event=='workflow_dispatch' else ('',)
    for ref in (branch,'refs/heads/main','refs/heads/unrelated'):
        for selector in selectors:
            original={job for job,v in a['jobs'].items() if condition(v.get('if','True'),event,ref,selector)}
            candidate={job for job,v in b['jobs'].items() if condition(v.get('if','True'),event,ref,selector)}
            if event=='push' and ref==branch:
                assert candidate == {'fixed-linux-supervisor','fixed-windows-platform'},candidate
            else:
                assert candidate==original,(event,ref,selector,original,candidate)
            checks.append({'event':event,'ref':ref,'selector':selector,'jobs':sorted(candidate)})
# Model real reusable calls with the caller's original event context.
for event in ('push','pull_request','workflow_dispatch'):
    for ref in (branch,'refs/heads/main','refs/heads/unrelated'):
        original={job for job,v in a['jobs'].items() if condition(v.get('if','True'),event,ref,'')}
        candidate={job for job,v in b['jobs'].items() if condition(v.get('if','True'),event,ref,'',reusable=True)}
        assert candidate==original,(event,ref,original,candidate)
        checks.append({'event':event,'ref':ref,'selector':'','reusable_call':True,'jobs':sorted(candidate)})
push_suffix="${{ github.event_name == 'push' && github.ref == 'refs/heads/dot/platform-leaf-qualification-20261006' && inputs.reusable-call != true && '::diagnostic-platform-push' || '' }}"
assert b['concurrency']['group'].replace(push_suffix,'',1)==a['concurrency']['group']
assert b['concurrency']['cancel-in-progress']==a['concurrency']['cancel-in-progress']
for name in ('fixed-linux-supervisor','fixed-windows-platform'):
    assert b['jobs'][name]['env']['SOURCE_SHA']=='${{ github.sha }}'
    assert b['jobs'][name]['env']['TESTED_SHA']=='${{ github.sha }}'
    assert b['jobs'][name]['env']['HEPTA_CI_LANE']=='source-head'
    assert b['jobs'][name]['timeout-minutes']==60
    assert all('actions/cache/save' not in step.get('uses','') for step in b['jobs'][name]['steps'])
patch=subprocess.run(['git','diff','--no-index','--full-index','--',str(BASE),str(CANDIDATE)],capture_output=True,text=True)
assert patch.returncode==1
text=patch.stdout.replace('a'+str(BASE),'a/.github/workflows/bazel.yml').replace('b'+str(CANDIDATE),'b/.github/workflows/bazel.yml')
(ROOT/'diagnostic-push-only.patch').write_text(text)
result={'base_source':'b10db17cb3c88fb65e0e03d61a8a19bd77b771c7','base_tree':'4006c525784de71d3a09656fec0fe20a6475141e','changed_paths':['.github/workflows/bazel.yml'],'sha256':hashlib.sha256(text.encode()).hexdigest(),'routing_cases':len(checks),'cases':checks,'unchanged':'all existing job payloads, inputs/defaults, permissions, native commands, source guards, cache policy, timeouts and artifact steps','publication':'not published'}
(ROOT/'checks.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))
