#!/usr/bin/env python3
"""Offline binding of the completed original job to a separate HOLD config."""
import difflib
import hashlib
import json
import pathlib

OUT=pathlib.Path('/tmp/hepta-36fa-coordinator-a489-maintenance-successor-v1')
RUN=pathlib.Path('/tmp/hepta-36fa-coordinator-a489-materializer-runtime-v1')

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def write(name,b):
    p=OUT/name
    if p.exists():assert p.read_bytes()==b
    else:
        with p.open('xb') as f:f.write(b)
    return {'name':name,**pin(b)}

def original(name):
    raw=(RUN/name).read_bytes();sdk=json.loads(raw);assert sdk.get('isError') is False
    texts=[x['text'] for x in sdk['content'] if x.get('type')=='text'];assert len(texts)==1
    return json.loads(texts[0]),raw

raw=(RUN/'RESULT.json').read_bytes()
assert pin(raw)=={'bytes':14663,'sha256':'d64b804836db43eac9b178c31059c8d339f2de5cd2d0a3582d64b791ddf451bd','git_blob':'30ab4aad6ff10942063da972e02db49629e3809c'}
result=json.loads(raw)
normal,normal_raw=original('STATUS_04.original.json')
assert pin(normal_raw)=={'bytes':952,'sha256':'fd1140f7bdc02bcc7ea475a15542bd64cfb0d2f23d78dd0708525b49ad214d30','git_blob':'2a11b4b9e2baa380c247b6a728f90edfbcdcd644'}
assert normal['job_id']=='1a1d468462a-392-3bb' and normal['state']=='succeeded' and normal['exit_code']==0
assert all(normal[x] is False for x in ('automatic_retry','cancelled','timed_out'))
assert all(normal[x] is True for x in ('output_complete','output_durable','terminal_publication_confirmed'))
admission,_=original('MAIN_ADMISSION.original.json')
assert admission['job']['id']==normal['job_id'] and admission['job']['env_keys']==[]
assert admission['reused'] is False and admission['launch']['ok'] is True
request=json.loads((RUN/'MAIN_REQUEST.original.json').read_bytes())
assert admission['job']['idempotency_key']==request['idempotency_key']
assert admission['job']['args']==request['args'] and admission['job']['cwd']==request['cwd'] and admission['job']['executable']==request['executable']
cfg_raw=(OUT/'WAITING_CONFIG.json').read_bytes();cfg=json.loads(cfg_raw)
assert cfg['status']=='HOLD_ACTUAL_MATERIALIZATION_AND_ROOT_EXACT_REVIEW_REQUIRED' and cfg['root_execution_approved'] is False
assert result['status']=='MATERIALIZED_EXACT_CANDIDATE_FOR_MAINTENANCE_REVIEW_ONLY'
assert result['source_commit']==cfg['source_commit'] and result['source_tree']==cfg['source_tree'] and result['parents']==cfg['parents']
assert result['destination_repo']==cfg['source_repo']
assert result['source_repo']=='/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1'
for k in ('action_completed','new_repo_created','new_files_and_directories_synced','donor_physical_and_git_file_state_unchanged','input_identities_unchanged'):
    assert result[k] is True
for k in ('automatic_retry','cargo_or_formatter_started','dependency_installation_started','old_source_writes','qualification','remote_ref_updates','rollback'):
    assert result[k] is False
assert result['test_commands_dispatched']==0 and result['cleanup_errors']==[] and 'error' not in result and 'retention_error' not in result
assert {r['check']:r['status'] for r in result['final_audits']}=={'donor_physical_source_and_git_files':'verified','new_source_and_git':'verified','inputs_and_coordination':'verified'}
assert len(result['final_audits'])==3 and result['new_objects_fully_verified']==16661 and result['donor_objects_fully_verified']==16449 and result['physical_leaves_created']==15243
assert result['current_source_before']==result['current_source_after'] and result['current_git_state_before']==result['current_git_state_after']
assert result['current_source_after']['inventory']==cfg['source_inventory'] and result['current_source_after']['status']==''
assert result['donor_source_before']==result['donor_source_after'] and result['donor_git_state_before']==result['donor_git_state_after']
records={}
for key in ('command_records','mutation_records','input_records','artifact_records'):
    row=result[key];body=(RUN/row['name']).read_bytes();identity=pin(body)
    assert identity=={k:row[k] for k in ('bytes','sha256','git_blob')}
    records[key]=identity
