"""Pure review: parse frozen files; never load or execute a candidate module."""
import ast
import base64
import hashlib
import json
import pathlib
import stat

P = pathlib.Path('/tmp/hepta-36fa-isolated-native-launch-candidate-v1')
A = pathlib.Path('/tmp/hepta-36fa-isolated-native-actual-inputs-v1')
M = pathlib.Path('/tmp/hepta-36fa-native-ci-resumed-20261113T0255/materialization')
OUT = pathlib.Path(__file__).parent

def ident(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                git_blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest())

def read(p):
    return p.read_bytes()

def assignment(source, name):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.Assign)
                and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == name)
    return node, ast.get_source_segment(source, node)

old = read(P/'ORIGINAL_NATIVE_BOOTSTRAP.py').decode()
new = read(P/'NATIVE_BOOTSTRAP.CANDIDATE.py').decode()
assert ident(old.encode())['git_blob'] == '1e3402a037b259f44213ac6de487e6d91cc6b445'
assert ident(new.encode())['git_blob'] == 'd60e62a8bb28f40d314c25824fb665ab8ef1ea9c'
inverse = new
for name in ['BASE', 'PINS']:
    before = assignment(old, name)[1]
    after = assignment(new, name)[1]
    assert inverse.count(after) == 1
    inverse = inverse.replace(after, before, 1)
for literal, expression in [
    ("'/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2/source-handoff/RESULT.json'", "str(BASE / 'source-handoff' / 'RESULT.json')"),
    ("'/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2/source-handoff/ORIGINAL_RUN_RESULT.json'", "str(BASE / 'source-handoff' / 'ORIGINAL_RUN_RESULT.json')")]:
    assert inverse.count(literal) == 1
    inverse = inverse.replace(literal, expression, 1)
replacement = json.loads(read(P/'STAGING_REPLACEMENT.json'))
assert inverse.count(replacement['after']) == 1
inverse = inverse.replace(replacement['after'], replacement['before'], 1)
assert inverse == old
functions = lambda s: {n.name: ast.get_source_segment(s,n) for n in ast.parse(s).body if isinstance(n,ast.FunctionDef)}
assert functions(new) == functions(old)
assert len(functions(new)) == 5
marker = '# The original native wrapper owns all gate results and its own failure records.'
assert new[new.index(marker):] == old[old.index(marker):]
body = ast.parse(new).body
tail_exec = body[-1]
assert isinstance(tail_exec,ast.Expr) and isinstance(tail_exec.value,ast.Call) and isinstance(tail_exec.value.func,ast.Name) and tail_exec.value.func.id == 'exec'

pins = ast.literal_eval(assignment(new,'PINS')[0].value)
success = ast.literal_eval(assignment(new,'SOURCE_SUCCESS')[0].value)
payload_raw = read(P/'NATIVE_STDIN.CANDIDATE.json')
payload = json.loads(payload_raw)
assert set(payload) == {'format','files','source_supervisor_base64'}
assert payload['format'] == 'hepta-isolated-native-staging-and-source-prerequisite-v1'
assert len(payload['files']) == len(pins) == 6
decoded = {row['name']:base64.b64decode(row['base64'],validate=True) for row in payload['files']}
assert len(decoded) == 6 and set(decoded) == set(pins)
for name,raw in decoded.items():
    assert ident(raw) == pins[name], name
    if name.endswith('.py'):
        ast.parse(raw)
req = json.loads(read(P/'NATIVE_PROCESS_INPUT.CANDIDATE.json'))
assert set(req) == {'host','executable','args','cwd','stdin','idempotency_key','timeout_seconds'}
assert req['host']=='desktop' and req['executable']=='/usr/bin/python3'
assert req['args']==['-B','-c',new] and req['stdin'].encode()==payload_raw
assert req['cwd']=='/home/qian-qi' and req['timeout_seconds']==45000
assert req['idempotency_key']=='hepta-utility-36fa-final-native-gates-cc57-isolated-v1'
assert pins['native-wrapper.py']['git_blob']=='de3e9dc5e7eb30f47929f9e1ba9f460035a94fae'
assert pins['native-driver.original.py']['git_blob']=='b92ddded4fce78aeb076d022471c62bf81ce2e4f'
assert pins['PLAN.original.json']['git_blob']=='3aefbc71d69d8014eed9e5a18269bbcc866a7583'
assert pins['qualification-admission.py']['git_blob']=='23d412ed67927a6cbfa5f521884e891afc93eb6f'

cfg = json.loads(decoded['APPROVED_QUALIFICATION_INPUT.json'])
hold = json.loads(read(A/'WAITING_CONFIG.ACTUAL_MATERIALIZATION.json'))
diffkeys = {k for k in set(cfg)|set(hold) if cfg.get(k)!=hold.get(k)}
assert diffkeys=={'state','root_execution_approved'}
assert cfg['state']=='READY_FOR_FINAL_SOURCE_QUALIFICATION' and cfg['root_execution_approved'] is True
assert cfg['runtime_guard']['minimum_target_free_bytes']==34359738368
assert cfg['runtime_guard']['create_target_if_absent'] is False
assert cfg['repo']=='/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1'
assert cfg['historical_source_repo']=='/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
assert success['result_path']=='/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2/source-handoff/RESULT.json'
assert success['original_run_result_path']=='/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2/source-handoff/ORIGINAL_RUN_RESULT.json'
normal_raw=base64.b64decode(payload['source_supervisor_base64'],validate=True)
assert ident(normal_raw)==success['supervisor']
normal_env=json.loads(normal_raw)
normal=json.loads(normal_env['content'][0]['text'])
assert normal_env['isError'] is False and len(normal_env['content'])==1
assert normal['job_id']==success['job_id']=='1a1d23c92f3-2564-1cb4'
for key,val in {'state':'succeeded','exit_code':0,'timed_out':False,'cancelled':False,'automatic_retry':False,'output_complete':True,'output_durable':True,'terminal_publication_confirmed':True}.items():
    assert normal[key]==val, key
