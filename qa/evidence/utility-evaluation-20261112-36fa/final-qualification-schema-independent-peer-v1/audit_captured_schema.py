#!/usr/bin/env python3
"""Pure offline inspection of captured bytes. Does not import/execute any input module."""
import ast
import hashlib
import json
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
INPUT = Path('/tmp/hepta-36fa-final-qualification-admission-successor-hold-v1/inputs')
MAT = Path('/tmp/hepta-36fa-coordinator-a489-materializer-runtime-v1')
MAINT = Path('/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1')

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def no_duplicates(items):
    result = {}
    for key, value in items:
        assert key not in result, key
        result[key] = value
    return result

def parse(raw):
    return json.loads(raw, object_pairs_hook=no_duplicates)

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()

input_rows = []
def read(path, expected):
    raw = path.read_bytes()
    actual = identity(raw)
    assert actual['git_blob'] == expected, (path, actual)
    input_rows.append({'local': str(path), **actual})
    return raw

def read_input(name, expected):
    return read(INPUT / name, expected)

get_inputs = [
    ('ADMISSION_23D412.original.py', '23d412ed67927a6cbfa5f521884e891afc93eb6f'),
    ('V5_GUARD_6632.original.py', '6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'),
    ('CANONICAL_TEMPLATE_E8D606.HOLD.py', 'e8d606b801b54ab949c5f215c49cdf47ed0ea89a'),
    ('MATERIALIZATION_3BB_RESULT.json', '30ab4aad6ff10942063da972e02db49629e3809c'),
    ('MAINTENANCE_41E_RESULT.json', 'b87aed7647ac34e3db0e381110bf685438aee0ee'),
    ('ARCHIVE_V3_READBACK.json', 'e1c3ebf8a5c1a0de7b3aaa15189bbc1e733266a8'),
    ('PLAN_3AEF.json', '3aefbc71d69d8014eed9e5a18269bbcc866a7583'),
    ('WORKFLOW_D256.yml', 'c0012652889b0cca409b27f87bfdc74b234c0fbe'),
]
raws = {}
get_records = []
for name, pin in get_inputs:
    body = read_input(name, pin)
    sdk_path = HERE / 'github' / (name + '.GET.original.json')
    sdk = parse(sdk_path.read_bytes())
    assert sdk['structuredContent']['content'].encode() == body, name
    raws[name] = body
    get_records.append({'name': name, **identity(body), 'full_get_equal': True, 'sdk': str(sdk_path)})

env_path = Path('/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1/inputs/HISTORICAL_ENV8B62.original.json')
env_raw = read(env_path, '8b62ac16f554c1f34ee72974637752f5a3b58aec')
env_sdk = HERE / 'github/HISTORICAL_ENV8B62.original.json.GET.original.json'
assert parse(env_sdk.read_bytes())['structuredContent']['content'].encode() == env_raw
get_records.append({'name': env_path.name, **identity(env_raw), 'full_get_equal': True, 'sdk': str(env_sdk)})

materialized = parse(raws['MATERIALIZATION_3BB_RESULT.json'])
maintained = parse(raws['MAINTENANCE_41E_RESULT.json'])
packet = parse(read_input('MATERIALIZATION_3BB_PACKET.json', 'b05c78c478bbd55219fea7869b1c7871617509c7'))
maintenance_cfg = parse(read_input('MAINTENANCE_41E_CONFIG.json', '7bddb6c423afbe739bc36a7df2516730911a9337'))
maintenance_code = read_input('MAINTENANCE_41E.original.py', '59461030d4160f7ad6a978df5a7b6aaeb33fb2a6')
mat_meta_raw = read(MAT / 'final.git-metadata.json', '8d6af319d99c5f9c47e5a7e761c118c5ba2c767b')
before_meta = read(MAINT / 'SOURCE_GIT_METADATA.before.json', '42e3986f6a5f06d8518067f0d9dd2ec3e6b46c6a')
after_meta = read(MAINT / 'SOURCE_GIT_METADATA.after.json', '42e3986f6a5f06d8518067f0d9dd2ec3e6b46c6a')
before_git_raw = read(MAINT / 'SOURCE_GIT_STATE.before.json', 'aef9e645b81c2a7f349b11d546c5555b1475c906')
assert before_meta == after_meta
mat_files = parse(mat_meta_raw)
v5_metadata = parse(before_meta)
v5_files = {x['path']: x for x in v5_metadata['files'] if x['kind'] == 'file'}
assert len(v5_files) == len(mat_files) == 6
assert set(v5_files) == {x['path'] for x in mat_files}
for row in mat_files:
    s = row['stat']
    assert set(s) == {'st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns'}
    assert stat.S_ISREG(s['st_mode']) and s['st_uid'] == s['st_gid'] == 1000 and s['st_nlink'] == 1
    projected = {'path': row['path'], 'mode': stat.S_IMODE(s['st_mode']), 'device': s['st_dev'],
                 'inode': s['st_ino'], 'nlink': s['st_nlink'], 'mtime_ns': s['st_mtime_ns'],
                 'ctime_ns': s['st_ctime_ns'], 'kind': 'file', 'bytes': row['bytes'], 'sha256': row['sha256']}
    assert s['st_size'] == row['bytes']
    assert projected == v5_files[row['path']], row['path']

