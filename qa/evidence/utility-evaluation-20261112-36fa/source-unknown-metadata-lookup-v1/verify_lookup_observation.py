from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT = Path('/tmp/hepta-36fa-final-source-qualification-b608-v2-runtime-v1/metadata-lookup-v1')
KEY = 'hepta-utility-36fa-final-source-gates-b608-v2'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def read(name):
    return json.loads((ROOT / name).read_bytes())

def write(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    with (ROOT / name).open('xb') as stream:
        stream.write(raw)
    return {'name': name, **pin(raw)}

approval = read('ROOT_LOOKUP_APPROVAL.original.json')
assert pin((ROOT / 'ROOT_LOOKUP_APPROVAL.original.json').read_bytes()) == {'bytes': 3447, 'sha256': '18ae7fc1b3077852ad0e5125f804060bbfd08e0b748a8289c1afec460caf869f', 'git_blob': '8b874c4621289f9ad037581ed0ef00bf74ad63f7'}
assert approval['exact_idempotency_key'] == KEY
q1, q2 = read('PAGE_01.REQUEST.original.json'), read('PAGE_02.REQUEST.original.json')
s1, s2 = read('PAGE_01.SDK.original.json'), read('PAGE_02.SDK.original.json')
assert q1 == {'host': 'desktop', 'limit': 64}
assert s1['isError'] is False
assert len(s1['content']) == 1 and s1['content'][0]['type'] == 'text'
page = json.loads(s1['content'][0]['text'])
assert page['jobs'] == [] and page['validation_pending'] is True
assert page['inventory_complete'] is False and page['status_authoritative'] is False
assert page['has_more'] is True and isinstance(page['next_cursor'], str)
assert q2 == {**q1, 'cursor': page['next_cursor']}
assert s2['isError'] is True
assert [item['text'] for item in s2['content'] if item['type'] == 'text'] == ['durable inventory source entry bound exceeded']
projection = {
    'format': 'hepta-exact-original-key-matching-row-projection-v1',
    'approval': pin((ROOT / 'ROOT_LOOKUP_APPROVAL.original.json').read_bytes()),
    'host': 'desktop', 'idempotency_key': KEY, 'matching_rows': [],
    'matching_row_observed': False, 'job_id': None, 'accepted': None, 'reused': None,
    'reason': 'The first response contained no rows and a validation-pending cursor. The only continuation refused with durable inventory source entry bound exceeded.',
    'raw_sdk_provenance': [{'name': name, **pin((ROOT / name).read_bytes())} for name in ['PAGE_01.SDK.original.json', 'PAGE_02.SDK.original.json']],
    'no_unrelated_job_contents': True, 'no_credentials_in_projection': True,
    'execution_status': 'Unknown', 'does_not_prove_request_absent_or_not_applied': True,
}
projection_pin = write('MATCHING_ROW_PROJECTION.json', projection)
original_names = ['ROOT_LOOKUP_APPROVAL.original.json', 'ROOT_LOOKUP_APPROVAL.GET.original.json'] + [f'PAGE_{i:02d}.{suffix}' for i in (1, 2) for suffix in ('REQUEST.original.json', 'INTENT.json', 'SDK.original.json', 'RETURN_OBSERVATION.json')]
review = {
    'format': 'hepta-bounded-source-lookup-observation-review-v1',
    'created_at': datetime.now(timezone.utc).isoformat(),
    'validation': 'Pure Python parsing of preserved original SDK bytes; no H calls or JavaScript native integer parsing',
    'call_count': 2, 'snapshot_count': 1, 'same_host_and_limit': True,
    'continuation_exactly_matches_returned_cursor': True,
    'returned_job_row_count': 0, 'inventory_complete': False,
    'stop_reason': 'First continuation error: durable inventory source entry bound exceeded',
    'no_refresh_no_further_page_no_start_no_status_or_logs': True,
    'execution_status': 'Unknown', 'qualification': False,
    'metadata_sdk_policy': 'Raw SDKs remain local only; not published. This review and the empty matching projection contain no unrelated job rows. Root reviews any later publication.',
    'matching_projection': projection_pin,
    'timing_observations': [{'page': i, 'intent': read(f'PAGE_{i:02d}.INTENT.json'), 'return': read(f'PAGE_{i:02d}.RETURN_OBSERVATION.json')} for i in (1, 2)],
    'original_files': [{'name': name, **pin((ROOT / name).read_bytes())} for name in original_names],
}
review_pin = write('LOOKUP_OBSERVATION_REVIEW.json', review)
print(json.dumps({'review': review_pin, 'projection': projection_pin, 'execution_status': 'Unknown', 'calls': 2, 'returned_rows': 0}))
