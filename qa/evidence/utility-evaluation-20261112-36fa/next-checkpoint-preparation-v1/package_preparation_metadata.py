#!/usr/bin/env python3
"""Package this fixed independent checkpoint preparation without publishing it."""
from pathlib import Path
import base64,gzip,hashlib,json,re

P=Path('/tmp/hepta-36fa-next-evidence-preparation-v1')
PREFIX='next-checkpoint-preparation-v1/'
def ident(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def jb(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def put(name,b):
 p=P/name;p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():assert p.read_bytes()==b,name
 else:p.write_bytes(b)
 return p
def main():
 base=json.loads((P/'BASE_2268_FILEMAP.json').read_bytes());data=json.loads((P/'FINAL_EVIDENCE_FILEMAP_BEFORE_README.json').read_bytes())
 assert len(base)==2268 and len(data)==2732 and all(data[k]==v for k,v in base.items())
 verified=set(json.loads((P/'BLOB_VERIFICATION_PROVENANCE.json').read_bytes()))
 for name in ['NEW_SMALL_OBJECT_UPLOADS.json','FINAL_NATIVE_AND_PUBLICATION_UPLOADS.json']:
  d=json.loads((P/name).read_bytes());assert d['all_full_readback_equal'] is True
  for r in d['objects']:assert r['full_readback_equal'] is True;verified.add(r['git_blob'])
  for r in d.get('core_originals_previously_verified',[]):assert r['full_readback_equal'] is True;verified.add(r['git_blob'])
 for raw in (P/'final-snapshots/ROOT_UPLOADS.original.jsonl').read_bytes().splitlines():
  r=json.loads(raw);assert r['full_readback_equal'] is True;verified.add(r['sha'])
 new={k:v for k,v in data.items() if k not in base}
 assert set(new.values())<=verified,sorted(set(new.values())-verified)
 rows=[];transport=[];snapshot_resolution=[]
 def add(path,local,kind):
  b=local.read_bytes();assert len(b)<=400000,(path,len(b));r={'path':path,'local_path':str(local),**ident(b),'kind':kind};rows.append(r);return r
 # Preserve all input captures; reference original already-placed blobs when possible.
 snapshot_files=sorted((P/'input-snapshots').iterdir())+sorted((P/'canonical-actual-addendum').glob('ROOT_UPLOADS*.jsonl'))+[P/'final-snapshots/ROOT_UPLOADS.original.jsonl']
 placed_by_sha={v:[k for k,s in data.items() if s==v] for v in set(data.values())}
 for f in snapshot_files:
  if not f.is_file():continue
  b=f.read_bytes();pin=ident(b)
  if pin['git_blob'] in placed_by_sha:paths=placed_by_sha[pin['git_blob']]
  else:
   dest=PREFIX+'input-snapshots/'+f.parent.name+'--'+f.name
   add(dest,f,'exact stable local input snapshot; original producer not re-executed');paths=[dest];placed_by_sha[pin['git_blob']]=paths
  snapshot_resolution.append({'local_snapshot':str(f),**pin,'available_at':paths})
 put('INPUT_SNAPSHOT_RESOLUTION.json',jb(snapshot_resolution))
 # Final per-blob proof keeps the binary-companion exception explicit.
 review={
  'format':'hepta-final-checkpoint-evidence-object-review-v1','existing_paths':2268,'new_paths':len(new),'combined_data_paths':len(data),
  'all_previous_paths_same_sha':True,'unique_new_blob_identities':len(set(new.values())),
  'all_new_blob_identities_have_retained_verification_provenance':True,
  'new51_small_objects_created_and_full_readback':True,'new29_canonical_publication_objects_created_and_full_readback':True,
  'native_canonical_core_RESULT_and_normal_created_and_full_readback':True,
  'binary_exception':{'blob':'d8b9b85afae3934c166fc9e0c777fe03fcfd608b','direct_full_UTF8_readback':False,'original_binary_creation_verified':True,'exact_original_native_bytes_matched_full_readback_base64_companion':'5bcdddad0cc813c36835aa03c18e3a63a28ed688'},
  'source_publication_actual_originals_retained':True,'qualification_not_inferred':True,
  'evidence_capture_cutoff':'2026-11-12T22:36:44.085972+00:00',
  'later_root_events':'Root appends later admission and hosted observations separately; not chased by this frozen preparation',
  'root_collector_executed':False,'root_files_written':False,'commit_ref_PR_H_or_source_mutation_by_this_preparation':False,
 }
 put('FINAL_OBJECT_VERIFICATION_REVIEW.json',jb(review))
 put('PREPARATION_READ_RECONCILIATION_NOTES.json',jb({
  'format':'hepta-local-preparation-reconciliation-notes-v1',
  'events':[{'kind':'local_inventory_collection_guard','detail':'Early capture retained the original native binary gzip UTF8=false field; verification uses its exact native bytes and full-readback base64 companion.'},
            {'kind':'Root_append_only_ledger','detail':'Root appended entries while preparation was in progress. Earlier captures are retained. A local fixed208-row assertion rejected an actual209-row snapshot before map mutation; the successor local helper verifies append-only growth and records the actual count. The filename ROOT_UPLOADS_208_ROWS.original.jsonl is an earlier failed-guard capture, not a claim that its actual row count is208.'}],
  'original_error_SDK_reconstructed':False,'native_source_run_or_retry':False,'qualification_inference':False}))
 payloads=['collect_independent_increment.py','append_canonical_observation.py','finish_checkpoint_preparation.py','package_preparation_metadata.py',
  'COLLECTION_SUMMARY.json','BASE_PRESERVATION_REVIEW.json','INPUT_SNAPSHOT_INDEX.json','INPUT_SNAPSHOT_RESOLUTION.json',
  'BASE_2268_FILEMAP.json','FINAL_EVIDENCE_INCREMENTAL_FILEMAP.json','FINAL_EVIDENCE_FILEMAP_BEFORE_README.json',
  'FINAL_FACTS_AND_LIMITS.json','FINAL_OBJECT_VERIFICATION_REVIEW.json','NEW_SMALL_OBJECT_UPLOADS.json','FINAL_NATIVE_AND_PUBLICATION_UPLOADS.json',
  'FINAL_NATIVE_AND_PUBLICATION_INDEX.json','CANONICAL_OBSERVATION_ADDENDUM.json','IDENTICAL_BLOB_PATH_ALIASES.json',
  'PREPARATION_READ_RECONCILIATION_NOTES.json','README.DRAFT.md','PR.DRAFT.md']
 for name in payloads:add(PREFIX+name,P/name,'derived independent checkpoint preparation; not an execution result')
 for name in ['PATH_PROVENANCE.json','FINAL_PATH_PROVENANCE.json','BLOB_VERIFICATION_PROVENANCE.json']:
  raw=(P/name).read_bytes();gz=gzip.compress(raw,compresslevel=9,mtime=0);parts=[]
  for i,start in enumerate(range(0,len(gz),196608),1):
   b=base64.b64encode(gz[start:start+196608])+b'\n';part=name+'.gz.part'+str(i).zfill(3)+'.b64';f=put('metadata-parts/'+part,b);r=add(PREFIX+'metadata-parts/'+part,f,'deterministic lossless transport of full provenance');parts.append({k:r[k] for k in ['path','bytes','sha256','git_blob']})
  transport.append({'original_name':name,'original':ident(raw),'gzip':ident(gz),'parts':parts,'reconstruction':'Base64 decode each listed part, concatenate gzip bytes in order, then gzip decompress and verify original3pins.'})
 manifest={
  'format':'hepta-next-evidence-checkpoint-preparation-v1','cutoff':'2026-11-12T22:36:44.085972+00:00',
  'base_files':2268,'fixed_data_increment_paths':464,'fixed_data_combined_paths':2732,
  'base_readme':'3e8b17601e82f5f7be49d172784bc2c4a452a080','base_readme_archive':'checkpoints/README_2268FILES_BEFORE_FINAL_NONRUST.md',
  'source_commit':'246d8cb614770252ee42029a5c014f2a4904176a','source_tree':'d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087',
  'source_ref_publication':'Actual Root publication and exact readback retained; this preparation does not update refs.',
  'real_qualified_task_chains':0,'complete_source_native_qualification':'Pending at bound input cutoff; Root will append later actual execution records.',
  'payloads':rows,'lossless_provenance_transport':transport,
  'publication_instructions':['Merge FINAL_EVIDENCE_INCREMENTAL_FILEMAP without changing any2268existing SHA.','Add the preparation PLACEMENT payloads.','The separately proposed README may replace current README only after its old3e8 exactblob archive is retained.','Append later actual Root source-launch/hosted/qualification records and final commit/count readback; do not infer a gate outcome from these controls.'],
  'generated_filemaps_exclude_their_own_recursive_identity':True,'created_commit_ref_PR_H_or_source_run':False}
 mf=put('MANIFEST.json',jb(manifest));add(PREFIX+'MANIFEST.json',mf,'preparation manifest')
 placement={'format':'hepta-next-evidence-preparation-placement-v1','repository_prefix':'qa/evidence/utility-evaluation-20261112-36fa/','files':rows,'qualification':False,'note':'PLACE this file itself separately if desired; it is excluded from its own entries.'}
 put('PLACEMENT.json',jb(placement))
 combined=dict(data)
 for r in rows:
  assert r['path'] not in combined or combined[r['path']]==r['git_blob'];combined[r['path']]=r['git_blob']
 assert all(combined[k]==v for k,v in base.items())
 put('READY_FILEMAP_WITH_PREPARATION_BEFORE_README.json',jb(combined))
 combined['README.md']=ident((P/'README.DRAFT.md').read_bytes())['git_blob']
 assert {k for k,v in base.items() if combined[k]!=v}=={'README.md'}
 put('READY_FILEMAP_WITH_DRAFT_README.json',jb(combined))
 # Every map target new to this preparation is uploaded/read back before handoff.
 unique={r['git_blob']:r for r in rows}
 for name in ['PLACEMENT.json','READY_FILEMAP_WITH_PREPARATION_BEFORE_README.json','READY_FILEMAP_WITH_DRAFT_README.json']:
  f=P/name;pin=ident(f.read_bytes());unique[pin['git_blob']]={'path':None,'local_path':str(f),**pin,'kind':'delivery index, not self-recursively placed'}
 put('METADATA_UPLOAD_QUEUE.json',jb(list(unique.values())))
 # All relative README evidence links must resolve in the actual proposed map.
 for dest in re.findall(r'\]\(([^)]+)\)',(P/'README.DRAFT.md').read_text()):
  if not dest.startswith(('https://','#')):assert dest in combined,dest
 print(json.dumps({'metadata_entries':len(rows),'unique_metadata_objects_to_upload':len(unique),'ready_files_with_preparation':len(combined),'base_changed_only':['README.md'],'metadata_max_bytes':max(x['bytes'] for x in unique.values())}))

if __name__=='__main__':main()
