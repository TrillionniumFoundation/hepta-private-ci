import base64
import hashlib
import json
import pathlib

ROOT = pathlib.Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1')
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1'
JOB = '1a1d4cbd33e-392-5a9'

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def create(name, raw):
    target = ROOT / name
    if target.exists():
        assert target.read_bytes() == raw, name
    else:
        with target.open('xb') as stream:
            stream.write(raw)
    return {'name': name, 'path': str(target), **identity(raw)}

def payload(name):
    outer = json.loads((ROOT / name).read_bytes())
    assert not outer.get('isError'), name
    blocks = [row['text'] for row in outer['content'] if row['type'] == 'text']
    assert len(blocks) == 1, name
    return json.loads(blocks[0])

records = []
for name, count, path in [
    ('RESULT.json', 4, CONTROL + '/run/RESULT.json'),
    ('ARTIFACTS.json', 2, CONTROL + '/run/ARTIFACTS.json'),
    ('STAGING_READBACK.json', 1, CONTROL + '/STAGING_READBACK.json'),
]:
    cursor = 0
    chunks = []
    observations = []
    version = size = None
    for number in range(1, count + 1):
        sdk_name = f'{name}.READ_{number:02}.original.json'
        row = payload(sdk_name)
        raw = base64.b64decode(row['data_base64'], validate=True)
        if version is None:
            version, size = row['version'], row['size']
        assert row['path'] == path and row['version'] == version and row['size'] == size
        assert row['offset'] == cursor and row['next_offset'] == cursor + len(raw)
        assert hashlib.sha256(raw).hexdigest() == row['chunk_sha256']
        assert row['eof'] == (row['next_offset'] == size)
        observations.append({'sdk': sdk_name, 'offset': cursor, 'next_offset': row['next_offset'], 'chunk_sha256': row['chunk_sha256']})
        chunks.append(raw)
        cursor = row['next_offset']
    assert cursor == size and row['eof']
    records.append({**create(name, b''.join(chunks)), 'native_path': path, 'version': version, 'chunks': observations})

normal = payload('STATUS_02.original.json')
streams = payload('STREAM_READ_01.original.json')
assert normal['job_id'] == streams['job_id'] == JOB
assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
assert normal['output_complete'] and normal['output_durable'] and normal['terminal_publication_confirmed']
assert not normal['timed_out'] and not normal['cancelled'] and not normal['automatic_retry']
for stream in ('stdout', 'stderr'):
    row = streams[stream]
    raw = bytes.fromhex(row['bytes_hex'])
    assert raw == row['text'].encode() and row['offset'] == 0
    assert row['next_offset'] == row['size'] == len(raw) and row['eof']
    assert normal['log_bytes'][stream] == {'seen': len(raw), 'stored': len(raw)}
    assert normal['log_synced'][stream] and not normal['log_truncated'][stream] and normal['log_errors'][stream] is None
    records.append(create(stream.upper() + '.original.txt', raw))

report = {'format': 'hepta-canonical-actual-core-native-binary-readback-v1', 'job_id': JOB, 'records': records, 'complete_fixed_version_coverage': True, 'terminal_and_full_streams_equal': True, 'qualification': False}
report_raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
print(json.dumps({'readback': create('CORE_READBACK_REVIEW.json', report_raw), 'records': [{k: v for k, v in row.items() if k not in ('chunks',)} for row in records]}, indent=2))
result = json.loads((ROOT / 'RESULT.json').read_bytes())
summary = {}
for key, value in result.items():
    if isinstance(value, list) and len(value) > 8:
        summary[key] = {'rows': len(value), 'first_keys': list(value[0]) if value and isinstance(value[0], dict) else None}
    elif len(json.dumps(value)) > 12000:
        summary[key] = {'type': type(value).__name__, 'keys': list(value) if isinstance(value, dict) else None}
    else:
        summary[key] = value
print(json.dumps({'actual_result': summary}, indent=2))
