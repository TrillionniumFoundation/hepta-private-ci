"""Pure offline verification and append-only map assembly; executes no inputs.

The prepared map is not a published tree. Root independently reviews/publishes.
All original event timestamps and the explicit input cutoff remain unchanged.
"""
from pathlib import Path
import base64,collections,gzip,hashlib,json

ROOT=Path(__file__).resolve().parent
PRIOR=Path('/tmp/hepta-36fa-post2841-evidence-preparation-v1')
def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def checked(raw,row):
    actual=pin(raw)
    for k in actual:
        if k in row:assert actual[k]==row[k],(k,row.get('path'),actual[k],row[k])
    return actual
def write_once(name,obj):
    raw=(json.dumps(obj,sort_keys=True,indent=2)+'\n').encode();p=ROOT/name
    if p.exists():assert p.read_bytes()==raw,('existing output differs',name)
    else:
        with p.open('xb') as f:f.write(raw)
    return pin(raw)

base_raw=(PRIOR/'FULL_FILEMAP.json').read_bytes()
checked(base_raw,{'bytes':355401,'sha256':'653b35a2bc85255f712a71b75a257b66cfcb38b252f118945e112e1252b02439','git_blob':'24d87c93c886fdb9b9f87ddfe41a4fdb8687b0bd'})
base=json.loads(base_raw);assert len(base)==3033
cutoff=json.loads((ROOT/'CUTOFF.json').read_bytes());rows=[]
for name in cutoff['input_snapshots']:rows+=json.loads((ROOT/name).read_bytes())['rows']
assert len(rows)==cutoff['payload_entries']==212
assert len({r['path'] for r in rows})==len(rows)
assert all(r['path'] not in base for r in rows)
receipts=[];resolved_preparation_errors=[]
for p in sorted((ROOT/'archive-receipts').glob('BATCH-*.json')):
    d=json.loads(p.read_bytes());receipts+=d['results'];resolved_preparation_errors+=d.get('errors',[])
by_sha={r['git_blob']:r for r in receipts}
assert all(r['full_readback_equal'] is True for r in receipts)
binaries={r['git_blob']:r for r in json.loads((ROOT/'BINARY_FULL_READBACK_LEDGER.json').read_bytes())}
verified=[];methods=collections.Counter()
for row in rows:
    raw=Path(row['frozen_local']).read_bytes();checked(raw,row);assert len(raw)<500000
    if row['git_blob'] in by_sha:
        receipt=by_sha[row['git_blob']];checked(raw,receipt)
        method='Fresh GitHub fetch, every returned UTF-8 byte compared with frozen payload.'
        evidence={'fresh_full_content_equal':True,'created_in_this_preparation':receipt['created_in_this_task']}
        counter='fresh_complete_UTF8_fetch'
    elif row.get('saved_original_full_fetch_proof'):
        evidence=row['saved_original_full_fetch_proof'];p=Path(evidence['local'])
        assert hashlib.sha256(p.read_bytes()).hexdigest()==evidence['sha256']
        original=json.loads(p.read_bytes())
        assert original['fetch']['structuredContent']['content'].encode('utf-8')==raw
        method='Saved original GitHub fetch response independently compared in full with frozen payload.'
        counter='saved_original_complete_fetch_bytes'
    else:
        evidence=binaries[row['git_blob']]
        proof=json.loads(Path(evidence['companion_fresh_full_fetch_receipt']).read_bytes())
        text=proof['actual_companion_full_fetch']['structuredContent']['content']
        assert base64.b64decode(text.strip(),validate=True)==raw
        create=json.loads(Path(evidence['binary_original_create_proof']).read_bytes())
        assert create['create']['structuredContent']['sha']==row['git_blob']
        method=evidence['verification_method'];counter='fresh_lossless_binary_companion_and_exact_raw_Git_creation'
    methods[counter]+=1
    verified.append({'path':row['path'],'local':row['frozen_local'],**pin(raw),
       'category':row['category'],'full_readback_equal':True,'verification_method':method,'evidence':evidence})

lookup={r['path']:r for r in rows}
def read(relative):return Path(lookup[relative]['frozen_local']).read_bytes()
def read_json(relative):return json.loads(read(relative))
transport=read_json('source-repair-canonical-alignment-v1/lossless-transport/MANIFEST.json')
assert len(transport['raw_originals'])==2
for raw in transport['raw_originals']:
    pieces=[]
    for part in raw['parts']:
        encoded=read(part['path']);checked(encoded,part)
        assert encoded.endswith(b'\n') and b'\n' not in encoded[:-1]
        decoded=base64.b64decode(encoded[:-1],validate=True);checked(decoded,part['decoded']);pieces.append(decoded)
    packed=b''.join(pieces);checked(packed,raw['offline_gzip']);plain=gzip.decompress(packed);checked(plain,raw)
    assert plain==Path(raw['frozen_original']).read_bytes()
    p=Path(raw['original_Git_full_fetch_proof']);assert hashlib.sha256(p.read_bytes()).hexdigest()==raw['original_Git_full_fetch_proof_sha256']
    assert json.loads(p.read_bytes())['fetch']['structuredContent']['content'].encode()==plain
    assert raw['logical_original_path'] not in lookup

