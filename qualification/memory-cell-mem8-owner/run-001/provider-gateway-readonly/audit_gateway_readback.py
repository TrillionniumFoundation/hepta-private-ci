#!/usr/bin/env python3
"""Read-only verification of the exact provider diagnostic evidence download."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

BASE = Path(__file__).resolve().parent
ORIGINAL = BASE.parent / 'mem-provider-gateway-readonly-20261111'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def main():
    response = json.loads((BASE / 'GATEWAY_ARCHIVE_READBACK.json').read_text())
    assert response['encoding'] == 'base64'
    encoded = response['content']
    assert set(encoded) <= set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r\t ')
    raw = base64.b64decode(''.join(encoded.split()), validate=True)
    assert len(raw) == 10824 and sha(raw) == '31deecb726696a4bf05b1018243757e99e4f0e63437cdd9040cfa3edd9b06ed7'
    assert blob(raw) == response['sha'] == '6d81a371568ca552ea4384b0b289034b150c9f86'
    assert '6d1b677ac1ffcac9b9ea15b9b07ecc83f8c6e1c9' in response['display_url']
    assert raw == (ORIGINAL / 'PROVIDER_READONLY_EVIDENCE.tar.xz').read_bytes()
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:xz') as archive:
        for entry in archive:
            p = PurePosixPath(entry.name)
            assert entry.isfile() and not p.is_absolute() and '..' not in p.parts and entry.name not in files
            files[entry.name] = archive.extractfile(entry).read()
    assert len(files) == 13
    manifest = json.loads(files['FILE_MANIFEST.json'])
    assert not manifest['raw_durable_stdout_included'] and not manifest['raw_gateway_log_or_get_bodies_included']
    assert set(files) == {x['path'] for x in manifest['members']} | {'FILE_MANIFEST.json'}
    for row in manifest['members']:
        data = files[row['path']]
        assert len(data) == row['bytes'] and sha(data) == row['sha256'] and blob(data) == row['git_blob_sha']
    destination = BASE / 'readback/provider-gateway-readonly'
    for name, data in files.items():
        assert data == (ORIGINAL / name).read_bytes()
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    statuses = json.loads(files['HOST_STATUS.json'])
    jobs = {}
    for host, expected in {'ai395': '1a1c92b0b1b-135c4-442', 'desktop': '1a1c92b2dac-135c4-444'}.items():
        transport = statuses[host]
        assert not transport['isError']
        receipt = json.loads(transport['content'][0]['text'])
        assert receipt['job_id'] == expected and receipt['state'] == 'succeeded' and receipt['exit_code'] == 0
        assert receipt['output_complete'] and receipt['output_durable'] and receipt['terminal_publication_confirmed']
        assert not any(receipt[x] for x in ['automatic_retry', 'cancelled', 'timed_out'])
        assert not any(receipt['log_truncated'].values())
        jobs[host] = expected
    journal = json.loads(files['AI395_RESULT.json'])
    current = json.loads(files['DESKTOP_GET_RESULT.json'])
    readback = json.loads(files['PROCESS_OUTPUT_READBACK_STATUS.json'])
    assert journal['original_provider_final_status'] == current['original_provider_final_status'] == 'UNKNOWN'
    assert journal['journal_queries'] == 1 and journal['journal_entries_parsed'] == journal['exact_identifier_match_count'] == 0
    assert journal['journal_command_receipt']['exit_code'] == 0 and journal['journal_command_receipt']['stdout_bytes'] == 0
    assert journal['window_utc'] == {'since': '2026-11-11 04:47:00 UTC', 'until': '2026-11-11 04:49:00 UTC'}
    assert current['retry_count'] == 0 and len(current['observations']) == 3
    observations = []
    for item in current['observations']:
        assert item['method'] == 'GET' and item['attempts'] == 1 and item['http_status'] == 200
        assert item['url'].startswith('http://127.0.0.1:18083/') and not item['raw_body_persisted']
        observations.append({k:item[k] for k in ['method', 'url', 'http_status', 'started_at', 'finished_at']})
    assert journal['model_requests'] == current['model_requests'] == 0
    assert not journal['service_changes'] and not current['service_changes']
    assert not readback['full_stream_result_received'] and not readback['remote_process_cancel_called']
    result = {'schema':'hepta.mem8.provider-gateway.root-readback.v1', 'immutable_commit':'6d1b677ac1ffcac9b9ea15b9b07ecc83f8c6e1c9', 'archive_bytes':len(raw), 'archive_sha256':sha(raw), 'archive_git_blob':blob(raw), 'safe_regular_members':len(files), 'all_member_full_bytes_and_hashes_match':True, 'terminal_jobs':jobs, 'journal_matches':0, 'current_get_observations':observations, 'durable_process_stdout_full_readback':False, 'safe_result_files_complete':True, 'original_provider_final_status':'UNKNOWN', 'original_physical_provider_requests':None, 'new_host_diagnostics_by_root_audit':0, 'new_models':0, 'passed':True}
    (BASE / 'ROOT_GATEWAY_READBACK_AUDIT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
