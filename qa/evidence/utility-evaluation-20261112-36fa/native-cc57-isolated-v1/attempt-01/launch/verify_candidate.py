import ast, base64, difflib, hashlib, json, pathlib
ROOT = pathlib.Path("/tmp/hepta-36fa-isolated-native-launch-candidate-v1")
def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), git_blob=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())
expected = json.loads((ROOT / 'EXPECTED_CANDIDATE_FILES.json').read_bytes())
actual = []
for row in expected:
    raw = (ROOT / row['name']).read_bytes()
    assert identity(raw) == {k:row[k] for k in ('bytes','sha256','git_blob')}, row['name']
    actual.append(dict(name=row['name'], **identity(raw)))
old = (ROOT / 'ORIGINAL_NATIVE_BOOTSTRAP.py').read_text()
new = (ROOT / 'NATIVE_BOOTSTRAP.CANDIDATE.py').read_text()
before_ast, after_ast = ast.parse(old), ast.parse(new)
compile(after_ast, str(ROOT / 'NATIVE_BOOTSTRAP.CANDIDATE.py'), 'exec')
def funcs(tree, code):
    return {n.name: ast.get_source_segment(code, n) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
old_funcs, new_funcs = funcs(before_ast, old), funcs(after_ast, new)
assert set(old_funcs) == set(new_funcs) == {'check','identity','real_parents','retain','read_fixed'}
assert old_funcs == new_funcs
tail = '# The original native wrapper owns all gate results and its own failure records.\n'
assert old.split(tail)[1] == new.split(tail)[1]
span = json.loads((ROOT / 'STAGING_REPLACEMENT.json').read_bytes())
assert new.count(span['after']) == 1 and old.count(span['before']) == 1
restored = new.replace(span['after'], span['before'])
for prefix in ('BASE = ', 'PINS = '):
    old_line = next(l for l in old.splitlines() if l.startswith(prefix))
    new_line = next(l for l in restored.splitlines() if l.startswith(prefix))
    assert restored.count(new_line) == 1
    restored = restored.replace(new_line, old_line)
for leaf in ('RESULT.json','ORIGINAL_RUN_RESULT.json'):
    old_value = "str(BASE / 'source-handoff' / '" + leaf + "')"
    new_value = "'/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2/source-handoff/" + leaf + "'"
    assert restored.count(new_value) == 1
    restored = restored.replace(new_value, old_value)
assert restored == old
request = json.loads((ROOT / 'NATIVE_PROCESS_INPUT.CANDIDATE.json').read_bytes())
assert set(request) == {'host','executable','args','cwd','stdin','idempotency_key','timeout_seconds'}
assert request['host']=='desktop' and request['executable']=='/usr/bin/python3' and request['cwd']=='/home/qian-qi'
assert request['args']==['-B','-c',new] and request['timeout_seconds']==45000
assert request['idempotency_key']=='hepta-utility-36fa-final-native-gates-cc57-isolated-v1'
assert request['stdin'].encode() == (ROOT / 'NATIVE_STDIN.CANDIDATE.json').read_bytes()
payload = json.loads(request['stdin'])
assert set(payload)=={'format','files','source_supervisor_base64'}
assert payload['format']=='hepta-isolated-native-staging-and-source-prerequisite-v1'
pins_node = next(n for n in after_ast.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PINS' for t in n.targets))
pins = ast.literal_eval(pins_node.value)
assert len(payload['files'])==len(pins)==6
seen={}
for row in payload['files']:
    assert set(row)=={'name','base64'} and row['name'] not in seen
    raw=base64.b64decode(row['base64'],validate=True)
    assert identity(raw)==pins[row['name']]
    seen[row['name']]=raw
assert set(seen)==set(pins)
cfg=json.loads(seen['APPROVED_QUALIFICATION_INPUT.json'])
hold=json.loads(pathlib.Path('/tmp/hepta-36fa-isolated-native-actual-inputs-v1/WAITING_CONFIG.ACTUAL_MATERIALIZATION.json').read_bytes())
assert cfg['state']=='READY_FOR_FINAL_SOURCE_QUALIFICATION' and cfg['root_execution_approved'] is True
undo=dict(cfg);undo['state']=hold['state'];undo['root_execution_approved']=False
assert undo==hold
assert cfg['admission_pin']==pins['qualification-admission.py'] and cfg['native_driver_pin']==pins['native-driver.original.py'] and cfg['plan_pin']==pins['PLAN.original.json']
assert cfg['isolated_materialization']['supervisor']==pins['ISOLATED_MATERIALIZATION_NORMAL.original.json']
success_node=next(n for n in after_ast.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE_SUCCESS' for t in n.targets))
success=ast.literal_eval(success_node.value)
normal=base64.b64decode(payload['source_supervisor_base64'],validate=True)
assert identity(normal)==success['supervisor']
sdk=json.loads(normal); terminal=json.loads(sdk['content'][0]['text'])
assert sdk['isError'] is False and terminal['job_id']==success['job_id']=='1a1d23c92f3-2564-1cb4'
assert terminal['state']=='succeeded' and terminal['exit_code']==0
assert all(terminal[k] is False for k in ('timed_out','cancelled','automatic_retry'))
assert all(terminal[k] is True for k in ('output_complete','output_durable','terminal_publication_confirmed'))
assert not any(terminal.get('log_truncated',{}).values())
report={
 'format':'hepta-isolated-native-launch-static-byte-review-v1',
 'status':'STATIC_CANDIDATE_ONLY_ROOT_EXACT_APPROVAL_REQUIRED',
 'qualification':False,'native_main_called':False,'H_calls':0,
 'candidate_files':actual,'all_files_full_hash_verified':True,
 'five_original_helpers_byte_identical':sorted(old_funcs),
 'original_native_tail_byte_identical':True,
 'all_code_inverse_replacements_restore_original_bytes':True,
 'inverse_replacements':['BASE','PINS','two SOURCE_SUCCESS absolute historical paths','one create-only staging span'],
 'six_staged_inputs':pins,
 'formal_candidate_only_two_approval_fields_changed':True,
 'seven_request_fields_exact':True,'no_env_override':True,'outer45000_unchanged':True,
 'source_success_remains_original_historical_execution':success,
 'materialization_actual':cfg['isolated_materialization'],
 'module_constructor_and_native_wrapper_not_called':True,
 'runtime_risks_are_original_live_checks_not_assumed_pass':True
}
for name, data in [
 ('STATIC_REVIEW.json',(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()),
 ('FROM_ORIGINAL_NATIVE.diff',''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='69e8/original-native-bootstrap.py',tofile='isolated-native-candidate.py')).encode())
]:
    with (ROOT/name).open('xb') as f:f.write(data)
print(json.dumps({'static_checks_passed':True,'report':identity((ROOT/'STATIC_REVIEW.json').read_bytes()),'diff':identity((ROOT/'FROM_ORIGINAL_NATIVE.diff').read_bytes()),'H_calls':0,'native_main_called':False}))
