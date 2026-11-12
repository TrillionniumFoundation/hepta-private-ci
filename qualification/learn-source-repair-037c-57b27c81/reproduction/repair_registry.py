"""Register only three demonstrated exact-57b callers; keep all other bytes."""
from pathlib import Path
import copy,difflib,hashlib,importlib.util,json,re,shutil,sys,tomllib

sys.dont_write_bytecode=True
R=Path(__file__).resolve().parent; O=R/'overlay'; OUT=R/'registry'; OUT.mkdir(exist_ok=False)
A='codex-rs/hepta-agentd/src/'
BASE_SHA='abd68af6b993cb2b363c1909581b628e6f94bab0696eff2e55120d5cf9d2f4b9'
ADDITIONS={
 'learning_original_owner_command_channel': A+'cell_q24_training_command_readback_service.rs',
 'learning_original_evaluation_host_profile': A+'neuron_cell_evaluation_host_training_readback.rs',
 'learning_original_evaluation_host_constructor': A+'neuron_cell_evaluation_host_training_readback.rs',
}
def meta(b): return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
before=(O/'CALLERS.toml').read_bytes(); assert meta(before)['sha256']==BASE_SHA
(R/'base/CALLERS.toml').write_bytes(before)
factory=A+'neuron_cell_evaluation_host_training_readback.rs'
fb=(R/'exact-new-dependencies'/factory).read_bytes(); assert meta(fb)['blob']=='6c8e5ae94ff4753a48cb92c6b46b8a7559f00793'
(O/factory).write_bytes(fb)
source=before.decode(); bm=tomllib.loads(source); rewritten=source; changes=[]
for name,path in ADDITIONS.items():
 positions=[i for i,x in enumerate(bm['boundary']) if x['id']==name]; assert len(positions)==1
 index=positions[0]; old=bm['boundary'][index]; assert path not in old['product_callers']
 new=copy.deepcopy(old); new['product_callers'].append(path)
 start=rewritten.rfind('[[boundary]]',0,rewritten.index('id = '+json.dumps(name)))
 end=rewritten.find('\n[[',start+1); end=len(rewritten) if end<0 else end
 oldblock=rewritten[start:end]
 line=re.search(r'^product_callers = (\[[^\n]*\])$',oldblock,re.M); assert line
 assert json.loads(line.group(1))==old['product_callers']
 replacement='product_callers = '+json.dumps(new['product_callers'])
 newblock=oldblock[:line.start()]+replacement+oldblock[line.end():]
 rewritten=rewritten[:start]+newblock+rewritten[end:]
 changes.append({'index':index,'id':name,'added_caller':path,'before':old,'after':new,'before_raw':oldblock,'after_raw':newblock})
after=rewritten.encode(); am=tomllib.loads(rewritten)
expected=copy.deepcopy(bm)
for x in changes: expected['boundary'][x['index']]=x['after']
assert am==expected
assert len(am['boundary'])==607 and len(am['protected_file'])==425
assert am['protected_file']==bm['protected_file']
assert all(am[k]==bm[k] for k in bm if k!='boundary')
for i,(x,y) in enumerate(zip(bm['boundary'],am['boundary'])):
 if x['id'] in ADDITIONS:
  assert y['product_callers']==x['product_callers']+[ADDITIONS[x['id']]]
  assert {k:v for k,v in x.items() if k!='product_callers'}=={k:v for k,v in y.items() if k!='product_callers'}
 else: assert x==y
patch=''.join(difflib.unified_diff(source.splitlines(keepends=True),rewritten.splitlines(keepends=True),fromfile='a/CALLERS.toml',tofile='b/CALLERS.toml'))
(OUT/'CALLERS.toml').write_bytes(after); (OUT/'CALLERS.patch').write_text(patch)
spec=importlib.util.spec_from_file_location('source57_registry_gap_proof',O/'scripts/verify_hepta_callers.py'); P=importlib.util.module_from_spec(spec);sys.modules[spec.name]=P;spec.loader.exec_module(P)
br={x.identifier:x for x in P._boundary_rows(bm)};ar={x.identifier:x for x in P._boundary_rows(am)}
paths={p for name,path in ADDITIONS.items() for p in [br[name].definition_path,*br[name].product_callers,path]}
raw={p:(O/p).read_text() for p in paths}; codes={p:P._strip_cfg_test_items(P._strip_rust_non_code(t)) for p,t in raw.items()}
def rejects(row,index,reason):
 try: P._verify_boundary(O,row,index,())
 except P.VerificationFailure as e:
  assert reason in str(e),(reason,str(e)); return str(e)
 raise AssertionError('original scanner did not reject '+row.identifier)
proofs=[]
for name,path in ADDITIONS.items():
 old=br[name];new=ar[name]
 fail=rejects(old,codes,'unexpected='); assert path in fail
 P._verify_boundary(O,new,codes,())
 missing=dict(codes);missing.pop(path);missing_fail=rejects(new,missing,'missing='); assert path in missing_fail
 extra=dict(codes);extra[A+'unregistered_same_original_owner.rs']=codes[path]
 extra_fail=rejects(new,extra,'unexpected='); assert 'unregistered_same_original_owner.rs' in extra_fail
 changed=copy.deepcopy(am)
 for row in changed['boundary']:
  if row['id']==name: row['product_callers'].remove(path)
 deleted={x.identifier:x for x in P._boundary_rows(changed)}[name]
 deletion_fail=rejects(deleted,codes,'unexpected='); assert path in deletion_fail
 symbol=old.symbol;pattern=re.escape(symbol)+r'\s*\('
 hits=[{'line':codes[path][:h.start()].count('\n')+1,'call_start':raw[path][h.start():h.start()+180]} for h in re.finditer(pattern,codes[path])]
 assert hits,(name,path)
 proofs.append({'id':name,'path':path,'symbol':symbol,'source':meta(raw[path].encode()),'actual_calls':hits,'before':'FAIL','before_error':fail,'after':'PASS','remove_registered_real_source':'REJECTED','remove_error':missing_fail,'append_unregistered_actual_source':'REJECTED','unregistered_error':extra_fail,'delete_only_added_registration':'REJECTED','delete_registration_error':deletion_fail})
result={'source':'57b27c81d0d5321b873ee751fd0e58e1d905b988','base_registry':meta(before),'after_registry':meta(after),'patch':meta(patch.encode()),'boundary_count':607,'protected_count':425,'exact_changed_boundary_count':3,'protected_rows_including_duplicates_unchanged':True,'all_other_top_level_fields_unchanged':True,'all_noncaller_fields_unchanged':True,'all_old_callers_preserved_in_order':True,'scanner':meta((O/'scripts/verify_hepta_callers.py').read_bytes()),'typed_scanner':meta((O/'scripts/hepta_typed_callers.py').read_bytes()),'proof_scope':'Exact 57b source files for the three actual boundaries; local original scanner proof, not whole-repository verification.','proof_inputs':[{'path':p,**meta(raw[p].encode())} for p in sorted(raw)],'changes':changes,'proofs':proofs,'source_products_changed':False,'scanner_changed':False,'authority_changed':False,'allowlist_changed':False,'full_source_gate':False,'fullcaller':False,'native':False,'ordinary_qualification':0}
(OUT/'REGISTRY_REPAIR_PROOF.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('base_registry','after_registry','boundary_count','protected_count','exact_changed_boundary_count')},indent=2))
