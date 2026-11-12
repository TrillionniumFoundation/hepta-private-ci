#!/usr/bin/env python3
"""Offline byte/identity verification of retained source-advance tool responses.

Reads existing local artifacts only. Does not execute any controller, source,
Git, compiler, formatter, network, or native command.
"""
import base64
import datetime
import hashlib
import json
from pathlib import Path


SOURCE = Path('/tmp/hepta-36fa-source-advance-9c4-v1')
OUTPUT = Path(__file__).resolve().parent / 'REVIEW.json'
VERSION = '2050:50139276:111744:1794512618489189978:1794512618489189978'
REMOTE_PATH = '/home/qian-qi/hepta-utility-36fa-evidence/source-advance-9c4-v1/run/RESULT.json'
JOB = '1a1d1490a3b-2564-1c26'
KEY = 'hepta-utility-36fa-source-advance-9c4-v1'


def identity(raw):
    return {
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest(),
    }


def read(name):
    raw = (SOURCE / name).read_bytes()
    inputs[name] = {'local_path': str(SOURCE / name), **identity(raw)}
    return raw


def payload(name):
    envelope = json.loads(read(name))
    assert envelope.get('isError') is False, name
    content = envelope['content']
    assert len(content) == 1 and content[0]['type'] == 'text', name
    return json.loads(content[0]['text'])


inputs = {}
chunks = []
decoded = []
for name, offset, next_offset, eof, expected_sha in (
    ('RESULT_READ_SDK.part00000.original.json', 0, 65536, False,
     'b836ec416c33629a293bdb38aee78898a6fd82f03ddb91ed8aa7047132150c22'),
    ('RESULT_READ_SDK.part65536.original.json', 65536, 111744, True,
     '32e6c4ba2138027d7a1e95d38d7ca9c07c977b89de8b7152e4742905d5e10b89'),
):
    part = payload(name)
    assert part['path'] == REMOTE_PATH
    assert part['version'] == VERSION
    assert part['size'] == 111744
    assert part['offset'] == offset and part['next_offset'] == next_offset
    assert part['eof'] is eof
    raw = base64.b64decode(part['data_base64'], validate=True)
    assert base64.b64encode(raw).decode('ascii') == part['data_base64']
    assert len(raw) == next_offset - offset
    assert hashlib.sha256(raw).hexdigest() == part['chunk_sha256'] == expected_sha
    chunks.append({'sdk': name, **{k: v for k, v in part.items() if k != 'data_base64'},
                   'decoded_bytes': len(raw)})
    decoded.append(raw)

raw_result = read('RESULT.json')
assert b''.join(decoded) == raw_result
assert identity(raw_result) == {
    'bytes': 111744,
    'sha256': 'fc41dfca19277e3e8ba70f98fc545a8ed3c4bf8d3548447b27a4d19857197ab9',
    'git_blob': 'd91a27aeddcd10bc729792a565b2e8489e8b03ef',
}
existing_review = json.loads(read('RESULT_FULL_READBACK.json'))
assert existing_review['raw_result'] == identity(raw_result)
assert existing_review['version'] == VERSION
assert existing_review['original_remote_path'] == REMOTE_PATH
assert existing_review['contiguous_chunks'] == [
    {k: v for k, v in part.items() if k not in ('sdk', 'decoded_bytes')} for part in chunks
]

normal = payload('MAIN_TERMINAL.original.json')
stream = payload('MAIN_READ0.original.json')
reconciliation = payload('MAIN_SAME_KEY_RECONCILIATION.original.json')
request = json.loads(read('ACTUAL_PROCESS_INPUT.json'))
assert normal['job_id'] == stream['job_id'] == reconciliation['job']['id'] == JOB
assert reconciliation['reused'] is True and reconciliation['retried_launch'] is False
assert reconciliation['launch'] is None
assert reconciliation['job']['launch_state'] == 'launched'
assert reconciliation['job']['launch_error'] is None
assert request['idempotency_key'] == reconciliation['job']['idempotency_key'] == KEY
for key in ('args', 'cwd', 'executable', 'host'):
    assert request[key] == reconciliation['job'][key], key
assert {k: v for k, v in normal.items() if k != 'audit_recorded'} == reconciliation['status']
assert normal['exit_code'] == 0 and normal['state'] == 'succeeded'
assert normal['timed_out'] is False and normal['cancelled'] is False
assert normal['automatic_retry'] is False
assert normal['output_complete'] is True and normal['output_durable'] is True
assert normal['terminal_publication_confirmed'] is True

