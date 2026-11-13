from pathlib import Path
from datetime import datetime, timezone
import json,hashlib
ROOT=Path('/tmp/hepta-36fa-publication-recovery-v1')
def ident(b):return {'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def save(name,obj):
    p=ROOT/name;p.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n');return p
mapping=json.loads((ROOT/'RECONSTRUCTED_PAYLOAD_MAP.json').read_text())
old=json.loads((ROOT/'published_leaf.map.json').read_text())
original_readme=mapping['README.md'];assert original_readme=='beaa457aad524b8f16bc71bc7c2029a65c327b99'
timestamp=datetime.now(timezone.utc).isoformat()
record={'format':'hepta-reconstructed-evidence-checkpoint-v1','frozen_at_utc':timestamp,
 'evidence_parent':'07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0','previous_leaf':'02f98a58fbed34eb796b38c75b048fac3d518b2f',
 'published_previous_files':3638,'reconstructed_payload_files_before_checkpoint_metadata':len(mapping),
 'source':{'commit':'cc57c7198db6293ccca562253c42fffbe2a04633','tree':'b7b357c07b5539769a068c6b9b009629f5612d1e','ref_changed':False},
 'source_gates':{'job':'1a1d23c92f3-2564-1cb4','status':'succeeded','closure_explicit_ok':492,'new_provider_included':False},
 'materialization':{'job':'1a1d2d20686-392-36','status':'succeeded','complete_physical_files':15188,'placement':'3615ba45eff7e0d58895e3e33d12b66540fc043e','full_capture_entries':54},
 'native':{'job':'1a1d2e908ac-392-5a','status':'failed','exit_code':1,'timed_out':False,'behavioral_tests_started':False,'behavioral_commands':0,'error':'ValueError: RUSTY_V8_ARCHIVE actual existing file required','source_comparison':'UnknownMissingBefore','placement':'b2f5cde318ed5e7db120d429f44d5cefafa16011','full_capture_entries':47},
 'readonly_diagnostic':{'job':'1a1d2f968fe-392-69','status':'succeeded','exit_code':0,'archive':'lstat ENOENT before and after','binding_bytes':39884,'binding_sha256':'7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506','writer_or_cause':'Unknown','placement':'20e5392b08b6bc4495b50c0c442949f8d15bb9a6','full_capture_entries':8,'repair_or_native_retry':False},
 'provider':{'preparation_only':True,'candidate_rust_paths_observed':53,'formatted':False,'compiled':False,'new_tests_executed':False,'full_public_fresh_chain_complete':False,'next_use_packet':'2b331b488fd789421f9731e3637d882bb57d7f0a','next_use_mount_packet':'468a449d78979c8c923009eb87140a2613ae0416','selector_local_packet':'90f0623289c99ecce60d68d9dad348d27e0bd7fa'},
 'recovery':{'reason':'Transient functions store became unavailable after one immutable Git tree creation; local files and Git objects remained available.','original_3896_map':'3f3d938d3a69898411c37bba9664c085ed2ac5d5','initial_large_tree_create':'actual HTTP 422 request timed out/input too large; no SHA returned','unpublished_expected_4287_leaf':'f5f5ca67c0cf1bf26686bebd084cf58eaeb53170','expected_leaf_actual_probe':'404 at the time','one_actual_partial_tree':'53bbb8c9e94f117de2cae423948eef6acdf2f193','partial_files':3717,'commit_or_ref_moved_by_previous_attempt':False,'exact_unpublished_4287_reconstruction_claimed':False,'known_limit':'Some Root-local SDK serializations only held in transient state are not reconstructed. Full original H job captures referenced above remain present. No jobs repeated due to state loss.'},
 'qualification':False,'real_qualified_task_chains':0,'merge_deploy_activation_authorized':False,
 'publication_scope':'Evidence leaf and its three ancestor entries only; source ref and source code are not promoted.'}
save('CHECKPOINT.json',record)
readme=f'''# Hepta utility evaluation — evidence checkpoint

Frozen at {timestamp}. **HOLD. Real qualified authorized task chains: 0.**

This checkpoint preserves the previous published evidence and adds exact source preparation, isolated materialization, the failed native preflight, and the completed read-only missing-material diagnosis. It grants no runtime authority and makes no Adopt, complete NoUpdate, deployment, independent-evaluation or real-consumer success claim.

## Current source and actual execution

The source branch remains at `cc57c7198db6293ccca562253c42fffbe2a04633`, tree `b7b357c07b5539769a068c6b9b009629f5612d1e`. The original source-gate job `1a1d23c92f3-2564-1cb4` completed successfully: the closure gate recorded 492 explicit ok cases, the self-test passed, and the complete caller check passed. These results apply to that exact source; the new provider preparation is excluded.

The isolated materialization job `1a1d2d20686-392-36` completed successfully with all 15,188 physical source entries and the exact source inventory. Its detached Git state uses the separately observed index SHA256 `95547dcfed1945bb06b5400468ec228037cff5374b674ca033a7f66468b34193`. It did not run native behavioral tests. See [complete materialization placement](../utility-evaluation-20261112-36fa/cc57-isolated-materialization-v1/reconciliation-01/PLACEMENT.json) and [Root review](cc57-isolated-materialization-root-review-v1/REVIEW.json).

The subsequent native job `1a1d2e908ac-392-5a` ended normally as **failed, exit 1**, without timeout, cancellation or automatic retry. Its exact error was `ValueError: RUSTY_V8_ARCHIVE actual existing file required`. It dispatched **zero behavioral test commands**. The wrapper's original `UnknownMissingBefore` remains unchanged; a separately successful admission inventory comparison is not substituted for its missing before snapshot. See [47-entry failure capture](native-cc57-isolated-v1/attempt-01/PLACEMENT.json) and [Root refusal review](native-cc57-isolated-v1/attempt-01/ROOT_PREFLIGHT_REFUSAL_REVIEW.json).

The one read-only diagnostic job `1a1d2f968fe-392-69` succeeded. The fixed V8 archive path returned `ENOENT` in both observations; the existing binding was fully read and matched all 39,884 bytes and SHA256 `7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506`. The observed parent and input identities remained stable. The cause, writer and time of loss are **Unknown**. This diagnostic performed no repair or native retry. See [complete diagnostic placement](native-cc57-isolated-v1/v8-readonly-observation-v1/PLACEMENT.json).

## Frozen source preparation

The evidence contains immutable original and successor source packets for the Root resident provider, fresh Training and B preparation, shared original Training/Evaluation readback, the Linux cfg correction, mechanism tests, the narrow test-helper filename correction, explicit typed calls, fresh material/staged T→B/E preparation, Selector local opaque readback, Version-owned same-C NextUse/readiness, and the append-only test mount. The local combined candidate contains 53 changed or new Rust paths at this freeze. It remains **unformatted, uncompiled and unexecuted**.

The Version-owned NextUse service keeps the original context and same consumer; its new path checks the original absolute Version deadline before and after each real handler. The old read service remains unchanged outside the narrow addition. The six new mechanism tests and their mount are source proposals, not measured successes. See [NextUse placement](version-next-use-seam-v1/PLACEMENT.json), [Selector placement](original-evaluated-selector-local-readback-v1/PLACEMENT.json), and [test mount](version-next-use-test-mount-increment-v1/PLACEMENT.json).

The original 33 Root CI parent cases are preserved and six additional parents are prepared in the workflow and source guards. The partial caller inspection removed eight ambiguous method receivers through explicit typed calls. It is not the complete 6,619-file caller gate. Further complete registration, original formatting/lint/test gates, dual-UID owner processes, the full Fresh → Version → same C path and daemon/Root cold recovery remain outstanding.

## Evidence publication recovery

The first large tree request returned an actual 422 timeout/size error with no tree SHA. The expected 4,287-file leaf was absent when probed. A smaller first batch created immutable tree `53bbb8c9e94f117de2cae423948eef6acdf2f193` with 3,717 files; no commit or ref was moved. Transient tool state then became unavailable while the local files and Git objects remained intact.

This is an explicitly reconstructed checkpoint, not a claim that the unpublished 4,287-file plan was recovered exactly. It uses the fully recovered 3,896-file map, the unchanged 3,638-file published leaf, actual agent placements, and byte-verified local artifacts. Some Root-local SDK serializations that existed only in transient state are unavailable. The complete original H source/materialization/native/diagnostic records are retained. No H job was repeated because of state loss. The prior unpublished README and manifest are archived under `publication-recovery-v1/UNPUBLISHED_4287_*`; they describe historical intent, not a successful publication.

All 3,637 previous non-README paths are preserved byte-for-byte. The previous README is archived [here](checkpoints/README_3638FILES_BEFORE_ISOLATED_MATERIALIZATION_AND_NATIVE_REVIEW.md), including its earlier provenance and failure history. The full reconstructed map is persisted as a separate immutable Git object before tree publication; its identity is recorded in the evidence commit message. Full API leaf readback and independent Git Merkle hashes are required before moving the evidence ref.

## Evaluation semantics and remaining acceptance

External user objectives, consequence predictions, policies, critic estimates, independently observed results and the public reward/cost contract remain separate. Missing authorization, outcomes, cost evidence, provenance, independence or original owner authority remains **Unknown / InsufficientEvidence**. Complete unfavorable comparison can support **Ineligible / NoUpdate** only when its evidence and hard gates are complete. Missing material or infrastructure failure is not objective fraud.

The required acceptance remains: a real authorized A → its original Training owner → independent B → Adopt or complete NoUpdate → a new actual consumer C → daemon and Root cold recovery. Model material must be obtainable and authorized, with actual consumer readback. Content identity alone cannot establish availability, legal authority or adoption. No real task satisfying that complete chain is counted here.

See [machine-readable checkpoint](publication-recovery-v1/CHECKPOINT.json) and [reconstruction provenance](publication-recovery-v1/RECONSTRUCTION_PROVENANCE.json).
'''
(ROOT/'README.md').write_text(readme)
new_local=[]
for name in ['CHECKPOINT.json','RECONSTRUCTION_PROVENANCE.json','LOCAL_BLOB_FETCH_RESULTS.json','LOCAL_BLOB_PERSIST_RESULTS.json','finalize_checkpoint.py']:
    p=ROOT/name;i=ident(p.read_bytes());mapping['publication-recovery-v1/'+name]=i['git_blob'];new_local.append({'local':str(p),**i})
p=ROOT/'README.md';i=ident(p.read_bytes());mapping['README.md']=i['git_blob'];new_local.append({'local':str(p),**i})
assert all(mapping[p]==s for p,s in old.items() if p!='README.md')
save('CHECKPOINT_LOCAL_BLOBS.json',new_local)
save('FINAL_FILEMAP.json',dict(sorted(mapping.items())))

def merkle(files):
    root={}
    for path,sha in files.items():
        node=root;parts=path.split('/')
        for part in parts[:-1]:node=node.setdefault(part,{})
        node[parts[-1]]=sha
    trees={}
    def walk(node,path):
        entries=[]
        for name,value in node.items():
            if isinstance(value,dict):mode='040000';kind='tree';sha=walk(value,path+'/'+name if path else name)
            else:mode='100644';kind='blob';sha=value
            entries.append({'path':name,'mode':mode,'type':kind,'sha':sha})
        entries.sort(key=lambda e:(e['path']+('/' if e['type']=='tree' else '')).encode())
        raw=b''.join((('40000' if e['type']=='tree' else e['mode'])+' '+e['path']).encode()+b'\0'+bytes.fromhex(e['sha']) for e in entries)
        sha=hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest();trees[path]={'sha':sha,'entries':entries};return sha
    return walk(root,''),trees
previous_sha,previous_trees=merkle(old);assert previous_sha=='02f98a58fbed34eb796b38c75b048fac3d518b2f'
leaf,trees=merkle(mapping);save('FINAL_TREES.json',trees)
changes=[{'path':p,'mode':'100644','type':'blob','sha':s} for p,s in sorted(mapping.items()) if old.get(p)!=s]
work=dict(old);batches=[];prior=previous_sha
for start in range(0,len(changes),80):
    batch=changes[start:start+80]
    for row in batch:work[row['path']]=row['sha']
    expected,_=merkle(work);batches.append({'number':len(batches)+1,'base_tree_sha':prior,'expected_tree_sha':expected,'elements':batch});prior=expected
assert prior==leaf and work==mapping
plan={'format':'hepta-exact-small-batch-evidence-publication-v1','evidence_parent':'07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0','previous_leaf':previous_sha,'final_leaf':leaf,'final_files':len(mapping),'changed_or_added':len(changes),'new_paths':len(mapping)-len(old),'only_replaced_path':'README.md','old_non_readme_unchanged':3637,'final_filemap':ident((ROOT/'FINAL_FILEMAP.json').read_bytes()),'directory_trees_including_leaf':len(trees),'batches':batches}
save('PUBLICATION_PLAN.json',plan)
print(json.dumps({k:plan[k] for k in ['final_leaf','final_files','changed_or_added','new_paths','old_non_readme_unchanged','final_filemap','directory_trees_including_leaf']}))
