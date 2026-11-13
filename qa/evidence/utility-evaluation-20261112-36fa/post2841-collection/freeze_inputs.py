#!/usr/bin/env python3
"""Offline, create-only capture of an explicitly scoped post2841 evidence increment.

No repository, native filesystem, tests, Git refs, or external application is changed.
GitHub upload/readback is a separate explicit step; computed identities are not
reported as successful uploads by this script.
"""
import base64
import datetime
import gzip
import hashlib
import json
from pathlib import Path

OUT = Path('/tmp/hepta-36fa-post2841-evidence-preparation-v1')
BASE = Path('/tmp/hepta-36fa-after2793-20261112')
PREFIX = 'qa/evidence/utility-evaluation-20261112-36fa/'
plan = json.loads((BASE / 'PUBLISH_PLAN.json').read_text())
base_files = plan['files']
assert len(base_files) == 2841
anchors = json.loads((BASE / 'PUBLISHED_2841_ANCHORS.json').read_text())
assert anchors['evidence_head'] == '64b921b3f6031d515883a7ca506207932da3997f'
assert anchors['evidence_leaf'] == plan['leaf_sha'] == 'dd01bc90b0c8a7671df8327fa6f11adf61a1fedd'
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
entries, retained_existing, errors = [], [], []
seen = {}

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, ('create-only frozen path differs', str(path))
        return
    with path.open('xb') as f:
        f.write(raw)
    assert path.read_bytes() == raw

def stable_read(path):
    path = Path(path)
    a = path.stat()
    raw = path.read_bytes()
    b = path.stat()
    fields = ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
    assert tuple(getattr(a,k) for k in fields) == tuple(getattr(b,k) for k in fields), str(path)
    return raw

def check_record(meta, actual):
    for key, aliases in [('bytes',('bytes','size')), ('sha256',('sha256',)),
                         ('git_blob',('git_blob','git_blob_sha','sha'))]:
        values = [meta[k] for k in aliases if k in meta]
        for value in values:
            assert value == actual[key], (key, value, actual[key])

def archived_readback(path, raw):
    proofs = []
    for suffix in ('.ARCHIVE.original.json','.GITHUB.original.json'):
        side = Path(str(path)+suffix)
        if not side.exists():
            continue
        proofraw = stable_read(side)
        obj = json.loads(proofraw)
        actual = pin(raw)
        if 'file' in obj:
            check_record(obj['file'], actual)
        created = obj.get('created', obj.get('creation'))
        assert created['structuredContent']['sha'] == actual['git_blob']
        assert not created.get('isError',False)
        text = obj['readback']['structuredContent']['content']
        assert isinstance(text,str) and text.encode('utf-8') == raw
        assert not obj['readback'].get('isError',False)
        assert obj.get('full_readback_equal', True) is True
        proofs.append({'saved_api_record': str(side), 'record_identity': pin(proofraw),
                       'local_bytes_equal_saved_complete_GitHub_readback': True})
    return proofs

def add(local, dest, category, expected=None, provenance=None):
    assert not dest.startswith('/') and '..' not in Path(dest).parts
    if dest.startswith(PREFIX):
        dest = dest[len(PREFIX):]
    local = Path(local)
    raw = stable_read(local)
    p = pin(raw)
    if expected:
        check_record(expected,p)
    if dest in seen:
        assert seen[dest] == p['git_blob'], ('conflicting new path', dest)
        return
    seen[dest] = p['git_blob']
    if dest in base_files:
        assert base_files[dest] == p['git_blob'], ('would overwrite old path',dest)
        retained_existing.append({'path':dest,'local':str(local),**p})
        return
    frozen = OUT / 'frozen' / dest
    save(frozen,raw)
    proofs = archived_readback(local,raw)
    entries.append({'path':dest,'local':str(frozen),'original_local':str(local),
                    'category':category,**p,'saved_readback_proofs':proofs,
                    'verification_status':'saved_full_GitHub_readback_validated' if proofs else 'requires_full_GitHub_readback',
                    'source_provenance':provenance})

