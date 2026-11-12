import base64,collections,datetime,gzip,hashlib,json
from pathlib import Path
R=Path('/tmp')
def load(p):return json.loads((R/p).read_text())
def facts(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob_sha':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
inp=load('hepta-36fa-all534-terminal-review-input.json');full=load('hepta-36fa-all534-full-transfer-review-input.json');comps=load('hepta-36fa-all534-binary-companions.json')
for k,v in {**inp,**full,**comps}.items():assert facts(v['content'].encode())['git_blob_sha']==v['sha'],k
placement=json.loads(full['all534_final_placement']['content'])
pmap={x['path']:x for x in placement['placements']};assert len(pmap)==69
assert all(x['bytes']<500000 and x['mode']=='100644' for x in pmap.values())
binary={}
for c in placement['base64_companions']:
 obj=comps['all534_companion:'+c['base64_path']]
 assert obj['sha']==c['base64_git_blob_sha']
 raw=base64.b64decode(obj['content']);f=facts(raw)
 assert f['bytes']==c['decoded_bytes'] and f['sha256']==c['decoded_sha256'] and f['git_blob_sha']==c['binary_git_blob_sha']
 binary[f['git_blob_sha']]=raw
reconstructed={}
for entry in placement['reconstruct_large_originals']:
 chunks=[]
 for part in entry['parts']:
  b=binary[part['git_blob_sha']]
  assert facts(b)=={'bytes':part['bytes'],'sha256':part['sha256'],'git_blob_sha':part['git_blob_sha']}
  chunks.append(b)
 raw=b''.join(chunks);raw=gzip.decompress(raw) if entry['encoding']=='gzip' else raw
 assert len(raw)==entry['original_bytes'] and facts(raw)['sha256']==entry['original_sha256']
 reconstructed[entry['original_path']]=raw
assert len(reconstructed)==8
prefix=placement['repository_prefix'].rstrip('/')+'/'
required=0
for key,directory in [('all534_actual_root_manifest',''),('all534_actual_phase_manifest','all-boundaries-scoped/')]:
 m=json.loads(inp[key]['content'])
 assert len(m['files'])==14
 for e in m['files']:
  for part in e['parts']:
   x=pmap[prefix+directory+part['path']]
   assert all(x[k]==part[k] for k in ('git_blob_sha','bytes','sha256'))
   required+=1
assert required==36
base_inventory=(R/'hepta-e8b-source-gate-transfer-36fa/source-inventory-e8b-original.json').read_bytes()
for path in ['all-boundaries-scoped/source-before.inventory.json','all-boundaries-scoped/source-after.inventory.json']:
 assert reconstructed[path]==base_inventory and len(base_inventory)==5432085
v2=load('hepta-36fa-readback-v2-packet.json')
expected_callers=base64.b64decode(next(f['postimage_base64'] for f in v2['files'] if f['path']=='CALLERS.toml'))
assert reconstructed['CALLERS.toml']==expected_callers
assert reconstructed['overlay.json']==(R/'hepta-36fa-rust-overlay-fixed-b298-prepared-v1.json').read_bytes()
raw=reconstructed['all-boundaries-scoped/all-boundaries-scoped.log']
assert raw==reconstructed['all-boundaries-scoped/forwarded.stdout.log']
report=json.loads(reconstructed['all-boundaries-scoped/diagnostic-result.json'])
progress_raw=reconstructed['all-boundaries-scoped/row-progress.jsonl']
events=[json.loads(x) for x in progress_raw.splitlines()]
lines=raw.splitlines()
assert lines[0]==b'BEGIN_SCOPED_ORIGINAL_ALL_BOUNDARIES'
assert json.loads(lines[-1])==report
assert [json.loads(x) for x in lines[1:-1]]==events
assert len(events)==1849 and len(report['boundaries'])==534 and len(report['protected'])==390
for offset,kind,count,key in [(0,'boundary',534,'id'),(1068,'protected',390,'path')]:
 rows=report['boundaries'] if kind=='boundary' else report['protected']
 for i in range(count):
  started,finished=events[offset+2*i:offset+2*i+2]
  assert started['event']==kind+'_started' and finished['event']==kind+'_completed'
  assert started['position']==finished['position']==i
  assert started[key]==finished[key]==rows[i][key]
  assert {k:v for k,v in finished.items() if k not in ('at','event','position')}==rows[i]
counts={'boundaries':{'passed':519,'failed':15,'unknown':0},'protected':{'passed':390,'failed':0,'unknown':0}}
for k in counts:
 observed=collections.Counter(r['status'] for r in report[k])
 assert dict(observed)=={s:n for s,n in counts[k].items() if n}
assert report['counts']==events[-1]['counts']==counts
for k in ['not_started_boundary_ids','unfinished_boundary_ids','not_started_protected_paths','unfinished_protected_paths']:assert report[k]==events[-1][k]==[]
assert events[-1]['event']=='diagnostic_completed'
run=json.loads(inp['all534_actual_run_result']['content']);gate=json.loads(inp['all534_actual_gate_final']['content']);runner=json.loads(inp['all534_actual_runner']['content'])
assert run['gate_summary']==gate
assert run['row_counts']==counts and run['comparison_unknown']==False and run['status']=='failed_scoped_diagnostic'
assert runner['returncode']==1 and not runner['timed_out'] and not runner['output_limit_exceeded']
assert facts(raw)['sha256']==runner['log_sha256'] and len(raw)==runner['log_bytes']==873489
assert gate['source_changed']==False and gate['before_inventory_sha256']==gate['after_inventory_sha256']=='a3077b5e249aadb856c4ec56a0cd4ef4b1bb83785a33fbd76866cf0fbd1393dd'
assert report['external_frozen_inputs_unchanged'] and report['all_original_rust_and_verifier_inputs_unchanged']
sdk=json.loads(inp['all534_actual_originals_sdk']['content']);payload=json.loads(sdk['content'][0]['text'])
sdkchecked=[]
for f in payload['files']:
 b=f['text'].encode()
 assert f['eof'] and len(b)==f['size'] and facts(b)['sha256']==f['sha256']
 sdkchecked.append({'path':f['path'],'bytes':len(b),'sha256':f['sha256'],'git_blob_sha':facts(b)['git_blob_sha']})
for key in ['all534_actual_run_result','all534_actual_gate_final','all534_actual_runner','all534_actual_phase_manifest','all534_actual_root_manifest']:
 assert inp[key]['sha'] in {f['git_blob_sha'] for f in sdkchecked}
fails=[{'position':i,'id':r['id'],'error':r.get('error')} for i,r in enumerate(report['boundaries']) if r['status']=='failed']
review={'schema':'hepta.utility.root-all534-complete-diagnostic-review.v1','reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'failed_scoped_diagnostic_original_status_preserved','run_blob':inp['all534_actual_run_result']['sha'],'original_runner_blob':inp['all534_actual_runner']['sha'],'placement_blob':full['all534_final_placement']['sha'],'exact_original_raw':facts(raw),'full_report':facts(reconstructed['all-boundaries-scoped/diagnostic-result.json']),'full_progress':facts(progress_raw),'all_1849_progress_events_byte_reconciled_with_original_stdout':True,'completed_boundary_rows':534,'completed_protected_rows':390,'counts':counts,'failures':fails,'not_started_or_unfinished':0,'exit_code':1,'timed_out':False,'output_limit_exceeded':False,'source_before_after':'full 5432085-byte inventories identical to preserved exact e8 a307 inventory; 14741 files','source_and_external_inputs_unchanged':True,'frozen_callers_sha256':report['callers_sha256'],'frozen_overlay_sha256':report['overlay_sha256'],'base_rust_files':6590,'projected_rust_files':6597,'all_eight_large_originals_reconstructed':[{'path':p,**facts(b)} for p,b in reconstructed.items()],'all_36_original_part_paths_retained':True,'placements':69,'original_sdk_complete_files':sdkchecked,'qualification':False,'limits':['This is the original v2 CALLERS plus 25 Rust postimage projection, not the integrated source tree.','All 15 failed rows remain failures; later typed fixes and source registration preparations have separate identities.','No full original source gate, full original caller gate, Rust run, A/B/C execution, or cold recovery is inferred.']}
out=R/'hepta-36fa-all534-terminal-root-review.json';out.write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'review_file':str(out),'review':facts(out.read_bytes()),'counts':counts,'events':len(events),'reconstructed_originals':8,'required_parts':36,'placements':69,'source_bytes':len(base_inventory),'failed_positions':[x['position'] for x in fails]},ensure_ascii=False))