publication=read_json('source-repair-cc57-source-publication-v1/SOURCE_PUBLICATION_REVIEW.json')
assert publication['published_source']=='cc57c7198db6293ccca562253c42fffbe2a04633'
assert publication['actual_ref_readback_equal'] and publication['actual_PR_head_readback_equal']
assert publication['initial_PR_read_head']=='246d8cb614770252ee42029a5c014f2a4904176a'
assert publication['later_readonly_PR_head']==publication['published_source'] and not publication['ref_update_repeated']
root_actual=read_json('cc57-qualification-root-inputs-v1/ROOT_ACTUAL_CANONICAL_REVIEW.json')
assert root_actual['actual_job_id']=='1a1d223a60b-2564-1ca3' and root_actual['all_commands_normal_zero']
assert root_actual['after']['commit']==publication['published_source']
assert root_actual['after']['tree']==publication['tree']=='b7b357c07b5539769a068c6b9b009629f5612d1e'
checked(read('source-repair-canonical-alignment-v1/RESULT.json'),root_actual['actual_result'])
checked(read('source-repair-canonical-alignment-v1/STATUS_01.original.json'),root_actual['actual_normal'])
checked(read('source-repair-canonical-alignment-v1/MAIN_ADMISSION.original.json'),root_actual['first_transport_timeout_retained'])
checked(read('source-repair-canonical-alignment-v1/EXACT_RECONCILE_01.original.json'),root_actual['actual_reconciliation'])
assert all(x['status']=='verified' for x in root_actual['final_audits'])
assert all(k in lookup for k in ['source-repair-canonical-alignment-v1/RESULT_READ_01.original.json',
 'source-repair-canonical-alignment-v1/GIT_STATE.final.json.READ_01.original.json',
 'source-repair-canonical-alignment-v1/GIT_STATE.final.json.READ_02.original.json'])
hosted=read_json('hosted-ci-cc57-observation-v1/REVIEW.json')
assert len(hosted['observations'])==4 and all(x['total_count']==0 for x in hosted['observations'])
assert next(x for x in hosted['observations'] if x['kind']=='status')['state']=='pending'

by_content=collections.defaultdict(list)
for r in verified:by_content[r['git_blob']].append(r['path'])
aliases=[{'git_blob':sha,'paths':paths,'reason':'Distinct original provenance/stage placements retained; same immutable object reused.'}
         for sha,paths in sorted(by_content.items()) if len(paths)>1]
write_once('INPUT_SNAPSHOT_MANIFEST.json',{'format':'hepta-post3033-frozen-payload-manifest-v1',
 'cutoff':cutoff['frozen_at_utc'],'base_3033_map':pin(base_raw),'files':rows,
 'source_and_native_future_runs_excluded':True,'logical_large_originals':transport['raw_originals']})
write_once('READBACK_LEDGER.json',{'format':'hepta-post3033-complete-payload-readbacks-v1',
 'cutoff':cutoff['frozen_at_utc'],'files':verified,'large_originals_exact_transport_verified':True})