endpoint = materialized['current_source_after']
assert endpoint == materialized['current_source_before']
assert endpoint['head'] == packet['current']['commit'] == maintained['source_commit']
assert endpoint['tree'] == packet['current']['tree'] == maintained['source_tree']
assert endpoint['parents'] == packet['current']['parents'] == maintained['parents']
assert {k: endpoint['inventory'][k] for k in ('bytes','sha256','git_blob')} == packet['current']['inventory']
assert endpoint['native_inventory'] == packet['current']['native_inventory']
assert endpoint['inventory'] == maintained['source_initial_inventory']
assert endpoint['inventory']['tracked_entries'] == endpoint['inventory']['filesystem_entries'] == 15243
assert parse(before_git_raw) == materialized['current_git_state_before'] == materialized['current_git_state_after']
assert maintained['actual_materialization_result'] == identity(raws['MATERIALIZATION_3BB_RESULT.json'])
assert maintained['materialization_current_git_metadata_verified'] == materialized['current_git_metadata'] == identity(mat_meta_raw)
assert maintained['materialization_current_index_verified'] == materialized['current_index']
assert maintained['actual_final_source']['inventory'] != {k: endpoint['inventory'][k] for k in ('bytes','sha256','git_blob')}
assert maintained['git_metadata_unchanged'] is True
assert maintained['actual_final_source']['postimages']['all_actual_physical_tree'] != endpoint['tree']

environment = parse(env_raw)
archive = parse(raws['ARCHIVE_V3_READBACK.json'])
historic_archive = environment['tool_and_material_files']['v8-sandbox-archive']
five = ('path','resolved','bytes','sha256','mode')
old_projection = {k: historic_archive[k] for k in five}
new_projection = {'path': archive['path'], 'resolved': archive['path'], 'bytes': archive['identity']['bytes'],
                  'sha256': archive['identity']['sha256'], 'mode': stat.S_IMODE(archive['stat']['st_mode'])}
assert old_projection == new_projection == maintenance_cfg['v8_files']['RUSTY_V8_ARCHIVE']
assert historic_archive['inode'] == 26738826 and archive['stat']['st_ino'] == 26738823
assert historic_archive['inode'] != archive['stat']['st_ino']
assert historic_archive['git_blob'] == archive['identity']['git_blob']

def definitions(raw):
    text = raw.decode()
    lines = text.splitlines(keepends=True)
    return {n.name: ''.join(lines[n.lineno-1:n.end_lineno]).encode()
            for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef)}
v5_defs = definitions(raws['V5_GUARD_6632.original.py'])
maint_defs = definitions(maintenance_code)
canonical_defs = definitions(raws['CANONICAL_TEMPLATE_E8D606.HOLD.py'])
for name in ('metadata_inventory','environment_preflight','project_runtime_file'):
    assert v5_defs[name] == maint_defs[name], name

plan = parse(raws['PLAN_3AEF.json'])
source_pins = plan['unchanged_original_controls']['reviewed_source_pins']['files']
workflow = next(x for x in source_pins if x['path'] == '.github/workflows/hepta-daemon-learning-native.yml')
actual_workflow = identity(raws['WORKFLOW_D256.yml'])
assert workflow['git_blob'] == '08ffc5c603a4c950cca285ed2b1e479508d8b5ed'
assert workflow['git_blob'] != actual_workflow['git_blob']
waiting = parse(read_input('CANONICAL_WAITING_CONFIG.HOLD.json', '69b2eb215ae4e51b2aaded60ac6d008f00006a62'))
for name in ('after_commit','after_tree','after_parents','after_inventory','before_inventory','expected_before_git_state','canonical_packet'):
    assert waiting[name] is None, name
