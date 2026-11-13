#!/usr/bin/env python3
"""Author the exact formatted protection and new coordinator registrations.

Only immutable lexical helpers and span extraction run here. No verifier main,
source gate, QA method, compiler, formatter or native command is invoked.
"""
from pathlib import Path
import ast, copy, hashlib, importlib.util, json, re, sys, tomllib, types
sys.dont_write_bytecode=True
R=Path(__file__).resolve().parent
AGENT='codex-rs/hepta-agentd/src/'
QA='qa/b4-no-bypass/'

def pin(raw):
 return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def save(path,value):
 raw=value if isinstance(value,bytes) else value.encode() if isinstance(value,str) else (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()
 p=R/'after'/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);return pin(raw)
def report(name,value):
 (R/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def toml(value):
 if isinstance(value,str):return json.dumps(value,ensure_ascii=False)
 if isinstance(value,bool):return str(value).lower()
 if isinstance(value,list):return '['+', '.join(toml(x) for x in value)+']'
 if isinstance(value,dict):return '{ '+', '.join(k+' = '+toml(v) for k,v in value.items())+' }'
 if isinstance(value,int):return str(value)
 raise TypeError(type(value))
def table(kind,row):return '[['+kind+']]\n'+'\n'.join(k+' = '+toml(v) for k,v in row.items())+'\n\n'

spec=importlib.util.spec_from_file_location('registration_original_lexical',R/'before/scripts/verify_hepta_callers.py')
P=importlib.util.module_from_spec(spec);sys.modules[spec.name]=P;spec.loader.exec_module(P)
scope_text=(R/'before'/QA/'test_evaluated_published_read_source_closure.py').read_text()
scope_defs=[n for n in ast.parse(scope_text).body if isinstance(n,ast.FunctionDef) and n.name.startswith('ordinary_')]
ns={'PROOF':P,'re':re}
exec(compile(ast.Module(body=scope_defs,type_ignores=[]),'original_scope_functions_only','exec'),ns)
SCOPES=types.SimpleNamespace(**ns)
provider_text=(R/'before'/QA/'test_resident_provider_local_read_source_closure.py').read_text()
provider_defs=[n for n in ast.parse(provider_text).body if isinstance(n,ast.FunctionDef)]
pn={'PROOF':P,'SCOPES':SCOPES,'re':re,'hashlib':hashlib}
exec(compile(ast.Module(body=provider_defs,type_ignores=[]),'original_provider_helpers_only','exec'),pn)
active_source,actual_scope,module_shape=pn['active_source'],pn['actual_scope'],pn['module_shape']

oldtext=(R/'before/CALLERS.toml').read_text();old=tomllib.loads(oldtext)
candidate=json.loads((R/'CALLERS_FORMAT_REFRESH.draft.json').read_text())
edge=json.loads((R/'COORDINATOR_BOUNDARIES.draft.json').read_text())
assert edge['uncertainties']==[] and edge['old_boundary_additions']==[]
assert len(edge['new_boundaries'])==12
assert candidate['boundary']==old['boundary']
candidate['boundary'].extend(edge['new_boundaries'])
candidate['privileged_inventory']['required_boundary_ids'].extend(row['id'] for row in edge['new_boundaries'])
assert len(candidate['boundary'])==633 and len({row['symbol'] for row in candidate['boundary']})==633
newpaths=[AGENT+name for name in ('neuron_generation_initial.rs','neuron_generation_initial_root_custody.rs','neuron_generation_initial_root_task.rs','neuron_generation_initial_root_cold.rs')]
raw={path:(R/'view'/path).read_text() for path in newpaths}
code={path:active_source(source)[0] for path,source in raw.items()}
select_scope=SCOPES.ordinary_select_scope;root_containers=SCOPES.ordinary_root_containers;depth_at=SCOPES.ordinary_depth_at
helper_source=Path('/tmp/hepta-36fa-provider-registration-root86-frozen-v3/build_registration_candidate_root86.py').read_text()
helper_defs=[n for n in ast.parse(helper_source).body if isinstance(n,ast.FunctionDef) and n.name in ('type_spans','function_spans')]
hn={'raw':raw,'code':code,'PROOF':P,'re':re,'select_scope':select_scope,'root_containers':root_containers,'depth_at':depth_at}
exec(compile(ast.Module(body=helper_defs,type_ignores=[]),'existing_registration_scope_helpers_only','exec'),hn)
types_by_path={p:hn['type_spans'](p) for p in newpaths}
functions={p:hn['function_spans'](p) for p in newpaths}
mounts={}
for path in newpaths:
 mounts[path]=[]
 for match in re.finditer(r'#\[path\s*=\s*"([^"\n]+\.rs)"\]\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;',raw[path]):
  child=str(Path(path).parent/match.group(1))
  if child not in newpaths:continue
  sp={'parent':path,'child':child,'path_literal':json.dumps(match.group(1)),'module_name':match.group(2)}
  actual=SCOPES.ordinary_mount_span(P,code[path],raw[path],sp)
  mounts[path].append({**sp,'raw':raw[path][actual['start']:actual['end']]})
newrows=[]
for path in newpaths:
 assert not any(row['path']==path for row in old['protected_file'])
 row={'path':path,'required':[m['raw'] for m in mounts[path]],'required_order':[],'required_function_order':[],
      'forbidden':['SigningKey::generate','SigningKey::from_bytes','LearningEvidenceVerifierV1::new','LearningEvidenceTrustV1',
                   'File::open','File::create','UnixStream::connect','TcpStream::connect','Deref','into_inner','permit_all','if false','#[derive(Clone)]']}
 for item in types_by_path[path]:
  body=code[path][item['start']:item['end']];kind=item['selector']['item_kind'];split=body.index(kind)+len(kind)+1
  row['required_order'].append([body[:split],body[split:]])
 for item in root_containers(P,code[path]):
  body=code[path][item['start']:item['end']];split=body.index(' ')+1
  row['required_order'].append([body[:split],body[split:]])
 for f in functions[path]:
  marker='fn '+f['name']+'('
  if code[path].count(marker)==1:row['required_function_order'].append({'function':marker,'sequence':['fn ',f['body'][3:]]})
  elif f['owner'] is None:row['required_order'].append(['fn ',f['body'][3:]])
 for marker in row['forbidden']:
  pattern=re.escape(marker)
  if marker[0].isalnum() or marker[0]=='_':pattern=r'(?<!\w)'+pattern
  if marker[-1].isalnum() or marker[-1]=='_':pattern+=r'(?!\w)'
  assert not re.search(pattern,code[path]),(path,marker)
 if path.endswith('/neuron_generation_initial.rs'):
  mount='#[cfg(target_os = "linux")]\n#[path = "neuron_generation_initial_root_custody.rs"]\nmod root_custody;'
  assert mount in raw[path];row['required'].append(mount)
 candidate['protected_file'].append(row);newrows.append({'index':len(candidate['protected_file'])-1,'row':row})
exports=['pub use neuron_generation_initial::'+name+';' for name in ('OriginalRootCircuitTaskCustodyV1','OriginalRootCircuitTaskInputsV1','OriginalRootCircuitTaskRuntimeV1','OriginalRootInitialGenerationCustodyV1','OriginalRootInitialInstallationErrorV1')]
lib=(R/'view'/AGENT/'lib.rs').read_text()
librow={'path':AGENT+'lib.rs','required':['#[cfg(target_os = "linux")]\n'+x for x in exports],'forbidden':[]}
assert all(lib.count(marker)==1 for marker in librow['required'])
candidate['protected_file'].append(librow);newrows.append({'index':len(candidate['protected_file'])-1,'row':librow})
assert len(candidate['protected_file'])==442
assert candidate['authority']==old['authority'] and candidate['source_roots']==old['source_roots'] and candidate['ignored_path_fragments']==old['ignored_path_fragments']
assert candidate['protected_file'][411]==old['protected_file'][411]
assert all(a['forbidden']==b['forbidden'] for a,b in zip(old['protected_file'],candidate['protected_file']))
starts=list(re.finditer(r'(?m)^\[\[(boundary|protected_file)\]\]\n',oldtext));authority_start=oldtext.index('[authority]')
prefix=oldtext[:starts[0].start()]
old_ids='required_boundary_ids = '+toml(old['privileged_inventory']['required_boundary_ids'])
assert prefix.count(old_ids)==1
prefix=prefix.replace(old_ids,'required_boundary_ids = '+toml(candidate['privileged_inventory']['required_boundary_ids']))
chunks=[prefix];bi=pi=0
for i,m in enumerate(starts):
 end=starts[i+1].start() if i+1<len(starts) else authority_start;block=oldtext[m.start():end]
 if m.group(1)=='boundary':
  assert candidate['boundary'][bi]==old['boundary'][bi];chunks.append(block);bi+=1
  if bi==len(old['boundary']):chunks.extend(table('boundary',x) for x in edge['new_boundaries'])
 else:
  after=candidate['protected_file'][pi];chunks.append(block if after==old['protected_file'][pi] else table('protected_file',after));pi+=1
chunks.extend(table('protected_file',x['row']) for x in newrows);chunks.append(oldtext[authority_start:])
callers=''.join(chunks);assert tomllib.loads(callers)==candidate
cp=save('CALLERS.toml',callers)
report('REGISTRATION_CONSTRUCTION_REVIEW.draft.json',{'status':'STATIC_PARTIAL_SOURCE_PREPARATION_NOT_GATE_PASS','before_boundary_count':621,'after_boundary_count':633,
 'all_621_original_boundary_rows_equal':candidate['boundary'][:621]==old['boundary'],'new_boundaries':edge['new_boundaries'],
 'before_protected_count':437,'after_protected_count':442,'formatted_rows_changed':json.loads((R/'FORMATTED_GUARD_REFRESH.draft.json').read_text())['changed_rows'],
 'new_protected_rows':newrows,'all_437_original_forbidden_arrays_equal':True,'original_row411_equal':True,'source_roots_ignore_authority_unchanged':True,
 'full_source_collector_still_required':True,'new_api_non_test_callers_observed':[],'deployment_closed_loop_completed':False,
 'callers':cp,'getter_successor':'5279a43b99aa7031343578a21dba895f5eac3188'})

# Update exact existing scope digests from actual formatter bytes, preserving
# every selector and all 83 attack cases unless a selector itself no longer
# locates that same actual formatted declaration (reported, never guessed).
old_contract=json.loads((R/'before'/QA/'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json').read_text())
contract=copy.deepcopy(old_contract);scope_updates=[]
for path,guards in contract['scopes'].items():
 old_path=R/'pre-format'/path
 old_source=old_path.read_text() if old_path.exists() else (R/'before'/path).read_text()
 source=(R/'view'/path).read_text();old_code,old_literal=active_source(old_source);new_code,new_literal=active_source(source)
 assert module_shape(old_code,old_literal)==old_contract['module_shapes'][path],path
 for guard in guards:
  start,end=actual_scope(old_code,guard['selector'])
  assert hashlib.sha256(old_code[start:end].encode()).hexdigest()==guard['masked_sha256'],path
  assert hashlib.sha256(old_literal[start:end].encode()).hexdigest()==guard['literal_source_sha256'],path
  begin,stop=actual_scope(new_code,guard['selector'])
  after_hash={'masked_sha256':hashlib.sha256(new_code[begin:stop].encode()).hexdigest(),'literal_source_sha256':hashlib.sha256(new_literal[begin:stop].encode()).hexdigest()}
  if any(guard[k]!=v for k,v in after_hash.items()):scope_updates.append({'path':path,'selector':guard['selector'],'before':{k:guard[k] for k in after_hash},'after':after_hash})
  guard.update(after_hash)
 contract['module_shapes'][path]=module_shape(new_code,new_literal)
for path in newpaths:
 c,literal=active_source(raw[path]);selectors=[]
 selectors.extend(item['selector'] for item in types_by_path[path])
 for item in root_containers(P,c):
  selector={'kind':'root_container','header':item['header']}
  same=[x for x in root_containers(P,c) if x['header']==item['header']]
  if len(same)>1:
   names=re.findall(r'\bfn\s+(\w+)\s*(?=[(<])',c[item['opening']+1:item['end']-1])
   anchors=[name for name in names if sum(bool(re.search(r'\bfn\s+'+re.escape(name)+r'\s*(?=[(<])',c[x['opening']+1:x['end']-1])) for x in same)==1]
   assert anchors;selector['anchor']=anchors[0]
  selectors.append(selector)
 for item in functions[path]:
  if item['owner'] is None:selectors.append({'kind':'root_function','name':item['name']})
 guards=[]
 for selector in selectors:
  begin,end=actual_scope(c,selector)
  guards.append({'selector':selector,'masked_sha256':hashlib.sha256(c[begin:end].encode()).hexdigest(),'literal_source_sha256':hashlib.sha256(literal[begin:end].encode()).hexdigest()})
 contract['scopes'][path]=guards;contract['module_shapes'][path]=module_shape(c,literal)
 if mounts[path]:contract['mounts'][path]=[{k:v for k,v in m.items() if k!='raw'} for m in mounts[path]]
contract['exports'].extend(exports)
contract['boundary_count']=len(candidate['boundary']);contract['new_boundaries']=candidate['boundary'][569:]
checked={key:candidate[key] for key in ('boundary','privileged_inventory','authority','source_roots','ignored_path_fragments')}
contract['complete_boundary_sha256']=hashlib.sha256(json.dumps(checked,sort_keys=True,separators=(',',':')).encode()).hexdigest()
contract['source_refresh_basis']={'actual_formatted_physical_tree':'f905b18e6b05de1582024548179725a05d932536','coordinator_source_packet':'773d67128190fd2e1c3271c372f72e2a5537d1e8','metadata_name_successor':'5279a43b99aa7031343578a21dba895f5eac3188','root_source_map_field_is_preserved_historical_origin':True,'qualification':False}
def attack(path,function,marker):return {'path':AGENT+path,'function':function,'marker':marker}
contract['attacks']['root_custody_consumption']=[
 attack('neuron_generation_initial_root_custody.rs','require_root','libc::getuid()'),
 attack('neuron_generation_initial_root_custody.rs','require_root','libc::geteuid()'),
 attack('neuron_generation_initial_root_custody.rs','from_original_prepared','current.recover_initial_operation(&operation_id, intent_digest)?'),
 attack('neuron_generation_initial_root_custody.rs','from_original_prepared','original.target() != prepared.prepared.target()'),
 attack('neuron_generation_initial_root_custody.rs','publish','std::mem::replace(&mut self.phase, InitialPhase::ReadbackRequired)'),
 attack('neuron_generation_initial_root_custody.rs','publish','(*prepared).publish(signed)?'),
 attack('neuron_generation_initial_root_custody.rs','recover_original','matches!(self.phase, InitialPhase::ReadbackRequired)'),
 attack('neuron_generation_initial_root_custody.rs','recover_original','recover_agentd_generation_initial_v1('),
]
contract['attacks']['root_cold_original_recovery']=[
 attack('neuron_generation_initial_root_cold.rs','recover_from_original_current','require_root()?'),
 attack('neuron_generation_initial_root_cold.rs','recover_from_original_current','current.recover_initial_operation('),
 attack('neuron_generation_initial_root_cold.rs','recover_from_original_current','current.read_initial_operation(&original)?'),
 attack('neuron_generation_initial_root_cold.rs','recover_from_original_current','recover_agentd_generation_initial_v1('),
 attack('neuron_generation_initial_root_cold.rs','recover_from_original_current','Arc::clone(&current)'),
 attack('neuron_generation_initial_root_cold.rs','recover_from_original_current','operation.read_original()? != before'),
]
contract['attacks']['root_task_same_cell']=[
 attack('neuron_generation_initial_root_task.rs','into_q24_task','require_root()?'),
 attack('neuron_generation_initial_root_task.rs','into_q24_task','InitialPhase::Ready(ready)'),
 attack('neuron_generation_initial_root_task.rs','into_q24_task','(*ready).into_circuit_feature_task(inputs.definition, inputs.source)?'),
 attack('neuron_generation_initial_root_task.rs','into_q24_task','let retirement = task.clone();'),
 attack('neuron_generation_initial_root_task.rs','into_q24_task','published_task: task'),
 attack('neuron_generation_initial_root_task.rs','into_q24_task','config.with_q24_circuit_task_profile(profile)?'),
 attack('neuron_generation_initial_root_task.rs','into_q24_task','cell: runtime.cell'),
 attack('neuron_generation_initial_root_task.rs','into_q24_task','source: runtime.source'),
 attack('neuron_generation_initial_root_task.rs','drain_completed_task','require_root()?'),
 attack('neuron_generation_initial_root_task.rs','drain_completed_task','.drain_completed_task(&self.cell, self.source.as_ref(), &self.identity)'),
]
attack_counts=[]
for group,cases in contract['attacks'].items():
 for case in cases:
  source=(R/'view'/case['path']).read_text();c,_=active_source(source)
  span=SCOPES.ordinary_select_scope(P,c,{'kind':'unique_function','name':case['function']})
  marker=case['marker'];pattern=r'\s*'.join(re.escape(x) for x in re.findall(r'\w+|[^\w\s]',marker))
  if marker[0].isalnum() or marker[0]=='_':pattern=r'(?<!\w)'+pattern
  if marker[-1].isalnum() or marker[-1]=='_':pattern+=r'(?!\w)'
  found=list(re.finditer(pattern,c[span['start']:span['end']]))
  assert found,(group,case)
  attack_counts.append({'group':group,**case,'actual_occurrences':len(found)})
assert all(contract['attacks'][key]==value for key,value in old_contract['attacks'].items())
contract_pin=save(QA+'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json',contract)
report('PROVIDER_SCOPE_REFRESH.draft.json',{'old_paths':len(old_contract['scopes']),'new_paths':len(contract['scopes']),'old_scope_digest_updates':scope_updates,
 'old_selectors_unchanged':True,'all_83_original_attacks_equal':True,'new_attack_specs':24,'actual_attack_locations':attack_counts,
 'contract':contract_pin,'whole_old_method_bodies_preserved_except_separate_required_registration_update':True,'qa_methods_executed':0})
print(json.dumps({'callers':cp,'boundaries':633,'protected':442,'new_root_scope_paths':len(newpaths),'contract':contract_pin,'old_scope_updates':len(scope_updates),'attack_specs':len(attack_counts)},indent=2))