report={'format':'hepta-post3033-append-only-integrity-review-v1',
 'status':'VERIFIED_PREPARATION_NOT_PUBLISHED','cutoff_utc':cutoff['frozen_at_utc'],
 'base':{'prepared_files':3033,'map':pin(base_raw),'prior_manifest':'adcb7e63012652c16833adfa0c92c35d5cb2d7ec',
 'published_2841_commit':'64b921b3f6031d515883a7ca506207932da3997f','published_2841_leaf':'dd01bc90b0c8a7671df8327fa6f11adf61a1fedd',
 'prior_cutoff_unchanged':True,'prior_five_bundle_sidecars_archived_as_historical_metadata':True},
 'payload':{'files':len(verified),'distinct_blobs':len(by_content),'bytes':sum(r['bytes'] for r in verified),
 'full_readback_methods':dict(methods),'unverified':0,'old_path_replacements':[],
 'content_aliases':aliases,'largest_published_payload_bytes':max(r['bytes'] for r in verified),
 'categories':dict(sorted(collections.Counter(r['category'] for r in verified).items()))},
 'large_originals':{'count':2,'raw_published_paths_omitted_only_for_size':True,'transport_parts':4,
 'complete_bytes_and_original_three_pins_retained':True,'fresh_or_saved_original_complete_Git_content_matches':True,
 'offline_transport_not_native_compression_observation':True},
 'resolved_preparation_read_errors':{'count':len(resolved_preparation_errors),
 'scope':'Two attempts to read binary gzip as UTF-8 failed locally. They were not native failures or missing artifacts. Strict fresh base64 companion decoding and exact original binary Git-create SHA verification completed instead.',
 'all_errors_accounted_for':len(resolved_preparation_errors)==2},
 'source_outcomes':{'prior_246d_source_gate':'FAILED preserved; no result borrowed for cc57',
 'actual_1c98':'Five non-Rust repairs applied; original fmt returned0 with no additional format changes; tests0.',
 'actual_1ca3':'Canonical snapshot/index/HEAD alignment succeeded; three audits verified; not qualification.',
 'actual_cc57_source_publication':publication,
 'cc57_new_source_gate_admission_or_result_in_this_window':False,
 'native_qualification_admission_or_result_in_this_window':False,
 'absence_from_this_window_is_not_a_claim_about_later_runtime_state':True,
 'actual_qualified_ordinary_task_chains_proved_by_this_package':0},
 'recovery_and_projection_boundaries':{
 'actual_1c98_postimages':'Exact raw/gzip/parts identities previously matched native ARTIFACTS; independently archived here, no second H read.',
 'cf8e_full_inventory':'Exact recovery of actual1c98 dirty physical inventory, not a second native observation.',
 '13d3_full_inventory':'Prepared clean inventory later matched actual1ca3 RESULT; original preparation files remain unchanged and keep their original labels.',
 'native_compact_projection':'Projection only; no actual native compact snapshot is proved by this append.',
 'standalone_git_state':'Two original read failures retained; 489B exact serializer recovery remains explicitly recovery, not a native second read.'},
 'hosted_CI':{'files':5,'actual_GET_originals':4,'review_files':1,'started_at':hosted['started_at'],
 'finished_at':hosted['finished_at'],'all_four_counts':0,'combined_status':'pending','PASS_claim':False},
 'failure_preservation':{'first_220_byte_timeout_retained':True,'initial_result_directory_missing_retained':True,
 'same_exact_key_reconciliation_retained':True,'two_standalone_Git_state_read_failures_retained':True,
 'first_PR_old_head_and_second_readonly_cc57_head_retained':True,'all_old3033_paths_unchanged':True},
 'preparation_actions':{'H':False,'source_edit':False,'tests_or_gates':False,'tree_creation':False,
 'commit_creation':False,'ref_update':False,'PR_update':False,'README_replacement':False},
 'acyclic_metadata':'Payload manifests/ledger describe the fixed payload. Outer maps/placement/manifest are not members of their own map; archive them in a later window if desired.',
 'initial_review_is_historical':'The initial140-row review preceded explicit extra handoffs; final selected payload is212. Neither original review nor prior3033 cutoff was overwritten.',
 'root_must_independently_review_merkle_and_publish':True}
write_once('PREPARATION_REVIEW.json',report)
write_once('VERIFIED_PAYLOAD_ENTRIES.json',verified)
metadata=['CUTOFF.json','INPUT_SNAPSHOT_MANIFEST.json','READBACK_LEDGER.json',
          'PREPARATION_REVIEW.json','verify_and_build_maps.py','INITIAL_DEDUP_INTEGRITY_REVIEW.json']
control_rows=[]
for name in metadata:
    p=ROOT/name;b=p.read_bytes();assert len(b)<500000
    path='post3033-collection/'+name;assert path not in base and path not in lookup
    control_rows.append({'path':path,'frozen_local':str(p),'original_local':str(p),
      'category':'later_window_freeze_and_verification_metadata',**pin(b),'known_remote':False})
write_once('FINAL_METADATA_UPLOAD_QUEUE.json',control_rows)
planned={r['path']:r['git_blob'] for r in verified+control_rows};assert len(planned)==len(verified)+len(control_rows)
combined={**base,**planned};assert len(combined)==len(base)+len(planned)
assert all(combined[p]==sha for p,sha in base.items()) and combined['README.md']==base['README.md']
write_once('PREPARED_INCREMENTAL_FILEMAP.json',planned);write_once('PREPARED_FULL_FILEMAP.json',combined)
print(json.dumps({'payload':len(verified),'metadata':len(control_rows),'increment':len(planned),
 'full_prepared':len(combined),'methods':dict(methods),'unverified':0,
 'review':pin((ROOT/'PREPARATION_REVIEW.json').read_bytes()),'cutoff':cutoff['frozen_at_utc']}))
