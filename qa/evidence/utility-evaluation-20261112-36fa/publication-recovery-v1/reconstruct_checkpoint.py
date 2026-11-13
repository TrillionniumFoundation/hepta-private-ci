from pathlib import Path
import json, hashlib, collections, gzip, base64

ROOT=Path('/tmp/hepta-36fa-publication-recovery-v1')
LEAF='qa/evidence/utility-evaluation-20261112-36fa/'
def read(p): return json.loads(Path(p).read_text())
def ident(b): return {'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
base=read(ROOT/'MAP_3896.original.json')
published=read(ROOT/'published_leaf.map.json')
partial=read(ROOT/'partial_uncommitted_leaf.map.json')
assert len(base)==3896 and len(published)==3638 and len(partial)==3717
assert all(base.get(p)==s for p,s in published.items())
assert all(base.get(p)==s for p,s in partial.items() if p!='README.md')
mapping=dict(base); provenance=[]; local_uploads={}
def add(path,sha,origin):
    if path.startswith(LEAF): path=path[len(LEAF):]
    assert not path.startswith('/') and '..' not in Path(path).parts and len(sha)==40
    if path in mapping: assert mapping[path]==sha,(path,mapping[path],sha)
    mapping[path]=sha; provenance.append({'path':path,'git_blob':sha,'origin':origin})
def local(path,dest,expected=None):
    p=Path(path); b=p.read_bytes(); i=ident(b)
    if expected:
        for k in ['git_blob','bytes','sha256']:
            if k in expected: assert i[k]==expected[k],(p,k,i[k],expected[k])
    add(dest,i['git_blob'],'local exact bytes: '+str(p))
    local_uploads.setdefault(i['git_blob'],{'local':str(p),**i})
    return i
catalog=read(ROOT/'INITIAL_OBJECTS.json')+read(ROOT/'EXTRA_OBJECTS.json')
bylabel={r['label']:r for r in catalog}
for r in catalog:
    local(r['path'],'publication-recovery-v1/metadata/'+r['label']+'.original.txt',r)

placement_dest={
 'production_placement':'shared-original-readback-minimal-v2/review-production-v2/PLACEMENT.json',
 'native_peer_placement':'shared-readback-implementation-peer-v2/PLACEMENT.json',
 'transport_placement':'shared-original-readback-transport-tests-v1/PLACEMENT.json',
 'eval_completed_placement':'evaluation-completed-preparation-v1/PLACEMENT.json',
 'tests_placement':'shared-original-readback-minimal-v2/tests-increment-v1/PLACEMENT.json',
 'material_placement':'fresh-provider-material-rebuilt-v1/PLACEMENT.json',
 'materialization_placement':'cc57-isolated-materialization-v1/reconciliation-01/PLACEMENT.json',
 'native_failure_placement':'native-cc57-isolated-v1/attempt-01/PLACEMENT.json',
 'diag_placement':'native-cc57-isolated-v1/v8-readonly-observation-v1/PLACEMENT.json',
 'selector_placement':'original-evaluated-selector-local-readback-v1/PLACEMENT.json',
}
for label,dest in placement_dest.items():
    c=bylabel[label]; j=read(c['path']); rows=j.get('entries',j.get('artifacts',j.get('files')))
    assert isinstance(rows,list)
    for row in rows:
        path=row.get('evidence_path',row['path']); sha=row.get('git_blob',row.get('blob',row.get('sha')))
        add(path,sha,'actual full-read placement '+c['git_blob'])
    add(dest,c['git_blob'],'actual placement')
for label,prefix,pin in [
 ('next_use_placement','version-next-use-seam-v1/','5ae9f90f4e1ba89aa10ec0d6b1a1ec2c36713737'),
 ('next_use_mount_placement','version-next-use-test-mount-increment-v1/','4af737ec5979d9eddbf2c7ce1a542f34634e298b')
]:
    p=ROOT/(label+'.json');assert ident(p.read_bytes())['git_blob']==pin
    for row in read(p)['entries']:
        dest=row.get('path',prefix+row.get('local',''))
        add(dest,row['git_blob'],'actual full-read placement '+pin)
    add(prefix+'PLACEMENT.json',pin,'actual placement')

combined=Path('/tmp/hepta-36fa-provider-combined-preparation-v1')
for version in [1,2]:
    folder=combined/f'assembled-v{version}'; dest=f'combined-provider-preparation-v{version}/'
    manifest=read(folder/'MANIFEST.json')
    for row in manifest['changes']:
        for side in ['before','after']:
            if row.get(side): local(folder/side/row['path'],dest+side+'/'+row['path'],row[side])
    for name in ['MANIFEST.json','changes.patch','SOURCE_PACKET.part-01.json','SOURCE_PACKET.part-02.json','SOURCE_PACKET.part-03.json']:
        local(folder/name,dest+name)
for name in ['assemble_frozen_layers.py','assemble_frozen_layers.initial.py','extend_frozen_layers_v2.py','new-increment-actual-originals.json','INPUT_FULL_READBACK.json','INPUT_IDENTITIES.json','SOURCE_BASE_TREE.json']:
    local(combined/name,'publication-recovery-v1/local-preparation/'+name)

register=Path('/tmp/hepta-36fa-provider-registration-preparation-v2')
for folder,prefix in [
 (Path('/tmp/hepta-36fa-fresh-provider-stage-increment-v1/review-stage-v1'),'fresh-provider-stage-increment-v1/'),
 (Path('/tmp/hepta-36fa-shared-readback-ufcs-increment-v1'),'shared-readback-typed-ufcs-increment-v1/'),
 (register/'root-test-registration-v1','provider-registration-preparation-v2/root-tests/'),
]:
    for file in sorted(folder.iterdir()):
        if file.is_file() and file.suffix in ['.json','.patch','.md','.py']: local(file,prefix+file.name)
    packet=read(folder/'SOURCE_PACKET.json')
    for row in packet['changes']:
        for side in ['before','after']:
            if not row.get(side): continue
            content=row.get(side+'_content',row.get(side+'_text'))
            assert isinstance(content,str),(folder,row['path'],side)
            b=content.encode(); assert ident(b)['git_blob']==row[side]['git_blob']
            cache=ROOT/'extracted-source'/row[side]['git_blob'];cache.parent.mkdir(parents=True,exist_ok=True)
            if cache.exists():assert cache.read_bytes()==b
            else:cache.write_bytes(b)
            local(cache,prefix+side+'/'+row['path'],row[side])

rename=read(register/'HELPER_RENAME.json')
local(register/'HELPER_RENAME.json','training-shared-helper-rename-v1/SOURCE_PACKET.json')
for dest,content,pin in [
 ('after/'+rename['rename']['new_path'],rename['rename']['content'],rename['rename']['content_pin']),
 ('after/'+rename['parent']['path'],rename['parent']['after_content'],rename['parent']['after']),
 ('before/'+rename['parent']['path'],rename['parent']['before_content'],rename['parent']['before'])
]:
    b=content.encode();cache=ROOT/'extracted-source'/pin['git_blob'];cache.parent.mkdir(parents=True,exist_ok=True);cache.write_bytes(b)
    local(cache,'training-shared-helper-rename-v1/'+dest,pin)
for name in ['prepare_root_test_registration.py','prepare_root_test_registration.initial.py','inspect_candidate_call_edges.py','OVERLAY_CALL_EDGE_INSPECTION.initial.json','OVERLAY_CALL_EDGE_INSPECTION.json']:
    local(register/name,'provider-registration-preparation-v2/recovered-local/'+name)
local(register/'SELECTOR_AND_NEXT_USE_INTEGRATION.json','provider-registration-preparation-v2/SELECTOR_AND_NEXT_USE_INTEGRATION.json')

known={
 'shared-original-readback-minimal-v2/linux-export-increment-v1/SOURCE_PACKET.json':'812b8308dbec3ee818bcbb7eae41fb60da10e086',
 'shared-original-readback-minimal-v2/linux-export-increment-v1/MANIFEST.json':'6ed069dc213bb5c24872f0f98da5f21adeab8655',
 'shared-original-readback-minimal-v2/linux-export-increment-v1/changes.patch':'f8c494630d0a88e2169c56d381760b60f91f6afb',
 'shared-original-readback-minimal-v2/linux-export-increment-v1/STATIC_REVIEW.json':'a4bf0102dc43c386b4fecea12479ae3f3c2f89cd',
 'shared-original-readback-minimal-v2/linux-export-increment-v1/after/codex-rs/hepta-agentd/src/lib.rs':'e4875d82be8b8bd9401c770584c1cf286ccb5eef',
 'fresh-c-original-chain-review-v1/REVIEW.json':'13b0e243009e42e3dd6cc4612e3d4f2077a67d33',
 'fresh-c-original-chain-review-v1/REFERENCES.json':'7a12f241e9bbdb2a8429eef1ac475f87f91b6de7',
 'cc57-isolated-materialization-root-review-v1/REVIEW.json':'05fefaacdda28aa8e263a0b86b3b1da86ac5e71b',
 'cc57-isolated-native-root-exact-approval-v1/REVIEW.json':'b22bb40cd49c58b084798fc7e63a66b1b1230257',
 'cc57-isolated-native-root-exact-approval-v1/APPROVAL.json':'3622556e48163010c65c754ccd1e5bbf31f21319',
 'cc57-isolated-native-root-exact-approval-v1/PEER_REVIEW.json':'a16ce8129abc47699246774acb5bb3e7275c2956',
 'cc57-isolated-native-root-exact-approval-v1/peer_review.py':'e2e79fe7d7a16c23bb2b351b038b7899a1110387',
 'native-cc57-isolated-v1/attempt-01/ROOT_PREFLIGHT_REFUSAL_REVIEW.json':'9f511c4abaff9bf2a6be7aab14bd84d8f9aae02e',
 'native-cc57-isolated-v1/v8-readonly-observation-v1/ROOT_APPROVAL.json':'e4e47e9348690070e8084300ea52afb6cad1d58e',
 'training-shared-helper-rename-v1/changes.patch':'6b1c05cd3afb5e51fe8ed7aede06a1fb0340d5c0',
 'training-shared-helper-rename-v1/STATIC_REVIEW.json':'da4b73122f903bcb93630c3afed5b9afe960156d',
 'checkpoints/README_3638FILES_BEFORE_ISOLATED_MATERIALIZATION_AND_NATIVE_REVIEW.md':'beaa457aad524b8f16bc71bc7c2029a65c327b99',
 'publication-recovery-v1/UNPUBLISHED_4287_README.md':'870ac12eb491ccd2c5a3734437a325a70c466ede',
 'publication-recovery-v1/UNPUBLISHED_4287_CHECKPOINT.json':'3112963338db5a55b72312812fe86e231cabdfaf',
}
for p,s in known.items():add(p,s,'previous actual Git-confirmed artifact; see recovery provenance')
for row in read(bylabel['root_materialization_review']['path'])['small_actual_artifacts']:
    add(row['path'],row['git_blob'],'Root actual materialization review')
for name in ['MAP_3896.original.json','published_leaf.map.json','partial_uncommitted_leaf.map.json','INITIAL_OBJECTS.json','EXTRA_OBJECTS.json','EXTRA_OBJECTS.initial_nested_hash.json','git_hash_helpers.original.js','reconstruct_checkpoint.py']:
    local(ROOT/name,'publication-recovery-v1/'+name)
for name in ['published_leaf.tree-readback.json','partial_uncommitted_leaf.tree-readback.json']:
    b=(ROOT/name).read_bytes(); packed=gzip.compress(b,mtime=0); encoded=base64.b64encode(packed)+b'\n'
    assert gzip.decompress(base64.b64decode(encoded))==b
    p=ROOT/(name+'.gz.base64');p.write_bytes(encoded)
    transport=local(p,'publication-recovery-v1/'+p.name)
    manifest={'format':'hepta-lossless-api-tree-readback-transport-v1','original':{'name':name,**ident(b),'raw_git_object_persisted':False},'gzip':ident(packed),'encoded':transport,'full_original_api_content_observed':True,'decoded_byte_identity_checked':True,'qualifying_execution':False}
    p=ROOT/(name+'.transport.json');p.write_text(json.dumps(manifest,indent=2)+'\n')
    local(p,'publication-recovery-v1/'+p.name)

assert all(mapping[p]==s for p,s in published.items())
assert all(mapping[p]==s for p,s in base.items())
(ROOT/'RECONSTRUCTED_PAYLOAD_MAP.json').write_text(json.dumps(dict(sorted(mapping.items())),indent=2)+'\n')
(ROOT/'LOCAL_BLOBS_TO_PERSIST.json').write_text(json.dumps(list(local_uploads.values()),indent=2)+'\n')
(ROOT/'RECONSTRUCTION_PROVENANCE.json').write_text(json.dumps({'format':'hepta-evidence-reconstruction-v1','base_full_map':ident((ROOT/'MAP_3896.original.json').read_bytes()),'published_non_readme_preserved':3637,'reconstructed_payload_files':len(mapping),'exact_unpublished_4287_recovery_claimed':False,'known_missing':'Some Root-local tool SDK serializations existed only in lost transient tool state; no reconstruction of their original execution metadata is claimed. Original H source/materialization/native/diagnostic job records are preserved via complete placements.','entries':provenance},indent=2)+'\n')
print(json.dumps({'payload_files':len(mapping),'new_paths_vs_published':len(mapping)-3638,'local_unique_blobs_to_persist':len(local_uploads),'all_3638_original_paths_unchanged':True,'unpublished_4287_exact_recovery_claimed':False}))
