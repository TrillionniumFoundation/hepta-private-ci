import ast,base64,copy,datetime,gzip,hashlib,json,re,tomllib
from pathlib import Path
R=Path('/tmp')
def load(name):return json.loads((R/name).read_text())
def facts(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob_sha':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def funs(s):return {n.name:(ast.dump(n,include_attributes=False),ast.get_source_segment(s,n)) for n in ast.walk(ast.parse(s)) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
inp=load('hepta-36fa-v32-review-input.json')
for k,v in inp.items():assert facts(v['content'].encode())['git_blob_sha']==v['sha'],k
manifest=json.loads(inp['readback_v32_manifest']['content'])
packetraw=gzip.decompress(base64.b64decode(inp['readback_v32_packet_b64']['content']))
assert facts(packetraw)['bytes']==1840348 and facts(packetraw)['sha256']=='ff64105a74fecf7830528376f73145272157595832f5463b421ecea91e327476'
packet=json.loads(packetraw);assert len(packet['files'])==9
assert packet['requires_preparation_manifest_blob']=='36f339c163bf0ac8449891c06a954f56b004825b'
assert packet['requires_callers_blob']=='155282ec6dd93e2637659a73da10eb2f3936a7b3'
assert packet['full_source_tree'] is None
merged={};base_identities={};chain=[]
for version in ('v2','v3','v31'):
 p=load('hepta-36fa-readback-'+version+'-packet.json')
 for f in p['files']:
  b=base64.b64decode(f['postimage_base64']);assert facts(b)==f['post']
  if f['path'] in merged:assert facts(merged[f['path']])==f['base']
  else:base_identities[f['path']]=f['base']
  merged[f['path']]=b
for e in load('hepta-36fa-v32-extra-bases.json'):
 b=e['content'].encode();assert facts(b)['git_blob_sha']==e['sha'];merged[e['path']]=b
before=merged.copy();verified=[]
for f,s in zip(packet['files'],manifest['files']):
 assert f['path']==s['path'] and f['mode']==s['mode']=='100644'
 assert f['base']==s['base']
 if f['base'] is None:assert f['path'] not in before
 else:assert facts(before[f['path']])==f['base']
 b=base64.b64decode(f['postimage_base64']);assert facts(b)==f['post']==s['post']
 if f['path'] not in base_identities:base_identities[f['path']]=f['base']
 merged[f['path']]=b;verified.append({'path':f['path'],'base':f['base'],'post':f['post']})
old=tomllib.loads(before['CALLERS.toml'].decode());new=tomllib.loads(merged['CALLERS.toml'].decode())
assert old.keys()==new.keys()
assert {k:v for k,v in old.items() if k not in ('boundary','protected_file')}=={k:v for k,v in new.items() if k not in ('boundary','protected_file')}
assert len(old['boundary'])==len(new['boundary'])==534
expected={335:'circuit_selection_command_readback.rs',337:'circuit_evaluated_selection_readback_owner.rs',338:'circuit_selection_readback_host.rs',347:'cell_q24_model_command_host.rs',365:'circuit_next_use_readback_host.rs',459:'neuron_cell_evaluation_host_training_readback.rs',460:'neuron_cell_evaluation_model_material_export.rs',461:'neuron_cell_evaluation_host_training_readback.rs'}
actual_changes=[]
for i,(a,b) in enumerate(zip(old['boundary'],new['boundary'])):
 if a==b:continue
 assert i in expected
 assert {k:v for k,v in a.items() if k!='product_callers'}=={k:v for k,v in b.items() if k!='product_callers'}
 assert b['product_callers']==a['product_callers']+['codex-rs/hepta-agentd/src/'+expected[i]]
 actual_changes.append({'index':i,'id':a['id'],'added':b['product_callers'][-1]})
assert [x['index'] for x in actual_changes]==list(expected)
assert len(old['protected_file'])==399 and len(new['protected_file'])==409
assert len({r['path'] for r in new['protected_file']})==338
changes=[i for i,(a,b) in enumerate(zip(old['protected_file'],new['protected_file'])) if a!=b]
assert changes==[279]
mask=load('hepta-36fa-nextuse-typed-trainer-protected-mask.json')
a=copy.deepcopy(old['protected_file'][279]);b=new['protected_file'][279]
func=next(f for f in a['required_function_order'] if f['function']=='fn predecessors(')
assert func['sequence'][0]==mask['before']['text']
func['sequence'][0]=mask['after']['text'];assert a==b
prep={}
newrows=[];evidence=[]
for tag,rowname in [('edge','protected-row-fragments.json'),('evaluation','evaluation-host-protected-row-fragments.json')]:
 p=load('hepta-36fa-readback_v32_'+tag+'_prep_packet.json')
 fm={}
 for f in p['files']:
  raw=f['content'].encode();assert facts(raw)=={k:f[k] for k in ('bytes','sha256','git_blob_sha')},(tag,f['path'])
  fm[f['path']]=f
 prep[tag]=fm;newrows+=json.loads(fm[rowname]['content'])
 for f in fm.values():
  if f['path'].startswith('validation-source/qa/'):
   path=f['path'].removeprefix('validation-source/')
   assert merged[path]==f['content'].encode()
assert new['protected_file'][399:]==newrows
assert sum(len(r.get('required_function_order',[])) for r in newrows)==25
qa=[]
for f in packet['files']:
 path=f['path']
 if not path.endswith('.py') or f['base'] is None:continue
 prev=before[path].decode();cur=merged[path].decode()
 assert funs(prev)==funs(cur),path
 pa=ast.parse(prev);ca=ast.parse(cur)
 pe=next(n for n in pa.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='EXPECTED')
 ce=next(n for n in ca.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='EXPECTED')
 assert isinstance(pe.value,ast.Dict) and isinstance(ce.value,ast.Dict)
 assert [ast.dump(k,include_attributes=False) for k in pe.value.keys]==[ast.dump(k,include_attributes=False) for k in ce.value.keys]
 changed_keys=[ast.literal_eval(k) for k,v,w in zip(pe.value.keys,pe.value.values,ce.value.values) if ast.dump(v,include_attributes=False)!=ast.dump(w,include_attributes=False)]
 oldseg=ast.get_source_segment(prev,pe);newseg=ast.get_source_segment(cur,ce)
 assert prev.count(oldseg)==1 and prev.replace(oldseg,newseg,1)==cur,path
 ci=ca.body.index(ce);ca.body[ci]=copy.deepcopy(pe)
 assert ast.dump(pa,include_attributes=False)==ast.dump(ca,include_attributes=False)
 qa.append({'path':path,'functions_byte_and_ast_equal':len(funs(prev)),'changed_expected_keys':changed_keys,'only_expected_assignment_bytes_changed':True})
assert len(qa)==5 and sum(q['functions_byte_and_ast_equal'] for q in qa)==56
assert sum(len(q['changed_expected_keys']) for q in qa)==9
newqa=[]
for f in packet['files']:
 if not f['path'].endswith('.py') or f['base'] is not None:continue
 source=merged[f['path']].decode()
 methods=[n for n in funs(source) if n.startswith('test_')]
 assert '_source_files(' not in source
 newqa.append({'path':f['path'],'methods':methods,'count':len(methods),'git_blob_sha':f['post']['git_blob_sha']})
assert sorted(x['count'] for x in newqa)==[5,8,11]
cases=[('edge','scoped-tests-attempt1',16,1),('edge','scoped-tests-attempt2',16,0),('evaluation','scoped-qa',8,0)]
for tag,prefix,count,exitcode in cases:
 fm=prep[tag];run=json.loads(fm[prefix+'-result.json']['content']);raw=fm[prefix+'.raw.log']['content'];rb=raw.encode()
 assert len(rb)==run['raw_bytes'] and facts(rb)['sha256']==run['raw_sha256']
 assert run['returncode']==exitcode and run['source_inputs_unchanged']
 assert json.loads(fm[prefix+'-before.json']['content'])==json.loads(fm[prefix+'-after.json']['content'])
 assert re.search(r'Ran '+str(count)+r' tests in ',raw)
 if exitcode==0:
  assert '\nOK\n' in raw and len(re.findall(r'\.\.\. ok$',raw,re.M))==count
 else:assert 'FAILED ' in raw and 'self' in raw
 evidence.append({'run_blob':fm[prefix+'-result.json']['git_blob_sha'],'raw_blob':fm[prefix+'.raw.log']['git_blob_sha'],'actual_methods_run':count,'exit_code':exitcode,'source_inputs_unchanged':True,'scope':'isolated authored source-mutation preparation only'})
chainout={'schema':'hepta.utility.merged-callers-qa-prepared.v1','base_commit':'b29869e856d08db1bfb066116a9c443376ccc57d','path_count':len(merged),'files':[{'path':path,'mode':'100644','base':base_identities[path],'post':facts(raw),'postimage_base64':base64.b64encode(raw).decode()} for path,raw in sorted(merged.items())]}
(R/'hepta-36fa-merged-callers-qa-final-prepared.json').write_text(json.dumps(chainout,sort_keys=True,separators=(',',':'))+'\n')
review={'schema':'hepta.utility.root-v3.2-independent-review.v1','reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'prepared_not_integrated_no_full_gate_pass','manifest_blob':inp['readback_v32_manifest']['sha'],'packet_blob':inp['readback_v32_packet_b64']['sha'],'packet_raw':facts(packetraw),'verified_files':verified,'boundaries':{'before':534,'after':534,'exact_member_additions':actual_changes,'other_526_rows_equal':True,'other_top_level_metadata_equal':True},'protected':{'before':399,'after':409,'unique_paths':338,'existing_changed_rows':[279],'only_change':'exact separately reviewed typed Trainer match sequence[0]','same_evaluated_branch_and_all_other_fields':True,'new_rows_exact_from_original_local_qa_preparation':10,'nongeneric_function_scoped_entries':25,'generic_fallback_limit':'Existing file-level required_order is not a function uniqueness or formal proof guarantee.'},'existing_qa':qa,'original_functions_preserved':56,'new_qa':newqa,'actual_preparation_runs':evidence,'merged_callers_qa_paths':len(merged),'no_change_to':['original verifier','workflow','budgets','production Rust in this delta','authority','Git refs'],'not_claimed':['full source gate','full caller gate','native runtime pass','600-second source gate compliance','A/B/C qualification','adoption','cold recovery']}
out=R/'hepta-36fa-v32-independent-review.json';out.write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'review_file':str(out),'review':facts(out.read_bytes()),'merged_paths':len(merged),'exact_member_additions':len(actual_changes),'protected':409,'unique_paths':338,'existing_functions':56,'actual_new_methods_passed':24,'prior_failed_prep_retained':True}))

