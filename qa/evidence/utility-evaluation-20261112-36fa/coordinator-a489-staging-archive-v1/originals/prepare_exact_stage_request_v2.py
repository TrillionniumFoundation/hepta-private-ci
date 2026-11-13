#!/usr/bin/env python3
"""Copy one already frozen request and create its one-time dispatch intent."""
import datetime
import json
import sys
from verify_stage_readback import OUT, CONTROL, pin, decode_json, create, original

number = int(sys.argv[1])
assert 2 <= number <= 5
approval_raw = (OUT/'ROOT_EXACT_APPROVAL.original.json').read_bytes()
assert pin(approval_raw) == {'bytes': 7698, 'sha256': '624156a7a015cdde153c39450cfc6838033d7e139d5405d238395803e95cfe7a', 'git_blob': 'a395a49b15c861be88d4e4e49f1e03557470ca55'}
approval = decode_json(approval_raw)
row = approval['allowed_staging_requests'][number-1]
previous, previous_pin = original(f'STAGE_{number-1:02d}.WRITE.original.json')
previous_row = approval['allowed_staging_requests'][number-2]
assert previous['written'] == previous['size'] == previous_row['decoded']['bytes']
assert previous['sha256'] == previous_row['decoded']['sha256']
assert previous['mode'] == previous_row['expected_mode'] and isinstance(previous['version'], str)
prefix = f'STAGE_{number:02d}'
assert not (OUT/(prefix+'.WRITE_INTENT.json')).exists(), 'intent exists: do not redispatch'
assert not (OUT/(prefix+'.WRITE.original.json')).exists(), 'original write receipt exists: do not redispatch'
raw = (CONTROL/row['name']).read_bytes()
assert pin(raw) == row['request']
parsed = decode_json(raw)
assert set(parsed) == {'data_base64', 'host', 'path', 'expected_version'}
assert all(parsed[key] == row[key] for key in ('host', 'path', 'expected_version'))
create(prefix+'.REQUEST.original.json', raw)
assert (OUT/(prefix+'.REQUEST.original.json')).read_bytes() == raw
intent = {'format': 'hepta-exact-fixed-staging-write-intent-v1',
          'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'sequence': number, 'approval': pin(approval_raw), 'request': row['request'],
          'host': parsed['host'], 'path': parsed['path'], 'expected_version': parsed['expected_version'],
          'decoded': row['decoded'], 'prior_stage_successful_original_write_sdk': previous_pin, 'original_driver_full_input_audit_still_required': True,
          'native_call': 'h_binary_write', 'maximum_invocations': 1,
          'unknown_rule': 'Read only the same fixed path; never repeat this write or change identity.'}
with (OUT/(prefix+'.WRITE_INTENT.json')).open('xb') as stream:
    stream.write((json.dumps(intent, indent=2)+'\n').encode())
print(json.dumps({'request_path': str(OUT/(prefix+'.REQUEST.original.json')), **pin(raw)}))
