import ast,base64,copy,gzip,hashlib,json,re,subprocess,tempfile,tomllib
from pathlib import Path
R=Path('/tmp')
def load(n):return json.loads((R/n).read_text())
def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def facts(b):return {'bytes':len(b),'sha256':sha(b),'git_blob_sha':blob(b)}
src=load('hepta-36fa-formatted-guard-marker-sync-review-input.json'); originals=load('hepta-36fa-formatted-guard-marker-sync-originals.json');om={x['path']:x for x in originals}
for x in src.values():assert blob(x['content'].encode())==x['sha']
for x in originals:assert facts(x['content'].encode())=={k:x[k] for k in ('bytes','sha256','git_blob_sha')}
m=json.loads(src['formatted_guard_marker_sync_manifest']['content']);packed=base64.b64decode(src['formatted_guard_marker_sync_packet']['content']);raw=gzip.decompress(packed);packet=json.loads(raw)
identity=json.loads(om['PACKET_IDENTITY.json']['content'])
assert facts(src['formatted_guard_marker_sync_packet']['content'].encode())==identity['encoded'] and facts(raw)==identity['decoded_json'] and identity['postimage_count']==3
prep=load('hepta-36fa-integrated-source-prepared-v1/packet.json');pc={x['path']:x for x in prep['changes']}
fm=load('hepta-36fa-post-maintenance-exact-file-map.json');assert fm['tree']=='faf047faf110c20115453766329bd2a66f303df7'
filemap={x['path']:dict(x) for x in fm['entries']};physical=load('hepta-36fa-post-maintenance-physical-inventory-expected.json');ph={x['path']:dict(x) for x in physical}
pre={};post={};assert len(packet['files'])==3
for f in packet['files']:
 path=f['path'];before=base64.b64decode(pc[path]['postimage_base64']);after=base64.b64decode(f['postimage_base64']);assert facts(before)==f['before'] and facts(after)==f['after'];assert filemap[path]['sha']==f['before']['git_blob_sha']
 pre[path]=before;post[path]=after;filemap[path]['sha']=blob(after);ph[path]={'path':path,'mode':f['mode'],'bytes':len(after),'sha256':sha(after),'blob':blob(after)}
b=tomllib.loads(pre['CALLERS.toml'].decode());a=tomllib.loads(post['CALLERS.toml'].decode());assert len(a['boundary'])==len(b['boundary'])==534 and a['boundary']==b['boundary'];assert len(a['protected_file'])==len(b['protected_file'])==409
diff=[]
def deep(x,y,path=()):
 assert type(x)==type(y),(path,type(x),type(y))
 if isinstance(x,dict):
  assert x.keys()==y.keys()
  for k in x:deep(x[k],y[k],path+(k,))
 elif isinstance(x,list):
  assert len(x)==len(y)
  for i,(u,v) in enumerate(zip(x,y)):deep(u,v,path+(i,))
 elif x!=y:diff.append({'path':list(path),'before':x,'after':y})
deep(b,a)
expected=[['protected_file',338,'required_function_order',1,'sequence',21],['protected_file',338,'required_function_order',1,'top_level',2],['protected_file',389,'required_function_order',0,'sequence',56],['protected_file',389,'required_function_order',0,'top_level',10]]
assert [x['path'] for x in diff]==expected
for x in diff:assert re.sub(r'\s+','',x['before'])==re.sub(r'\s+','',x['after'])
qpath='qa/b4-no-bypass/test_original_evaluation_retention_guard_source_closure.py';qb=ast.parse(pre[qpath]);qa=ast.parse(post[qpath]);oldc=[n.value for n in ast.walk(qb) if isinstance(n,ast.Constant)];newc=[n.value for n in ast.walk(qa) if isinstance(n,ast.Constant)];assert len(oldc)==len(newc)
constchanges=[(x,y) for x,y in zip(oldc,newc) if x!=y];assert len(constchanges)==4 and all(isinstance(x,str) and re.sub(r'\s+','',x)==re.sub(r'\s+','',y) for x,y in constchanges)
mapping={new:old for old,new in constchanges}
for n in ast.walk(qa):
 if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value in mapping:n.value=mapping[n.value]
assert ast.dump(qa,include_attributes=False)==ast.dump(qb,include_attributes=False)
assert len([n for n in ast.walk(qb) if isinstance(n,ast.FunctionDef)])==6
allow='.github/blob-size-allowlist.txt';line=('sha256:'+sha(post['CALLERS.toml'])+' CALLERS.toml\n').encode();assert line not in pre[allow] and post[allow]==pre[allow]+line
old_inv=json.loads(om['records/old-markers/source-before.json']['content']);new_inv=json.loads(om['records/synchronized-markers/source-before.json']['content']);assert len(old_inv)==len(new_inv)==7
assert om['records/old-markers/source-before.json']['content']==om['records/old-markers/source-after.json']['content'];assert om['records/synchronized-markers/source-before.json']['content']==om['records/synchronized-markers/source-after.json']['content']
changed_inputs=[p for p in old_inv if old_inv[p]!=new_inv[p]];assert set(changed_inputs)==set(pre)
for path in pre:
 assert old_inv[path]==facts(pre[path]) and new_inv[path]==facts(post[path])
