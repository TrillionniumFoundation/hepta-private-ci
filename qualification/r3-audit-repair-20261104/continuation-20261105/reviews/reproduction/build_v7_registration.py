from pathlib import Path
import hashlib,json,importlib.util

ROOT=Path('/workspace/scratch/07dd58cc9630')
P='qualification/r3-audit-repair-20261104/continuation-20261105/'
rows={}

def read(p): return json.loads(Path(p).read_text())
def ident(p):
 b=Path(p).read_bytes()
 return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def add(rel,path,claim=None,actual=False,role='Evidence for the explicitly recorded source/scope'):
 path=Path(path);path=path if path.is_absolute() else ROOT/path
 i=ident(path)
 assert i['bytes']<=512000,(path,i['bytes'])
 if claim:assert i['blob']==claim,(path,i['blob'],claim)
 dest=rel if rel.startswith(P) else P+rel
 row={'repository_path':dest,'local_file':str(path),'mode':'100644',**i,'role':role,
      'actual_object_verified':actual,'verification':'Owning agent actual create and complete byte-equal GET plus root local-byte rehash' if actual else 'Pending actual root create and complete GET'}
 if dest in rows:
  assert rows[dest]['blob']==i['blob'],('collision',dest)
  rows[dest]['actual_object_verified']|=actual
 else:rows[dest]=row
 return row
def simple_map(fn,prefix,base=None,kind='auto',self_blob=None):
 path=ROOT/fn;x=read(path)
 values=x if isinstance(x,list) else x.get('items',x.get('objects',x.get('files')))
 assert isinstance(values,list),(fn,list(x))
 for r in values:
  local=r.get('local_file',r.get('local_path',r.get('path',r.get('file'))))
  local=Path(local);local=local if local.is_absolute() else ROOT/local
  claim=r.get('blob',r.get('git_blob',r.get('actual_create_sha')))
  v=r.get('verification',{})
  actual=bool(r.get('actual_object_verified') or r.get('actual_create_get_byte_equal') or
              (r.get('actual_create') and (r.get('full_GET_byteequal') or r.get('full_get_byteequal'))) or
              (r.get('created') and (r.get('get_byte_equal') or (r.get('get_success') and r.get('byte_equal')))) or
              (r.get('actual_create_sha') and r.get('get_byte_equal')) or
              (isinstance(v,dict) and v.get('actual_create_sha')==claim and v.get('actual_GET_bytes_equal')))
  assert actual,('not_actual_map_item',fn,r)
  if kind=='registered':dest=r.get('repository_path',r.get('repo_relative_path'))
  else:
   name=local.relative_to(ROOT/base).as_posix() if base else local.name
   if name.endswith(('.rs','.yml')):name+='.source.txt'
   dest=prefix+'/'+name
  add(dest,local,claim,True)
 add(prefix+'/actual-delivery-map.json',path,self_blob,bool(self_blob),'Complete actual object registration map; source qualifiers remain in original records')

for fn,blob in [
 ('registration-terminal-macro-repair-v6.json','08e18ee65d662c574a7ae9fc85ccadcf43535603'),
 ('registration-native2-native3-post-v6.json','53e237ce93f59e81fb250159d87581aa2ed15609'),
 ('registration-label-observation-ace-semantics-post-v6.json','d81917c014c8a6943466634235be26671b2829e3'),
 ('registration-native4-post-v6.json','8d89c61304672196dd04089a0dca29f162a49eb1'),
 ('registration-native5-post-v7.json','95b558861e290caeff721b3460f84c47dbd8a8a1')]:
 simple_map('architecture-audit/b11-pr4884-ci-20261105/'+fn,'reviews/registries/'+fn.removesuffix('.json'),kind='registered',self_blob=blob)

simple_map('ci-audit/core-wait-span-20261105/project-nonpass-complete-v1/git-delivery-v1/git-delivery-map.json',
 'generated-evidence/rog-e78-complete-originals-v7',self_blob='47403c6e7516a92557c874abbdda68281031ba37')
simple_map('ci-audit/core-wait-span-20261105/ai395-c1-after-memory-stop-v1/native-c1-first-start/git-delivery-v1/git-delivery-map.json',
 'generated-evidence/ai395-c1-originals-v7',self_blob='815fe88a0d60b62c511f4e53db344f00af5d99c7')
simple_map('ci-audit/core-wait-span-20261105/ai395-candidate-default-full-v1/resource-stop-git-transport-v1/complete-actual-git-delivery.json',
 'generated-evidence/ca1-full-resource-stop-v7',self_blob='5a1a5006f39db00a8bdf8e3185a38e8850752874')
