from pathlib import Path
import base64
import datetime
import gzip
import hashlib
import json

SOURCE = Path('/tmp/hepta-36fa-postformat-capture-launch-v1')
DEST = Path('/tmp/hepta-36fa-after2268-20261112')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read_sdk(name):
    raw = (SOURCE / name).read_bytes()
    outer = json.loads(raw)
    assert not outer.get('isError'), name
    value = json.loads(outer['content'][0]['text'])
    return value, pin(raw)


result = json.loads((SOURCE / 'RESULT.json').read_bytes())
normal, normal_pin = read_sdk('STATUS_01.original.json')
assert normal['job_id'] == '1a1d1880477-2564-1c56'
assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
assert normal['output_complete'] and normal['output_durable'] and not normal['timed_out']
assert not any(normal['log_truncated'].values())
assert normal['log_bytes']['stdout']['stored'] == len((SOURCE / 'COMPLETE_STDOUT.log').read_bytes()) == 455
assert result['status'] == 'CAPTURED_ACTUAL_POSTFMT_REVIEW_REQUIRED'
assert result['captured_paths'] == 73 and result['tests_dispatched'] == 0
assert not result['source_changed'] and not result['source_write_authorized']
assert not result['extractor_executed'] and not result['qualification']
assert all(a['status'] == 'verified' for a in result['final_audits'])

chunks, observations, errors = {}, [], []
for path in sorted(SOURCE.glob('PACKET_READ_*.original.json')):
    outer = json.loads(path.read_bytes())
    if outer.get('isError'):
        errors.append({'name': path.name, **pin(path.read_bytes())})
        continue
    d, sdk_pin = read_sdk(path.name)
    raw = base64.b64decode(d['data_base64'], validate=True)
    assert hashlib.sha256(raw).hexdigest() == d['chunk_sha256']
    assert d['offset'] not in chunks
    assert len(raw) == d['next_offset'] - d['offset']
    assert d['size'] == 626888
    assert d['path'].endswith('/postformat-handoff-v5-v1/ACTUAL_73_FILES.json.gz')
    chunks[d['offset']] = raw
    observations.append({'sdk': path.name, 'sdk_pin': sdk_pin,
                         **{k: d[k] for k in ('offset', 'next_offset', 'size', 'version', 'eof')}})
assert len(chunks) == 10 and len(errors) == 3
assert len({d['version'] for d in observations}) == 1
cursor, pieces = 0, []
for d in sorted(observations, key=lambda x: x['offset']):
    assert d['offset'] == cursor
    assert d['eof'] == (d['next_offset'] == 626888)
    pieces.append(chunks[cursor])
    cursor = d['next_offset']
assert cursor == 626888
compressed = b''.join(pieces)
assert compressed == (SOURCE / 'ACTUAL_73_FILES.json.gz').read_bytes()
meta = result['capture_packet']
assert pin(compressed) == {k: meta[k] for k in ('bytes', 'sha256', 'git_blob')}
raw = gzip.decompress(compressed)
assert raw == (SOURCE / 'ACTUAL_73_FILES.json').read_bytes()
assert pin(raw) == meta['raw']
for part in meta['parts']:
    encoded = (SOURCE / part['name']).read_bytes()
    assert pin(encoded) == {k: part[k] for k in ('bytes', 'sha256', 'git_blob')}
    decoded = base64.b64decode(encoded.strip(), validate=True)
    assert len(decoded) == part['decoded_bytes']
    assert hashlib.sha256(decoded).hexdigest() == part['decoded_sha256']
    assert decoded == compressed[part['decoded_offset']:part['decoded_offset'] + len(decoded)]

packet = json.loads(raw)
inventory_raw = Path('/tmp/hepta-36fa-postformat-inventory-recovery-v1/final.inventory.recovered.json').read_bytes()
inventory = json.loads(inventory_raw)
assert pin(inventory_raw) == result['complete_inventory'] == packet['complete_inventory']
assert packet['source_identity'] == result['source_identity'] == inventory['source']
assert packet['actual_physical_tree'] == result['actual_physical_tree'] == '65b898bad23cd58c7f6fd53fafe618f9cf9562dc'
assert inventory['source']['head'] == '9c4a11f61d30e9cc352bf44d56c98909d202a55d'
assert inventory['source']['tree'] == 'ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'
assert inventory['source']['status']
rows = {x['path']: x for x in inventory['files']}
expected = set(base64.b64decode(json.loads((SOURCE / 'BOOTSTRAP_PAYLOAD.json').read_bytes())['files']['CAPTURE_PATHS.txt']).decode().splitlines())
assert len(packet['files']) == len(expected) == 73
assert {x['path'] for x in packet['files']} == expected
for item in packet['files']:
    content = base64.b64decode(item['content_base64'], validate=True)
    actual = pin(content)
    row = rows[item['path']]
    assert item['original_inventory_row'] == row
    assert actual['bytes'] == row['bytes'] == item['bytes']
    assert actual['sha256'] == row['sha256'] == item['sha256']
    assert actual['git_blob'] == row['working_blob'] == item['git_blob_sha']
    assert item['permissions'] == row['permissions'] and item['mode'] == row['index_mode']
    assert item['stable'] is True and row['stable'] is True
    assert item['kind'] == row['kind'] == 'file'

