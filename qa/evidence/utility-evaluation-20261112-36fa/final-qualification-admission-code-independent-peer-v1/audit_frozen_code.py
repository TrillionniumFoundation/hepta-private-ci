#!/usr/bin/env python3
"""Offline byte/AST/captured-JSON audit; never import or invoke an admission module."""
from pathlib import Path
import ast
import copy
import hashlib
import json
import os
import re
import stat
import textwrap

HERE = Path(__file__).resolve().parent
AUTHOR = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1')
EXPECTED_CODE = 'c77e3be6230d3267c08333be582f69f23c016fb9'
EXPECTED_CFG = '460139b9ce065184a0809def0823d8d20c45fe41'
EXPECTED_DIFF = '1a8faaeca7f0a48feeab0e57f9c687ba025d1eec'
def ident(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
def read(path, expected=None):
    raw = path.read_bytes()
    if expected is not None:
        assert ident(raw)['git_blob'] == expected, (str(path), ident(raw))
    return raw
def j(name):
    return json.loads(original_bytes[name])
def functions(raw):
    text = raw.decode(); lines = text.splitlines(keepends=True); tree = ast.parse(text)
    result = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            result[node.name] = (node, ''.join(lines[node.lineno-1:node.end_lineno]).encode())
        if isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, ast.FunctionDef):
                    result[node.name + '.' + method.name] = (method, ''.join(lines[method.lineno-1:method.end_lineno]).encode())
    return tree, result
def apply_unified(old, patch):
    old_lines = old.decode().splitlines(keepends=True)
    lines = patch.decode().splitlines(keepends=True)
    output = []; cursor = 0; at = 0; hunks = 0
    while at < len(lines):
        line = lines[at]
        if not line.startswith('@@ '):
            at += 1; continue
        match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        assert match
        start = int(match[1]) - 1; removed = int(match[2] or '1'); added = int(match[4] or '1')
        assert start >= cursor
        output.extend(old_lines[cursor:start]); cursor = start; at += 1; a = b = 0
        while at < len(lines) and not lines[at].startswith('@@ '):
            line = lines[at]
            if line.startswith(('--- ', '+++ ')): break
            assert line[:1] in (' ', '+', '-'), repr(line)
            if line[:1] in (' ', '-'):
                assert old_lines[cursor] == line[1:], (cursor, old_lines[cursor], line)
                cursor += 1; a += 1
            if line[:1] in (' ', '+'):
                output.append(line[1:]); b += 1
            at += 1
        assert (a, b) == (removed, added), (a, b, removed, added)
        hunks += 1
    output.extend(old_lines[cursor:])
    return ''.join(output).encode(), hunks

code = read(HERE/'inputs/qualification-admission.HOLD.py', EXPECTED_CODE)
cfg_raw = read(HERE/'inputs/QUALIFICATION_CONFIG.HOLD.json', EXPECTED_CFG)
delta = read(HERE/'inputs/ADMISSION_DELTA.patch', EXPECTED_DIFF)
input_index_raw = read(AUTHOR/'INPUT_COPY_INDEX.json')
input_index = json.loads(input_index_raw)
original_bytes = {}
original_rows = []
for row in input_index['entries']:
    raw = read(AUTHOR/'inputs'/row['name'], row['git_blob'])
    assert ident(raw) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    original_bytes[row['name']] = raw
    original_rows.append({'name': row['name'], **ident(raw)})
old = original_bytes['ADMISSION_23D412.original.py']
assert ident(old)['git_blob'] == '23d412ed67927a6cbfa5f521884e891afc93eb6f'
tree, defs = functions(code); old_tree, old_defs = functions(old)
same = [name for name in old_defs if old_defs[name][1] == defs[name][1]]
changed = [name for name in old_defs if old_defs[name][1] != defs[name][1]]
assert len(old_defs) == 13 and len(same) == 9
assert changed == ['Admission.__init__', 'Admission.acquire_and_validate', 'Admission.validate_materialization', 'Admission.finish']
reconstructed, hunk_count = apply_unified(old, delta)
assert reconstructed == code
constants = {}
for node in tree.body:
    if not isinstance(node, ast.Assign): continue
    assert len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
    name = node.targets[0].id
    if isinstance(node.value, ast.Call):
        assert isinstance(node.value.func, ast.Name) and node.value.func.id == 'Path' and len(node.value.args) == 1 and not node.value.keywords
        constants[name] = Path(ast.literal_eval(node.value.args[0]))
    else:
        constants[name] = ast.literal_eval(node.value)