def tree_sha(items):
    children = {}
    for path, mode, sha in items:
        first, sep, rest = path.partition('/')
        if sep:
            children.setdefault(first,[]).append((rest,mode,sha))
        else:
            assert first not in children
            children[first]=(mode,sha)
    encoded=[]
    for name,value in children.items():
        if isinstance(value,list): mode,sha='40000',tree_sha(value)
        else: mode,sha=value
        encoded.append((name.encode()+ (b'/' if mode=='40000' else b''),
                        mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha)))
    raw=b''.join(v for _,v in sorted(encoded))
    return hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

# Validate actual saved complete tree responses against the published map.
tree_reviews=[]
for name, expected in anchors['evidence_parent_trees'].items():
    raw = stable_read(BASE/(name+'.READ.response.json'))
    response=json.loads(raw)
    obj=json.loads(response['structuredContent']['content'])
    assert obj['sha']==expected and obj['truncated'] is False
    rows=obj['tree']
    if name=='leaf':
        blobs={r['path']:r['sha'] for r in rows if r['type']=='blob'}
        assert blobs==base_files and len(blobs)==2841
        assert all(r['mode']=='100644' for r in rows if r['type']=='blob')
        actual=tree_sha([(r['path'],r['mode'],r['sha']) for r in rows if r['type']=='blob'])
    else:
        actual=tree_sha([(r['path'],r['mode'].lstrip('0'),r['sha']) for r in rows])
    assert actual==expected,(name,actual,expected)
    tree_reviews.append({'name':name,'sha':expected,'entries':len(rows),
                         'read_response_identity':pin(raw),'raw_Git_tree_recomputed':True})

# Publication receipts are captured separately from the earlier 2793 publication.
publication_names = [
    'PUBLISHED_2841_ANCHORS.json','PUBLISH_PLAN.json','COMPLETE_TREE_READBACK_REVIEW.json',
    'COMMIT_REQUEST.json','COMMIT_CREATE.response.json','COMMIT_READ.response.json',
    'COMMIT_MESSAGE_TERMINAL_LF_REVIEW.json','REF_UPDATE_REQUEST.json',
    'REF_UPDATE.response.json','REF_READ.response.json','PR.PUBLISH.md',
    'PR_READ.original.json','PR_UPDATE.original.json',
    'parent-evidence.CREATE.response.json','parent-evidence.READ.response.json',
    'parent-qa.CREATE.response.json','parent-qa.READ.response.json',
    'parent-root.CREATE.response.json','parent-root.READ.response.json',
    'leaf.CREATE.response.json']
for name in publication_names:
    add(BASE/name,'checkpoint-2841-publication/'+name,'actual2841_publication_original')
add(BASE/'README.PUBLISH.md','checkpoints/README_2841FILES_BEFORE_POST2841_INCREMENT.md',
    'immutable_2841_readme_archive', {'git_blob':base_files['README.md']})

# Lossless bounded representation of the 2 MB original leaf-read response.
large_raw = stable_read(BASE/'leaf.READ.response.json')
large_gz = gzip.compress(large_raw,mtime=0)
parts=[]
for i,offset in enumerate(range(0,len(large_gz),196608),1):
    rawpart=large_gz[offset:offset+196608]
    encoded=base64.b64encode(rawpart)+b'\n'
    name=f'leaf.READ.response.original.json.gz.part{i:03d}.b64'
    local=OUT/'generated'/name
    save(local,encoded)
    add(local,'checkpoint-2841-publication/'+name,'lossless_original_API_response_encoding')
    parts.append({'name':name,'decoded_offset':offset,'decoded':pin(rawpart),'encoded':pin(encoded)})
large_manifest={'format':'hepta-lossless-original-api-response-v1','raw':pin(large_raw),
    'gzip':pin(large_gz),'parts':parts,'original_local':str(BASE/'leaf.READ.response.json'),
    'reconstruction':'Strip each part terminal LF, decode each base64 separately, concatenate, gunzip once; verify all identities.',
    'new_API_observation':False,'original_API_response_reserialized':False}
