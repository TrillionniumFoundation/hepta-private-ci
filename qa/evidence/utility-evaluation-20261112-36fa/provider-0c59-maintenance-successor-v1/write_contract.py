#!/usr/bin/env python3
"""Describe the frozen controls and exact input lineage; no control execution."""
import ast,hashlib,json
from pathlib import Path
ROOT=Path('/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1')

def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def save(name,value):
    b=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode();p=ROOT/name
    if p.exists():assert p.read_bytes()==b
    else:p.write_bytes(b)
    return {'name':name,'path':str(p),**pin(b)}

raw=(ROOT/'driver-maintenance.HOLD.py').read_text()
new_names=['validate_materialization','validate_materialization_current','validate_archive_restoration']
checks={}
for fn in ast.parse(raw).body:
    if isinstance(fn,ast.FunctionDef) and fn.name in new_names:
        calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('check','pin_bytes','parse_supervisor','read_input')]
        calls.sort(key=lambda n:(n.lineno,n.col_offset))
        checks[fn.name]=[{'operation':n.func.id,'exact_source':ast.get_source_segment(raw,n)} for n in calls]

contract={
 'format':'hepta-maintenance-successor-proof-contract-v1','status':'PREPARED_PENDING_ROOT_EXACT_ENGINEERING_APPROVAL',
 'driver':pin(raw.encode()),
 'historical_roles':{
  'runtime_six_command_result':{'commit':'86dd56a930277e0d1aef3e475e35c2b5d60b43b7','repo':'/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1',
      'result':'7832ed48200e8361ae4a7dd5ca8b7b5f7f289b09','environment':'8b62ac16f554c1f34ee72974637752f5a3b58aec',
      'changed_bytes':False,'current_source_proof':False},
  'archive_restore_v3':{'commit':'cc57c7198db6293ccca562253c42fffbe2a04633',
      'repo':'/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1',
      'result':'8c5b4818db13a46f990262c02ffe871c8e6f00dc','normal':'b5a9b8d0c8e5f9372eac59e3720ba90c42997579',
      'observed_archive_inode':26738823,'current_comparison_fields':['path','resolved','bytes','sha256','mode'],
      'historical_env_inode_rewritten':False},
  'new_materialization':{'donor_repo':'/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1',
      'destination_repo':'/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1',
      'commit':'0c59aaca0b4932507f068c723f73da2f96729b3d','tree':'4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09',
      'parents':['cc57c7198db6293ccca562253c42fffbe2a04633'],
      'result':'4832994442a8a1bc89ea3af7825a06310ceb7c64','normal':'b726c1fa0db15e96fc46f1398b362a7ce0391f3c',
      'git_metadata':'15430201d5bafa19d2396f5fe8a240cd3d271d5c','git_metadata_bytes':2234,
      'old_86dd_to_9c4_source_advance_reused':False}},
 'changed_functions':[
  {'name':'validate_materialization','change':'Replace old seed producer schema with the actual new isolated candidate schema; require exact result/normal, current endpoints, full index, raw Git, unchanged donor, three final audits, all four original record bodies and final complete metadata gzip/raw.'},
  {'name':'validate_source_advance','change':'Remove this inapplicable old 86dd→9c4 one-file proof consumer. No historical proof is reclassified.'},
  {'name':'validate_materialization_current','change':'New consumer after original current metadata_inventory. Re-read every actual Git file, verify full bytes/SHA/Git and all nine producer stat fields, compare complete path sets and reconstruct the exact producer 2234-byte metadata. Preserve original directory-inclusive before/after equality. Verify actual candidate commit/tree/ordered parent.'},
  {'name':'validate_runtime_restoration','change':'Only bind historical result.source_repo to its fixed old runtime repo; call separate archive-v3 validator before returning unchanged original ENV8b62.'},
  {'name':'validate_archive_restoration','change':'New separate actual cc57 archive RESULT/normal/readback/artifact proof. Full original new inode/stat retained, exact content projected to the unchanged old five-field comparison. No environment history rewrite.'},
  {'name':'validate_config','change':'Add explicit original 32GiB/createfalse, outer9300 and fixed coordination lock path checks; all original approval/source/command/budget/test/ref checks retained.'},
  {'name':'initial_preflight','change':'Remove old sourceadvance call; after full current metadata capture, call current materialization continuity consumer. Preserve all source-entry snapshots, original helper loading, inventory/Merkle, c0f verification, original environment and live guard.'}],
 'all_new_proof_predicates_in_source_order':checks,
 'unchanged_execution':{
  'definitions_count':45,'main_and_stage_and_execute_logged_call':True,'timeout_and_failure_classification':True,
  'global_process_guard_and_rejection_record':True,'source_entry_start_checks':True,'all_actual_postimages':True,
  'raw_git_state_equality':True,'full_directory_and_file_metadata_equality':True,
  'archive_diff_autoRefreshIndex_false':True,'minimum_target_free_bytes':34359738368,
  'cargo_target':'/data/hepta-utility-36fa-final-native-target-v1',
  'fix_argv':['just','fix','-p','codex-hepta-intelligence-eval','-p','codex-hepta-agentd','-p','codex-hepta-learning-ledger'],
  'fmt_argv':['just','fmt','--base','c0f78493f815780f68b9bf5e390a21314d79311f'],
  'budgets_seconds':{'outer':9300,'fix':7200,'fmt':900,'preflight':600,'records':300}},
 'cooperative_lock':{
  'path':'/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock',
  'actual_materialization_device':2050,'actual_materialization_inode':50139448,
  'successor_lease_observed':False,'existing_only_no_recreation':True,'all_nine_actual_stat_fields_checked':True,
  'code':'os.open existing O_RDWR|O_NOFOLLOW → exact stat → flock LOCK_EX|LOCK_NB → set_inheritable(True) → retain actual fresh lease → os.execv original Python driver; no close/unlock in between.',
  'scope':'Cooperating writers only. No backward coverage of historical work, no claim of unrelated-process exclusion; full inventories and global guard remain mandatory.'},
 'staging_and_main':{
  'staging_contract':'STAGING_CONTRACT.HOLD.json',
  'final_exact_input_index':'execution-candidate-v1/FILE_INDEX.json',
  'staging_creates_only':True,'staging_does_not_execute_driver':True,
  'ordered_approval':'Root exact engineering approval must cover the stage-only seven-field request followed, only after its actual normal0/full6file readback, by the six-field 9300-second main request.',
  'source_dir_or_ref_write_during_preparation':False,'unknown_job_never_replaced_or_retried_with_new_bytes':True},
 'limitations':['No maintenance/fmt/Cargo/source gate/native gate was executed by this preparation.',
                'All output postimages, future lease/process observation, formatting result and qualification remain unobserved.',
                'The same raw index and metadata must actually survive original commands; no stat-only or logical-index waiver is introduced.',
                'Separate 900-second control staging retains the observed bootstrap outer limit; it does not add time to maintenance commands or qualification gates.'],
 'qualification':False}