# Only these literal-data checks are compiled. No class, constructor, loader,
# inventory observer, filesystem observer, acquire/finish or gate entrypoint is compiled.
pure = ['check', 'identity', 'pin', 'exact_pin', 'pin_fields', 'audited', 'artifact_catalog',
        'canonical_to_v5_projection', 'physical_projection', 'native_projection',
        'metadata_file_projection', 'require_stage', 'Admission._require_complete_bindings',
        'Admission._check_materialization', 'Admission._check_archive',
        'Admission._check_maintenance', 'Admission._check_final_format']
ns = {'Path': Path, 'hashlib': hashlib, 'json': json, 'os': os, 're': re, 'stat': stat, **constants}
for name in pure:
    node = copy.deepcopy(defs[name][0]); node.decorator_list = []
    assert all(not (isinstance(c, ast.Call) and ast.unparse(c.func) in
                   {'open', 'os.open', 'os.mkdir', 'exec', 'eval', 'compile', 'Path.read_bytes'}) for c in ast.walk(node))
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<selected-frozen-pure-predicate>', 'exec'), ns)

accepted = []; rejected = []
def accept(label, fn, *args):
    value = fn(*args); accepted.append(label); return value
def reject(label, fn, *args):
    try: fn(*args)
    except (RuntimeError, KeyError, TypeError, ValueError, AssertionError) as error:
        rejected.append({'case': label, 'exception': type(error).__name__, 'reason': str(error)})
    else: raise AssertionError('incorrectly accepted negative case ' + label)
materialized = j('MATERIALIZATION_3BB_RESULT.json')
packet = j('MATERIALIZATION_3BB_PACKET.json')
records = {key: j(name + '.json') for key, name in constants['MATERIALIZATION_RECORDS'].items()}
accept('actual 3bb full result/packet/four records', ns['_check_materialization'], materialized, packet, records)
maintenance = j('MAINTENANCE_41E_RESULT.json')
maintenance_cfg = j('MAINTENANCE_41E_CONFIG.json')
maintenance_inputs = j('MAINTENANCE_41E_INPUT_IDENTITIES.json')
accept('actual 41e source, terminals, budgets and original inputs', ns['_check_maintenance'], maintenance, materialized, maintenance_cfg, maintenance_inputs)
final_format = j('FINAL_FORMAT_50F_RESULT.json')
final_cfg = j('FINAL_NONRUST_CONFIG.execution-candidate.json')
accept('actual 50f four paths, original fmt and complete endpoint', ns['_check_final_format'], final_format, maintenance, final_cfg)
archive = j('ARCHIVE_V3_RESULT.json'); readback = j('ARCHIVE_V3_READBACK.json'); environment = j('HISTORICAL_ENVIRONMENT_READY.json')
accept('actual archive v3 and unmodified historical ENV content projection', ns['_check_archive'], archive, readback, environment)
for name, wrapped in [('MATERIALIZATION_3BB_ARTIFACTS.json', False), ('MAINTENANCE_41E_ARTIFACTS.json', True), ('FINAL_FORMAT_50F_ARTIFACTS.json', True)]:
    accept('exact artifact schema '+name, ns['artifact_catalog'], j(name), wrapped)

v5 = j('MAINTENANCE_41E_GIT_METADATA.json')
files = accept('actual V5 metadata envelope', ns['metadata_file_projection'], v5)
mat_files = j('MATERIALIZATION_3BB_GIT_METADATA.json')
assert len(files) == len(mat_files) == 6 and set(files) == {row['path'] for row in mat_files}
for row in mat_files:
    expected = {'path': row['path'], 'kind': 'file', 'bytes': row['bytes'], 'sha256': row['sha256'], 'mode': stat.S_IMODE(row['stat']['st_mode'])}
    expected.update({a: row['stat'][b] for a,b in [('device','st_dev'),('inode','st_ino'),('nlink','st_nlink'),('mtime_ns','st_mtime_ns'),('ctime_ns','st_ctime_ns')]})
    assert files[row['path']] == expected