local=OUT/'generated/LEAF_READ_RESPONSE_ENCODING_MANIFEST.json'
save(local,(json.dumps(large_manifest,sort_keys=True,indent=2)+'\n').encode())
add(local,'checkpoint-2841-publication/LEAF_READ_RESPONSE_ENCODING_MANIFEST.json','lossless_original_API_response_encoding')

# Root already verified these immutable evidence uploads. Retain exact rows;
# fresh fetch will independently establish their contents in this preparation.
for name in ['ROOT_INITIAL_VERIFIED_UPLOADS.json','ROOT_INPUT_VERIFIED_UPLOADS.json','ROOT_LAUNCH_VERIFIED_UPLOADS.json']:
    path=Path('/tmp/hepta-36fa-after2841-20261112')/name
    rows=json.loads(stable_read(path))
    for row in rows:
        assert row['full_readback_equal'] is True
        add(row['local'],row['path'],'root_verified_source_repair_control',row,
            {'root_verified_list':name,'peer_reported_full_readback':True})
    add(path,'post2841-collection/root-upload-lists/'+name,'root_verification_ledger')
add('/tmp/hepta-36fa-after2841-20261112/ACTIVE_REPAIR_CHECKPOINT.json',
    'post2841-collection/ACTIVE_REPAIR_CHECKPOINT.original.json','checkpoint_only_admission_not_terminal')

# The two completed independent peer reviews and their exact placements.
for dirname in ['hepta-36fa-training-readonly-custody-peer-v1','hepta-36fa-source-closure-repair-peer-v1']:
    folder=Path('/tmp')/dirname
    placement=json.loads(stable_read(folder/'PLACEMENT.json'))
    prefix=placement['prefix'].removeprefix(PREFIX)
    for row in placement['files']:
        add(folder/row['path'],prefix+row['path'],'independent_peer_review',row)
    add(folder/'PLACEMENT.json',prefix+'PLACEMENT.json','independent_peer_review_placement')

# All already-complete source job originals and read failures at this cutoff.
# The source-gates job is terminal; no future directory watch is performed.
folder=Path('/tmp/hepta-36fa-final-source-qualification-launch-v1')
source_names=sorted(p.name for p in folder.iterdir() if p.is_file()
    and not p.name.endswith(('.GITHUB.original.json','.ARCHIVE.original.json')))
for name in source_names:
    add(folder/name,'final-source-gates-246d-v1/'+name,'completed_source_job_original_or_transport_record')

# Exact recovery: reuse the already-created seven text blobs. Binary originals
# are represented by the already-verified base64 parts, not redownloaded.
folder=Path('/tmp/hepta-36fa-source-gates-inventory-recovery-v1')
for name in ['recover_original_inventories.py','RECOVERY_REVIEW.json']+[f'CLONE_INVENTORY.original.part{i:04d}.b64' for i in range(5)]:
    add(folder/name,'final-source-gates-246d-v1/inventory-exact-recovery/'+name,
        'exact_recovery_not_new_physical_observation')

# Ordinary's frozen 27-item placement index. No raw 2.2 MB packet duplication;
# the exact compressed parts and original raw identities remain available.
folder=Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1')
idx=json.loads(stable_read(folder/'ARCHIVE_INPUT_INDEX.json'))
for row in idx['files']:
    if row['place_in_evidence']:
        add(folder/row['local_relative_path'],idx['evidence_prefix'].removeprefix(PREFIX)+row['local_relative_path'],
            'reviewed_source_repair_preparation_or_scoped_diagnostic',row,
            {'peer_reported_full_readback':True,'source_index':'ARCHIVE_INPUT_INDEX.json'})
add(folder/'ARCHIVE_INPUT_INDEX.json',idx['evidence_prefix'].removeprefix(PREFIX)+'ARCHIVE_INPUT_INDEX.json',
    'reviewed_source_repair_preparation_index')