simple_map('architecture-audit/b11-acl-repair-20261105/execution-candidate-v2/actual-readback-map.json',
 'candidate-published/b11-acl-v2','architecture-audit/b11-acl-repair-20261105',self_blob='62bfc51d22d4c39e9b39e3beaa2f38a4285dcd64')
simple_map('architecture-audit/memory-owner-expiry-20261105/real-clock-fixture-candidate-v2/actual-readback-map.json',
 'candidate-published/memory-real-expiry-v2','architecture-audit/memory-owner-expiry-20261105/real-clock-fixture-candidate-v2',self_blob='73f25d34e0b241f54799523df3cb6bdcbcbb9f9e')
simple_map('architecture-audit/approval-shell-fixtures-20261105/nonlogin-candidate-v1/actual-readback-map.json',
 'candidate-published/nonlogin-fixtures-v1','architecture-audit/approval-shell-fixtures-20261105/nonlogin-candidate-v1')
simple_map('research-audit/core-parallel-resume-triage-20261105/github-delivery-map.json',
 'candidate-published/tree-resume-fixture-v1','research-audit/core-parallel-resume-triage-20261105')
simple_map('research-audit/inventory-blob-packaging-20261105/github-readback-map.json',
 'candidate-published/inventory-packaging-v1','research-audit/inventory-blob-packaging-20261105',self_blob='4aa38a1b0d70b00502b34bd02e31f5f5d0d9a69a')

registry='research-audit/published-5b633-ci-20261105/immutable-v7-main-windows-and-publication-cut0004-final/registry-plan.json'
simple_map(registry,'reviews/registries/main-windows-and-publication-cut0004-v7',kind='registered',self_blob='cd162f36a95d99468a2c4541273a8edf33d9a629')
simple_map('research-audit/pr4855-pool-reuse-delta-20261105/registry-plan.json',
 'reviews/registries/pr4855-refused-commit-reuse-v7',kind='registered',self_blob='c3e54fc2b23f73870ab394f076c3fde14fa57327')
ci_registry=ROOT/'ci-audit/published-eed4d6-ci-20261105/immutable-success-increment-v1/registry.actual-v1.json'
ci_actual=read(ci_registry)
assert ci_actual['state']=='ALL_36_LISTED_OBJECTS_ACTUAL_CREATE_AND_FULL_GET_BYTE_EQUAL'
for r in ci_actual['records']:
 assert r['actual_create_get_verified'] is True
 add(r['repo_path'],r['path'],r['git_blob'],True)
add('ci/eed-success-increment-20261105/registry.actual-v1.json',ci_registry,
    'cd3bcc268c057e518a6e5949eeecd9341da5c04a',True)

for rel,local,blob in [
 ('generated-evidence/ai395-c1-originals-v7/complete-prerequisites-addendum.json','ci-audit/core-wait-span-20261105/ai395-c1-after-memory-stop-v1/native-c1-first-start/complete-prerequisite-originals-v1/complete-prerequisites-addendum.json','3bae15c3e84d3cd9f5c87e7f46c4b99c0ef1c913'),
 ('generated-evidence/resource-feasibility-r1-r2-v7/complete-originals-bundle.json','ci-audit/core-wait-span-20261105/resource-feasibility-after-C1-stop-v1/R1-R2-complete-originals-bundle-v1.json','3011b3096e2a26c7474903356cb4b2430451ba62'),
 ('reviews/b22-original-windows-closure-root-verification-v1.json','hepta-audit-fifth/inputs/b22-original-windows-closure-root-verification-v1.json','0e60a44c0bd703461de322e80464f9969c71602c'),
 ('reviews/inventory-packaging-root-verification-v1.json','hepta-audit-fifth/inputs/inventory-packaging-root-verification-v1.json','562310ce3d1909ad21a7f523d5c50a9794a4a74a'),
 ('reviews/integrated-13-path-candidate-v1.json','hepta-audit-fifth/inputs/integrated-13-path-candidate-v1.json','59930d16294411bcee400f89dccd15b1ebef34c8'),
 ('reviews/b11-acl-v2-independent.json','research-audit/b11-acl-repair-independent-20261105/independent-review.json','d80874b92e5b8788f9b7b0ea1af829eae3dc39ba'),
 ('reviews/memory-real-expiry-v2-independent.json','research-audit/memory-owner-expiry-independent-20261105/independent-static-review.json','11db46ed26206c35458e292c83713ff6329f741c')]:add(rel,local,blob,True)

for name in ['b13-original-windows-closure-root-verification-v1.json','b13-artifact-list-api-bindings-v1.json',
 'primary-14-path-publication-v1.json','b11-acl-four-path-publication-v1.json','b11-native4-root-original-verification-v1.json',
 'b11-native2-native3-root-archive-verification-v1.json','rog-complete29-root-verification-v2.json','integrated-14-path-candidate-v2.json',
 'b11-ace-semantics-publication-v1.json','ca1-native-transition-root-source-reference.json',
 'b11-native5-root-original-verification-v1.json','b11-native5-artifacts-api.json']:
 add('reviews/'+name,'hepta-audit-fifth/inputs/'+name)