accepted.append('actual 3bb six-file to 41e twelve-row DFS metadata bridge')
catalog41 = ns['artifact_catalog'](j('MAINTENANCE_41E_ARTIFACTS.json'), True)
catalog50 = ns['artifact_catalog'](j('FINAL_FORMAT_50F_ARTIFACTS.json'), True)
rawpin = lambda row: {k: row['raw_'+k] for k in ('bytes','sha256','git_blob')}
assert rawpin(catalog41['SOURCE.before.inventory.json.gz']) == ns['pin_fields'](materialized['current_source_after']['inventory'])
assert rawpin(catalog41['final.inventory.json.gz']) == rawpin(catalog50['SOURCE.before.inventory.json.gz']) == constants['MAINTENANCE_FINAL_PIN']
assert rawpin(catalog50['final.inventory.json.gz']) == constants['FINAL_FORMAT_PIN']
accepted.append('actual catalog raw identities connect 3bb -> 41e -> 50f')
assert constants['RUNTIME_GUARD'] == {k: maintenance_cfg[k] for k in constants['RUNTIME_GUARD']}
accepted.append('entire unchanged runtime guard equals actual maintenance control projection')

# These negatives mutate captured data only. None is represented as a new observation.
for label, base, key, wrong, checker, extra in [
    ('materialization must not be relabelled final canonical', materialized, 'source_commit', constants['FINAL_SUBJECT']['commit'], '_check_materialization', [packet, records]),
    ('materialization cannot grant tests', materialized, 'qualification', True, '_check_materialization', [packet, records]),
    ('maintenance cannot use materialization as final subject', maintenance, 'source_commit', constants['FINAL_SUBJECT']['commit'], '_check_maintenance', [materialized, maintenance_cfg, maintenance_inputs]),
    ('maintenance command failure remains rejected', maintenance, 'status', 'FAILED', '_check_maintenance', [materialized, maintenance_cfg, maintenance_inputs]),
    ('final format cannot claim a repeated fix', final_format, 'fix_dispatched', True, '_check_final_format', [maintenance, final_cfg]),
    ('final formatter changed paths require rejection', final_format, 'formatter_changed_paths', ['CALLERS.toml'], '_check_final_format', [maintenance, final_cfg]),
    ('archive cannot overwrite historical source role', archive, 'source_repo', constants['HISTORICAL_REPO'], '_check_archive', [readback, environment]),
]:
    value = copy.deepcopy(base); value[key] = wrong; reject(label, ns[checker], value, *extra)
value = copy.deepcopy(maintenance); value['stages'][0]['timeout_seconds'] += 1
reject('original fix budget immutable', ns['_check_maintenance'], value, materialized, maintenance_cfg, maintenance_inputs)
value = copy.deepcopy(final_format); value['applied_paths'] = value['applied_paths'][:-1]
reject('all four exact non-Rust paths required', ns['_check_final_format'], value, maintenance, final_cfg)
value = copy.deepcopy(readback); value['stat']['st_ino'] = environment['tool_and_material_files']['v8-sandbox-archive']['inode']
reject('new archive stat cannot be old ENV inode', ns['_check_archive'], archive, value, environment)
cfg = json.loads(cfg_raw)
reject('frozen HOLD cannot satisfy complete actual binding', ns['_require_complete_bindings'], cfg)
value = copy.deepcopy(cfg); value.update(source=constants['FINAL_SUBJECT']['commit'], tree=constants['FINAL_SUBJECT']['tree'], parents=constants['FINAL_SUBJECT']['parents'])
reject('known final commit still lacks actual canonical inventory', ns['_require_complete_bindings'], value)
value = copy.deepcopy(v5); value['files'].append(copy.deepcopy(value['files'][0]))
reject('duplicate metadata path', ns['metadata_file_projection'], value)

init = defs['Admission.__init__'][0]
assert ast.unparse(init.body[0].value.func) == 'check'
assert ast.unparse(init.body[1].value.func) == 'self._require_complete_bindings'
assert all(not isinstance(n, ast.Call) or ast.unparse(n.func) not in {'os.mkdir','load','os.open'} for statement in init.body[:2] for n in ast.walk(statement))
assert cfg['state'] == 'HOLD_FOR_ACTUAL_FINAL_SOURCE_BINDINGS' and cfg['root_execution_approved'] is False
assert all(cfg['canonical_alignment'][key] is None for key in ['job_id','result','supervisor','artifacts','final_index_raw','final_git_metadata_raw'])

