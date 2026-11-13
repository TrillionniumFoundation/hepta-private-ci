#!/usr/bin/env python3
"""Pure local byte transformation. Never imports or executes maintenance controls."""
import ast
import copy
import difflib
import hashlib
import json
from pathlib import Path

ROOT=Path('/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1')
INPUT=ROOT/'inputs'
RUNTIME=Path('/tmp/hepta-36fa-provider-0c59-materialization-runtime-v1')
CONTROL='/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-maintenance-v1'
REPO='/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1'
DONOR='/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1'
OLD_REPO='/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
MATERIALIZED='/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-isolated-materialization-v1/run'
RESTORED='/home/qian-qi/hepta-utility-36fa-evidence/v8-single-archive-restore-v3/run'
LOCK='/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock'
HEAD='0c59aaca0b4932507f068c723f73da2f96729b3d'
TREE='4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09'
DONOR_HEAD='cc57c7198db6293ccca562253c42fffbe2a04633'
DONOR_TREE='b7b357c07b5539769a068c6b9b009629f5612d1e'

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def read(name):
    return (INPUT/name).read_bytes()

def js(value):
    return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()

def save(name,body):
    path=ROOT/name
    if path.exists():
        assert path.read_bytes()==body, 'never overwrite a changed frozen artifact: '+name
    else:
        path.write_bytes(body)
    return {'name':name,'path':str(path),**pin(body)}

def replace_once(source,old,new):
    assert source.count(old)==1, ('exact unique replacement',old,source.count(old))
    return source.replace(old,new,1)

