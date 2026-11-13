#!/usr/bin/env python3
"""Pure local preparation of the closed historical input transport; no H calls."""
from pathlib import Path
import ast
import base64
import gzip
import hashlib
import json

HERE = Path(__file__).resolve().parent
AUDIT = Path('/tmp/hepta-36fa-source65a-path-provenance-independent-review-v1')
OLD = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1')
EVIDENCE = '/home/qian-qi/hepta-utility-36fa-evidence'
CONTROL = EVIDENCE + '/final-qualification-b608-transported-originals-v1'
SOURCE_CONTROL = EVIDENCE + '/final-qualification-b608-v2'
PART_PREFIX = EVIDENCE + '/final-qualification-b608-transported-originals-v1.payload.json.gz'
ROLES = '''canonical.supervisor runtime.supervisor canonical.config canonical.packet
final_format.supervisor canonical.driver canonical.artifacts canonical.commands
canonical.metadata_delta canonical.metadata_before_gzip canonical.metadata_final_gzip
canonical.git_state_final canonical.index_delta_gzip canonical.index_audit_gzip
canonical.index_raw_gzip canonical.inputs canonical.progress canonical.result
final_format.config maintenance.supervisor final_format.driver final_format.artifacts
final_format.inputs final_format.result final_format.metadata_after_gzip
final_format.metadata_before_gzip final_format.git_state_final
final_format.inventory_final_gzip final_format.empty_transition_gzip
materialization.config materialization.packet materialization.driver
materialization.artifacts materialization.commands materialization.inputs
materialization.mutations materialization.result materialization.metadata_final_gzip
maintenance.config materialization.supervisor archive.supervisor maintenance.driver
maintenance.artifacts maintenance.inputs maintenance.result maintenance.metadata_after_gzip
maintenance.metadata_before_gzip maintenance.git_state_before maintenance.git_state_final
runtime.environment_ready runtime.result archive.readback archive.artifacts archive.result'''.split()

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def jbytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()

def retain(name, raw):
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, ('create-only local mismatch', str(path))
    else:
        with path.open('xb') as f:
            f.write(raw)
    return {'path': str(path), **identity(raw)}

def original_sdk_body(path, expected_sdk):
    raw = Path(path).read_bytes()
    assert identity(raw) == expected_sdk, ('original SDK pin', path)
    outer = json.loads(raw)
    assert outer['isError'] is False and len(outer['content']) == 1
    assert outer['content'][0]['type'] == 'text'
    return json.loads(outer['content'][0]['text'])

def recover_captured_read(row):
    observation = row['captured_complete_reads'][0]
    chunks, offset = [], 0
    for item in observation['chunks']:
        value = original_sdk_body(item['sdk'], item['sdk_pin'])
        data = base64.b64decode(value['data_base64'], validate=True)
        assert value['path'] == row['path']
        assert value['version'] == observation['version']
        assert value['size'] == row['pin']['bytes']
        assert value['offset'] == offset
        assert value['next_offset'] == offset + len(data)
        assert hashlib.sha256(data).hexdigest() == value['chunk_sha256']
        offset += len(data)
        assert value['eof'] == (offset == row['pin']['bytes'])
        chunks.append(data)
    assert offset == row['pin']['bytes']
    data = b''.join(chunks)
    assert identity(data) == row['pin'] == observation['complete_pin']
    return data, {'kind': 'decoded_existing_complete_binary_read',
                  'version': observation['version'],
                  'original_sdks': [{'path': item['sdk'], **item['sdk_pin']}
                                    for item in observation['chunks']]}

