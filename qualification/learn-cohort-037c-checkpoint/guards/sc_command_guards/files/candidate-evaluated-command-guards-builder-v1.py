"""Generate an isolated, reviewable CALLERS delta; never edit a shared checkout."""
from pathlib import Path
import copy,hashlib,importlib.util,json,re,shutil,sys,tomllib
ROOT=Path('/workspace/scratch/037c0371c195')
OUT=ROOT/'candidate-evaluated-command-guards-a96-v1'
OVER=OUT/'overlay'
OUT.mkdir(exist_ok=True);OVER.mkdir(exist_ok=True)
frozen_external=[]
if (OUT/'CALLERS_DELTA_PLAN.json').exists():
 recorded=json.loads((OUT/'CALLERS_DELTA_PLAN.json').read_text())['external_caller_snapshots']
 for row in {item['path']:item for item in recorded}.values():
  payload=(OVER/row['path']).read_bytes()
  assert hashlib.sha256(payload).hexdigest()==row['sha256'],row['path']
  frozen_external.append((row,payload))
BASE=ROOT/'profile-evaluated-read-guards-4ab-v1'
for source in (BASE/'overlay').rglob('*'):
 if source.is_file() and (source.suffix in ('.rs','.py') or source.name=='CALLERS.toml'):
  target=OVER/source.relative_to(BASE/'overlay');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
shutil.copyfile(BASE/'postimages/CALLERS.toml',OVER/'CALLERS.toml')
def meta(b): return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
m=tomllib.loads((OVER/'CALLERS.toml').read_text());base_manifest=copy.deepcopy(m)
assert len(m['boundary'])==541 and len(m['protected_file'])==389
P='codex-rs/hepta-agentd/src/'
own={};inputs=[]
for name,expected in [
 ('candidate-evaluated-c-remote-formatted-v1','702a60e1b9a34f9d63dace2b5360066493d1c4dafcd3b5e63413bdd8d95ece13'),
 ('candidate-evaluated-s-command-formatted-v1','2f678992c893814ccd5857bb3ae5433403dc6f97c65eaa5cc2ae1f252aa65f69'),
 ('candidate-evaluated-c-command-formatted-v1','ea4708304a36b1ca0bbeef0384d631115bce27221d24ae6663a4df35893db9cc'),
]:
 root=ROOT/name;manifest=root/'VERIFIED_MANIFEST.json';assert meta(manifest.read_bytes())['sha256']==expected
 verified=json.loads(manifest.read_text());assert verified['actual_returncode']==0
 inputs.append({'manifest':str(manifest),**meta(manifest.read_bytes())})
 for row in verified['files']:
  path=row['path'];b=(root/'postimages'/path).read_bytes();assert meta(b)=={k:row[k] for k in ('bytes','sha256','blob')}
  target=OVER/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
  if not path.endswith('_tests.rs'):own[path]={'origin':str(root/'postimages'/path),**meta(b)}
