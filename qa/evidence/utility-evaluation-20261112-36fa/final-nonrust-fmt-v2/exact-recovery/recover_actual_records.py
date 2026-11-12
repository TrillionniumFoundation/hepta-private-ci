"""Offline exact-byte recovery from already read actual pins and retained inputs.

No source modules are imported or executed. No Git, H, subprocess, formatter,
test or repository write is performed. Only this external recovery directory
receives output. A candidate is retained as exact only after three full pins
match the independently observed ARTIFACTS entry.
"""
from pathlib import Path
import ast
import base64
import gzip
import hashlib
import json
import sys
import zlib

OUT = Path(__file__).resolve().parent
ACTUAL = Path('/tmp/hepta-36fa-final-nonrust-fmt-launch-v2')
PROPOSAL = Path('/tmp/hepta-36fa-reviewed-final-nonrust-v2')
BASE = Path('/tmp/hepta-36fa-postformat-inventory-recovery-v1/final.inventory.recovered.json')
AFTER = Path('/tmp/hepta-36fa-final-source-preparation-v2/FINAL_DIRTY_INVENTORY.candidate.json')
CAPTURE = Path('/tmp/hepta-36fa-postformat-capture-launch-v1/ACTUAL_73_FILES.json')
V5 = Path('/tmp/hepta-36fa-final-nonrust-fmt-v1/MAINTENANCE_V5.original.py')


