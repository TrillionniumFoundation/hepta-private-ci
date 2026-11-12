import base64,datetime,gzip,hashlib,json
from pathlib import Path
R=Path('/tmp')
def load(n):return json.loads((R/n).read_text())
def facts(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob_sha':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
base=load('hepta-36fa-b298-exact-file-map.json'); base_map={f['path']:f for f in base['entries']}
assert len(base_map)==14842
merge=load('hepta-36fa-fixed-b298-merge-input.json')
extra=load('hepta-36fa-final-extra-postimages.json')
overlay=load('hepta-36fa-rust-overlay-fixed-b298-prepared-v1.json')
om={f['path']:f for f in overlay['changes']}
changes={}
def add(path,raw,before,category):
 assert path not in changes
 if before is None:assert path not in base_map,(path,base_map.get(path))
 else:assert base_map[path]['sha']==before,(path,base_map[path]['sha'],before)
 assert facts(raw)['git_blob_sha']!=before,path
 changes[path]={'path':path,'mode':'100644','base_blob':before,'post':facts(raw),'category':category,'postimage_base64':base64.b64encode(raw).decode()}
for o in merge['overrides']:
 if o['before_blob'] is not None:assert facts(o['before'].encode())['git_blob_sha']==o['before_blob']
 assert facts(o['after'].encode())['git_blob_sha']==o['after_blob']
 add(o['path'],o['after'].encode(),o['before_blob'],'preserved_e8_fix')
guards=['codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_binding.rs','codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_verify.rs']
for path in guards:
 f=om[path];add(path,f['content'].encode(),f['before_blob'],'primary_eligible_requires_all_retention_eligible')
fixtures=['circuit_original_evaluation_task_support_tests.rs','circuit_selection_command_owner_tests.rs','circuit_next_use_command_owner_tests.rs','circuit_original_evaluation_provider_tests.rs']
for name in fixtures:
 path='codex-rs/hepta-agentd/src/'+name;f=om[path];add(path,f['content'].encode(),f['before_blob'],'fixture_precondition_repair')
m=json.loads(extra['nextuse_typed_trainer_manifest']['content']);a=extra['nextuse_typed_trainer_after']
path='codex-rs/hepta-agentd/src/circuit_next_use_receipt_owner.rs'
add(path,a['content'].encode(),'821125b04b65cb63d79ac7d5d1285fbaf3155204','explicit_original_trainer_reference')
m=json.loads(extra['native_panel_boxing_manifest']['content']);a=extra['native_panel_boxing_after']
add(m['path'],a['content'].encode(),m['before_blob'],'private_panel_fixture_boxed_future')
qa=load('hepta-36fa-merged-callers-qa-final-prepared.json')
assert qa['path_count']==19
for f in qa['files']:
 raw=base64.b64decode(f['postimage_base64']);assert facts(raw)==f['post']
 before=f['base']['git_blob_sha'] if f['base'] else None
 add(f['path'],raw,before,'original_callers_and_source_protection')
allow=extra['b298_final_prepared_allowlist'];line='sha256:42f75c0b463c6793048e3b5afd50b18f57e5e770a3b7fc9e89c1c4c29b532b91 CALLERS.toml\n'
assert line not in allow['content']
raw=(allow['content']+line).encode()
add(allow['path'],raw,allow['before_blob'],'exact_callers_blob_size_exception')
assert len(changes)==40
final_map={p:dict(f) for p,f in base_map.items()}
for p,f in changes.items():final_map[p]={'path':p,'mode':f['mode'],'sha':f['post']['git_blob_sha'],'type':'blob'}
def all_trees(file_map):
 dirs={}
 for path,f in file_map.items():
  parent,name=path.rsplit('/',1) if '/' in path else ('',path)
  dirs.setdefault(parent,{})[name]={'path':name,'mode':f['mode'],'sha':f['sha'],'type':f['type']}
  parts=parent.split('/') if parent else []
  for i in range(len(parts)):dirs.setdefault('/'.join(parts[:i]),{})
 result={}
 for path in sorted(dirs,key=lambda s:s.count('/')+(1 if s else 0),reverse=True):
  es=sorted(dirs[path].values(),key=lambda e:(e['path']+('/' if e['type']=='tree' else '')).encode())
  raw=b''.join((('40000' if e['type']=='tree' else e['mode'])+' '+e['path']).encode()+b'\0'+bytes.fromhex(e['sha']) for e in es)
  sha=hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
  result[path]={'path':path,'type':'tree','sha':sha,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'data_base64':base64.b64encode(raw).decode()}
  if path:
   parent,name=path.rsplit('/',1) if '/' in path else ('',path)
   dirs[parent][name]={'path':name,'mode':'040000','sha':sha,'type':'tree'}
 return result
bt=all_trees(base_map);ft=all_trees(final_map)
assert bt['']['sha']=='906546af39b07474f0b9d046a6e780b6d3342743'
changed_trees=[t for p,t in sorted(ft.items()) if p not in bt or t['sha']!=bt[p]['sha']]
canonical_inventory=json.dumps(sorted(final_map.values(),key=lambda x:x['path'].encode()),sort_keys=True,separators=(',',':')).encode()
packet={'schema':'hepta.utility.fixed-b298-integrated-source-preparation.v1','status':'prepared-not-formatted-not-compiled-not-tested','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_parent':'e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd','fixed_upstream':'b29869e856d08db1bfb066116a9c443376ccc57d','base_tree':base['tree'],'prepared_tree':ft['']['sha'],'base_file_count':len(base_map),'prepared_file_count':len(final_map),'changes':[changes[p] for p in sorted(changes)],'new_tree_objects':changed_trees,'expected_source_entries':sorted(final_map.values(),key=lambda x:x['path'].encode()),'expected_source_inventory_sha256':hashlib.sha256(canonical_inventory).hexdigest(),'native_instructions':['Require original e8 exact source and retained independent e8 checkout before changing isolated review source.','Require exact complete b298 tip tree objects independently of preserved failed full-history fsck.','Import each supplied blob and tree by exact raw object bytes and verify Git SHA; never weaken or mask fsck.','Stage only this complete prepared tree in the owned isolated review checkout; no published source ref is moved by this packet.','Run the already authorized original scoped just fix and formatting commands. Capture full source before and after and all actual changed postimages before a new canonical published commit is created.','No original qualification test pass is transferred to this prepared source. Use original just test, stack sizes, test inventory, limits and full evidence when final source is frozen.'],'not_claimed':['source or caller gate PASS','Rust runtime PASS','full history fsck PASS','independent real task results','ordinary A/B/C completion','daemon or Root cold recovery','production activation']}
raw=(json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
out=R/'hepta-36fa-integrated-source-prepared-v1';out.mkdir(exist_ok=True)
(out/'packet.json').write_bytes(raw);gz=gzip.compress(raw,mtime=0);(out/'packet.json.gz').write_bytes(gz)
enc=base64.b64encode(gz).decode()
parts=[]
for n,offset in enumerate(range(0,len(enc),450000)):
 b=(enc[offset:offset+450000]+'\n').encode();name=f'packet.part-{n:02}.b64';(out/name).write_bytes(b);parts.append({'name':name,**facts(b)})
allowbytes=base64.b64decode(changes[allow['path']]['postimage_base64']);(out/'blob-size-allowlist.txt').write_bytes(allowbytes)
manifest={k:v for k,v in packet.items() if k not in ('changes','new_tree_objects','expected_source_entries')}
manifest.update({'changes':[{k:v for k,v in f.items() if k!='postimage_base64'} for f in packet['changes']],'new_tree_objects':[{k:v for k,v in t.items() if k!='data_base64'} for t in changed_trees],'packet_raw':facts(raw),'packet_gzip':facts(gz),'parts':parts,'reviewed_callers_blob':'2354abb1eb485629ecdf17a2e8952a529b8df384','root_v32_review_blob':'e17bd192f8579404ba1099ef3c5ac9017f903a72','root_boxing_build_deep_review_blob':'3012e25c0b8957e8018202ac473b13af0e47600c','root_typed_reference_review_blob':'f97477ec9d1d347c7284ea47a3b0dc30b376c9ac','retention_positive_branch_runtime_coverage':'Unavailable under inspected deterministic real-provider/frozen-plan construction; source proof aefd229fdce01e1d7d4101998c9f33ee0825977c; never fabricate positive qualification'})
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(out/'tree-elements.json').write_text(json.dumps([{'path':f['path'],'mode':f['mode'],'type':'blob','sha':f['post']['git_blob_sha']} for f in packet['changes']]))
print(json.dumps({'directory':str(out),'changed_paths':len(changes),'base_files':len(base_map),'prepared_files':len(final_map),'prepared_tree':ft['']['sha'],'new_tree_objects':len(changed_trees),'raw_bytes':len(raw),'gzip_bytes':len(gz),'parts':parts,'allowlist':facts(allowbytes),'categories':{x:sum(1 for f in changes.values() if f['category']==x) for x in sorted({f['category'] for f in changes.values()})}},ensure_ascii=False))