for name,path in [
 ('approval-nonlogin-independent.json','research-audit/approval-shell-fixtures-independent-20261105/independent-static-review.json'),
 ('core-tree-resume-independent.json','architecture-audit/core-tree-resume-fixture-independent-20261105/independent-review.json'),
 ('core-tree-resume-complete-output-correlation.json','research-audit/core-parallel-resume-triage-20261105/complete-original-output-correlation-addendum.json')]:add('reviews/'+name,path)
add('reviews/eed-windows-success-review-v2.json','ci-audit/published-eed4d6-ci-20261105/success-review-v2/review.json')

for name in ['run_candidate_default_full.py','runner-derivation.json','C1-to-candidate-default-full.delta.patch','manifest-DISABLED.json','freeze_runner.py','new_stage_functions.py.txt','package_disabled_request.py']:
 add('native-plan/ca1-full-v1/'+name,'ci-audit/core-wait-span-20261105/ai395-candidate-default-full-v1/'+name)
for name in ['root-execution-guard.json','enabled-identities.json']:
 add('native-plan/ca1-full-v1/'+name,'hepta-audit-fifth/inputs/ca1-full-execution-v1/'+name)

# The native24-original archive already contains the exact enabled610281-byte
# process request. Its stdin embeds the577392-byte request, compressed complete
# stage inputs and exact runner. Do not duplicate or truncate those originals.
spec=importlib.util.spec_from_file_location('packv7',ROOT/'hepta-audit-fifth/pack_originals_v5.py')
pack=importlib.util.module_from_spec(spec);spec.loader.exec_module(pack)
pack.OUT=ROOT/'hepta-audit-fifth/v7-archives'
label='concurrent-pr-increment-1644-v7'
manifest=pack.OUT/label/'manifest.json'
if not manifest.exists():pack.pack(label,[('search-and-pr-metadata.original.json','hepta-audit-fifth/pr-increment-1644/search-and-pr-metadata.original.json')])
pack.verify(manifest)
for f in sorted(manifest.parent.iterdir()):
 if f.is_file():add('generated-evidence/'+label+'/'+f.name,f)

for fn in ['LATEST.zh-CN.md','CONTINUATION_PROGRESS_V6.zh-CN.md','PROJECT_DIRECTION_AND_EXECUTION_PLAN_V4.zh-CN.md','continuation-blocker-progress-v5.json']:
 add(fn,'hepta-audit-fifth/v7-deliverables/'+fn,role='Current human or machine-readable deliverable; original exits preserved;10/12/1')
for fn in ['verify_b13_original_windows.py','verify_b11_native5_originals.py','build_v7_deliverables.py','append_v7_postcut.py','build_v7_registration.py','build_v7_index.py']:
 add('reviews/reproduction/'+fn,'hepta-audit-fifth/'+fn)

# Preserve root create+GET attestations by content identity, including when a
# report changes after an earlier batch. Never reuse an attestation by path alone.
actual_path=ROOT/'hepta-audit-fifth/v7-root-actual-objects.json'
if actual_path.exists():
 for actual in read(actual_path):
  assert actual['actual_create_sha']==actual['blob'] and actual['full_GET_byte_equal'] is True
  for row in rows.values():
   if row['blob']==actual['blob']:
    assert row['bytes']==actual['bytes'] and row['sha256']==actual['sha256']
    row.update(actual_object_verified=True,verification=actual['verification'],
               actual_create_sha=actual['actual_create_sha'],full_GET_byte_equal=True)

items=list(rows.values())
result={'schema':'hepta-evidence-only-registration-plan-v7-pending-actual-root-writes',
 'base_audit_commit':'526aca0c1aba938d3dfea0f8dd29c51bfc00fcc9','base_audit_tree':'d30a21b5ecaed91814ef93ad84ff31a3595b56c8',
 'evidence_only':True,'all_blockers_closed':False,'whole_product_qualified':False,
 'counts':{'CLOSED_SCOPED':10,'OPEN':12,'SCIENTIFIC_HOLD':1},'entry_count':len(items),'items':items}
out=ROOT/'hepta-audit-fifth/registration-plan-v7-pending.json'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
pending=[r for r in items if not r['actual_object_verified']]
(ROOT/'hepta-audit-fifth/v7-pending-actual-objects.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'entries':len(items),'already_actual':len(items)-len(pending),'root_actual_pending':len(pending),'total_bytes':sum(r['bytes'] for r in items),'largest':max(r['bytes'] for r in items),'pending_files':[r['local_file'] for r in pending]},ensure_ascii=False))
