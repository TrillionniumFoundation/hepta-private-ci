from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT = Path('/tmp/hepta-36fa-final-source-qualification-b608-v2-runtime-v1')

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def read(name):
    raw = (ROOT / name).read_bytes()
    return raw, json.loads(raw)

def utc_ns(value):
    seconds, nanos = divmod(value, 1_000_000_000)
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + '.' + f'{nanos:09d}' + 'Z'

approval_raw, approval = read('ROOT_EXACT_APPROVAL.original.json')
request_raw, request = read('ACTUAL_PROCESS_INPUT.original.json')
intent_raw, intent = read('SOURCE_DISPATCH_INTENT.json')
timeout_raw, timeout = read('SOURCE_ADMISSION.original.json')
query_raw, query = read('RESULT_READ_01.request.json')
observation_raw, observation = read('RESULT_READ_01.original.json')
assert identity(approval_raw) == {'bytes': 10788, 'sha256': '4ba2d95d6e859298b3d611f3aa21cf511884d012f1dfaea12f5488373abcb87e', 'git_blob': '9a48727adf7f73ee6adf8d45b567db3000a83c5f'}
assert identity(request_raw) == {'bytes': 280984, 'sha256': '3245e534618d004ba767b5b2ec5483194bcc5453fe6531ef8aff7ee393fb8214', 'git_blob': 'eb4658e231aac54f226a78585d647e2bab8aa6e1'}
assert set(request) == {'args', 'cwd', 'executable', 'host', 'idempotency_key', 'stdin', 'timeout_seconds'}
assert request['host'] == 'desktop' and request['cwd'] == '/home/qian-qi'
assert request['idempotency_key'] == 'hepta-utility-36fa-final-source-gates-b608-v2'
assert request['timeout_seconds'] == 7200 and request['executable'] == '/usr/bin/python3'
assert request['args'][:2] == ['-B', '-c'] and len(request['args']) == 3
assert request['args'][2].encode() == (ROOT / 'ACTUAL_BOOTSTRAP.original.py').read_bytes()
assert request['stdin'].encode() == (ROOT / 'ACTUAL_STDIN.original.json').read_bytes()
assert intent['approval'] == identity(approval_raw) and intent['request'] == identity(request_raw)
assert timeout['isError'] is True and '-32603: MCP request timed out' in timeout['content'][0]['text']
assert query == {'host': 'desktop', 'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v2/source-handoff/RESULT.json', 'offset': 0, 'limit': 65536}
assert observation['isError'] is True and observation['structuredContent']['error_code'] == 'INVALID_ARGUMENT'
assert "FileNotFoundError: [Errno 2] No such file or directory: 'final-qualification-b608-v2'" in observation['content'][0]['text']

original_names = [
    'ROOT_EXACT_APPROVAL.original.json', 'ROOT_EXACT_APPROVAL.GET.original.json',
    'ACTUAL_PROCESS_INPUT.original.json', 'ACTUAL_BOOTSTRAP.original.py', 'ACTUAL_STDIN.original.json',
    'SOURCE_DISPATCH_INTENT.json', 'EXACT_INTENT_VERIFICATION.original.json',
    'SOURCE_ADMISSION.original.json', 'RESULT_READ_01.request.json', 'RESULT_READ_01.original.json',
    'READONLY_RECONCILIATION_CAPABILITIES.json',
]
times = {}
for name in ['SOURCE_DISPATCH_INTENT.json', 'SOURCE_ADMISSION.original.json', 'RESULT_READ_01.request.json', 'RESULT_READ_01.original.json']:
    stat = (ROOT / name).stat()
    times[name] = {'cloud_file_mtime_ns': stat.st_mtime_ns, 'cloud_file_ctime_ns': stat.st_ctime_ns,
                   'cloud_file_mtime_utc': utc_ns(stat.st_mtime_ns)}
report = {
    'format': 'hepta-source-dispatch-unknown-window-v1',
    'created_at': datetime.now(timezone.utc).isoformat(),
    'source_request': identity(request_raw), 'approval': identity(approval_raw),
    'one_process_start_invoked': True,
    'observation_scope': 'One exact start response and one fixed RESULT path read; no other H calls in this window',
    'idempotency_key': request['idempotency_key'], 'host': request['host'],
    'actual_job_id': None, 'accepted': None, 'reused': None,
    'execution_status': 'Unknown', 'source_gate_execution_status': 'Unknown',
    'no_source_gate_pass_or_failure_claim': True,
    'first_process_response': identity(timeout_raw),
    'fixed_result_read_request': identity(query_raw), 'fixed_result_read_response': identity(observation_raw),
    'path_observation': 'Only the exact control path was reported unavailable at this read; no conclusion about job admission, cause, later execution, or source contents',
    'original_invocation_start_utc': None, 'original_invocation_return_utc': None,
    'timestamp_limit': 'The original tool response exposes no timestamps. Exact invocation and return timestamps were not independently sampled. Preserved intent and cloud-file timestamps below are observation boundaries, not native or exact API execution times.',
    'pre_dispatch_intent_time': intent['observed_cloud_time'],
    'cloud_original_file_times': times,
    'no_status_or_stream_request_without_job_id': True,
    'no_second_start_no_new_key_no_diagnostic_no_list_no_write': True,
    'old_65a_failure_preserved': True,
    'native_14_phase_authorized': False, 'qualification': False,
    'source_or_ref_mutation_authorized': False,
    'primary_originals': [{'name': name, **identity((ROOT / name).read_bytes())} for name in original_names],
    'validation': 'Pure local byte/schema verification; no H or source execution',
}
raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
with (ROOT / 'UNKNOWN_EXECUTION_REVIEW.json').open('xb') as stream:
    stream.write(raw)
print(json.dumps({'review': identity(raw), 'originals': len(original_names), 'execution_status': 'Unknown'}))