original=read('DRIVER_6632.original.py').decode()
assert pin(original.encode())['git_blob']=='6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'
old_ast=ast.parse(original)
old_defs={n.name:ast.get_source_segment(original,n) for n in old_ast.body
          if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
new_proofs=(ROOT/'NEW_PROOF_FUNCTIONS.py.txt').read_text()
new_defs={n.name:ast.get_source_segment(new_proofs,n) for n in ast.parse(new_proofs).body}
materialization=json.loads(read('MATERIALIZATION_RESULT.original.json'))
archive=json.loads(read('ARCHIVE_READBACK.original.json'))
inventory=materialization['current_source_after']['inventory']
native_inventory=materialization['current_source_after']['native_inventory']
assert materialization['current_source_before']==materialization['current_source_after']
assert materialization['current_git_state_before']==materialization['current_git_state_after']
assert materialization['current_git_metadata']==pin(read('MATERIALIZATION_GIT_METADATA.original.json'))
assert materialization['current_index']==json.loads(read('MATERIALIZATION_INDEX_CHECK.original.json'))

driver=original
replacements=[
 ('REPO=pathlib.Path("'+OLD_REPO+'")','REPO=pathlib.Path("'+REPO+'")'),
 ('EVIDENCE=pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1")',
  'EVIDENCE=pathlib.Path("'+CONTROL+'")'),
 ('OUT=EVIDENCE/"run-v5"','OUT=EVIDENCE/"run"'),
 ('CONFIG=EVIDENCE/"APPROVED_CONFIG_V5.json"','CONFIG=EVIDENCE/"APPROVED_MAINTENANCE_CONFIG.json"'),
 ('INVENTORY_FILE=EVIDENCE/"inventory-driver-v2.py"','INVENTORY_FILE=EVIDENCE/"inventory-driver.original.py"'),
 ('HEAD="9c4a11f61d30e9cc352bf44d56c98909d202a55d"','HEAD="'+HEAD+'"'),
 ('TREE="ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7"','TREE="'+TREE+'"'),
 ('PARENTS=[SEED_HEAD]','PARENTS=["'+DONOR_HEAD+'"]'),
 ('LEAVES=15188','LEAVES=15237'),
 ('FIX=["just","fix","-p","codex-hepta-intelligence-eval","-p","codex-hepta-agentd"]',
  'FIX=["just","fix","-p","codex-hepta-intelligence-eval","-p","codex-hepta-agentd","-p","codex-hepta-learning-ledger"]')]
for before,after in replacements:
    driver=replace_once(driver,before,after)
for name in ['SEED_INVENTORY','SUCCESSOR_INVENTORY','SOURCE_ADVANCE_CHANGE','SOURCE_ADVANCE_PACKET_PIN','SOURCE_ADVANCE_BEFORE_INDEX']:
    node=next(n for n in old_ast.body if isinstance(n,ast.Assign) and
              any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
    before=ast.get_source_segment(original,node)
    if name=='SUCCESSOR_INVENTORY':
        after='SUCCESSOR_INVENTORY='+json.dumps(inventory,sort_keys=True,separators=(',',':'))
    else:
        after=''
    driver=replace_once(driver,before+'\n',after+'\n' if after else '')
anchor='PARENTS=["'+DONOR_HEAD+'"]\n'
constants=(
    'HISTORICAL_RUNTIME_REPO=pathlib.Path("'+OLD_REPO+'")\n'
    'MATERIALIZATION_DONOR=pathlib.Path("'+DONOR+'")\n'
    'DONOR_HEAD="'+DONOR_HEAD+'"\n'
    'DONOR_TREE="'+DONOR_TREE+'"\n'
    'COORDINATION_LOCK=pathlib.Path("'+LOCK+'")\n'
    'NATIVE_INVENTORY='+json.dumps(native_inventory,sort_keys=True,separators=(',',':'))+'\n')
driver=replace_once(driver,anchor,anchor+constants)
driver=replace_once(driver,old_defs['validate_materialization'],new_defs['validate_materialization'])
driver=replace_once(driver,old_defs['validate_source_advance'],new_defs['validate_materialization_current'])
runtime=old_defs['validate_runtime_restoration']
runtime=replace_once(runtime,'observed.get("source_repo")==str(REPO)',
                     'observed.get("source_repo")==str(HISTORICAL_RUNTIME_REPO)')
runtime=replace_once(runtime,'    return environment','    validate_archive_restoration(environment)\n    return environment')
driver=replace_once(driver,old_defs['validate_runtime_restoration'],runtime+'\n\n'+new_defs['validate_archive_restoration'])
config_def=old_defs['validate_config']
anchor='    input_pins[str(CONFIG)]='
addition=('    check(value.get("minimum_target_free_bytes")==34359738368 and\n'
          '          value.get("create_target_if_absent") is False,"unchanged 32 GiB existing-target contract")\n'
          '    check(value.get("outer_timeout_seconds")==9300 and\n'
          '          value.get("coordination_lock",{}).get("path")==str(COORDINATION_LOCK),\n'
          '          "original outer budget and one actual cooperative lock path")\n')
config_def=replace_once(config_def,anchor,addition+anchor)
driver=replace_once(driver,old_defs['validate_config'],config_def)
preflight=old_defs['initial_preflight']
preflight=replace_once(preflight,'    validate_source_advance(initial_inventory,initial_git_state)\n','')
preflight=replace_once(preflight,'    gzrecord("SOURCE_GIT_METADATA.before.json.gz",initial_git_metadata)\n',
                       '    gzrecord("SOURCE_GIT_METADATA.before.json.gz",initial_git_metadata)\n'
                       '    validate_materialization_current(observed,initial_inventory,initial_git_state,initial_git_metadata)\n')
driver=replace_once(driver,old_defs['initial_preflight'],preflight)
ast.parse(driver)
compile(driver,'driver-maintenance.HOLD.py','exec')
driver_info=save('driver-maintenance.HOLD.py',driver.encode())
save('DRIVER_6632_TO_SUCCESSOR.diff',''.join(difflib.unified_diff(
     original.splitlines(True),driver.splitlines(True),fromfile='6632/driver-v5.py',
     tofile='successor/driver-maintenance.HOLD.py')).encode())

old_cfg=json.loads(read('APPROVED_OLD_CONFIG.original.json'))
cfg=copy.deepcopy(old_cfg)
cfg.update(status='HOLD_PENDING_ROOT_EXACT_EXECUTION_APPROVAL',root_execution_approved=False,
           formal_approved_config_created=False,driver_sha256=driver_info['sha256'],
           driver_git_blob=driver_info['git_blob'],source_repo=REPO,source_commit=HEAD,
           source_tree=TREE,parents=[DONOR_HEAD],source_inventory=inventory,
           fix_argv=old_cfg['fix_argv']+['-p','codex-hepta-learning-ledger'],
           outer_timeout_seconds=9300,coordination_lock=materialization['coordination_lock'])
del cfg['source_advance']
cfg['historical_known_runtime_blockers']=cfg.pop('known_runtime_blockers')
cfg['materialization']={
    'job_id':'1a1d3cdda18-392-1e2',
    'result_path':MATERIALIZED+'/RESULT.json','result':pin(read('MATERIALIZATION_RESULT.original.json')),
    'supervisor_path':CONTROL+'/MATERIALIZATION_SUPERVISOR.original.json',
    'supervisor':pin(read('MATERIALIZATION_SUPERVISOR.original.json')),
    'git_state':materialization['current_git_state_after'],'index':materialization['current_index'],
    'git_metadata':materialization['current_git_metadata'],
    'git_metadata_gzip':pin((RUNTIME/'final.git-metadata.json.gz').read_bytes()),
    'records':{key:{k:materialization[key][k] for k in ('bytes','sha256','git_blob')}
               for key in ['command_records','mutation_records','input_records','artifact_records']}}
cfg['archive_restoration']={
    'job_id':'1a1d38b82e9-392-160',
    'result_path':RESTORED+'/RESULT.json','result':pin(read('RESTORE_V3_RESULT.original.json')),
    'supervisor_path':CONTROL+'/V8_RESTORATION_SUPERVISOR.original.json',
    'supervisor':pin(read('RESTORE_V3_NORMAL.original.json')),
    'archive_readback_path':RESTORED+'/ARCHIVE_READBACK.json',
    'archive_readback':pin(read('ARCHIVE_READBACK.original.json')),
    'artifacts_path':RESTORED+'/ARTIFACTS.json','artifacts':pin(read('RESTORE_V3_ARTIFACTS.original.json')),
    'archive_actual':archive}
cfg['waiting_for_actual_records']=(
    'HOLD. New candidate materialization RESULT/normal, four original records and complete original Git metadata '
    'are actual observed bytes; they do not approve maintenance. Runtime 86dd proof and ENV8b62 remain historical '
    'and byte-identical. The separate actual cc57 archive restore v3 is bound without editing historical inode data. '
    'Root must independently approve this exact successor and launcher before one maintenance request; the current '
    'launcher pins this unapproved HOLD config and refuses it. No future maintenance outcome, fresh process guard, '
    'actual launcher lease, tool verification, qualification or real task-chain result is supplied by this preparation.')
cfg['source_inventory_observation']=(
    'Complete expected inventory affce692... and native686c5168... exactly match actual new materialization '
    'RESULT 4832994442a8a1bc89ea3af7825a06310ceb7c64. Future maintenance must read the entire current inventory '
    'and six original Git files again and reproduce the original 2234-byte metadata, then preserve original '
    'complete maintenance metadata equality throughout fix/fmt. No source-advance proof is transplanted.')
cfg_info=save('MAINTENANCE_CONFIG.HOLD.json',js(cfg))
save('CONFIG_OLD_TO_HOLD.diff',''.join(difflib.unified_diff(
     read('APPROVED_OLD_CONFIG.original.json').decode().splitlines(True),
     js(cfg).decode().splitlines(True),fromfile='a66/APPROVED_CONFIG_V5.json',
     tofile='successor/MAINTENANCE_CONFIG.HOLD.json')).encode())

old_launcher=read('ACTUAL_V5_LAUNCHER.original.py').decode()
assert pin(old_launcher.encode())['git_blob']=='972319b7e0a5feea19f9ee582fadd6fdfb05023e'
launcher=old_launcher
launcher=replace_once(launcher,'ROOT=Path("/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1")',
                     'ROOT=Path("'+CONTROL+'")')
lnode=next(n for n in ast.parse(launcher).body if isinstance(n,ast.Assign) and
           any(isinstance(t,ast.Name) and t.id=='PINS' for t in n.targets))
pins={'driver-maintenance.py':tuple(driver_info[k] for k in ('bytes','sha256','git_blob')),
      'APPROVED_MAINTENANCE_CONFIG.json':tuple(cfg_info[k] for k in ('bytes','sha256','git_blob'))}
launcher=replace_once(launcher,ast.get_source_segment(launcher,lnode),'PINS='+repr(pins))
launcher=launcher.replace('"run-v5"','"run"').replace('"APPROVED_CONFIG_V5.json"','"APPROVED_MAINTENANCE_CONFIG.json"')
launcher=launcher.replace('"driver-v5.py"','"driver-maintenance.py"')
launcher=replace_once(launcher,'# This lease starts with this V5 launch; it does not cover historical runs.',
                     '# This fresh lease covers only this launch; the already observed cooperative lock is reused.')
old_lock='''LOCK=ROOT/"SOURCE_COORDINATION.lock"
created=False
try:
 lock_fd=os.open(LOCK,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);created=True
except FileExistsError:
 lock_fd=os.open(LOCK,os.O_RDWR|os.O_NOFOLLOW)
lock_info=os.fstat(lock_fd)'''
new_lock='''LOCK=Path("'''+LOCK+'''")
p=Path(LOCK.anchor)
for part in LOCK.parts[1:-1]:
 p=p/part;s=p.lstat();need(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode),"real existing lock parent")
created=False
lock_fd=os.open(LOCK,os.O_RDWR|os.O_NOFOLLOW)
lock_info=os.fstat(lock_fd)
need(config["coordination_lock"]["path"]==str(LOCK) and config["coordination_lock"]["mode"]=="LOCK_EX","same actual cooperative lock")
need({k:getattr(lock_info,k) for k in ("st_dev","st_ino","st_mode","st_uid","st_gid","st_nlink","st_size","st_mtime_ns","st_ctime_ns")}==config["coordination_lock"]["stat"],"exact actual lock inode/stat; no replacement lock")'''
launcher=replace_once(launcher,old_lock,new_lock)
launcher=launcher.replace(OLD_REPO,REPO)
launcher=launcher.replace('The original V5 main process exits; the descriptor is deliberately retained across exec.',
                          'The original maintenance main process exits; the descriptor is deliberately retained across exec.')
launcher=launcher.replace('SOURCE_COORDINATION_EX_V5.json','SOURCE_COORDINATION_EX.json')
launcher=launcher.replace('ACTUAL_LAUNCHER_V5.py','ACTUAL_LAUNCHER.py')
launcher=launcher.replace('ACTUAL_LAUNCHER_ARGV_V5.json','ACTUAL_LAUNCHER_ARGV.json')
launcher=launcher.replace('fixed_original_maintenance_v5_launcher_verified','fixed_original_maintenance_0c59_launcher_verified')
ast.parse(launcher);compile(launcher,'LAUNCHER.HOLD.py','exec')
launcher_info=save('LAUNCHER.HOLD.py',launcher.encode())
save('LAUNCHER_V5_TO_HOLD.diff',''.join(difflib.unified_diff(
     old_launcher.splitlines(True),launcher.splitlines(True),fromfile='972319/ACTUAL_LAUNCHER_V5.py',
     tofile='successor/LAUNCHER.HOLD.py')).encode())
typed=json.loads(read('ACTUAL_V5_PROCESS_INPUT.original.json'))
assert set(typed)=={'host','executable','args','cwd','idempotency_key','timeout_seconds'}
assert typed['args']==['-B','-c',old_launcher] and typed['timeout_seconds']==9300
typed['args']=['-B','-c',launcher]
typed['idempotency_key']='hepta-utility-36fa-provider-0c59-maintenance-v1'
save('PROCESS_INPUT.HOLD.json',js(typed))

new_ast=ast.parse(driver)
definitions={n.name:ast.get_source_segment(driver,n) for n in new_ast.body
             if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
unchanged=[name for name,body in old_defs.items() if definitions.get(name)==body]
changed=[name for name in old_defs if name in definitions and definitions[name]!=old_defs[name]]
removed=sorted(set(old_defs)-set(definitions));added=sorted(set(definitions)-set(old_defs))
assert changed==['validate_materialization','validate_runtime_restoration','validate_config','initial_preflight'],changed
assert removed==['validate_source_advance'] and added==['validate_archive_restoration','validate_materialization_current']
assert len(unchanged)==45
for name in unchanged:
    assert ast.dump(ast.parse(old_defs[name]),include_attributes=False)==ast.dump(ast.parse(definitions[name]),include_attributes=False)
old_functions={n.name:ast.get_source_segment(old_launcher,n) for n in ast.parse(old_launcher).body if isinstance(n,ast.FunctionDef)}
new_functions={n.name:ast.get_source_segment(launcher,n) for n in ast.parse(launcher).body if isinstance(n,ast.FunctionDef)}
assert old_functions==new_functions and len(old_functions)==5
inventory_path=Path('/tmp/hepta-36fa-full-candidate-graph-v1/expected-inventory-v1/EXPECTED_CLEAN_INVENTORY.json')
actual_expected=inventory_path.read_bytes();assert pin(actual_expected)=={k:inventory[k] for k in ('bytes','sha256','git_blob')}
source_pins=ast.literal_eval(next(n.value for n in old_ast.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE_PINS' for t in n.targets)))
inventory_data=json.loads(actual_expected);files={r['path']:r for r in inventory_data['files']}
source_proof=[]
for row in source_pins:
    f=files[row['path']]
    assert (row['bytes'],row['sha256'],row['git_blob'])==(f['bytes'],f['sha256'],f['working_blob'])
    source_proof.append({'path':row['path'],'pin':{k:row[k] for k in ('bytes','sha256','git_blob')},'complete_expected_inventory_row_equal':True})
review={
    'format':'hepta-maintenance-successor-static-byte-review-v1','status':'HOLD_PREPARATION_ONLY',
    'original_driver':pin(original.encode()),'driver':driver_info,'config':cfg_info,'launcher':launcher_info,
    'original_definition_count':len(old_defs),'unchanged_definitions_byte_and_ast':unchanged,
    'changed_definitions':changed,'removed_inapplicable_definition':removed,'new_definitions':added,
    'unchanged_launcher_helpers':list(old_functions),'main_and_stage_byte_equal':True,
    'git_state_and_full_metadata_final_equality_byte_equal':True,'original_global_guard_byte_equal':True,
    'original_environment_preflight_byte_equal':True,'original_executable_entry_sixpins':source_proof,
    'fix_delta':'append only -p codex-hepta-learning-ledger after the original two packages',
    'budgets':{'fix':7200,'fmt':900,'outer':9300,'preflight':600,'record':300},
    'lock':{'path':LOCK,'observed_producer_stat':materialization['coordination_lock']['stat'],
            'existing_only':True,'exclusive_nonblocking':True,'inheritable_before_exec':True,
            'no_unlock_or_close_before_exec':True,'future_lease_is_not_observed':True},
    'exact_actual_inputs':{name:pin(read(name)) for name in [
        'MATERIALIZATION_RESULT.original.json','MATERIALIZATION_SUPERVISOR.original.json',
        'MATERIALIZATION_GIT_METADATA.original.json','MATERIALIZATION_INDEX_CHECK.original.json',
        'MATERIALIZATION_COMMANDS.original.json','MATERIALIZATION_MUTATIONS.original.json',
        'MATERIALIZATION_INPUTS.original.json','MATERIALIZATION_ARTIFACTS.original.json',
        'RESTORE_V3_RESULT.original.json','RESTORE_V3_NORMAL.original.json','ARCHIVE_READBACK.original.json',
        'RESTORE_V3_ARTIFACTS.original.json']},
    'executed':'Only this pure local byte/AST/config transformation; neither generated driver nor launcher was imported or run.',
    'h_calls':0,'cargo_fix_fmt_qa_gate_commands':0,'source_or_ref_writes':0,
    'maintenance_execution_approval':False,'qualification':False}
save('STATIC_REVIEW.json',js(review))
print(json.dumps({'driver':driver_info,'config':cfg_info,'launcher':launcher_info,
                  'unchanged_definitions':len(unchanged),'changed':changed,'removed':removed,'added':added},indent=2))