plan = j('PLAN_3AEF.json')
original_controls = plan['unchanged_original_controls']['reviewed_source_pins']['files']
assert len(original_controls) == len({x['path'] for x in original_controls}) == 12
workflow = original_bytes['WORKFLOW_D256.yml']
assert ident(workflow) == constants['WORKFLOW_OVERRIDE_READY']['reviewed_current_pin']
old_workflow = next(row for row in original_controls if row['path'] == constants['WORKFLOW_OVERRIDE_READY']['path'])
assert ns['pin_fields'](old_workflow) == constants['WORKFLOW_OVERRIDE_READY']['original_plan_pin']
marker = '          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
text = workflow.decode(); assert text.count(marker) == 1
embedded = textwrap.dedent(text.split(marker,1)[1].split('          PY\n',1)[0])
driver_tree = ast.parse(embedded); workflow_constants = {}
for node in driver_tree.body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and getattr(node.targets[0],'id',None) in ('parents','packages'):
        name=node.targets[0].id;assert name not in workflow_constants;workflow_constants[name]=ast.literal_eval(node.value)
assert len(workflow_constants['parents']) == len(set(workflow_constants['parents'])) == 48
assert workflow_constants['packages'] == constants['ORIGINAL_ORDINARY_PACKAGES']

opens = [{'line':n.lineno,'call':ast.unparse(n)} for n in ast.walk(tree) if isinstance(n,ast.Call) and ast.unparse(n.func)=='os.open']
assert len(opens)==2 and all('os.O_RDONLY | os.O_NOFOLLOW' in row['call'] for row in opens)
for n in ast.walk(tree):
    if isinstance(n,ast.Call):
        assert ast.unparse(n.func) not in {'subprocess.run','subprocess.Popen','os.system','os.execv','os.execve','signal.alarm','time.sleep','m.main','self.m.main','self.inventory.main'}
live_calls = [{'owner':name,'line':n.lineno} for name,(node,_) in defs.items() for n in ast.walk(node) if isinstance(n,ast.Call) and ast.unparse(n.func)=='self._require_live_metadata']
assert [r['owner'] for r in live_calls] == ['Admission.acquire_and_validate','Admission.finish']
constant_bytes = sum(len(ast.get_source_segment(code.decode(),n).encode()) for n in tree.body if isinstance(n,ast.Assign))
result = {
 'format':'hepta-qualification-admission-code-independent-dataflow-v1',
 'scope':'Frozen source AST, captured actual JSON and literal-only pure predicates; no module import, constructor, acquire, finish, live observation, gate or H invocation.',
 'code':ident(code),'hold_config':ident(cfg_raw),'diff':ident(delta),'input_index':ident(input_index_raw),
 'originals':original_rows,'old_definition_count':len(old_defs),'unchanged_definitions':same,'migrated_definitions':changed,
 'new_helpers':sorted(set(defs)-set(old_defs)),'new_helpers_count':len(set(defs)-set(old_defs)),
 'complete_patch_apply_equal':True,'patch_hunks':hunk_count,'top_level_constant_bytes':constant_bytes,
 'accepted':accepted,'rejected':rejected,'selected_pure_functions':pure,
 'metadata_bridge':{'materialization_file_rows':len(mat_files),'v5_all_rows':len(v5['files']),'mapped_files':len(files),'canonical_actual_pending':True,'uid_gid_removal_is_projection_only':True},
 'workflow':{'pin':ident(workflow),'old_pin':ns['pin_fields'](old_workflow),'original_controls':12,'overrides':1,'unchanged_original_controls':11,'parents':workflow_constants['parents'],'packages':workflow_constants['packages']},
 'live_metadata_call_sites':live_calls,'os_open_calls':opens,
 'HOLD_rejected_before_any_constructor_io':True,'canonical_actual_in_this_review':None,
 'H_calls':0,'project_commands':0,'runtime_admission_calls':0,'qualification':False,
 'limitations':['No actual canonical output was supplied to this frozen first-layer review.','No live directory or index observer was executed.','Inherited finish can report a secondary SourceChanged when initial_git was never established; do not infer actual source mutation from that secondary error alone.','No source/native qualification was dispatched or passed by this audit.']
}
with (HERE/'FROZEN_CODE_DATAFLOW.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps({'bytes':len(code),'old':len(old_defs),'same':len(same),'migrated':len(changed),'new_helpers':len(set(defs)-set(old_defs)),'accepted':len(accepted),'negative_rejections':len(rejected),'originals':len(original_rows),'qualification':False},sort_keys=True))
