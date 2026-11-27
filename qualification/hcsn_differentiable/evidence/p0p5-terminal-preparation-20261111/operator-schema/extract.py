"""Read retained local operator originals; no native/process/model operations."""
import hashlib
import json
from pathlib import Path
import resource
import time
import zipfile

START = time.perf_counter()
CPU = time.process_time()
BASE = Path('/workspace/scratch/c385a7439f8e')
OUT = Path(__file__).resolve().parent
PUB = BASE / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-c2-launch-20261110'
ZIP = PUB / 'first-step/control-plane-originals-v1.zip'
MEMBER = 'c2-native-execution-preparation-v1/LAUNCH-REQUEST.json'
INPUTS = {
    'ORIGINAL-LAUNCH-ACK.json': PUB / 'launch/LAUNCH-RESPONSE.json',
    'TERMINAL-OBSERVER-STATUS-RAW.json': BASE / 'training-store-recovery-20261111-v1/v8/STATUS-RAW.json',
    'TERMINAL-OBSERVER-READ-RAW.json': BASE / 'training-store-recovery-20261111-v1/v8/READ-RAW.json',
}

def identity(path):
    b = path.read_bytes()
    return {'path': str(path), 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}

def emit(name, value):
    b = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    with (OUT / name).open('xb') as f:
        f.write(b)

def payload(value):
    wrappers = [k for k in ('raw', 'result') if k in value]
    assert len(wrappers) == 1 and not value.get('isError')
    item = value[wrappers[0]]
    assert not item.get('isError')
    return json.loads(item['content'][0]['text'])

before = {str(p): identity(p) for p in [ZIP, *INPUTS.values(), Path(__file__)]}
with zipfile.ZipFile(ZIP) as z:
    request_bytes = z.read(MEMBER)
assert len(request_bytes) == 25059
assert hashlib.sha256(request_bytes).hexdigest() == '72f319c01eccafb3b50b48d4e0aecebbd1e7b372d87869267392db9f7838eb53'
with (OUT / 'ORIGINAL-LAUNCH-REQUEST.json').open('xb') as f:
    f.write(request_bytes)
for name, path in INPUTS.items():
    with (OUT / name).open('xb') as f:
        f.write(path.read_bytes())
request = json.loads(request_bytes)
ack = payload(json.loads(INPUTS['ORIGINAL-LAUNCH-ACK.json'].read_bytes()))
status = payload(json.loads(INPUTS['TERMINAL-OBSERVER-STATUS-RAW.json'].read_bytes()))
read = payload(json.loads(INPUTS['TERMINAL-OBSERVER-READ-RAW.json'].read_bytes()))
assert status['job_id'] == read['job_id']
request_extract = {k: v for k, v in request.items() if k not in ('args', 'stdin')}
request_extract.update(args_prefix=request['args'][:6], args_count=len(request['args']),
                       inline_arg_sha256=hashlib.sha256(request['args'][6].encode()).hexdigest(),
                       stdin_bytes=len(request['stdin'].encode()),
                       stdin_sha256=hashlib.sha256(request['stdin'].encode()).hexdigest())
streams = {}
for name in ('stdout', 'stderr'):
    s = read[name]
    b = bytes.fromhex(s['bytes_hex'])
    assert b.decode('utf-8') == s['text']
    assert s['offset'] + len(b) == s['next_offset']
    streams[name] = {k: s[k] for k in ('eof', 'offset', 'next_offset', 'size')}
    streams[name].update(keys=list(s), decoded_bytes=len(b), sha256=hashlib.sha256(b).hexdigest())
emit('SCHEMA-EXTRACT.json', {
    'schema': 'retained-operator-native-schema-extract-v1',
    'scope': 'Actual retained C2 launch and completed observer schemas; no live C2 input or new native call',
    'request_original': identity(OUT / 'ORIGINAL-LAUNCH-REQUEST.json'),
    'request_zip_member': {'archive': before[str(ZIP)], 'member': MEMBER},
    'request_top_level_keys': list(request), 'actual_C2_request_extract': request_extract,
    'ack_top_level_keys': list(ack), 'ack_job_keys': list(ack['job']),
    'ack_binding': {k: ack['job'][k] for k in ('id', 'host', 'executable', 'cwd', 'env_keys', 'execution_mode', 'idempotency_key', 'request_digest', 'created_unix_ms', 'launch_state', 'launch_error', 'unit')},
    'ack_launch': ack['launch'], 'ack_reused': ack['reused'],
    'terminal_status_actual_observer': status,
    'read_top_level_keys': list(read), 'read_job_id': read['job_id'], 'read_streams': streams,
    'limits': ['The ACK does not echo env values, timeout_seconds, nice, CPU quota or MemoryMax; retain and bind exact REQUEST independently.',
               'REQUEST file SHA256 is not the daemon request_digest; the latter uses runtime request canonicalization.',
               'Parse original content.text with an integer-preserving parser; do not bind the 64-bit request_fingerprint through JavaScript Number.',
               'The succeeded status/read sample belongs to the completed v8 observer, not the currently running/unknown C2 job.',
               'Actual C2 REQUEST uses -c plus stdin deployment. A future pre-staged direct bootstrap request is a new request, not this historical one.',
               'Future audit timeout1950/resources must come from its frozen contract, not these historical C2 values.'],
    'native_processes_started_by_extraction': 0, 'model_operations': 0,
})
after = {str(p): identity(p) for p in [ZIP, *INPUTS.values(), Path(__file__)]}
assert before == after
emit('EXTRACTION-RECEIPT.json', {'schema': 'local-schema-extraction-receipt-v1', 'status': 'completed',
     'source_before': before, 'source_after': after, 'sources_unchanged': True,
     'wall_seconds': time.perf_counter() - START, 'cpu_seconds': time.process_time() - CPU,
     'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
     'cost_scope': 'Local extraction body; excludes interpreter startup and tool transport. No native/model work.'})
rows = [{**identity(p), 'source': str(p), 'suggested_name': p.name} for p in sorted(OUT.iterdir()) if p.is_file()]
emit('COPY_LIST.json', {'schema': 'copy-list-v1', 'files': rows})
print(json.dumps(identity(OUT / 'COPY_LIST.json')))
