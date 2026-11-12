from pathlib import Path
import ast,importlib.util,json,sys
root=Path('/workspace/scratch/ce434f960ee9/learn-current-v3')
helper=Path('/workspace/scratch/ce434f960ee9/issuer_24057_guard_patch.py')
spec=importlib.util.spec_from_file_location('issuer_guard_span',helper)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
source=helper.read_text()
prefix=source[:source.index("\npath = ROOT / 'CALLERS.toml'")]
exec(compile(prefix,str(helper),'exec'),module.__dict__)
path=root/'qa/b4-no-bypass/test_retained_version_issuer_source_closure.py'
text=path.read_text()
tree=ast.parse(text)
paths={
'WRAPPER':'codex-rs/hepta-agentd/src/root_retained_version_issuer.rs',
'WORKER':'codex-rs/hepta-agentd/src/circuit_retained_version_issuer.rs',
'HOST':'codex-rs/hepta-agentd/src/circuit_retained_version_host.rs',
'EFFECT':'codex-rs/hepta-agentd/src/circuit_retained_version_effect.rs',
'SERVICE':'codex-rs/hepta-agentd/src/circuit_retained_version_service.rs',
}
offsets=[0]
for line in text.splitlines(keepends=True):offsets.append(offsets[-1]+len(line))
changes=[]
replacements={}
for node in ast.walk(tree):
 if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute) or node.func.attr not in ('reject_each','rejects') or len(node.args)!=3:continue
 name,fn,markers=node.args
 if not isinstance(name,ast.Name) or name.id not in paths or not isinstance(fn,ast.Constant) or not isinstance(fn.value,str):continue
 items=markers.elts if node.func.attr=='reject_each' and isinstance(markers,(ast.Tuple,ast.List)) else [markers]
 for marker in items:
  if not isinstance(marker,ast.Constant) or not isinstance(marker.value,str):raise ValueError('nonliteral mutation marker')
  value=marker.value
  actual,_=module.actual_marker((root/paths[name.id]).read_text(),value,'fn '+fn.value+'(')
  assert module.equivalent(value,actual)
  if actual==value:continue
  start=offsets[marker.lineno-1]+marker.col_offset
  end=offsets[marker.end_lineno-1]+marker.end_col_offset
  replacements[(start,end)]=json.dumps(actual)
  changes.append({'path':str(path.relative_to(root)),'source_path':paths[name.id],'function':fn.value,'old':value,'new':actual})
for (start,end),value in sorted(replacements.items(),reverse=True):text=text[:start]+value+text[end:]
new_tree=ast.parse(text)
names=lambda t:sorted((type(n).__name__,n.name) for n in ast.walk(t) if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)))
assert names(new_tree)==names(tree)
path.write_text(text)
Path('/workspace/scratch/ce434f960ee9/issuer-24057-qa-markers.json').write_text(json.dumps(changes,indent=2)+'\n')
print(json.dumps({'actual_scoped_mutation_literal_changes':len(changes),'method_names_unchanged':True}))
