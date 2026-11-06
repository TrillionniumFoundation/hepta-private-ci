from pathlib import Path, PurePosixPath
import ast
import base64
import gzip
import hashlib
import json
import os
import tomllib

P = Path('source53-final-scope-preparation')
O = Path('source53-final-scope-root-review')
S = PurePosixPath('/home/alex/work/hepta-cell-unified-20261106-a/source')
COMMIT = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
TREE = '440d4a8e09af4009e4d9ea067388826308da8803'

def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}

def check(b, row):
    actual = pin(b)
    assert all(actual[k] == row[k] for k in actual), row
    return actual

def get(name):
    return json.loads((P / name).read_bytes())

handoff = get('HANDOFF-MANIFEST.json')
assert len(handoff['files']) == 85
for row in handoff['files']:
    check((P / row['path']).read_bytes(), row)
assert {p.relative_to(P).as_posix() for p in P.rglob('*') if p.is_file()} == {r['path'] for r in handoff['files']} | {'HANDOFF-MANIFEST.json'}
mapping = get('INPUT-SOURCE-MAPPING.json')['files']
exact_copies = 0
for row in mapping:
    if row['transform'] == 'exact_copy':
        assert Path(row['source']).read_bytes() == (P / row['destination']).read_bytes(), row['source']
        exact_copies += 1

transfer = get('TRANSFER-READBACK.json')
chunks = []
offset = 0
for row in transfer['scope_chunks']:
    raw = get(row['transport_original'])
    data = base64.b64decode(raw['data_base64'], validate=True)
    assert raw['offset'] == offset and raw['next_offset'] == offset + len(data)
    assert raw['version'] == transfer['scope_file_info']['version']
    assert hashlib.sha256(data).hexdigest() == raw['chunk_sha256']
    check(data, row)
    chunks.append(data)
    offset += len(data)
scope_raw = b''.join(chunks)
assert scope_raw == (P / 'input/native-workspace-r31-scope.json').read_bytes()
check(scope_raw, transfer['scope'])
compressed = (P / 'input/native-workspace-r31-metadata.json.gz').read_bytes()
assert compressed[4:8] == b'\0' * 4
metadata_raw = gzip.decompress(compressed)
check(metadata_raw, transfer['metadata_uncompressed'])
assert len(metadata_raw) == transfer['metadata_fresh_file_info']['size']
assert pin(metadata_raw)['sha256'] == transfer['metadata_fresh_file_info']['sha256']
metadata = json.loads(metadata_raw)
scope = json.loads(scope_raw)
source_raw = (P / 'input/native-candidate-r30-source.json').read_bytes()
source = json.loads(source_raw)
assert source['source_commit'] == scope['source_commit'] == COMMIT
assert source['source_tree'] == scope['source_tree'] == TREE
raw_name = 'input/r31-start/evidence/native-workspace-r31-metadata-raw-process-result.json'
raw = get(raw_name)
receipt = get('input/r31-start/evidence/native-workspace-r31-metadata-receipt.json')
check((P / raw_name).read_bytes(), receipt['raw_process_result'])
assert raw['exit_code'] == receipt['exit_code'] == 0
assert raw['command'] == receipt['command'] == ['cargo','metadata','--locked','--no-deps','--format-version','1']
assert raw['start_unix'] == receipt['start_unix'] == 1793995431.0169575
assert raw['end_unix'] == receipt['end_unix'] and raw['end_unix'] > raw['start_unix']
check(metadata_raw, receipt['stdout'])
assert receipt['source_guards_pass'] is True
assert scope['metadata_generated_on_current_source'] is True and scope['old_metadata_reused_as_current'] is False
ids = metadata['workspace_members']
assert len(ids) == len(set(ids)) == 193 and set(ids) == set(metadata['workspace_default_members'])
packages = {p['id']: p for p in metadata['packages']}
for key in ['workspace_members', 'workspace_default_members']:
    assert scope[key] == [{k: packages[i][k] for k in ['id', 'name', 'manifest_path']} for i in metadata[key]]
assert scope['command'] == ['just', 'test', '--locked', '--retries', '0']

expected = get('EXPECTED-SELECTION.json')
proposed = get('PACKAGE-ARGS.json')
commands = get('RUST-FILE-COMMANDS.json')
primary = get('PRIMARY-SOURCE-PINS.json')
assert len(primary) == 34
for row in primary:
    check((P / 'input/primary' / row['path']).read_bytes(), row)