assert waiting['root_execution_approved'] is False

report = {
    'format': 'hepta-final-qualification-captured-schema-peer-data-v1',
    'scope': 'Only pinned captured UTF-8/binary JSON read, hashes, equality, AST parsing. No input code imported or executed; no original path/H/project test access.',
    'input_full_get': get_records,
    'additional_pinned_inputs': input_rows,
    'materialization_start': endpoint,
    'current_raw_git_through_maintenance': parse(before_git_raw),
    'materialization_to_maintenance': {
        'same_full_input_inventory': True, 'same_nine_field_git_state': True,
        'materialization_regular_file_rows': len(mat_files), 'v5_total_rows': len(v5_metadata['files']),
        'v5_directory_rows': len(v5_metadata['files'])-len(mat_files),
        'complete_regular_file_projection_equal': True, 'maintenance_metadata_before_after_raw_equal': True,
        'v5_metadata_identity': identity(before_meta),
        'maintenance_final_inventory': maintained['actual_final_source']['inventory'],
        'maintenance_final_physical_tree': maintained['actual_final_source']['postimages']['all_actual_physical_tree'],
        'materialization_inventory_is_not_final_qualification_inventory': True,
    },
    'archive_bridge': {'historical_environment': identity(env_raw), 'historic_inode': historic_archive['inode'],
        'restored_inode': archive['stat']['st_ino'], 'content_projection': old_projection,
        'five_field_projection_equal': True, 'historical_bytes_modified': False,
        'scope': 'Captured actual restoration evidence plus five-field equality. Does not freshly observe the current archive inode.'},
    'canonical_to_v5_metadata': {
        'canonical_envelope_keys': ['root','files'], 'v5_envelope_keys': ['format','root','files'],
        'v5_format': 'hepta-source-git-metadata-inventory-v1',
        'additional_canonical_row_keys': ['uid','gid'],
        'common_row_keys': ['path','mode','device','inode','nlink','mtime_ns','ctime_ns','kind'],
        'file_additional_keys': ['bytes','sha256'],
        'canonical_order': 'whole relative path sorted by os.fsencode',
        'v5_order': 'depth-first traversal, siblings sorted by os.fsencode',
        'canonical_serialization': 'sort_keys=True,separators=(comma,colon),default ensure_ascii=True,LF',
        'v5_serialization': 'sort_keys=True,separators=(comma,colon),ensure_ascii=False,LF',
        'future_canonical_actual_metadata_observed': False,
        'required': 'Preserve/validate the complete rich raw canonical record, exact supported kind/key schema and unique safe paths; compare every V5 common field and independently uid/gid. Reproduce V5 DFS/envelope/serialization for its original byte equality rather than asserting raw formats equal.',
    },
    'source_workflow_pin': {'historical_plan_pin': workflow, 'current_48_parent_workflow': actual_workflow,
        'literal_old_plan_pin_would_reject_current': True, 'other_original_control_paths': len(source_pins)-1,
        'required': 'Keep original full plan; explicit exact-path current workflow pin binding only, preserving all other original pins and command/JUnit logic.'},
    'unchanged_v5_function_bodies': {name: identity(v5_defs[name]) for name in ('metadata_inventory','environment_preflight','project_runtime_file')},
    'canonical_function_bodies': {name: identity(canonical_defs[name]) for name in ('metadata_inventory','verify_metadata','physical_projection','final_source','final_git')},
    'future_actuals': {'final_format_result': None, 'canonical_result': None, 'canonical_clean_inventory': None,
        'canonical_raw_git_metadata': None, 'final_native_compact': None},
    'execution': {'H': 0, 'original_module_imports': 0, 'admission_main_preflight': 0,
        'source_gate_QA_Rust': 0, 'source_or_ref_writes': 0, 'qualification': False},
}
out = HERE / 'CAPTURED_SCHEMA_DATAFLOW.json'
with out.open('xb') as f:
    f.write((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
print(json.dumps({'output':str(out),**identity(out.read_bytes()),'observed_checks':'captured 3bb→41e, six Git files, archive projection, four schema seams; future actuals null'}))
