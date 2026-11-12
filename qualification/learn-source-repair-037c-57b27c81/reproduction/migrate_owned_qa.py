"""Append only actual, separately proved callers to exact-57b QA constants."""
from pathlib import Path
import ast,difflib,hashlib,json,re,shutil,tomllib

R=Path(__file__).resolve().parent; O=R/'overlay'; W=R/'work'; A='codex-rs/hepta-agentd/src/'
proof=json.loads((R/'TYPED_EDGE_EVIDENCE.json').read_text())
additions={x['boundary']:x['new_callers'] for x in proof['boundaries']}
additions['learning_original_owner_command_channel'].append(A+'cell_q24_training_command_readback_service.rs')
registry=tomllib.loads((R/'registry/CALLERS.toml').read_text()); rows={r['id']:r for r in registry['boundary']}
files=list(sorted((R/'base/qa/b4-no-bypass').glob('*.py')))
for name in ('test_evaluated_retention_command_source_closure.py','test_evaluated_version_source_closure.py'):
 p=R/'all-exact-qa/qa/b4-no-bypass'/name
 dest=R/'additional-base/qa/b4-no-bypass'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes());files.append(dest)
def meta(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def offset(lines,node,end=False):
 return sum(len(x) for x in lines[:(node.end_lineno if end else node.lineno)-1])+(node.end_col_offset if end else node.col_offset)
def closed_env(tree):
 env={}
 for n in tree.body:
  if not isinstance(n,ast.Assign) or len(n.targets)!=1 or not isinstance(n.targets[0],ast.Name):continue
  if not all(isinstance(x,(ast.Constant,ast.Name,ast.Load,ast.Tuple,ast.List,ast.Dict,ast.BinOp,ast.Add)) for x in ast.walk(n.value)):continue
  try:v=eval(compile(ast.Expression(n.value),'<constants only>','eval'),{'__builtins__':{}},env)
  except (NameError,TypeError,ValueError):continue
  env[n.targets[0].id]=v
 return env
def method_sources(s):
 return {n.name:ast.get_source_segment(s,n) for n in ast.walk(ast.parse(s)) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_')}
records=[];patches=[]
for p in files:
 before=p.read_text(); tree=ast.parse(before);env=closed_env(tree);lines=before.splitlines(keepends=True); edits=[];changes=[]
 for n in tree.body:
  if not isinstance(n,ast.Assign) or len(n.targets)!=1 or not isinstance(n.targets[0],ast.Name) or n.targets[0].id not in ('CALLERS','EXPECTED') or not isinstance(n.value,ast.Dict):continue
  for key,value in zip(n.value.keys,n.value.values):
   name=ast.literal_eval(key);old=list(env[n.targets[0].id][name]);new=rows[name]['product_callers']
   if old==new:continue
   assert name in additions,(p.name,name)
   delta=new[len(old):];assert new[:len(old)]==old,(p.name,name)
   if p.parent.parent.parent==R/'additional-base':
    assert name=='learning_original_owner_command_channel' and delta==[A+'cell_q24_training_command_readback_service.rs']
   else:assert delta==additions[name],(p.name,name,delta,additions[name])
   start,end=offset(lines,value),offset(lines,value,True);raw=before[start:end];assert raw.startswith('(') and raw.endswith(')')
   prefix=raw[:-1].rstrip(); sep='' if prefix.endswith(',') else ','
   if '\n' in raw:
    last=value.elts[-1]; indent=' '*last.col_offset
    tail=raw[len(prefix):-1]; closing_indent=tail.rsplit('\n',1)[-1] if '\n' in tail else ''
    changed=prefix+sep+'\n'+''.join(indent+json.dumps(x)+',\n' for x in delta)+closing_indent+')'
   else:changed=prefix+sep+' '+', '.join(json.dumps(x) for x in delta)+')'
   assert eval(changed,{'__builtins__':{}},env)==tuple(new)
   edits.append((start,end,changed));changes.append({'boundary':name,'before':old,'after':new,'actual_added_paths':delta})
 after=before
 for start,end,changed in sorted(edits,reverse=True):after=after[:start]+changed+after[end:]
 special=[]
 if p.name=='test_original_training_owner_source_closure.py':
  changes_exact=[
   ('MODEL_LANE = "codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs"\n','MODEL_LANE = "codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs"\nSOURCE_LANE = "codex-rs/hepta-agentd/src/cell_q24_training_source_read_lane.rs"\n'),
   ('for path in (OWNER, STAGE, MODEL_LANE, native, SNAPSHOT, BOUND, BOOTSTRAP)','for path in (OWNER, STAGE, MODEL_LANE, SOURCE_LANE, native, SNAPSHOT, BOUND, BOOTSTRAP)'),
   ('expected = (STAGE,) if name == "cell_q24_original_training_execute" else (STAGE, MODEL_LANE)','expected = (STAGE,) if name == "cell_q24_original_training_execute" else (STAGE, MODEL_LANE, SOURCE_LANE)'),
  ]
  for old,new in changes_exact:assert after.count(old)==1;(special.append({'before':old,'after':new}));after=after.replace(old,new)
 bm=method_sources(before);am=method_sources(after);assert bm.keys()==am.keys()
 changed_methods=[name for name in bm if bm[name]!=am[name]]
 assert changed_methods==(['test_pair_and_model_lane_keep_exact_native_callers'] if special else []),(p.name,changed_methods)
 if special:
  old_ast=ast.dump(ast.parse(bm[changed_methods[0]].replace('\n    ','\n')),include_attributes=False) if False else None
  assert 'unregistered_fit.rs' in am[changed_methods[0]] and 'assertRaisesRegex(PROOF.VerificationFailure, "unexpected")' in am[changed_methods[0]]
 path='qa/b4-no-bypass/'+p.name;target=W/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(after);(O/path).write_text(after)
 patch=''.join(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),fromfile='a/'+path,tofile='b/'+path));patches.append(patch)
 records.append({'path':path,'before':meta(before.encode()),'after':meta(after.encode()),'literal_migrations':changes,'source_lane_expected_migration':special,'test_cases_before_after_identical':list(bm),'changed_method_bodies':changed_methods,'all_other_test_methods_byte_identical':True,'all_old_negative_assertions_retained':True})
assert len(records)==10
shutil.copyfile(R/'registry/CALLERS.toml',O/'CALLERS.toml')
(R/'OWNED_QA.patch').write_text(''.join(patches))
(R/'OWNED_QA_MIGRATIONS.json').write_text(json.dumps({'source':'57b27c81d0d5321b873ee751fd0e58e1d905b988','registry':meta((O/'CALLERS.toml').read_bytes()),'files':records,'product_changes':False,'scanner_changes':False,'test_cases_removed':0,'mutations_removed':0,'source_gate':False,'native':False,'qualification':0},indent=2)+'\n')
print(json.dumps({'files':len(records),'dict_value_changes':sum(len(x['literal_migrations']) for x in records),'test_cases':sum(len(x['test_cases_before_after_identical']) for x in records),'patch':meta((R/'OWNED_QA.patch').read_bytes())},indent=2))