stdout = bytes.fromhex(stream['stdout']['bytes_hex'])
assert stdout == stream['stdout']['text'].encode('utf-8') == read('MAIN.stdout.log')
assert (stream['stdout']['offset'], stream['stdout']['next_offset'], stream['stdout']['size']) == (0, 630, 630)
assert stream['stdout']['eof'] is True
assert stream['stderr'] == {'bytes_hex': '', 'eof': True, 'next_offset': 0,
                            'offset': 0, 'size': 0, 'text': ''}
for channel, size in (('stdout', 630), ('stderr', 0)):
    assert normal['log_bytes'][channel] == {'seen': size, 'stored': size}
    assert normal['log_errors'][channel] is None
    assert normal['log_synced'][channel] is True
    assert normal['log_truncated'][channel] is False

events = [json.loads(line) for line in stdout.splitlines()]
assert [e['event'] for e in events] == [
    'fixed_original_source_advance_launcher_verified', 'preconditions_verified', 'source_advance_terminal'
]
assert events[0]['driver_sha256'] == identity(read('driver.py'))['sha256']
assert events[0]['config_sha256'] == identity(read('APPROVED_CONFIG.json'))['sha256']
assert events[0]['qualification'] is False
result = json.loads(raw_result)
assert events[1]['source_commit'] == result['before']['commit']
assert events[1]['tree'] == result['before']['tree']
assert events[1]['tracked_entries'] == result['before']['inventory']['tracked_entries'] == 15188
assert events[2]['status'] == result['status'] == 'SOURCE_ADVANCED_FOR_MAINTENANCE_ONLY'
assert events[2]['local_head_advanced'] is result['local_head_advanced'] is True
for key in ('qualification', 'cargo_or_formatter_started', 'dependency_installation_started',
            'remote_ref_updates', 'source_branch_refs_updated', 'automatic_retry'):
    assert result[key] is False, key
assert result['test_commands_dispatched'] == 0
registry = json.loads(read('MAIN_REGISTRY_ERROR.original.json'))
assert registry['isError'] is True

review = {
    'format': 'hepta-source-advance-existing-transfer-peer-review-v1',
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'status': 'OFFLINE_TRANSPORT_AND_JOB_BINDING_VERIFIED',
    'scope': 'Existing retained SDK byte decoding, exact RESULT identity, same job and same-key reconciliation only.',
    'qualification': False,
    'new_h_calls': 0,
    'producer_executions': 0,
    'source_or_control_executions': 0,
    'inputs': inputs,
    'result_transfer': {'fixed_version': VERSION, 'path': REMOTE_PATH, 'chunks': chunks,
                        'concatenation_equals_existing_result_bytes': True,
                        'result_identity': identity(raw_result),
                        'existing_full_readback_metadata_matches': True},
    'job_binding': {'job_id': JOB, 'idempotency_key': KEY, 'original_request_fields_equal': True,
                    'normal_and_reconciled_status_equal': True, 'reused': True,
                    'retried_launch': False, 'launch_response': None,
                    'normal': normal, 'stdout_bytes': identity(stdout),
                    'stdout_hex_text_and_file_equal': True, 'stdout_events': events},
    'reported_source_advance': {
        'status': result['status'], 'started_at': result['started_at'], 'finished_at': result['finished_at'],
        'before': result['before'], 'after': result['after'], 'changes': result['changes'],
        'final_audits': result['final_audits'],
        'scope_note': 'These are fields from the byte-verified original result; this peer check does not reexecute or independently repeat source/object audits.'},
    'registry_observation_error': {
        'envelope_identity': inputs['MAIN_REGISTRY_ERROR.original.json'],
        'content': registry['content'], 'structuredContent': registry.get('structuredContent'),
        'interpretation': 'Registry inventory response-budget error retained separately; it is not the job normal terminal and does not imply another launch.'},
    'limits': [
        'No new native read, producer run, formatter, Cargo, or source edit was performed.',
        'Same-key reused=true and retried_launch=false are actual reconciliation fields; this does not assert an unobserved global process inventory.',
        'The source-advance result is maintenance-only. It is not successful fix/fmt, a final formatted source, source-gate PASS, runtime qualification, or real A/B/C evidence.',
        'Earlier maintenance UNKNOWN and compiler return 101 remain unchanged.'
    ],
}
with OUTPUT.open('xb') as handle:
    handle.write((json.dumps(review, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8'))
print(json.dumps({'review': str(OUTPUT), **identity(OUTPUT.read_bytes()), 'status': review['status']}))