assert (P / 'PRIMARY-SOURCE-PINS.json').read_bytes() == Path('source51-final-scope-readonly/PRIMARY-SOURCE-PINS.json').read_bytes()
paths = sorted(row['path'] for row in source['changed_files'])
rust = sorted(p for p in paths if p.endswith('.rs'))
python = ['scripts/run-nextest.py', 'scripts/test_run_nextest_helpers.py']
assert len(paths) == 197 and len(rust) == 183
assert expected['changed_paths'] == paths and expected['rust_paths'] == rust
assert expected['python_paths'] == ['./' + p for p in python]
roots = {PurePosixPath(packages[i]['manifest_path']).parent.relative_to(S).as_posix(): packages[i] for i in ids}
owners = {}
rebuilt = []
for path in rust:
    ancestor = PurePosixPath(path).parent
    while ancestor.as_posix() not in roots:
        assert ancestor != ancestor.parent
        ancestor = ancestor.parent
    package = roots[ancestor.as_posix()]
    manifest = PurePosixPath(package['manifest_path']).relative_to(S).as_posix()
    cargo = tomllib.loads((P / 'input/primary/original' / manifest).read_text())
    edition = cargo['package']['edition']
    if isinstance(edition, dict):
        assert edition == {'workspace': True}
        edition = tomllib.loads((P / 'input/primary/original/codex-rs/Cargo.toml').read_text())['workspace']['package']['edition']
    assert edition == package['edition'] == '2024'
    row = owners.setdefault(package['name'], {'package': package['name'], 'package_id': package['id'], 'package_directory': ancestor.as_posix(), 'manifest_path': manifest, 'edition': edition, 'default_workspace_member': True, 'rust_paths': []})
    row['rust_paths'].append(path)
    rebuilt.append({'path': path, 'owning_package': package['name'], 'manifest_path': manifest, 'cwd': str(S / ancestor), 'command': ['rustfmt','--edition',edition,'--config','imports_granularity=Item,skip_children=true','--',str(S / path)]})
for row in owners.values():
    row['rust_path_count'] = len(row['rust_paths'])
names = sorted(owners)
assert len(names) == 26
assert expected['owners'] == [owners[n] for n in names]
assert proposed['owners'] == names and rebuilt == commands
args = [x for name in names for x in ('-p', name)]
assert proposed['package_args'] == args
assert proposed['command'] == ['just','fix','--locked',*args]
assert proposed['recipe_expansion'] == ['cargo','clippy','--fix','--tests','--allow-dirty','--locked',*args]
assert expected['default_formatter_command'] == ['just','fmt'] and expected['all_flag_used'] is False
assert expected['python_formatter_command'] == ['uv','run','--frozen','--project','scripts','ruff','format',*['./'+p for p in python]]
assert expected['formatting_configuration_changed_paths'] == []
assert expected['unselected_by_default_formatter'] == sorted(set(paths)-set(rust)-set(python))
assert len(expected['ci_selectors']) == 27 and set(expected['ci_selectors']) == set(names) | {'codex-hepta-control-plane'}
assert expected['final_scope_execution_authorized'] is False and expected['workspace_result'] is None
assert proposed['fix_executed'] is False and proposed['same_source_workspace_pass_bound'] is False

report = {'schema': 'hepta.root-source53-fresh-scope-review.v1', 'result': 'STATIC_CLEAR_NOT_FINALIZER_AUTHORIZATION',
          'handoff': pin((P/'HANDOFF-MANIFEST.json').read_bytes()), 'all_85_declared_files_rehashed': True,
          'exact_source_copies_read': exact_copies, 'fresh_R31_metadata_original_rc': 0, 'metadata_local_cache_reuse_is_bytes_only': True,
          'scope_chunks_reassembled': 2, 'metadata_default_members': 193, 'changed_paths': 197, 'rust': 183,
          'python': 2, 'owners': names, 'ci_selector_count': 27, 'primary_files_rehashed': 34,
          'owner_and_edition_independently_rebuilt_from_metadata_and_Cargo': True,
          'all_183_formatter_commands_rebuilt': True, 'original_just_fix_and_default_fmt_only': True,
          'scope_inputs': {n: pin((P/n).read_bytes()) for n in handoff['scope_input_names']},
          'workspace_result': None, 'fix_fmt_executed': False, 'source_commit': COMMIT, 'source_tree': TREE}
with (O/'ROOT-READBACK.json').open('xb') as f:
    f.write((json.dumps(report, indent=2)+'\n').encode()); f.flush(); os.fsync(f.fileno())
print(json.dumps({'result': report['result'], 'report': pin((O/'ROOT-READBACK.json').read_bytes())}))