for name in ['RAW_FAILURE_INDEX.initial-fqn-labels.json.gz.b64','DRAFT_PARSER_RETENTION.json',
             'parse_original_raw.initial-fqn-labels.py','INITIAL_OBSERVED_RECORD_REVIEW.json']:
    add(folder/name,idx['evidence_prefix'].removeprefix(PREFIX)+name,
        'historical_parser_attempt_preserved_not_authoritative_failure_count')
for name in ['GITHUB_FULL_READBACK.json','PLACEMENT.json']:
    add(folder/name,idx['evidence_prefix'].removeprefix(PREFIX)+name,
        'peer_derived_completed_upload_ledger_not_raw_API_payload')

# Ready successor control and exact launch originals. No later status/result
# files are selected, even if the admitted formatter finishes while archiving.
folder=Path('/tmp/hepta-36fa-source-repair-finalfmt-246d-v1')
for name in ['driver.HOLD.py','FROM_24D.diff','WAITING_CONFIG.json','STATIC_REVIEW_SCOPE.json','prepare_control.py',
             'BOOTSTRAP_FROM_BF8608.diff','BOOTSTRAP_PREPARATION.json','BOOTSTRAP_TEMPLATE.HOLD.py','WAITING_CONFIG.packet-bound.json']:
    add(folder/name,'source-repair-246d/fmt-control-preparation/'+name,'successor_format_control_preparation')
folder=Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1')
for name in ['ACTUAL_BOOTSTRAP.py','ACTUAL_PROCESS_INPUT.json','ACTUAL_STDIN.json',
             'EXACT_LAUNCH_MANIFEST.json','seal_exact_launch.py','MAIN_DISPATCH_INTENT.json','MAIN_ADMISSION.original.json']:
    add(folder/name,'source-repair-246d/fmt-launch/'+name,'approved_request_or_actual_admission_not_terminal')

finished = datetime.datetime.now(datetime.timezone.utc).isoformat()
cutoff={'format':'hepta-post2841-evidence-input-freeze-v1','selection_started_utc':started,
    'frozen_cutoff_utc':finished,'base_evidence_commit':anchors['evidence_head'],
    'base_evidence_leaf':anchors['evidence_leaf'],'base_count':2841,
    'base_map_identity':pin(stable_read(BASE/'PUBLISH_PLAN.json')),
    'source_commit_at_scope':'246d8cb614770252ee42029a5c014f2a4904176a',
    'source_qualification_status':'failed; closure failed, caller self-test and full verification passed',
    'source_qualification_job':'1a1d1e83bd4-2564-1c86',
    'source_repair_admitted_job':'1a1d2107dce-2564-1c98',
    'source_repair_terminal_not_collected_in_this_increment':True,
    'native_qualification_execution_collected':False,'real_qualified_task_chain_outcomes':0,
    'base_README_unchanged_in_proposed_map':True,'README_archive_for_root_later_replacement':True,
    'canonical_inventory14_already_in_base_not_added_again':True,
    'scope_exclusions':['Future repair formatter status/result/postimages','No H or native execution',
      'No source/refs/PR/tree/commit mutation','No tests/gates repeated','No native compact inventory claim'],
    'existing_entries_reused':retained_existing,'new_frozen_entries':entries,
    'base_tree_reviews':tree_reviews}
save(OUT/'CUTOFF_AND_INPUTS.json',(json.dumps(cutoff,sort_keys=True,indent=2)+'\n').encode())
save(OUT/'BASE_FILES.json',(json.dumps(base_files,sort_keys=True,indent=2)+'\n').encode())
save(OUT/'PENDING_UPLOADS.json',(json.dumps([r for r in entries if not r['saved_readback_proofs']],sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'cutoff':finished,'frozen_new_entries':len(entries),
    'existing_exact_paths_reused':len(retained_existing),
    'saved_complete_readback_validated':sum(bool(r['saved_readback_proofs']) for r in entries),
    'remaining_full_readback':sum(not r['saved_readback_proofs'] for r in entries),
    'bytes_new_frozen':sum(r['bytes'] for r in entries),'base_tree_verified':True}))