small_reads = []
for stem, filename in [('SOURCE_COORDINATION_SH_json', 'SOURCE_COORDINATION_SH.json'),
                       ('GIT_BEFORE_json_gz', 'GIT_BEFORE.json.gz'),
                       ('GIT_AFTER_json_gz', 'GIT_AFTER.json.gz')]:
    failure = SOURCE / (stem + '_READ.original.json')
    assert json.loads(failure.read_bytes())['isError'] is True
    errors.append({'name': failure.name, **pin(failure.read_bytes())})
    d, sdk_pin = read_sdk(stem + '_READ_RETRY01.original.json')
    actual = base64.b64decode(d['data_base64'], validate=True)
    assert d['offset'] == 0 and d['eof'] is True and d['next_offset'] == d['size'] == len(actual)
    assert hashlib.sha256(actual).hexdigest() == d['chunk_sha256']
    assert actual == (SOURCE / filename).read_bytes()
    indexed = next(x for x in result['artifacts'] if x['name'] == filename)
    assert pin(actual) == {k: indexed[k] for k in ('bytes', 'sha256', 'git_blob')}
    small_reads.append({'name': filename, 'sdk_pin': sdk_pin, 'version': d['version'], **pin(actual)})
before_git = gzip.decompress((SOURCE / 'GIT_BEFORE.json.gz').read_bytes())
after_git = gzip.decompress((SOURCE / 'GIT_AFTER.json.gz').read_bytes())
assert before_git == after_git == (SOURCE / 'GIT_BEFORE.json').read_bytes() == (SOURCE / 'GIT_AFTER.json').read_bytes()
lease = json.loads((SOURCE / 'SOURCE_COORDINATION_SH.json').read_bytes())
approved = json.loads(Path('/tmp/hepta-36fa-postformat-collector-v5-root-approval/APPROVED_CAPTURE_CONFIG.json').read_bytes())
assert lease['path'] == approved['source_lock_path'] and lease['lock_acquired'] == 'LOCK_SH|LOCK_NB'
assert {k: lease[k] for k in approved['source_lock_identity']} == approved['source_lock_identity']

review = {
    'format': 'hepta-root-complete-actual-sh73-readback-v1',
    'reviewed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'status': 'COMPLETE_ORIGINAL_PACKET_AND_SOURCE_BINDINGS_VERIFIED',
    'native_job': normal['job_id'], 'normal': normal_pin,
    'result': pin((SOURCE / 'RESULT.json').read_bytes()),
    'packet_raw': pin(raw), 'packet_gzip': pin(compressed),
    'actual_files': 73, 'complete_inventory': pin(inventory_raw),
    'actual_physical_tree': packet['actual_physical_tree'],
    'source_identity': packet['source_identity'], 'actual_shared_lease': lease,
    'git_before_after_equal': True, 'git_metadata_raw': pin(before_git),
    'all_raw_file_pins_and_complete_original_inventory_rows_equal': True,
    'original_fixed_version_packet_reads': sorted(observations, key=lambda x: x['offset']),
    'original_fixed_version_small_reads': small_reads,
    'preserved_original_transport_errors': errors,
    'qualification': False, 'new_native_execution': False,
    'real_qualified_task_chain_outcomes': 0,
    'next': 'Root may bind the unchanged f868 read-only extractor to these actual files and originals; final source/gates still require actual integration and results.',
    'limits': ['This closes retrieval missing at the 21:01:19 evidence checkpoint without rewriting that snapshot.',
               'Full inventory bytes are exact original V5 recovery; the new SH capture independently pins equal full before/after inventories.',
               'Task cooperative shared locking does not claim machine-wide exclusion or independent outcome evaluation.']
}
(DEST / 'ROOT_COMPLETE_CAPTURE_REVIEW.json').write_text(json.dumps(review, sort_keys=True, indent=2) + '\n')
print(json.dumps({'review': pin((DEST / 'ROOT_COMPLETE_CAPTURE_REVIEW.json').read_bytes()), 'files': 73, 'chunks': 10, 'preserved_errors': len(errors)}))