def main():
    matrix_raw = (AUDIT / 'CAPTURED_PATH_MATRIX.json').read_bytes()
    matrix = json.loads(matrix_raw)
    extra_raw = (AUDIT / 'ORIGINAL_V5_HISTORY_ADDENDUM.json').read_bytes()
    extra = json.loads(extra_raw)
    assert len(matrix['rows']) == len(ROLES) == 54
    source = (OLD / 'qualification-admission.HOLD.py').read_text()
    actual = next(ast.literal_eval(n.value) for n in ast.parse(source).body
                  if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name)
                  and t.id == 'ACTUAL_PROOFS' for t in n.targets))
    jobs = {name: value['job_id'] for name, value in actual.items()}
    jobs['canonical'] = '1a1d4cbd33e-392-5a9'
    explicit = {
        'runtime.supervisor': OLD / 'inputs/HISTORICAL_RUNTIME_NORMAL.json',
        'runtime.environment_ready': OLD / 'inputs/HISTORICAL_ENVIRONMENT_READY.json',
        'runtime.result': OLD / 'inputs/HISTORICAL_RUNTIME_RESULT.json',
        'canonical.packet': Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-inputs-v1/CANONICAL_PACKET.json'),
        'canonical.index_audit_gzip': Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1/recovered-index-audit/INDEX.final.audit.json.gz'),
        'final_format.inventory_final_gzip': Path('/tmp/hepta-36fa-a489-final-nonrust-exact-recovery-v1/final.inventory.json.gz'),
        'materialization.config': OLD / 'inputs/MATERIALIZATION_3BB_CONFIG.json',
        'materialization.packet': OLD / 'inputs/MATERIALIZATION_3BB_PACKET.json',
        'materialization.driver': OLD / 'inputs/MATERIALIZER_3BB.original.py',
    }
    records, recovery, files = [], [], {}
    for role, row in zip(ROLES, matrix['rows']):
        if row['captured_complete_reads']:
            data, local = recover_captured_read(row)
        else:
            p = explicit[role]
            data = p.read_bytes()
            assert identity(data) == row['pin'], ('exact retained body', role)
            local = {'kind': 'existing_exact_original_or_lossless_recovery', 'path': str(p),
                     'historical_observation_scope': row['historical_path_evidence']}
        assert row['path'].startswith(EVIDENCE + '/')
        assert '/.git/' not in row['path'] and not row['path'].endswith('.lock')
        name = role + '.original'
        records.append({'role': role, 'producer_job_id': jobs[role.split('.')[0]],
                        'original_path': row['path'], 'pin': row['pin'],
                        'transport_path': CONTROL + '/originals/' + name,
                        'original_path_evidence': row['historical_path_evidence'],
                        'original_consumers': row['consumers']})
        files[role] = data
        retained = retain('originals/' + name, data)
        recovery.append({'role': role, 'retained': retained, 'reconstruction': local})
    role = 'historical_environment.started'
    path = Path('/tmp/hepta-36fa-coordinator-a489-maintenance-staging-v1/native-readback/MAINTENANCE_STARTED.original.json')
    data = path.read_bytes()
    assert identity(data) == extra['pin']
    files[role] = data
    records.append({'role': role, 'producer_job_id': None,
                    'producer_job_scope': 'The supplied historical record does not establish a producer job ID; no job is invented.',
                    'original_path': extra['path'], 'pin': extra['pin'],
                    'transport_path': CONTROL + '/originals/' + role + '.original',
                    'original_path_evidence': 'content_pin_known_no_original_path_read_in_finite_input_set',
                    'original_consumers': ['V5.environment_preflight.ENVIRONMENT_FILE']})
    recovery.append({'role': role, 'retained': retain('originals/' + role + '.original', data),
                     'reconstruction': {'kind': 'existing_exact_original_staged_copy', 'path': str(path),
                     'scope': 'This later copied body does not prove present availability at the historical origin.'}})
    assert len(records) == len({r['role'] for r in records}) == len({r['original_path'] for r in records}) == 55
    assert sum(len(b) for b in files.values()) == 7976106
    manifest = {'format': 'hepta-closed-transported-originals-manifest-v1',
                'control': CONTROL, 'source_control': SOURCE_CONTROL,
                'qualification': False, 'root_execution_approved': False,
                'historical_original_count': 55,
                'raw_original_bytes': sum(map(len, files.values())),
                'rows': records,
                'origin_path_availability': 'Unknown; transport never creates an original-location availability assertion.',
                'scope': 'Only fixed immutable historical proof files; all live source, Git, ownership metadata, tool/material, environment and coordination checks keep their original subjects.'}
    manifest_pin = retain('TRANSPORT_MANIFEST.HOLD.json', jbytes(manifest))
    packet = {'format': 'hepta-closed-transported-originals-packet-v1',
              'manifest': identity(jbytes(manifest)),
              'files': [{'role': row['role'], 'data_base64': base64.b64encode(files[row['role']]).decode('ascii')}
                        for row in records]}
    raw = (json.dumps(packet, sort_keys=True, separators=(',', ':')) + '\n').encode()
    compressed = gzip.compress(raw, mtime=0)
    assert gzip.decompress(compressed) == raw
    packet_pin = retain('TRANSPORT_PACKET.json', raw)
    gzip_pin = retain('TRANSPORT_PACKET.json.gz', compressed)
    writes = []
    for i, offset in enumerate(range(0, len(compressed), 307200), 1):
        part = compressed[offset:offset + 307200]
        base64_raw = base64.b64encode(part) + b'\n'
        part_pin = retain('parts/PART_%03d.b64' % i, base64_raw)
        request = {'host': 'desktop', 'path': PART_PREFIX + '.part-%03d' % i,
                   'data_base64': base64.b64encode(part).decode(), 'expected_version': 'absent'}
        request_raw = jbytes(request)
        assert len(request_raw) <= 512000 < 1048576
        request_pin = retain('write-requests/STAGE_%03d.REQUEST.HOLD.json' % i, request_raw)
        writes.append({'sequence': i, 'native_path': request['path'], 'request': request_pin,
                       'encoded_part': part_pin, 'decoded_offset': offset, 'decoded_pin': identity(part)})
    for entry in packet['files']:
        data = base64.b64decode(entry['data_base64'], validate=True)
        assert data == files[entry['role']]
    review = {'format': 'hepta-transported-originals-pure-byte-preparation-v1',
              'H_calls': 0, 'source_writes': 0, 'qualification': False,
              'original_count': len(records), 'distinct_raw_bodies': len({identity(x)['git_blob'] for x in files.values()}),
              'raw_original_bytes': sum(map(len, files.values())),
              'transport_packet': identity(raw), 'transport_gzip': identity(compressed),
              'transport_base64_bytes': len(base64.b64encode(compressed)),
              'write_count': len(writes), 'maximum_part_raw_bytes': max(x['decoded_pin']['bytes'] for x in writes),
              'maximum_typed_write_bytes': max(x['request']['bytes'] for x in writes),
              'typed_limit': 1048576, 'evidence_leaf_limit': 512000,
              'one_request_is_insufficient': len(base64.b64encode(compressed)) > 1048576,
              'all_55_complete_originals_exact': True, 'all_roundtrips_exact': True,
              'source_matrix': identity(matrix_raw), 'additional_V5_record': identity(extra_raw),
              'stage_script_and_new_main': 'not executed; successor code and exact future staging approval remain separate',
              'old_65a': {'job_id': '1a1d4f0c3d4-392-65a', 'status': 'failed', 'driver_main_entered': False,
                          'original_three_source_gates_started': 0, 'native_phases_started': 0}}
    retain('ORIGINAL_RECOVERY_LEDGER.json', jbytes(recovery))
    retain('STAGING_WRITE_MANIFEST.HOLD.json', jbytes({'format': 'hepta-closed-history-bounded-writes-v1',
           'root_execution_approved': False, 'qualification': False, 'automatic_retry': False,
           'history_manifest': identity(jbytes(manifest)), 'packet': identity(raw),
           'gzip': identity(compressed), 'writes': writes,
           'unknown_rule': 'Reconcile only the same frozen path/version; no repeat write, overwrite, rename or next main on Unknown.'}))
    retain('PURE_BYTE_REVIEW.json', jbytes(review))
    print(json.dumps(review, sort_keys=True))

if __name__ == '__main__':
    main()
