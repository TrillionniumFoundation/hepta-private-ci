"""Prove the explicit old-QA caller additions against actual code, before edits."""
from pathlib import Path
import ast,hashlib,importlib.util,json,re,sys,tomllib
sys.dont_write_bytecode=True
R=Path(__file__).resolve().parent;O=R/'overlay';A='codex-rs/hepta-agentd/src/'
ADDITIONS={
 'learning_evidence_original_owner_readback':['circuit_evaluated_version_commands.rs'],
 'learning_original_published_read_client_current':['circuit_evaluated_next_use_remote.rs','circuit_evaluated_version_commands.rs'],
 'learning_original_dataset_readback_context':['circuit_evaluated_version_host.rs'],
 'learning_original_owner_command_channel':['circuit_evaluated_next_use_command.rs','circuit_evaluated_next_use_command_service.rs','circuit_evaluated_selection_command.rs','circuit_evaluated_selection_command_service.rs','circuit_evaluated_selection_readback_owner.rs','circuit_evaluated_selection_remote_readback.rs','circuit_evaluated_version_readiness.rs','circuit_evaluated_completion_readiness_service.rs'],
 'learning_original_owner_snapshot_encode':['circuit_evaluated_learning_read.rs','circuit_evaluated_next_use_command_context.rs','circuit_evaluated_next_use_command_wire.rs','circuit_evaluated_selection_command_context.rs','circuit_evaluated_selection_command_wire.rs','circuit_evaluated_version_context.rs'],
 'learning_original_owner_snapshot_decode':['circuit_evaluated_next_use_command_wire.rs','circuit_evaluated_selection_command_wire.rs'],
 'learning_original_material_initial_context_check':['circuit_evaluated_version_context.rs','circuit_evaluated_version_host.rs'],
 'learning_original_material_dataset_context_check':['circuit_evaluated_completion_readiness.rs','circuit_evaluated_next_use_command_context.rs','circuit_evaluated_selection_command_context.rs','circuit_evaluated_version_context.rs','circuit_evaluated_version_host.rs'],
 'cell_q24_original_training_pair_binding':['cell_q24_training_source_read_lane.rs'],
}
MEANINGS={
 'learning_evidence_original_owner_readback':'Closed Version C factory reads the same original Selector signature, compares the complete attestation, then rechecks its original publication.',
 'learning_original_published_read_client_current':'Evaluated remote C and Version closed factories consume the original bounded read client and verify actual Source/Cell evidence; no owner or new channel is manufactured.',
 'learning_original_dataset_readback_context':'Fresh and recovered evaluated Version host bind the existing Dataset readback to the exact original Material context before storing custody.',
 'learning_original_owner_command_channel':'Explicit evaluated S/C command, readonly S and evaluated readiness transports use the existing original owner channel constructor with frozen purposes and original bounds.',
 'learning_original_owner_snapshot_encode':'The separate evaluated read/S/C/Version domains encode their exact full snapshot pins through the original codec.',
 'learning_original_owner_snapshot_decode':'The evaluated S/C wire decoders use the same original snapshot decoder before exact request and receipt checks.',
 'learning_original_material_initial_context_check':'Evaluated Version cut and host perform the original Material initial-context authentication.',
 'learning_original_material_dataset_context_check':'Evaluated readiness, S/C command contexts and Version cut/host authenticate the original complete Dataset against its original Material context.',
 'cell_q24_original_training_pair_binding':'The private source-read transaction keeps the actual mutable native Training owner bound to the original Dataset/scope before starting source readback.',
}
spec=importlib.util.spec_from_file_location('source57_actual_edge_proof',O/'scripts/verify_hepta_callers.py');P=importlib.util.module_from_spec(spec);sys.modules[spec.name]=P;spec.loader.exec_module(P)
m=tomllib.loads((O/'CALLERS.toml').read_text());rows={r.identifier:r for r in P._boundary_rows(m)}
paths={p for name in ADDITIONS for p in [rows[name].definition_path,*rows[name].product_callers]}
raw={p:(O/p).read_text() for p in paths};code={p:P._strip_cfg_test_items(P._strip_rust_non_code(text)) for p,text in raw.items()}
def meta(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def call_end(mask,start):
 par=mask.index('(',start);depth=0
 for i in range(par,len(mask)):
  if mask[i]=='(':depth+=1
  elif mask[i]==')':
   depth-=1
   if depth==0:return i+1
 raise AssertionError('call end')
def functions(mask):
 out=[]
 for hit in re.finditer(r'\bfn\s+(\w+)\s*(?:<|\()',mask):
  end=P._rust_item_end(mask,hit.start())
  if end is not None:out.append((hit.start(),end+1,hit.group(1)))
 return out
reports=[];checks=[]
for name,names in ADDITIONS.items():
 row=rows[name];fields=P.authority_fields(code,row.receiver_type) if row.receiver_type else {}
 observed={p for p,c in code.items() if p!=row.definition_path and (P.has_authority_call(c,row.receiver_type,row.symbol.rsplit('::',1)[-1],fields) if row.receiver_type else re.search(re.escape(row.symbol)+r'\s*\(',c))}
 assert observed==set(row.product_callers),(name,sorted(observed),row.product_callers)
 P._verify_boundary(O,row,code,())
 for file in names:
  path=A+file;assert path in observed
  source=raw[path];mask=code[path];method=row.symbol.rsplit('::',1)[-1]
  pattern=(re.escape(row.symbol)+r'\s*\(') if not row.receiver_type else r'(?:\b'+re.escape(row.receiver_type)+r'\s*::\s*'+re.escape(method)+r'|\.\s*'+re.escape(method)+r')\s*\('
  calls=[];spans=functions(mask)
  for hit in re.finditer(pattern,mask):
   enclosing=[x for x in spans if x[0]<=hit.start()<x[1]]
   assert enclosing,(name,path,hit.start())
   fn=min(enclosing,key=lambda x:x[1]-x[0]);end=call_end(mask,hit.start());line=mask[:hit.start()].count('\n')+1
   calls.append({'line':line,'function':fn[2],'call':source[hit.start():end],'function_signature':source[fn[0]:source.index('{',fn[0],fn[1])].strip(),'typed_occurrence':row.receiver_type is None or row.receiver_type+'::'+method in re.sub(r'\s+','',mask[hit.start():end]),'receiver_type_occurrences':[(i+1,l.strip()) for i,l in enumerate(source.splitlines()) if row.receiver_type and row.receiver_type in l]})
  assert calls,(name,path)
  # Deleting this actual newly-registered source and cloning that source into
  # an unregistered path must both fail the unchanged original scanner.
  missing=dict(code);missing.pop(path)
  try:P._verify_boundary(O,row,missing,())
  except P.VerificationFailure as e:assert 'missing=' in str(e)
  else:raise AssertionError('new edge not required '+path)
  extra=dict(code);extra[A+'unregistered_actual_source57.rs']=mask
  try:P._verify_boundary(O,row,extra,())
  except P.VerificationFailure as e:assert 'unexpected=' in str(e),str(e)
  else:raise AssertionError('copied actual edge accepted '+path)
  reports.append({'boundary':name,'symbol':row.symbol,'receiver_type':row.receiver_type,'path':path,**meta(source.encode()),'original_scanner_observed_this_actual_file':True,'actual_calls':calls,'purpose':MEANINGS[name],'deletion_attack':'REJECTED_MISSING','same_actual_code_unregistered_attack':'REJECTED_UNEXPECTED'})
 checks.append({'boundary':name,'actual_observed_callers':sorted(observed),'registry_matches_observed':True,'new_callers':[A+x for x in names]})
# Independent literal additions for seven data tables. They must be exactly the
# explicit reviewed paths; no existing caller may disappear or reorder.
migrations=[]
for p in sorted((R/'base/qa/b4-no-bypass').glob('*.py')):
 env={};tree=ast.parse(p.read_text())
 for node in tree.body:
  if not isinstance(node,ast.Assign) or len(node.targets)!=1 or not isinstance(node.targets[0],ast.Name):continue
  value=node.value
  if not all(isinstance(x,(ast.Constant,ast.Name,ast.Load,ast.Tuple,ast.List,ast.Dict,ast.BinOp,ast.Add)) for x in ast.walk(value)):continue
  try:v=eval(compile(ast.Expression(value),'<closed source constants>','eval'),{'__builtins__':{}},env)
  except (NameError,TypeError,ValueError):continue
  env[node.targets[0].id]=v
 for key in ('CALLERS','EXPECTED'):
  for name,before in env.get(key,{}).items():
   after=list(rows[name].product_callers)
   if list(before)==after:continue
   assert name in ADDITIONS,(p.name,name)
   additions=[A+x for x in ADDITIONS[name]]
   assert after==list(before)+additions,(p.name,name,before,after,additions)
   migrations.append({'path':'qa/b4-no-bypass/'+p.name,'boundary':name,'before':list(before),'after':after,'additions':additions})
result={'status':'ACTUAL_TYPED_AND_FREE_CALLER_ADDITIONS_PROVED','source':'57b27c81d0d5321b873ee751fd0e58e1d905b988','scanner':meta((O/'scripts/verify_hepta_callers.py').read_bytes()),'registry':meta((O/'CALLERS.toml').read_bytes()),'scope':'the nine affected edges over their actual source declarations/callers; not the full repository index','unique_added_edges':len(reports),'records':reports,'boundaries':checks,'literal_migrations':migrations,'source_registry_verifier_changed':False,'qualification':0}
(R/'TYPED_EDGE_EVIDENCE.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':result['status'],'new_edges':len(reports),'actual_calls':sum(len(x['actual_calls']) for x in reports),'dict_value_migrations':len(migrations)},indent=2))
