from pathlib import Path
import base64
import gzip
import hashlib
import json
import re

ROOT = Path('/tmp/hepta-36fa-provider-0c59-maintenance-runtime-v1')
JOB = '1a1d3eccd3a-392-231'

def pin(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

def put(name, data):
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == data, name
    else:
        with path.open('xb') as stream:
            stream.write(data)
    return {'name': name, 'path': str(path), **pin(data)}

def jput(name, value):
    return put(name, (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode())

def payload(name):
    sdk = json.loads((ROOT / name).read_bytes())
    assert sdk.get('isError') is False, (name, sdk)
    result = sdk.get('structuredContent')
    if result is None:
        result = json.loads(sdk['content'][0]['text'])
    return result

def assert_pin(data, expected):
    actual = pin(data)
    assert all(actual[k] == expected[k] for k in ['bytes', 'sha256', 'git_blob']), (actual, expected)

artifacts = json.loads((ROOT / 'ARTIFACTS.json').read_bytes())
rows = {r['name']: r for r in artifacts['files']}
assert len(rows) == len(artifacts['files'])
positions = {'stdout': 0, 'stderr': 0}
streams = {'stdout': bytearray(), 'stderr': bytearray()}
observations = []
for i in range(1, 11):
    name = f'MAIN_STREAMS_READ_{i:02d}.original.json'
    value = payload(name)
    assert value['job_id'] == JOB
    record = {'sdk': {'name': name, **pin((ROOT / name).read_bytes())}}
    for stream in positions:
        item = value[stream]
        data = bytes.fromhex(item['bytes_hex'])
        assert item['offset'] == positions[stream]
        assert item['next_offset'] == item['offset'] + len(data)
        assert data == item['text'].encode('utf-8')
        streams[stream].extend(data)
        positions[stream] = item['next_offset']
        record[stream] = {k: item[k] for k in ['offset', 'next_offset', 'size', 'eof']}
    observations.append(record)

normal = payload('MAIN_STATUS_06.original.json')
assert normal['job_id'] == JOB
assert normal['state'] == 'failed'
assert normal['exit_code'] == 1 and normal['timed_out'] is False
assert normal['output_complete'] and normal['output_durable']
stream_rows = []
for stream in positions:
    assert len(streams[stream]) == positions[stream]
    stream_rows.append(put(f'MAIN_COMPLETE_{stream.upper()}.raw.txt', bytes(streams[stream])))
assert positions == {'stdout': 129815, 'stderr': 0}

data = bytes(streams['stdout'])
events = []
offset = 0
for line in data.splitlines(keepends=True):
    try:
        value = json.loads(line)
    except (ValueError, UnicodeError):
        value = None
    if isinstance(value, dict) and 'event' in value:
        events.append({'offset': offset, 'end': offset + len(line), 'value': value})
    offset += len(line)
start = [e['end'] for e in events if e['value'].get('event') == 'original_maintenance_command_attempted' and e['value'].get('name') == 'fix']
end = [e['offset'] for e in events if e['value'].get('event') == 'original_maintenance_command_terminal' and e['value'].get('name') == 'fix']
assert len(start) == len(end) == 1
fix = data[start[0]:end[0]]
assert_pin(fix, rows['fix.raw.log'])
logged = json.loads((ROOT / 'fix.execute_logged.original.json').read_bytes())
assert logged['log_bytes'] == len(fix)
assert logged['log_sha256'] == pin(fix)['sha256']
assert logged['returncode'] == 101 and not logged['timed_out'] and not logged['output_limit_exceeded']
fix_row = put('fix.raw.exact_recovered.log', fix)
first_error = fix.index(b'error[E0364]')
errors = fix[first_error:]
error_row = put('fix.compiler_errors.original_excerpt.txt', errors)
assert len(re.findall(rb'^error\[E[0-9]+\]:', errors, re.MULTILINE)) == 6

decoded = []
failed_reads = []
names = ['final.postimages.json.gz.part-001.b64', 'final.HEAD-working.patch',
         'SOURCE_GIT_STATE.before.json', 'SOURCE_GIT_METADATA.before.json.gz.part-001.b64',
         'SOURCE_GIT_METADATA.after.json.gz.part-001.b64', 'READONLY_COMMANDS.json',
         'fix.after.postimages.json.gz.part-001.b64', 'INPUT_IDENTITIES.json']
for name in names:
    sdkname = 'RUN_' + re.sub(r'[^A-Za-z0-9]', '_', name) + '_READ_000000.original.json'
    sdk = json.loads((ROOT / sdkname).read_bytes())
    if sdk.get('isError'):
        failed_reads.append({'artifact_name': name, 'sdk_name': sdkname, **pin((ROOT / sdkname).read_bytes()), 'first_version_observed': None})
        continue
    value = payload(sdkname)
    body = base64.b64decode(value['data_base64'], validate=True)
    assert value['offset'] == 0 and value['eof'] is True
    assert value['next_offset'] == value['size'] == len(body)
    assert value['chunk_sha256'] == pin(body)['sha256']
    assert_pin(body, rows[name])
    item = {'sdk_name': sdkname, 'version': value['version'], 'original_path': value['path'], **put(name, body)}
    if name.endswith('.gz.part-001.b64'):
        gzipname = name[:-len('.part-001.b64')]
        gz = base64.b64decode(body.strip(), validate=True)
        assert_pin(gz, rows[gzipname])
        raw = gzip.decompress(gz)
        expected = {k: rows[gzipname]['raw_' + k] for k in ['bytes', 'sha256', 'git_blob']}
        assert_pin(raw, expected)
        item['decoded_gzip'] = put(gzipname, gz)
        item['decoded_raw'] = put(gzipname[:-3], raw)
    decoded.append(item)

report = {
    'format': 'hepta-failed-maintenance-original-terminal-readback-v1', 'job_id': JOB,
    'normal': {'name': 'MAIN_STATUS_06.original.json', **pin((ROOT / 'MAIN_STATUS_06.original.json').read_bytes())},
    'streams': stream_rows, 'stream_observations': observations,
    'fix_log': fix_row, 'fix_slice_in_actual_supervisor_stdout': {'offset': start[0], 'end': end[0]},
    'fix_log_provenance': 'Exact bytes recovered from complete actual supervisor stdout; equal to native execute_logged and ARTIFACTS three identities. This is not a second native fix.raw.log file read.',
    'compiler_errors': error_row, 'error_slice_in_actual_fix_log': {'offset': first_error, 'end': len(fix)},
    'compiler_error_count': 6, 'fix_returncode': 101, 'fmt_attempted': False, 'behavioral_tests_dispatched': 0,
    'decoded_actual_artifacts': decoded, 'failed_artifact_reads_preserved': failed_reads,
    'prior_cloud_reconstruction_assertion': {'observed': 'AssertionError after complete stdout/stderr files were saved', 'scope': 'Offline analysis only; no native execution affected', 'correct_schema': 'ARTIFACTS.files', 'original_artifacts_unchanged': True},
}
jput('TERMINAL_ORIGINAL_READBACK_REVIEW.json', report)
print(json.dumps({'fix_log':fix_row,'compiler_errors':error_row,'decoded_artifacts':decoded,'failed_reads':failed_reads},ensure_ascii=False))