assert not any(normal['log_truncated'].values())

material_raw=read(M/'RESULT.json')
assert ident(material_raw)==cfg['isolated_materialization']['result']
material=json.loads(material_raw)
material_normal_raw=decoded['ISOLATED_MATERIALIZATION_NORMAL.original.json']
assert ident(material_normal_raw)==cfg['isolated_materialization']['supervisor']
material_normal=json.loads(json.loads(material_normal_raw)['content'][0]['text'])
assert material_normal['job_id']==cfg['isolated_materialization']['job_id']=='1a1d2d20686-392-36'
assert material_normal['state']=='succeeded' and material_normal['exit_code']==0 and material_normal['timed_out'] is False
current=material['current_source_after']
assert current==material['current_source_before']
assert current['inventory']==cfg['full_physical_inventory'] and current['head']==cfg['source'] and current['tree']==cfg['tree'] and current['parents']==cfg['parents'] and current['status']==''
assert current['native_inventory']['sha256']==cfg['expected_inventory_sha256']
assert current['inventory']['filesystem_entries']==cfg['expected_file_count']==15188
assert material['current_git_state_after']==material['current_git_state_before']
assert material['current_git_state_after']['refs_bytes']==0
lock=material['coordination_lock']; expected_lock=cfg['coordination_lock']
assert lock['path']==expected_lock['path'] and lock['mode']=='LOCK_EX'
for actual, expected in [('st_dev','device'),('st_ino','inode'),('st_uid','uid'),('st_nlink','nlink')]:
    assert lock['stat'][actual]==expected_lock[expected]
assert stat.S_IMODE(lock['stat']['st_mode'])==expected_lock['mode']
records={}
for key,name in [('command_records','COMMANDS.json'),('mutation_records','MUTATION_INTENTS.json'),('input_records','INPUT_IDENTITIES.before.json'),('artifact_records','ARTIFACTS.json')]:
    raw=read(M/name); pin=material[key]
    assert pin['name']==name and ident(raw)=={k:pin[k] for k in ('bytes','sha256','git_blob')}
    records[key]=json.loads(raw)
assert records['command_records'] and all(x['actual_terminal']=='observed' and x['returncode']==0 and x['timed_out'] is False for x in records['command_records'])
assert [x['kind'] for x in records['mutation_records']]==['create_new_repository','write_exact_new_physical_source_and_standard_pack','import_independent_standard_pack','new_index_and_detached_head']
assert all(x['actual_terminal']=='observed' for x in records['mutation_records'])
assert len(material['final_audits'])==3 and all(x['status']=='verified' for x in material['final_audits'])
assert material['old_source_before']==material['old_source_after'] and material['old_git_state_before']==material['old_git_state_after']
assert material['old_source_writes'] is False and material['qualification'] is False

report={
 'format':'hepta-isolated-native-exact-launch-independent-static-review-v1',
 'verdict':'NO_CONCRETE_BLOCKER_IN_REVIEWED_STATIC_SCOPE',
 'bootstrap':ident(new.encode()), 'typed_request':ident(read(P/'NATIVE_PROCESS_INPUT.CANDIDATE.json')),
 'config':ident(decoded['APPROVED_QUALIFICATION_INPUT.json']),
 'source_supervisor':success['supervisor'], 'materialization_result':ident(material_raw),
 'five_helpers_full_bytes_equal':sorted(functions(new)),
 'inverse_restores_original_bootstrap_entire_bytes':True,
 'original_native_tail_outside_staging_try':True,
 'staged_files':pins, 'exact_typed_fields':sorted(req),
 'outer_timeout_seconds':45000, 'env_override':False,
 'source_success_paths_keep_historical_1cb4':True,
 'candidate_config_changed_only':sorted(diffkeys),
 'actual_materialization_current_full_inventory':current['inventory'],
 'actual_materialization_current_native_inventory':current['native_inventory'],
 'actual_materialization_records_verified':{k:material[k] for k in records},
 'actual_materialization_command_count':len(records['command_records']),
 'actual_materialization_lock_schema_projection_verified':True,
 'historical_runtime_and_current_source_instances_separate':True,
 'limits':[
   'Pure AST, byte and retained-artifact checks only; no candidate constructor, bootstrap, native wrapper, H or test was executed.',
   'Candidate state/approval values are not this reviewer granting execution; Root must approve the exact typed request.',
   'Historical source gates remain original 1cb4 execution. Materialization is a separate exact-content prerequisite, not a new source-gate run.',
   'Current runtime, live global guard, current raw Git equality, resource checks and all original native gates still must execute normally.',
   'Materialization proves two snapshot closures, not complete Git ancestry; old preserved scope is declared files/ref listing and physical snapshot, not entire donor metadata.',
   'This narrow review rechecks four materialization record identities/normal terminals; prior complete producer/consumer review remains a separate evidence item.'
 ]
}
out=OUT/'REVIEW.json'
with out.open('x') as f: json.dump(report,f,indent=2,sort_keys=True); f.write('\n')
print(json.dumps({'report':str(out),**ident(read(out)),'verdict':report['verdict'],'commands':len(records['command_records'])}))