commands=json.loads((RUN/'COMMANDS.json').read_bytes())
mutations=json.loads((RUN/'MUTATION_INTENTS.json').read_bytes())
assert all(r['actual_terminal']=='observed' and r['returncode']==0 and r['timed_out'] is False for r in commands)
assert all(r['actual_terminal']=='observed' for r in mutations)
artifacts=json.loads((RUN/'ARTIFACTS.json').read_bytes());assert len(artifacts)==len({r['name'] for r in artifacts})==267
meta=next(r for r in artifacts if r['name']=='final.git-metadata.json.gz')
assert pin((RUN/'final.git-metadata.json').read_bytes())==result['current_git_metadata']=={k:meta['raw_'+k] for k in ('bytes','sha256','git_blob')}
assert pin((RUN/'final.git-metadata.json.gz').read_bytes())=={k:meta[k] for k in ('bytes','sha256','git_blob')}
assert pin((RUN/'final.new-index.raw').read_bytes())==result['current_index']['raw']
assert result['current_index']['entries']==15243 and result['current_index']['assume_unchanged_or_skip_worktree_entries']==0
assert result['current_index']['all_actual_stat_fields_verified'] and result['current_index']['all_entry_logical_identities_verified']
assert json.loads((RUN/'SOURCE_COORDINATION_EX.json').read_bytes())==result['coordination_lock']
before=json.loads((RUN/'INPUT_IDENTITIES.before.json').read_bytes())
after=json.loads((RUN/'INPUT_IDENTITIES.final.json').read_bytes())
assert isinstance(before,dict) and isinstance(after,list) and len(before)==len(after)==13
assert {r['path']:{k:r[k] for k in ('bytes','sha256','git_blob')} for r in after}==before
cfg['materialization'].update(job_id=normal['job_id'],result=pin(raw),supervisor=pin(normal_raw),
                              git_state=result['current_git_state_after'],index=result['current_index'],
                              git_metadata=result['current_git_metadata'],git_metadata_gzip={k:meta[k] for k in ('bytes','sha256','git_blob')},records=records)
cfg['coordination_lock']=result['coordination_lock']
cfg['waiting_for_actual_records']='Actual d256 materialization normal/result/four records/raw index/Git metadata/coordination/three audits are bound. This remains HOLD pending Root exact maintenance approval and complete create-only staging. No maintenance or source/native qualification has run for this new candidate.'
cfg['source_inventory_observation']='Pre-held complete expected inventory 0463522b... and native projection 69cab8dc... match the actual original materialization RESULT before/after pins. The original producer fully read all source leaves. This is not a second external download of complete inventory bytes. New raw index and Git metadata were actually read from retained producer artifacts; future maintenance must reread all current source/Git bytes and exact metadata again.'
out=(json.dumps(cfg,indent=2,ensure_ascii=False)+'\n').encode()
config=write('WAITING_CONFIG.ACTUAL_MATERIALIZATION.json',out)
diff=write('CONFIG_ACTUAL_MATERIALIZATION.diff',''.join(difflib.unified_diff(cfg_raw.decode().splitlines(keepends=True),out.decode().splitlines(keepends=True),fromfile='original-HOLD-null-proofs',tofile='actual-materialization-HOLD')).encode())
review={'format':'hepta-actual-materialization-maintenance-binding-v1','status':'ACTUAL_PROOF_BOUND_MAINTENANCE_STILL_HOLD','job_id':normal['job_id'],'result':pin(raw),'normal':pin(normal_raw),'records':records,
        'observed_command_count':len(commands),'observed_mutation_count':len(mutations),'all_commands_zero_no_timeout':True,'all_mutations_observed':True,'artifact_count':len(artifacts),'complete_input_count':len(after),'input_before_after_equal':True,
        'actual_git_metadata':pin((RUN/'final.git-metadata.json').read_bytes()),'actual_raw_index':pin((RUN/'final.new-index.raw').read_bytes()),
        'config':config,'diff':diff,'historical_holds_preserved':True,'approval_false':cfg['root_execution_approved'] is False,'formal_approved_config_created':cfg['formal_approved_config_created'],
        'no_maintenance_H_request':True,'no_native_current_fs_read':True,'scope':'Pure offline binding of already completed original SDK and artifact bytes; does not execute guard/preflight/main or replace future live checks.'}
reviewrow=write('ACTUAL_MATERIALIZATION_BINDING_REVIEW.json',(json.dumps(review,indent=2)+'\n').encode())
print(json.dumps({'config':config,'diff':diff,'review':reviewrow}))