def ident(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def exact(raw, expected, label):
    observed = ident(raw)
    assert all(observed[k] == expected[k] for k in observed), (label, observed, expected)
    return observed


def jbytes(value):
    # Exact independently read V5 jbytes expression, no imported execution.
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def write(name, raw):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, ('refuse overwrite', name)
    else:
        path.write_bytes(raw)
    assert path.read_bytes() == raw
    return {'local': str(path), **ident(raw)}


def original_raw_pin(row):
    return {'bytes': row['raw_bytes'], 'sha256': row['raw_sha256'], 'git_blob': row['raw_git_blob']}


result_raw = (ACTUAL / 'RESULT.json').read_bytes()
artifacts_raw = (ACTUAL / 'ARTIFACTS.json').read_bytes()
normal_raw = (ACTUAL / 'STATUS_RETRY01.original.json').read_bytes()
exact(result_raw, {'bytes': 8585, 'sha256': 'e2983c5ff45c3474ecc84be80eebd48fbde3c156ae193f56e309c90b0a420ea8', 'git_blob': '7b9c39083f2acd84d41740c18e6288914496d136'}, 'actual result')
exact(artifacts_raw, {'bytes': 65193, 'sha256': '8abc518314358d90d2f444277974a81d75782bdfeb0bc7abe17104c40fe21da5', 'git_blob': '7a09b4bfd7b497c452fb4bb7b647c35ea795b89f'}, 'actual artifacts')
exact(normal_raw, {'bytes': 912, 'sha256': '744efd4d8ea413862929697ff5ad994eeb0cb5a4124ae6f395ed9df7d80c0c36', 'git_blob': 'cc5e721f649b1bb90619877e3a5c22e970cf3f58'}, 'actual normal supervisor')
result = json.loads(result_raw)
normal = json.loads(json.loads(normal_raw)['content'][0]['text'])
assert normal['job_id'] == '1a1d1cb5f1a-2564-1c7c'
assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
assert normal['output_complete'] and normal['output_durable'] and normal['terminal_publication_confirmed']
assert not normal['timed_out'] and not normal['automatic_retry'] and not normal['cancelled']
assert result['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
assert result['source_commit'] == '9c4a11f61d30e9cc352bf44d56c98909d202a55d'
assert result['attempted_commands'] == ['fmt'] and result['not_run_commands'] == []
assert result['formatter_changed_paths'] == [] and result['format_source_stable'] is True
assert result['fix_dispatched'] is False and result['test_commands_dispatched'] == 0
assert len(result['final_audits']) == 3 and all(r['status'] == 'verified' for r in result['final_audits'])
artifacts = {row['name']: row for row in json.loads(artifacts_raw)['files']}

base_raw = BASE.read_bytes()
after_raw = AFTER.read_bytes()
exact(base_raw, result['baseline_inventory'], 'retained original V5 postfmt baseline')
exact(after_raw, result['actual_final_source']['inventory'], 'candidate equals actual complete final inventory')
base = json.loads(base_raw)
after = json.loads(after_raw)
assert base['tracked_entries'] == after['tracked_entries'] == 15188
assert base['filesystem_entries'] == after['filesystem_entries'] == 15188
assert base['source']['head'] == after['source']['head'] == result['source_commit']
assert base['source']['tree'] == after['source']['tree'] == result['source_tree']
bmap = {r['path']: r for r in base['files']}
amap = {r['path']: r for r in after['files']}
assert len(bmap) == len(base['files']) == len(amap) == len(after['files'])
assert set(bmap) == set(amap)

capture_raw = CAPTURE.read_bytes()
exact(capture_raw, {'bytes': 3018618, 'sha256': '44477f7ce5ec90f2d052911745fb3b244111155a9539a22365c545b47e86c9a1', 'git_blob': '1399f73925ee43aff84829c9ae681d0bde017e1e'}, 'actual SH73 raw')
captured = {r['path']: r for r in json.loads(capture_raw)['files']}
packet_raw = (PROPOSAL / 'NONRUST_PACKET.json').read_bytes()
exact(packet_raw, {'bytes': 2442538, 'sha256': 'd1c1151be959db7917832a1573a3ab2b3fd04f0840740806c20fed9743b86441', 'git_blob': '5aa96020a8701f6e12b93c6a214964f61b69224f'}, 'reviewed final nonRust V2')
prepared = json.loads(packet_raw)
changes = []
actual_paths = sorted(path for path in bmap if bmap[path] != amap[path])
assert actual_paths == result['applied_paths'] == [r['path'] for r in prepared['changes']]
assert len(actual_paths) == 11
for item in prepared['changes']:
    path = item['path']
    old = (PROPOSAL / 'before' / path).read_bytes()
    new = base64.b64decode(item['after_base64'], validate=True)
    assert new == (PROPOSAL / 'after' / path).read_bytes()
    assert old == base64.b64decode(captured[path]['content_base64'], validate=True)
    assert captured[path]['original_inventory_row'] == bmap[path]
    for raw, metadata, row in ((old, item['before'], bmap[path]), (new, item['after'], amap[path])):
        exact(raw, metadata, path)
        exact(raw, {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}, path + ' actual inventory')
        assert row['kind'] == 'file' and row['stable'] is True
    changes.append({'path': path, 'before': bmap[path], 'after': amap[path],
                    'before_raw_base64': base64.b64encode(old).decode('ascii'),
                    'after_raw_base64': base64.b64encode(new).decode('ascii')})

v5_raw = V5.read_bytes()
assert ident(v5_raw)['git_blob'] == '6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'
v5_text = v5_raw.decode()
parsed = ast.parse(v5_text)
functions = {n.name: ast.get_source_segment(v5_text, n) for n in parsed.body if isinstance(n, ast.FunctionDef)}
serializer_provenance = {n: ident(functions[n].encode()) for n in ('jbytes', 'gzrecord', 'archive_transition', 'capture_source')}
write('ORIGINAL_SERIALIZERS.txt', ('\n\n'.join(functions[n] for n in serializer_provenance) + '\n').encode())
outputs = []


def retain_original(name, raw):
    expected = artifacts[name]
    exact(raw, original_raw_pin(expected), name + ' full original raw')
    gz = gzip.compress(raw, mtime=0)
    exact(gz, expected, name + ' full original gzip')
    assert gzip.decompress(gz) == raw
    raw_name = name.removesuffix('.gz')
    write('recovered/' + raw_name, raw)
    write('recovered/' + name, gz)
    parts = []
    joined = []
    for i, off in enumerate(range(0, len(gz), 262144)):
        segment = gz[off:off + 262144]
        encoded = base64.b64encode(segment) + b'\n'
        observed_part = expected['parts'][i]
        exact(encoded, observed_part, observed_part['name'])
        assert observed_part['decoded_offset'] == off and observed_part['decoded_bytes'] == len(segment)
        assert observed_part['decoded_sha256'] == hashlib.sha256(segment).hexdigest()
        part = write('recovered/' + observed_part['name'], encoded)
        part.update(original_native_name=observed_part['name'], decoded_offset=off,
                    decoded_bytes=len(segment), decoded_sha256=hashlib.sha256(segment).hexdigest())
        parts.append(part)
        joined.append(base64.b64decode(encoded, validate=False))
    assert len(parts) == len(expected['parts']) and b''.join(joined) == gz
    output = {'original_native_name': name,
              'raw': {**ident(raw), 'local': str(OUT / 'recovered' / raw_name)},
              'gzip': {**ident(gz), 'local': str(OUT / 'recovered' / name)},
              'parts': parts, 'all_raw_gzip_part_pins_equal_observed_artifacts': True,
              'provenance': 'Exact reconstruction against independently observed original identities; no second native full read.'}
    outputs.append(output)
    return output


for stage, previous_raw, selected_changes in (
        ('apply.after', base_raw, changes), ('fmt.after', after_raw, []), ('final', base_raw, changes)):
    value = {'format': 'hepta-maintenance-actual-source-transition-v1', 'stage': stage,
             'source_commit_unchanged': result['source_commit'],
             'base_inventory_sha256': hashlib.sha256(previous_raw).hexdigest(),
             'after_inventory_sha256': hashlib.sha256(after_raw).hexdigest(),
             'changes': selected_changes,
             'all_physical_changes_including_untracked_or_ignored_are_recorded': True,
             'qualification': False}
    retain_original(stage + '.postimages.json.gz', jbytes(value))
retain_original('final.inventory.json.gz', after_raw)

aliases = []
for name, row in artifacts.items():
    if name.endswith('.gz') and row.get('raw_git_blob') == ident(after_raw)['git_blob']:
        assert all(row[k] == artifacts['final.inventory.json.gz'][k] for k in (
            'bytes', 'sha256', 'git_blob', 'raw_bytes', 'raw_sha256', 'raw_git_blob'))
        for old_part, new_part in zip(row['parts'], artifacts['final.inventory.json.gz']['parts'], strict=True):
            assert all(old_part[k] == new_part[k] for k in old_part if k != 'name')
        aliases.append({'original_native_name': name,
                        'same_exact_bytes_as': 'final.inventory.json.gz',
                        'original_part_names': [p['name'] for p in row['parts']],
                        'retained_part_names': [p['name'] for p in artifacts['final.inventory.json.gz']['parts']]})

# The small gzip was also actually read from native. It independently anchors
# the same pure constructor; this does not extend that read to the large files.
anchor_path = ACTUAL / 'fmt.after.postimages.json.gz.READ.original.json'
anchor_raw = anchor_path.read_bytes()
sdk = json.loads(anchor_raw)
assert sdk['isError'] is False
chunk = json.loads(sdk['content'][0]['text'])
native_small = base64.b64decode(chunk['data_base64'], validate=True)
assert chunk['offset'] == 0 and chunk['next_offset'] == chunk['size'] == 276 and chunk['eof'] is True
assert hashlib.sha256(native_small).hexdigest() == chunk['chunk_sha256']
assert native_small == (OUT / 'recovered/fmt.after.postimages.json.gz').read_bytes()

small = []
for stage, source_key in (('apply.after', 'application'), ('fmt.after', 'stages'), ('final', 'actual_final_source')):
    value = result['stages'][0]['retention']['postimages'] if source_key == 'stages' else result[source_key]['postimages']
    name = stage + '.postimages-summary.json'
    raw = jbytes(value)
    exact(raw, artifacts[name], name)
    small.append({'original_native_name': name, **write('recovered/' + name, raw)})

preserved_failures = []
for name in ('RESULT_READ_01.original.json', 'STATUS_01.original.json', 'STDOUT_READ_01.original.json'):
    raw = (ACTUAL / name).read_bytes()
    assert json.loads(raw).get('isError') is True
    preserved_failures.append({'original_local': str(ACTUAL / name), **ident(raw),
                               'original_status': 'transport observation failed; not the normal producer terminal'})

review = {
    'format': 'hepta-final-format-exact-recovery-review-v1',
    'status': 'EXACT_RECOVERY_ALL_OBSERVED_RAW_GZIP_PART_IDENTITIES_MATCH',
    'scope': 'Offline record reconstruction only; original actual source apply/fmt observation belongs to the pinned native job.',
    'actual_job': normal['job_id'],
    'inputs': {
        'actual_result': {'local': str(ACTUAL / 'RESULT.json'), **ident(result_raw)},
        'actual_normal_supervisor': {'local': str(ACTUAL / 'STATUS_RETRY01.original.json'), **ident(normal_raw)},
        'actual_artifacts': {'local': str(ACTUAL / 'ARTIFACTS.json'), **ident(artifacts_raw)},
        'actual_baseline_inventory_exact_recovered': {'local': str(BASE), **ident(base_raw)},
        'final_inventory_candidate_now_exact_original': {'local': str(AFTER), **ident(after_raw)},
        'actual_SH73': {'local': str(CAPTURE), **ident(capture_raw)},
        'reviewed_V2_source_packet': {'local': str(PROPOSAL / 'NONRUST_PACKET.json'), **ident(packet_raw)},
        'original_V5_serializer_module': {'local': str(V5), **ident(v5_raw)},
    },
    'serializer_functions': serializer_provenance,
    'applied_paths': actual_paths,
    'actual_changed_paths_exactly_the_reviewed_11': True,
    'all_11_before_bytes_also_equal_actual_SH73': True,
    'untouched_other_15177_inventory_rows_equal': True,
    'actual_formatter_postimage_count': 0,
    'whole_inventory_preserves_54_dirty_paths_head9c4_indexee42': True,
    'original_complete_physical_leaf_count': 15188,
    'original_physical_tree': result['actual_final_source']['postimages']['all_actual_physical_tree'],
    'outputs': outputs, 'inventory_exact_aliases': aliases, 'small_original_records_recovered': small,
    'native_small_gzip_anchor': {'local': str(anchor_path), **ident(anchor_raw), 'actual_version': chunk['version'],
                                'actual_gzip': ident(native_small), 'whole_bytes_equal': True},
    'preserved_original_transport_failures': preserved_failures,
    'HEAD_working_patch_bytes_not_recovered_by_this_report': True,
    'native_source_read_again': False, 'native_process_repeated': False,
    'source_control_module_or_main_executed': False,
    'H_requests': 0, 'Cargo_or_formatter_dispatched': 0, 'source_or_ref_writes': 0,
    'qualification_tests_run_or_inherited': False,
    'python': sys.version, 'zlib': zlib.ZLIB_VERSION,
}
write('RECOVERY_REVIEW.json', json.dumps(review, indent=2, sort_keys=True).encode() + b'\n')
print(json.dumps({'status': review['status'], 'records': [
    {'name': r['original_native_name'], 'raw': r['raw'], 'gzip': r['gzip'], 'parts': len(r['parts'])}
    for r in outputs], 'inventory_aliases': len(aliases), 'report': str(OUT / 'RECOVERY_REVIEW.json')}, indent=2))