save('PREDICATE_CONTRACT.json',contract)
source=[]
for path in sorted((ROOT/'inputs').iterdir()):
 if path.is_file():source.append({'name':path.name,'local_path':str(path),**pin(path.read_bytes()),
     'role':'exact previous Git object or actual original materialization/restoration record; no generated execution result'})
save('INPUT_PROVENANCE.json',{'format':'hepta-maintenance-successor-input-lineage-v1','inputs':source,
 'note':'Original blob identities are unchanged. Complete live materialization metadata is obtained from the actual producer and its artifact index, not synthesized from an expected source graph.'})
files=[]
for path in sorted(ROOT.iterdir()):
 if path.is_file() and path.name not in ('ARCHIVE_INPUT_INDEX.json','MANIFEST.json','PLACEMENT.json','FULL_GIT_READBACK.json'):
  files.append({'name':path.name,'path':str(path),**pin(path.read_bytes())})
for path in sorted((ROOT/'execution-candidate-v1').iterdir()):
 if path.is_file():files.append({'name':'execution-candidate-v1/'+path.name,'path':str(path),**pin(path.read_bytes())})
save('ARCHIVE_INPUT_INDEX.json',files)
print(json.dumps({'artifacts':len(files),'predicate':pin((ROOT/'PREDICATE_CONTRACT.json').read_bytes()),'input_count':len(source)},indent=2))