external=[]
if frozen_external:
 for row,payload in frozen_external:
  target=OVER/row['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(payload)
  external.append(row)
else:
 for name in ['root-evaluated-candidate-a96-v1','profile-evaluated-version-a96-v3']:
  root=ROOT/name/'work'
  for source in root.rglob('*.rs'):
   path=str(source.relative_to(root))
   if path in own or path.endswith('_tests.rs'):continue
   b=source.read_bytes();target=OVER/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
   external.append({'path':path,'origin':str(source),**meta(b),'status':'independent producer snapshot; not our product or native PASS'})
spec=importlib.util.spec_from_file_location('command_delta_proof',OVER/'scripts/verify_hepta_callers.py')
proof=importlib.util.module_from_spec(spec);sys.modules[spec.name]=proof;spec.loader.exec_module(proof)
strip=lambda s:proof._strip_cfg_test_items(proof._strip_rust_non_code(s))
oldrows={r['path']:r for r in m['protected_file']}
source=lambda p:(OVER/p).read_text()
def functions(code):
 found=[]
 for mat in re.finditer(r'\bfn ([A-Za-z_]\w*)\(',code):
  name=mat[1];start=mat.start();end=proof._rust_item_end(code,start)
  if end is None:raise ValueError(('function end',name))
  if code[end]!='}' or code.count('fn '+name+'(')!=1:continue
  opening=code.index('{',start,end);line=code.rfind('\n',0,start)+1
  found.append((name,start,opening,end,'\n'+code[line:opening].rstrip()))
 return found
def chunks(code,opening,end):
 result=[];start=opening+1;curly=paren=bracket=0
 for i in range(opening+1,end):
  ch=code[i]
  if ch=='{':curly+=1
  elif ch=='}':curly-=1
  elif ch=='(':paren+=1
  elif ch==')':paren-=1
  elif ch=='[':bracket+=1
  elif ch==']':bracket-=1
  assert min(curly,paren,bracket)>=0
  split=ch==';' and curly==paren==bracket==0
  if ch=='}' and curly==paren==bracket==0:
   prefix=code[start:i+1].strip();rest=code[i+1:end].lstrip()
   if re.match(r'(?:if|for|while|loop|match)\b',prefix) and not rest.startswith(('else',';','.','?')):
    split=True
  if split:
   text=code[start:i+1].strip()
   if text:result.append((start,i+1,text))
   start=i+1
 tail=code[start:end].strip()
 if tail:result.append((start,end,tail))
 assert re.sub(r'\s','',code[opening+1:end])==re.sub(r'\s','',''.join(x[2] for x in result))
 return result
def whole_type_guards(code):
 groups=[]
 for mat in re.finditer(r'\b(?:struct|enum) ([A-Za-z_]\w*)',code):
  start=mat.start();ending=proof._rust_item_end(code,start)
  if ending is None or code[ending]!='}':continue
  opening=code.find('{',start,ending)
  if opening<0:continue
  line=code.rfind('\n',0,start)+1
  # Capture contiguous attributes as real code, including deny_unknown_fields.
  scan=line
  while scan>0:
   previous=code.rfind('\n',0,scan-1)+1;value=code[previous:scan].strip()
   if value.startswith('#['):line=previous;scan=previous
   else:break
  groups.append(['\n'+code[line:opening].rstrip(),code[opening:ending+1]])
 return groups
def freeze_functions(path,row,all_functions=True,selected=None):
 code=strip(source(path));old={x['function']:x for x in row.get('required_function_order',[])}
 guards=[];visibility=[]
 for name,start,opening,end,signature in functions(code):
  if selected is not None and name not in selected:continue
  parts=chunks(code,opening,end)
  assert parts,(path,name)
  body=code[start:end+1];tops=[]
  for idx,(a,b,text) in enumerate(parts):
   marker=text
   if body.count(marker)!=1:
    for high in range(idx+1,len(parts)):
     marker=code[a:parts[high][1]].strip()
     if body.count(marker)==1:break
    else:
     marker=code[parts[0][0]:b].strip()
   assert body.count(marker)==1,(path,name,marker)
   # The manifest verifier counts real braces, not indentation.
   pos=body.index(marker)
   assert body[:pos].count('{')-body[:pos].count('}')==1,(path,name,marker[:80])
   if marker not in tops:tops.append(marker)
  # A safe suffix after an inserted early cached return is not a live I/O
  # proof. Pin the complete actual body as well as its top-level statements.
  item={'function':'fn '+name+'(','sequence':['fn '+name+'(',code[opening:end+1]],'top_level':tops}
  previous=old.get(item['function'],{})
  if previous.get('literal_calls'):
   item['literal_calls']=previous['literal_calls']
  guards.append(item);visibility.append([signature,parts[0][2]])
 if selected is not None:
  guards=[x for x in row.get('required_function_order',[]) if x['function'][3:-1] not in selected]+guards
 row['required_function_order']=guards
 row.setdefault('required_order',[]).extend(x for x in visibility if x not in row.get('required_order',[]))
 for group in whole_type_guards(code):
  if group not in row['required_order']:row['required_order'].append(group)
 return row

newfiles=set(p for p in own if p not in oldrows and not p.endswith('/lib.rs'))
changed=set(p for p in own if p in oldrows)
common={P+'circuit_selection_receipt_owner.rs',P+'circuit_next_use_receipt_owner.rs'}
protected=set(newfiles)|changed|common
# lib.rs is only a mounted export surface, checked by exact live-attribute QA.
protected.discard(P+'lib.rs')
COMMON_FORBIDDEN=['SigningKey::generate','SigningKey::from_bytes','LearningEvidenceVerifierV1::new','LearningEvidenceTrustV1','File::open','File::create','UnixStream::connect','with_root_learning_stage_owners(','LearningIterationStageOwnerPortsV1 for','permit_all','if false','unwrap_or','RootResidentLearningEffectGateV3']
changes=[];actual_functions={}
for path in sorted(protected):
 before=copy.deepcopy(oldrows.get(path))
 if before is None:
  row={'path':path,'required':[],'forbidden':list(COMMON_FORBIDDEN),'required_order':[],'required_function_order':[]}
 else:row=copy.deepcopy(before)
 if path.endswith('learning_iteration_evidence_client.rs'):
  # Other agents add disjoint exports to this shared mount file. Preserve its
  # original behavioral guards exactly, and add only our real mounts below.
  pass
 else:row=freeze_functions(path,row)
 if before is not None:
  assert set(before['forbidden']).issubset(row['forbidden'])
  assert all(text in source(path) for text in before['required']),(path,'legacy required marker lost')
 else:
  for name in ['struct','enum']:
   pass
 if path.endswith(('circuit_evaluated_selection_remote_readback.rs','circuit_evaluated_selection_readback_binding.rs','circuit_evaluated_selection_command_evidence.rs','circuit_evaluated_next_use_command_evidence.rs')):
  row['forbidden'] += [x for x in ['attest_original_evaluated','attest_source(','commit_once(','sign_original(','execute_selection(','attest_completed_task(','OriginalCircuitSelectionReceiptOwnerV1::create_evaluated','OriginalCircuitNextUseReceiptOwnerV1::create_evaluated'] if x not in row['forbidden']]
 if path.endswith(('circuit_evaluated_selection_remote.rs','circuit_evaluated_next_use_remote.rs')):
  row['forbidden'] += [x for x in ["&'a mut",'ObservationLocation::RemoteOwner','ObservationLocation::LocalOwner','CommandOrigin::Recovered => self.attest_source'] if x not in row['forbidden']]
 if path.endswith('_command.rs'):
  row['forbidden'] += [x for x in ['pub context:','pub(crate) context:','pub(super) context:','pub channel:','pub(crate) channel:','pub retained:','pub(crate) retained:','pub enum Retained','pub(crate) enum Retained','pub(super) enum Retained','derive(Deserialize','impl Default'] if x not in row['forbidden']]
 if path.endswith('_command_wire.rs'):
  # Wire envelopes may deserialize. Opaque original receipts may not.
  row['forbidden'] += ['OriginalCircuitEvaluatedRetentionContextV1::from_snapshot','OriginalCircuitEvaluatedSelectionReceiptV1::from_snapshot','OriginalCircuitEvaluatedNextUseReceiptV1::from_snapshot']
 if path.endswith('circuit_evaluated_next_use_receipt.rs'):
  row['forbidden'] += [x for x in ['Deserialize','Deref','impl Default','pub fn from_checkpoint','pub fn from_bytes'] if x not in row['forbidden']]
 actual_functions[path]=[x[0] for x in functions(strip(source(path)))]
 changes.append({'path':path,'before':before,'after':row,'legacy_forbidden_preserved':True,'reason':'Actual evaluated remote/command paths; top-level statement ordering. Original S readback validation moved to shared private binding.'})
 if before is None:m['protected_file'].append(row)
 else:m['protected_file'][m['protected_file'].index(oldrows[path])]=row

# Inventory only the actual privileged typed entry points, not every private
# validation helper. Existing rows keep all old approved unrelated callers.
boundaries={b['symbol']:b for b in m['boundary']};adds=[]
# The original initial-head authentication was extracted verbatim into the
# shared private binding. Pin its actual invocation at the same factory and
# protect the complete original_context implementation in its new row.
boundaries['OriginalCircuitEvaluatedSelectionReadbackOwnerV1::from_original_receipt_owner']['definition_markers']=[
 'fn from_original_receipt_owner(',
 'binding::original_context(config, &selection)?',
 'owner: Mutex::new(owner)',
]
def add(id,receiver,method,file,marker=None):
 symbol=receiver+'::'+method
 assert symbol not in boundaries,symbol
 row={'id':id,'symbol':symbol,'receiver_type':receiver,'definition_path':P+file,'definition_markers':[marker or 'fn '+method+'('],'product_callers':[],'caller_markers':[]}
 boundaries[symbol]=row;adds.append(row);m['boundary'].append(row)
 m['privileged_inventory']['required_boundary_ids'].append(id)
add('learning_original_evaluated_read_next_use_binding','OriginalCircuitLearningReadClientV1','require_original_evaluated_next_use','circuit_evaluated_learning_read.rs','pub(crate) fn require_original_evaluated_next_use(')
for id,recv,method,file in [
 ('learning_original_evaluated_selection_remote_readback_transfer','OriginalCircuitSelectionReceiptOwnerV1','into_evaluated_remote_readback_owner','circuit_evaluated_selection_remote.rs'),
 ('learning_original_evaluated_selection_remote_readback_host_bind','OriginalCircuitEvaluatedSelectionRemoteReadbackOwnerV1','from_original_receipt_owner','circuit_evaluated_selection_remote_readback.rs'),
 ('learning_original_evaluated_selection_remote_readback_host_serve','OriginalCircuitEvaluatedSelectionRemoteReadbackOwnerV1','serve_readback','circuit_evaluated_selection_remote_readback.rs'),
 ('learning_original_evaluated_next_use_remote_attest','OriginalCircuitNextUseReceiptOwnerV1','attest_original_evaluated_remote_completion','circuit_evaluated_next_use_remote.rs'),
 ('learning_original_evaluated_next_use_remote_readback','OriginalCircuitNextUseReceiptOwnerV1','readback_evaluated_remote_completion','circuit_evaluated_next_use_remote.rs'),
]:add(id,recv,method,file)
for short,kind,owner,receipt in [('selection','Selection','OriginalCircuitSelectionReceiptOwnerV1','OriginalCircuitEvaluatedSelectionReceiptV1'),('next_use','NextUse','OriginalCircuitNextUseReceiptOwnerV1','OriginalCircuitEvaluatedNextUseReceiptV1')]:
 receipt_file='circuit_evaluated_'+short+'_receipt.rs'
 prefix='learning_original_evaluated_'+short+'_command_'
 getter='original_evaluated_command_context' if short=='selection' else 'original_evaluated_command_selection'
 add(prefix+'original_context',owner,getter,receipt_file)
 add(prefix+'authenticate_response',receipt,'authenticate_original_command_response',receipt_file)
 add(prefix+'transfer',owner,'into_evaluated_command_owner',receipt_file)
 host='OriginalCircuitEvaluated'+kind+'CommandOwnerV1';client='OriginalCircuitEvaluated'+kind+'CommandClientV1'
 for tag,method in [('host_bind','from_original_receipt_owner'),('host_serve','serve_commands'),('host_evidence_serve','serve_evidence_readback')]:
  add(prefix+tag,host,method,'circuit_evaluated_'+short+'_command_service.rs')
 for tag,method,file in [
  ('create','from_original_stream','command.rs'),('recover','recover_from_original_stream','command.rs'),
  ('stage_bind','bind_original_stage_channel','command_context.rs'),('stage_recover','recover_original_stage_channel','command_context.rs'),
  ('execute','execute_selection' if short=='selection' else 'attest_completed_task','command.rs'),
  ('readback','readback','command.rs'),('attestation','receipt_attestation','command.rs'),
 ]:add(prefix+tag,client,method,'circuit_evaluated_'+short+'_'+file)

index={str(p.relative_to(OVER)):strip(p.read_text()) for p in OVER.rglob('*.rs') if not proof._is_ignored(str(p.relative_to(OVER)),tuple(m['ignored_path_fragments']))}
fields={}
def matched(row,path,code):
 if path==row['definition_path']:return False
 receiver=row.get('receiver_type')
 if receiver:
  if receiver not in fields:fields[receiver]=proof.authority_fields(index,receiver)
  return any(proof.has_authority_call(code,receiver,method,fields[receiver]) for method in row.get('receiver_methods') or [row['symbol'].rsplit('::',1)[-1]])
 return bool(re.search(row.get('call_pattern') or re.escape(row['symbol'])+r'\s*\(',code))
boundary_changes=[];ownpaths=set(own);externalpaths={x['path'] for x in external}
for row in m['boundary']:
 previous=next((b for b in base_manifest['boundary'] if b['id']==row['id']),None)
 is_new=previous is None
 # Only derive deltas that can intersect our actual new/changed code or our
 # own boundary definitions; other agents' API inventories remain theirs.
 shared_external={
  'learning_original_material_dataset_context_check':{P+'circuit_evaluated_completion_readiness.rs'},
  'learning_original_owner_command_channel':{P+'circuit_evaluated_version_readiness.rs'},
  'learning_original_published_read_client_current':{P+'circuit_evaluated_version_commands.rs'},
 }
 candidates=set(index) if is_new else ownpaths | (externalpaths if row['definition_path'] in protected else set()) | shared_external.get(row['id'],set())
 method=row['symbol'].rsplit('::',1)[-1]
 if not is_new and not any(re.search(r'\b'+re.escape(method)+r'\s*(?:\(|::|<)',index.get(path,'')) for path in candidates):continue
 actual=set(path for path in candidates if path in index and matched(row,path,index[path]))
 if is_new:expected=actual
 else:
  expected=set(previous['product_callers'])
  expected-=ownpaths-actual
  expected|=actual
 row['product_callers']=(sorted(expected) if is_new else
     [path for path in previous['product_callers'] if path in expected]
     +sorted(expected-set(previous['product_callers'])))
 if is_new or row!=previous:
  boundary_changes.append({'id':row['id'],'before':previous,'after':copy.deepcopy(row),'observed_own':sorted(actual&ownpaths),'observed_external':sorted(actual&externalpaths)})
def value(x):
 if isinstance(x,bool):return 'true' if x else 'false'
 if isinstance(x,str):return json.dumps(x,ensure_ascii=False)
 if isinstance(x,list):return '['+', '.join(value(v) for v in x)+']'
 if isinstance(x,dict):return '{'+', '.join(k+' = '+value(v) for k,v in x.items())+'}'
 return str(x)
text=(BASE/'postimages/CALLERS.toml').read_text()
def replace_table(text,kind,key,target,row):
 pattern=re.compile(r'\[\['+kind+r'\]\]\n(?:(?!\n\[\[|\n\[[^\[]).)*',re.S)
 for match in pattern.finditer(text):
  parsed=tomllib.loads(match[0])[kind][0]
  if parsed[key]==target:
   new='[['+kind+']]\n'+'\n'.join(k+' = '+value(v) for k,v in row.items())+'\n'
   return text[:match.start()]+new+text[match.end():]
 raise ValueError((kind,target))
for change in boundary_changes:
 if change['before'] is not None:text=replace_table(text,'boundary','id',change['id'],change['after'])
 else:text+='\n[[boundary]]\n'+'\n'.join(k+' = '+value(v) for k,v in change['after'].items())+'\n'
for change in changes:
 if change['before'] is not None:text=replace_table(text,'protected_file','path',change['path'],change['after'])
 else:text+='\n[[protected_file]]\n'+'\n'.join(k+' = '+value(v) for k,v in change['after'].items())+'\n'
ids=base_manifest['privileged_inventory']['required_boundary_ids']
old='required_boundary_ids = '+value(ids)
# The authoritative source uses a multi-line ID array; replace just this field.
text,n=re.subn(r'required_boundary_ids\s*=\s*\[.*?\]', 'required_boundary_ids = '+value(m['privileged_inventory']['required_boundary_ids']),text,count=1,flags=re.S);assert n==1
parsed=tomllib.loads(text)
assert parsed==m,'lossless original manifest plus explicit delta'
(OVER/'CALLERS.toml').write_text(text)
plan={'source_commit':'a96d1b821d10ed3d9e99dd06c5141f9f242ae318','source_tree':'f96bebefbc1e7d8187efadb62f88d524cdd18451','base_manifest':meta((BASE/'postimages/CALLERS.toml').read_bytes()),'inputs':inputs,'own_final_files':own,'external_caller_snapshots':external,'boundary_changes':boundary_changes,'protected_changes':changes,'new_inventory_ids':[x['id'] for x in adds],'before_counts':[541,389],'after_counts':[len(m['boundary']),len(m['protected_file'])],'qualification':'Source-only isolated plan; final full-Rust-index, native, ordinary and Root qualification remain unrun'}
(OUT/'CALLERS_DELTA_PLAN.json').write_text(json.dumps(plan,indent=2)+'\n')
(OUT/'GUARDED_FUNCTIONS.json').write_text(json.dumps(actual_functions,indent=2)+'\n')
print(json.dumps({'protected_changed':len(changes),'new_boundaries':len(adds),'boundary_rows_changed':len(boundary_changes),'counts':plan['after_counts'],'manifest':meta(text.encode()),'plan':meta((OUT/'CALLERS_DELTA_PLAN.json').read_bytes()),'legacy_forbidden_preserved':True},indent=2))
selected={'protected_file':[x['after'] for x in changes]}
proof._verify_protected_files(OVER,selected)
print('isolated protected rows PASS',len(changes))

