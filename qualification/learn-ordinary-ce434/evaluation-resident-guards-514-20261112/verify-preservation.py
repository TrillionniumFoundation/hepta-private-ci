from pathlib import Path
import ast,hashlib,importlib.util,json,re,subprocess,sys,tomllib
root=Path('/workspace/scratch/ce434f960ee9/evaluation-guard-514');out=root.parent/'evaluation-guard-514-evidence';base=subprocess.check_output(['git','show','HEAD:CALLERS.toml'],cwd=root,text=True);current=(root/'CALLERS.toml').read_text();before=tomllib.loads(base);after=tomllib.loads(current)
for key in before:
 if key not in ('boundary','protected_file'):assert before[key]==after[key],key
assert len(before['boundary'])==len(after['boundary'])==480;assert len(before['protected_file'])==len(after['protected_file'])==368
TOKEN=re.compile(r'"(?:\\.|[^"\\])*"|[A-Za-z_]\w*|[0-9][A-Za-z0-9_]*|::|->|=>|&&|\|\||!=|==|>=|<=|[^\s]')
def normalized(s):
 ts=TOKEN.findall(s);return [t for i,t in enumerate(ts) if not(t==',' and i+1<len(ts) and ts[i+1] in (')',']','}'))]
def compare(a,b,path):
 if a==b:return
 if isinstance(a,dict):
  assert a.keys()==b.keys(),path
  for k in a:compare(a[k],b[k],path+'/'+k)
 elif isinstance(a,list):
  assert len(a)==len(b),path
  for i,(x,y) in enumerate(zip(a,b)):compare(x,y,path+'/'+str(i))
 elif isinstance(a,str):
  if path.startswith('boundary/196/caller_markers/'):
   assert a=='state.require_circuit_learning_source(request)' and b=='.require_circuit_learning_source(request)'
  elif path.startswith('protected_file/308/required_function_order/') and a.startswith('GateActionV3::'):
   assert normalized(a)==[x for x in normalized(b) if x!='{'],(path,a,b)
  else:assert normalized(a)==normalized(b),(path,a,b)
 else:raise AssertionError((path,a,b))
compare(before['boundary'],after['boundary'],'boundary');compare(before['protected_file'],after['protected_file'],'protected_file')
# Exact counterpart paths may intentionally have more than one protected row.
assert [x['path'] for x in before['protected_file']]==[x['path'] for x in after['protected_file']]
changed=subprocess.check_output(['git','diff','--name-only'],cwd=root,text=True).splitlines();assert changed and all(p=='CALLERS.toml' or p.startswith('qa/b4-no-bypass/test_') and p.endswith('.py') for p in changed)
qa=[]
for p in changed:
 if p=='CALLERS.toml':continue
 old=subprocess.check_output(['git','show','HEAD:'+p],cwd=root,text=True);new=(root/p).read_text()
 def cases(s):return [(c.name,n.name) for c in ast.parse(s).body if isinstance(c,ast.ClassDef) for n in c.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_')]
 assert cases(old)==cases(new),p
 qa.append({'path':p,'tests':len(cases(new)),'sha256':hashlib.sha256(new.encode()).hexdigest()})
for a,b in zip(before['protected_file'],after['protected_file']):
 if a['path'].endswith('/cell_q24_candidate_stage_evaluation.rs'):assert a==b
spec=importlib.util.spec_from_file_location('direct_owned_514',root/'scripts/verify_hepta_callers.py');proof=importlib.util.module_from_spec(spec);sys.modules[spec.name]=proof;spec.loader.exec_module(proof)
def own(path):
 n=Path(path).name
 return n.startswith(('authority_host_learning_resident','circuit_original_evaluation','neuron_cell_evaluation')) or n in {'deployment_learning_resident.rs','authority_host_resident_registration.rs','authority_host_runtime.rs','runtime.rs','objective_learning_source.rs','resident_learning_delivery.rs','circuit_task_source_policy.rs'}
rows=[r for r in after['protected_file'] if own(r['path'])];proof._verify_protected_files(root,{'protected_file':rows})
delta=json.loads((out/'complete-row-delta.json').read_text());assert len(delta)==31
r={'source':'514fe5f53cfdc254477667f8862d652ea756c807','parent_tree':'490dcafbd5a7f12a8fac19f5fa5b00b5c3ce4879','boundaries':480,'protected':368,'unchanged_metadata':True,'unchanged_authority_callers_and_inventory':True,'unchanged_protected_multiset_order_and_constraints':True,'changed_rows':31,'changed_boundary_rows':2,'changed_protected_rows':29,'owned_protected_passed':len(rows),'rust_and_scanner_delta':False,'candidate_evaluation_row_unchanged':True,'qualification_files':qa,'representation_exception':'Shared completed-source caller marker uses common method spelling; exact receiver-call association remains in each actual caller function and is covered by replacement/separation mutations plus typed unexpected-caller rejection.','match_arm_braces':'Three GateAction match arms gained formatter braces; guard operands and effect order remain exact.','manifest_sha256':hashlib.sha256(current.encode()).hexdigest()};(out/'preservation.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