for path in old_inv:
 if path not in pre:assert old_inv[path]==new_inv[path] and old_inv[path]['git_blob_sha']==filemap[path]['sha']
for phase,rc in [('old-markers',1),('synchronized-markers',0)]:
 result=json.loads(om['records/'+phase+'/result.json']['content']);log=om['records/'+phase+'/raw.log']['content'];assert result['returncode']==rc and not result['timed_out'] and result['source_unchanged'] and facts(log.encode())==result['raw_log'];assert 'Ran 3 tests' in log
 if phase=='old-markers':assert 'FAILED (failures=2, errors=1)' in log and len(re.findall(r'^test_.* \.\.\. FAIL$',log,re.M))==2 and len(re.findall(r'^test_.* \.\.\. ERROR$',log,re.M))==1
 else:assert len(re.findall(r'^test_.* \.\.\. ok$',log,re.M))==3 and log.endswith('\nOK\n')
ast.parse(om['run_three_methods.py']['content'])
with tempfile.TemporaryDirectory(prefix='hepta-36fa-marker-diff-') as d:
 d=Path(d)
 for path,content in pre.items():(d/path).parent.mkdir(parents=True,exist_ok=True);(d/path).write_bytes(content)
 pp=d/'sync.patch';pp.write_text(src['formatted_guard_marker_sync_patch']['content']);subprocess.run(['git','apply','--check',str(pp)],cwd=d,check=True,capture_output=True);subprocess.run(['git','apply',str(pp)],cwd=d,check=True,capture_output=True);assert all((d/path).read_bytes()==content for path,content in post.items())
mod=ast.parse((R/'hepta-36fa-compose-final-source.py').read_text());fn=next(n for n in mod.body if isinstance(n,ast.FunctionDef) and n.name=='all_trees');exec(compile(ast.Module(body=[fn],type_ignores=[]),'<tree-reconstructor>','exec'))
trees=all_trees(filemap);raw_inventory=json.dumps(sorted(ph.values(),key=lambda x:x['path'].encode()),sort_keys=True,separators=(',',':')).encode();assert len(ph)==14851
out=R/'hepta-36fa-final-formatted-source';out.mkdir(exist_ok=True)
(out/'expected-physical-inventory.json').write_bytes(raw_inventory);(out/'expected-leaf-map.json').write_text(json.dumps({'tree':trees['']['sha'],'entries':list(filemap.values())})+'\n')
prepmap={x['path']:x for x in prep['expected_source_entries']};oldtrees=all_trees(prepmap);newtrees=[v for k,v in trees.items() if k not in oldtrees or v['sha']!=oldtrees[k]['sha']]
elements=[]
for path,f in filemap.items():
 if prepmap[path]['sha']!=f['sha']:elements.append({'path':path,'mode':f['mode'],'type':'blob','sha':f['sha']})
assert len(elements)==6
(out/'source-tree-elements.json').write_text(json.dumps(elements)+'\n');(out/'new-tree-objects.json').write_text(json.dumps(newtrees)+'\n')
report={'schema':'hepta.utility.formatted-guard-marker-root-review.v1','status':'reviewed-source-ready-for-non-Rust-native-application-and-publication','native_maintenance_tree':fm['tree'],'final_source_tree':trees['']['sha'],'source_files':len(ph),'expected_physical_inventory_bytes':len(raw_inventory),'expected_physical_inventory_sha256':sha(raw_inventory),'actual_original_evidence_placements_checked':len(originals),'boundary_count':534,'protected_count':409,'caller_leaf_changes':diff,'qa_constant_changes':constchanges,'other_qa_AST_equal':True,'original_qa_function_count':6,'old_actual_test_result':{'methods':3,'passed':0,'failed':2,'errors':1,'exit':1},'new_actual_test_result':{'methods':3,'passed':3,'failed':0,'errors':0,'exit':0},'both_runs_source_unchanged':True,'only_three_non_Rust_inputs_differ_between_runs':True,'all_original_534_boundaries_unchanged':True,'all_other_protected_fields_unchanged':True,'exact_allowlist_append':line.decode().strip(),'final_delta_from_prepared_a8':elements,'new_tree_objects':len(newtrees),'not_claimed':['full source closure pass','full caller pass','Rust behavior test pass','positive retention guard runtime coverage','real authorized ordinary A/B/C qualification']}
(out/'ROOT_REVIEW.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'tree':trees['']['sha'],'files':len(ph),'inventory_bytes':len(raw_inventory),'inventory_sha256':sha(raw_inventory),'new_trees':len(newtrees),'changed_from_a8':len(elements),'review':str(out/'ROOT_REVIEW.json')}))

