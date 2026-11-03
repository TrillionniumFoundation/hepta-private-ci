from pathlib import Path
import hashlib,json,subprocess,tomllib,re,yaml,ast
R=Path('/workspace/shared/supervisor-runfiles-repair');O=Path(__file__).resolve().parent
BASE='72a148b78ed267e9345b56e724fb2f9e4d1c2770'
def old(path):return subprocess.check_output(['git','show',BASE+':'+path],cwd=R)
p='codex-rs/hepta-supervisor/tests/robrix_control_projection.rs';before=old(p).decode();after=(R/p).read_text()
pattern=r'fn read_tracked_artifacts\(\) -> Result<BTreeMap<String, Vec<u8>>> \{.*?\n\}'
assert re.sub(pattern,'LOCATOR',before,flags=re.S)==re.sub(pattern,'LOCATOR',after,flags=re.S)
assert 'codex_utils_cargo_bin::find_resource!(manifest_resource)?' in after
assert 'read_artifacts(root)' in after
assert after.count('#[test]')==before.count('#[test]')==2
assert 'artifact set contains a non-file' in after
fixtures=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'codex-rs/hepta-supervisor/fixtures/robrix-control-v2'],cwd=R,text=True).splitlines();assert len(fixtures)==5
inventory=[]
for p in fixtures:
 data=(R/p).read_bytes();assert data==old(p)
 inventory.append({'path':p,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
a=tomllib.loads(old('codex-rs/Cargo.lock').decode());b=tomllib.loads((R/'codex-rs/Cargo.lock').read_text())
assert len(a['package'])==len(b['package'])
for x,y in zip(a['package'],b['package']):
 if x['name']=='codex-hepta-supervisor':
  z={**x,'dependencies':sorted(x['dependencies']+['codex-utils-cargo-bin'])};assert z==y
 else:assert x==y
manifest=tomllib.loads((R/'codex-rs/hepta-supervisor/Cargo.toml').read_text());baseline=tomllib.loads(old('codex-rs/hepta-supervisor/Cargo.toml').decode());assert manifest['dev-dependencies'].pop('codex-utils-cargo-bin')=={'workspace':True};assert manifest==baseline
utility=(R/'codex-rs/utils/cargo-bin/src/lib.rs').read_text()
assert '$crate::resolve_bazel_runfile(option_env!("BAZEL_PACKAGE"), resource)' in utility
assert 'Ok(manifest_dir.join(resource))' in utility
assert 'runfile does not exist at:' in utility
workflow=yaml.safe_load((R/'.github/workflows/bazel.yml').read_text());original=yaml.safe_load(old('.github/workflows/bazel.yml'))
assert workflow[True]['push']=={'branches':['dot/platform-supervisor-qualification-20261006']}
for event in ('workflow_call','workflow_dispatch'):assert workflow[True][event]==original[True][event]
def condition(expr,event,ref,selector='',reusable=False):
 text=expr.removeprefix('${{').removesuffix('}}').strip()
 for x,y in [('github.event_name','event'),('github.ref','ref'),('inputs.qualification-group','selector'),('inputs.reusable-call','reusable')]:text=text.replace(x,y)
 text=re.sub(r'\btrue\b','True',text).replace('always()','True').replace('&&',' and ').replace('||',' or ');text=re.sub(r'!(?!=)',' not ',text).strip();tree=ast.parse(text,mode='eval')
 assert all(isinstance(n,(ast.Expression,ast.BoolOp,ast.And,ast.Or,ast.UnaryOp,ast.Not,ast.Compare,ast.Eq,ast.NotEq,ast.Name,ast.Load,ast.Constant)) for n in ast.walk(tree))
 return bool(eval(compile(tree,'<routing>','eval'),{'__builtins__':{}},dict(event=event,ref=ref,selector=selector,reusable=reusable)))
def selected(w,e,r,s='',reuse=False):return {k for k,v in w['jobs'].items() if condition(v.get('if','True'),e,r,s,reuse)}
branch='refs/heads/dot/platform-supervisor-qualification-20261006';assert selected(workflow,'push',branch)=={'fixed-linux-supervisor'}
checks=1
for ref in (branch,'refs/heads/dot/platform-leaf-qualification-20261006','refs/heads/main','refs/heads/unrelated'):
 for event in ('push','pull_request','workflow_dispatch'):
  assert selected(original,event,ref,reuse=True)==selected(workflow,event,ref,reuse=True);checks+=1
 for selector in ('','full','linux-supervisor','windows-platform','invalid'):
  assert selected(original,'workflow_dispatch',ref,selector)==selected(workflow,'workflow_dispatch',ref,selector);checks+=1
for k in original['jobs']:
 x=original['jobs'][k].copy();y=workflow['jobs'][k].copy();x.pop('if',None);y.pop('if',None);assert x==y
patch=subprocess.check_output(['git','diff','--full-index','--binary'],cwd=R);(O/'supervisor-runfiles-and-linux-only.patch').write_bytes(patch)
result={'source_base':'dc36dcf5d0fca0d44bed8c31aa31b7c07002dcbf','base_tree':'7c5f57443016cca05a02f4f0133b59029d2a6b4d','patch_sha256':hashlib.sha256(patch).hexdigest(),'fixtures':inventory,'assertions':'all source outside read_tracked_artifacts byte-identical; full-directory enumeration retained','dependency_delta':'one existing workspace dev-dependency edge; no package/version changes','routing_cases':checks,'native':'unrun','locked_offline_metadata':'exit0, no-deps','proposed_branch':'dot/platform-supervisor-qualification-20261006'}
(O/'manifest.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='fixtures'},indent=2))
