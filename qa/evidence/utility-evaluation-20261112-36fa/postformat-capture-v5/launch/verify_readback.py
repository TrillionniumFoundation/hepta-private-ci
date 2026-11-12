import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-postformat-capture-launch-v1')
VERSION = '2050:50401559:626888:1794516721097205008:1794516721097205008'

def ident(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def save(name, raw):
    p = ROOT / name
    if p.exists():
        assert p.read_bytes() == raw, name
    else:
        with p.open('xb') as f:
            f.write(raw)
    return {'name': name, **ident(raw)}

def decoded(name):
    raw = (ROOT / name).read_bytes()
    sdk = json.loads(raw)
    assert sdk.get('isError') is not True, name
    payload = sdk.get('structuredContent') or json.loads(next(c['text'] for c in sdk['content'] if c['type'] == 'text'))
    data = base64.b64decode(payload['data_base64'], validate=True)
    assert hashlib.sha256(data).hexdigest() == payload['chunk_sha256'], name
    assert len(data) == payload['next_offset'] - payload['offset'], name
    return payload, data, {'sdk': name, 'sdk_identity': ident(raw), **{k:v for k,v in payload.items() if k != 'data_base64'}}

result = json.loads((ROOT / 'RESULT.json').read_bytes())
assert result['status'] == 'CAPTURED_ACTUAL_POSTFMT_REVIEW_REQUIRED'
assert result['source_changed'] is False and result['qualification'] is False
assert result['source_write_authorized'] is False and result['tests_dispatched'] == 0
assert result['captured_paths'] == 73
assert all(row['status'] == 'verified' for row in result['final_audits'])

chunks = []
readbacks = []
for offset in range(0, 626888, 65536):
    suffix = '_RETRY01' if offset in (327680, 458752, 524288) else ''
    name = f'PACKET_READ_{offset:06d}{suffix}.original.json'
    p, data, record = decoded(name)
    assert p['version'] == VERSION and p['size'] == 626888 and p['offset'] == offset
    assert p['eof'] == (p['next_offset'] == 626888)
    chunks.append(data); readbacks.append(record)
packed = b''.join(chunks)
pin = result['capture_packet']
assert ident(packed) == {k: pin[k] for k in ('bytes', 'sha256', 'git_blob')}
save('ACTUAL_73_FILES.json.gz', packed)
raw = gzip.decompress(packed)
assert ident(raw) == pin['raw']
save('ACTUAL_73_FILES.json', raw)
for row in pin['parts']:
    part = packed[row['decoded_offset']:row['decoded_offset']+row['decoded_bytes']]
    assert len(part) == row['decoded_bytes'] and hashlib.sha256(part).hexdigest() == row['decoded_sha256']
    encoded = base64.b64encode(part) + b'\n'
    assert ident(encoded) == {k:row[k] for k in ('bytes','sha256','git_blob')}
    save(row['name'], encoded)

inventory_path = Path('/tmp/hepta-36fa-postformat-inventory-recovery-v1/final.inventory.recovered.json')
inventory_raw = inventory_path.read_bytes()
assert ident(inventory_raw) == result['complete_inventory']
inventory = json.loads(inventory_raw)
rows = {r['path']: r for r in inventory['files']}
assert len(rows) == 15188
packet = json.loads(raw)
assert packet['source_identity'] == inventory['source'] == result['source_identity']
assert packet['complete_inventory'] == result['complete_inventory']
assert packet['actual_physical_tree'] == result['actual_physical_tree'] == '65b898bad23cd58c7f6fd53fafe618f9cf9562dc'
paths = Path('/tmp/hepta-36fa-postformat-handoff-v1/CAPTURE_PATHS.txt').read_text().splitlines()
assert [r['path'] for r in packet['files']] == paths and len(paths) == len(set(paths)) == 73
for row in packet['files']:
    b = base64.b64decode(row['content_base64'], validate=True)
    i = ident(b)
    assert row['bytes'] == i['bytes'] and row['sha256'] == i['sha256'] and row['git_blob_sha'] == i['git_blob']
    assert row['original_inventory_row'] == rows[row['path']]
    assert row['stable'] is True and row['permissions'] == rows[row['path']]['permissions']
    assert i['sha256'] == rows[row['path']]['sha256'] and i['git_blob'] == rows[row['path']]['working_blob']

artifacts = {r['name']: r for r in result['artifacts']}
for name in ('SOURCE_COORDINATION_SH.json', 'GIT_BEFORE.json.gz', 'GIT_AFTER.json.gz'):
    p, data, record = decoded(name.replace('.', '_') + '_READ_RETRY01.original.json')
    assert p['offset'] == 0 and p['next_offset'] == p['size'] and p['eof']
    assert ident(data) == {k: artifacts[name][k] for k in ('bytes','sha256','git_blob')}
    save(name, data); readbacks.append(record)
    if name.endswith('.gz'):
        plain = gzip.decompress(data)
        assert ident(plain) == artifacts[name]['raw']
        save(name[:-3], plain)
        row = artifacts[name]['parts'][0]
        encoded = base64.b64encode(data) + b'\n'
        assert ident(encoded) == {k: row[k] for k in ('bytes','sha256','git_blob')}
        save(row['name'], encoded)
assert (ROOT/'GIT_BEFORE.json.gz').read_bytes() == (ROOT/'GIT_AFTER.json.gz').read_bytes()
lease = json.loads((ROOT/'SOURCE_COORDINATION_SH.json').read_bytes())
assert lease['lock_acquired'] == 'LOCK_SH|LOCK_NB' and lease['inode'] == 50139448

status_sdk = json.loads((ROOT/'STATUS_01.original.json').read_bytes())
status = status_sdk.get('structuredContent') or json.loads(next(c['text'] for c in status_sdk['content'] if c['type'] == 'text'))
assert status['job_id'] == '1a1d1880477-2564-1c56' and status['state'] == 'succeeded' and status['exit_code'] == 0
assert status['output_complete'] is True and status['output_durable'] is True and status['timed_out'] is False

review = {'format': 'hepta-postformat-handoff-complete-readback-v1',
          'qualification': False, 'new_native_execution': False,
          'native_job': status['job_id'], 'normal_terminal_observed': True,
          'full_packet_identity': ident(raw), 'gzip_identity': ident(packed),
          'complete_actual_file_count': 73, 'all_raw_file_hashes_and_inventory_rows_verified': True,
          'source_inventory_identity': ident(inventory_raw),
          'source_inventory_provenance': 'Root exact recovery of the original V5 bytes; this readback is not a second native inventory execution.',
          'original_source_before_and_after_equal': True, 'actual_git_before_and_after_equal': True,
          'actual_sh_lease': lease, 'readbacks': readbacks,
          'original_transport_timeouts_preserved': [p.name for p in sorted(ROOT.glob('*READ*.original.json')) if json.loads(p.read_bytes()).get('isError') is True],
          'git_publication': 'This verifier computes identities only. Root separately publishes the retained originals.'}
save('COMPLETE_READBACK_REVIEW.json', (json.dumps(review, indent=2, sort_keys=True) + '\n').encode())
placement = {'format': 'hepta-local-postformat-handoff-placement-v1',
             'directory': str(ROOT), 'qualification': False,
             'computed_identities_are_not_publication_claims': True,
             'files': [{'local_path':str(p), 'name':p.name, **ident(p.read_bytes())} for p in sorted(ROOT.iterdir()) if p.is_file() and p.name != 'LOCAL_COMPLETE_PLACEMENT.json']}
save('LOCAL_COMPLETE_PLACEMENT.json', (json.dumps(placement,indent=2,sort_keys=True)+'\n').encode())
print(json.dumps({'status':'all_complete_actual_readback_verified','files':73,'packet':ident(raw),'gzip':ident(packed),'placement_entries':len(placement['files']), 'review':ident((ROOT/'COMPLETE_READBACK_REVIEW.json').read_bytes())},indent=2))
