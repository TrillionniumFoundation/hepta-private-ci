import pathlib,json,hashlib,base64,gzip,datetime
P=pathlib.Path('/tmp/hepta-36fa-a96-recovery')
def sha(b): return hashlib.sha256(b).hexdigest()
def gid(b,t='blob'): return hashlib.sha1(t.encode()+b' '+str(len(b)).encode()+b'\0'+b).hexdigest()
def checked(b,n,s,g):
 assert (len(b),sha(b),gid(b))==(n,s,g),(len(b),sha(b),gid(b))
meta=json.loads((P/'native-root-review.json').read_bytes())
idx=json.loads((P/'original-part-index.json').read_bytes())
assert len(idx)==52 and len({x['name'] for x in idx})==52
indexed={x['name']:x for x in idx}
items=[]; part_checks=[]
for original_name,gz_name,raw_name in [
 ('SNAPSHOT_LEAVES.json.gz','SNAPSHOT_LEAVES.recovered.json.gz','SNAPSHOT_LEAVES.recovered.json'),
 ('OBJECT_AUDIT.json.gz','OBJECT_AUDIT.json.gz.recovered','OBJECT_AUDIT.json.recovered'),
 ('TREE_AND_ANCHOR_RAW.json.gz','TREE_AND_ANCHOR_RAW.json.gz.recovered','TREE_AND_ANCHOR_RAW.json.recovered')]:
 row=next(x for x in meta['artifacts'] if x['name']==original_name)
 gz=(P/gz_name).read_bytes();raw=(P/raw_name).read_bytes()
 checked(gz,row['bytes'],row['sha256'],row['git_blob'])
 checked(raw,row['raw_bytes'],row['raw_sha256'],row['raw_git_blob'])
 assert gzip.decompress(gz)==raw
 offset=0; allparts=[]
 for part in row['parts']:
  i=indexed[part['name']]
  assert all(i[k]==part[k] for k in ('name','bytes','sha256','git_blob'))
  b=pathlib.Path(i['path']).read_bytes()
  checked(b,part['bytes'],part['sha256'],part['git_blob'])
  assert b.endswith(b'\n') and b.count(b'\n')==1
  piece=base64.b64decode(b[:-1],validate=True)
  assert part['decoded_offset']==offset and len(piece)==part['decoded_bytes'] and sha(piece)==part['decoded_sha256']
  assert piece==gz[offset:offset+len(piece)]
  allparts.append(piece);offset+=len(piece)
  part_checks.append({'name':part['name'],'bytes':len(b),'sha256':sha(b),'git_blob':gid(b),'decoded_offset':part['decoded_offset'],'decoded_bytes':len(piece),'decoded_sha256':sha(piece),'original_metadata_equal':True})
 assert b''.join(allparts)==gz and offset==len(gz)
 items.append({'name':original_name,'gzip_bytes':len(gz),'gzip_sha256':sha(gz),'gzip_git_blob':gid(gz),'raw_bytes':len(raw),'raw_sha256':sha(raw),'raw_git_blob':gid(raw),'parts':len(allparts),'whole_raw_and_gzip_equal_original_metadata':True})
assert len(part_checks)==52
leaves=json.loads((P/'SNAPSHOT_LEAVES.recovered.json').read_bytes())
review=json.loads((P/'SNAPSHOT_RECOVERY_REVIEW.json').read_bytes())
expected=[{'key':'base_b298','commit':'b29869e856d08db1bfb066116a9c443376ccc57d','tree':review['base_tree'],'files':review['base_files']},{'key':'reuse_c0f','commit':'c0f78493f815780f68b9bf5e390a21314d79311f','tree':review['reuse_tree'],'files':review['reuse_files']}]+[{'key':r['commit'],**r} for r in review['snapshots']]
assert len(leaves)==len(expected)==9
for r in expected:
 rows=leaves[r['key']]
 assert len(rows)==r['files'] and len({x['path'] for x in rows})==len(rows)
 assert rows==sorted(rows,key=lambda x:x['path'].encode())
anchors=json.loads((P/'recovered-anchor-commits.json').read_bytes())
anchor_checks=[]
for a,name in zip(anchors,['b298','c0f']):
 b=base64.b64decode(a['raw_base64'],validate=True)
 assert len(b)==a['bytes'] and sha(b)==a['sha256'] and gid(b,'commit')==a['sha']
 assert b==(P/(name+'-canonical.commit')).read_bytes()
 api=json.loads((P/(name+'-git-commit.json')).read_bytes())
 assert api['sha']==a['sha']
 anchor_checks.append({'commit':a['sha'],'bytes':len(b),'sha256':sha(b),'raw_commit_git_sha_matches':True,'same_raw_commit_file':True,'original_github_metadata_commit_sha_matches':True})
before=json.loads((P/'b298-before-verified-metadata.json').read_bytes())
req=json.loads((P/'b298-before-blob-requests.json').read_bytes())
assert len(before)==len(req)==32 and len({r['sha'] for r in before})==32
for r in before:
 q=next(x for x in req if x['sha']==r['sha'])
 assert all(r[k]==q[k] for k in ('path','mode','bytes','sha'))
