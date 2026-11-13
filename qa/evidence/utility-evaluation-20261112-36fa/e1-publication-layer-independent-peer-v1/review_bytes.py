from pathlib import Path
import hashlib,json,difflib
P=Path('/tmp/hepta-36fa-root-product-e1-proposal-v1/publication-layer-v1')
Q=Path('/tmp/hepta-36fa-root-product-e1-proposal-v1/lease-observation-increment-v1')
O=Path('/tmp/hepta-36fa-e1-publication-layer-independent-peer-v1')
O.mkdir(mode=0o700,exist_ok=True)
def pin(b):
 return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def put(name,obj):
 b=(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
 with (O/name).open('xb') as f:f.write(b)
 return pin(b)
M=json.loads((P/'MANIFEST.json').read_text())
raw=Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json').read_bytes()
assert pin(raw)=={'bytes':5631947,'sha256':'de044334afed8b804f2a997f8b8e8d16e6e1c596d2a5b3400c40f350229b054e','git_blob':'457adb9bf9ba3a844e9dfa149be49460bb306998'}
V=json.loads(raw)
assert V['source']=={'head':'b6084394a4a38ab495c16eaba09e879f04a96f8e','tree':'8ebb37e523ad3932a58cf016af0a9f4e0eeb6638','status':''}
R={r['path']:r for r in V['files']}
assert len(R)==len(V['files'])==15243
rows=[]
for row in M['files']:
 path=row['path'];a=(P/'after'/path).read_bytes()
 assert pin(a)==row['after']
 changes=[]
 if row['before'] is None:
  assert path not in R
 else:
  b=(P/'before'/path).read_bytes();bp=pin(b);assert bp==row['before']
  original=R[path]
  assert original['kind']=='file' and original['stable'] is True and original['matches_index'] is True
  assert original['index_mode']=='100644' and original['permissions']==420
  assert original['bytes']==bp['bytes'] and original['sha256']==bp['sha256']
  assert original['index_blob']==original['working_blob']==bp['git_blob']
  bl=b.splitlines(keepends=True);al=a.splitlines(keepends=True)
  inverse=al[:]
  ops=difflib.SequenceMatcher(a=bl,b=al,autojunk=False).get_opcodes()
  for tag,i,j,k,l in reversed(ops):
   if tag!='equal':
    assert tag=='insert',(path,tag)
    del inverse[k:l]
  assert b''.join(inverse)==b
  changes=[{'kind':tag,'before_line_offset':i,'after_line_offset':k,'added_bytes':len(b''.join(al[k:l])),'added_text':b''.join(al[k:l]).decode()} for tag,i,j,k,l in ops if tag!='equal']
 rows.append({'path':path,'before':row['before'],'after':row['after'],'baseline_match':True,'old_bytes_preserved_by_removing_exact_insertions':row['before'] is not None,'insertions':changes})
assert len(rows)==7 and sum(r['before'] is None for r in rows)==2
N=json.loads((Q/'MANIFEST.json').read_text());assert len(N['files'])==1
row=N['files'][0];path=row['path'];b=(Q/'before'/path).read_bytes();a=(Q/'after'/path).read_bytes()
assert pin(b)==row['before'] and pin(a)==row['after']
assert b==(P/'after'/path).read_bytes()
added=b'        if self.clock.now_unix_ms().map_err(invalid)? >= lease.expires_at_unix_ms {\n            return Err(invalid("original generation lease expired during readback"));\n        }\n        self.require_before()?;\n'
assert a.count(added)==1 and a.replace(added,b'',1)==b
put('LOCAL_AUDIT_FIRST_ERROR.json',{'kind':'local offline reviewer schema error','error':"KeyError: 'git_blob'",'scope':'Initial byte-check attempted a nonexistent inventory row key after first old file; original actual inventory uses index_blob and working_blob. No source or control execution occurred. This successor uses both explicit fields plus matches_index/stable/mode/bytes/SHA.','candidate_modified':False,'H_calls':0,'Rust_or_QA_calls':0})
proof={'format':'hepta-e1-publication-layer-independent-byte-proof-v1','status':'captured bytes matched; not compile/runtime proof','baseline_inventory':pin(raw),'manifest':pin((P/'MANIFEST.json').read_bytes()),'patch':pin((P/'SOURCE_DELTA.patch').read_bytes()),'source_rows':rows,'lease_increment':{'manifest':pin((Q/'MANIFEST.json').read_bytes()),'patch':pin((Q/'SOURCE_DELTA.patch').read_bytes()),'path':path,'before':pin(b),'after':pin(a),'only_four_lines_added':True,'inverse_full_bytes_equal':True},'counts':{'covered_paths':7,'old_files':5,'new_files':2,'old_source_removals_or_replacements':0,'lease_delta_lines':4},'source_objects_created':False,'H_calls':0,'Rust_compile_fmt_tests_QA':0}
print(json.dumps({'file':'BYTE_PROOF.json',**put('BYTE_PROOF.json',proof)}))