cmp=json.loads((P/'b298-c0f-compare.json').read_bytes())
assert len(cmp['files'])==41 and sum(x['status']=='added' for x in cmp['files'])==9 and sum(x['status']=='modified' for x in cmp['files'])==32
canonical=(P/'CANONICAL_COMMITS_AND_DIFFS.recovered.json').read_bytes()
cref=next(x for x in meta['artifacts'] if x['name']=='CANONICAL_COMMITS_AND_DIFFS.json')
checked(canonical,cref['bytes'],cref['sha256'],cref['git_blob'])
assert len(json.loads(canonical))==7
object_anchor=json.loads("{\"format\":\"hepta-actual-retained-object-audit-prefix-v1\",\"original_path\":\"/home/qian-qi/hepta-utility-36fa-evidence/a96-canonical-independent-validation-v1/validation/OBJECT_AUDIT.json.gz\",\"version\":\"2050:50138535:1916374:1794501223973444585:1794501223973444585\",\"original_bytes\":1916374,\"actual_read_bytes\":262144,\"range\":[0,262144],\"prefix_sha256\":\"db5ae723816e83f50ae9258615c0feb5c46e50c1eb68a8c1b07d4b0c990552b9\",\"prefix_git_blob\":\"7ffa25c8252a4c6acc72e095d9705bc0848d72f3\",\"complete_original_read\":false,\"reads_previously_requested\":true,\"new_h_read_performed\":false,\"chunks\":[{\"offset\":0,\"bytes\":65536,\"sha256\":\"d2b9520e145d0ca837194047510a2a914ef909da5264b15f6aa047ee88d54161\",\"version\":\"2050:50138535:1916374:1794501223973444585:1794501223973444585\"},{\"offset\":65536,\"bytes\":65536,\"sha256\":\"5eac23f96c0313fe469123717dc3a9d9006259d583a0627baa0e2b3a2a0778ad\",\"version\":\"2050:50138535:1916374:1794501223973444585:1794501223973444585\"},{\"offset\":131072,\"bytes\":65536,\"sha256\":\"54d18e5886fd4324d7db4556e62a272821220aa2c35972ce0d5c44a2fb5a32a8\",\"version\":\"2050:50138535:1916374:1794501223973444585:1794501223973444585\"},{\"offset\":196608,\"bytes\":65536,\"sha256\":\"c3a0a293a6f25eeafa1b99445e7fa42a719df947c07b23f80e3dc039922b23d0\",\"version\":\"2050:50138535:1916374:1794501223973444585:1794501223973444585\"}],\"artifacts\":[{\"name\":\"chunk-0.tool-result.json\",\"bytes\":87843,\"sha256\":\"3644e0c2c8b463ac7378e4816dd8f4acfca30c6139bd751bc9fea602da6c0d71\",\"blob\":\"f921896e6e7afb904eaff49eb18c0c0d4f5edd00\"},{\"name\":\"chunk-65536.tool-result.json\",\"bytes\":87848,\"sha256\":\"a22bd1e850e4093ad606f61d213b2c12ece26b269d0d0e5cbda64f2e400f3b89\",\"blob\":\"3d0d1847b6b9ad239b82c405b8fbe79fc007b3cc\"},{\"name\":\"chunk-131072.tool-result.json\",\"bytes\":87849,\"sha256\":\"7cbcac75b6927f406cd07cb858fb086771315be7b28d8abf7502eed0a661f4c0\",\"blob\":\"5ae7fd7f26734fa8f79bfc531b839f3cec661c33\"},{\"name\":\"chunk-196608.tool-result.json\",\"bytes\":87849,\"sha256\":\"fc01392dacc4929427ec229eb0f229f9ec44c4fd815d8b0a4e6350eebe028809\",\"blob\":\"46ac2b896cfe891c8a97fd5cb0b228628cb9b706\"},{\"name\":\"OBJECT_AUDIT.json.gz.actual-first-262144.bytes.b64\",\"bytes\":349529,\"sha256\":\"65f7f1f5be0ad9d67133689b859e31e2ec7b440ea52625827dbb6d0389e6aedf\",\"blob\":\"45e91658a2786be316f5a34207852827a8484652\"}]}")
prefix=(P/'OBJECT_AUDIT.json.gz.recovered').read_bytes()[:object_anchor['actual_read_bytes']]
assert len(prefix)==262144 and sha(prefix)==object_anchor['prefix_sha256'] and gid(prefix)==object_anchor['prefix_git_blob']
checks=[]
for ch in object_anchor['chunks']:
 b=prefix[ch['offset']:ch['offset']+ch['bytes']]
 assert len(b)==ch['bytes'] and sha(b)==ch['sha256']
 checks.append({'offset':ch['offset'],'bytes':len(b),'sha256':sha(b),'matches_retained_original_chunk_hash':True})
result={'schema':'hepta.utility.recovery-packaging-independent-check.v1','checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Read-only local byte/hash and structural comparison of already recovered artifacts; no execution of either recovery script or native validator','original_native_root_git_blob':'d7c135961dfacc04fe8b69697a66450e65566acb','local_metadata_serialization_git_blob':gid((P/'native-root-review.json').read_bytes()),'local_metadata_semantically_equal_original_root_confirmed_separately_in_v8':True,'artifacts':items,'canonical_diff':{'bytes':len(canonical),'sha256':sha(canonical),'git_blob':gid(canonical),'commits':7},'snapshot_maps':expected,'merkle_recomputed_by_this_packaging_check':False,'merkle_roots_reconstruction_report':'f58576cfe66debbcd026d209b5a6d406e5a73d7c','before_metadata_rows':32,'before_compare_paths':41,'part_count':len(part_checks),'parts':part_checks,'anchor_commits':anchor_checks,'object_actual_prefix_anchor':{'manifest_git_blob':'022b2bbb59a23be9f4808d7b48fc59110d48ad28','bytes':len(prefix),'sha256':sha(prefix),'git_blob':gid(prefix),'four_chunk_hash_checks':checks,'comparison':'Recovered prefix whole identities and each original chunk SHA256 equal the retained actual-read manifest; original SDKs referenced without new H request'},'new_h_reads':0,'new_native_runs':0,'new_source_or_ref_writes':0,'qualification':False}
print(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')))
