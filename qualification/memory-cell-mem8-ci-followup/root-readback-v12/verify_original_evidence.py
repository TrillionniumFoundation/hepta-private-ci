#!/usr/bin/env python3
"""Read immutable receipts and archive members; never execute archived programs."""
import base64
import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
READBACK = ROOT / 'readback'
REF = 'cf406b45b7309d14ecc379cfee7c911e2eca98a5'
PINNED = {
    0: (302680, '62267ab429df3c6034ee05485625c0277a1969d49ce03c8240b1b9b10e27759c', 12, 'MANIFEST.json'),
    2: (15780, '9a425183857f673371f8eb5abadc2b0450675eddbec538347e299c7fbe4d3d70', 21, 'V1_FAILURE_MANIFEST.json'),
    9: (11940, '2b816daf9e3c25b2ae8da8f72bbd37dbe48ad69e7667949410cadaadeaf60ae4', 72, 'MEMBER_MANIFEST.json'),
    10: (163076, '11022e801d89742574905d95508c7c15d15447b9091e127103f2c67d883a91ca', 19, 'MEMBER_MANIFEST.json'),
    11: (39596, 'f5aa46ce6be114b516887ffb7bc3c1330d7a55d9ebef647871456fe1b2953f11', 32, 'BUNDLE_MANIFEST.json'),
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def inspect_archive(data, expected_count, manifest_name):
    members = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as tar:
        entries = tar.getmembers()
        assert len(entries) == expected_count
        assert sum(item.size for item in entries) <= 30_000_000
        for item in entries:
            path = PurePosixPath(item.name)
            assert item.isfile() and not path.is_absolute() and '..' not in path.parts
            assert str(path) == item.name and item.name not in members
            content = tar.extractfile(item).read()
            assert len(content) == item.size
            members[item.name] = content
    manifest = json.loads(members[manifest_name])
    rows = manifest['members']
    assert len(rows) == len(members) - 1
    assert {row['path'] for row in rows} == set(members) - {manifest_name}
    for row in rows:
        content = members[row['path']]
        assert len(content) == row['bytes'] and sha(content) == row['sha256']
        if 'git_blob' in row:
            assert blob(content) == row['git_blob']
    return members, {'members': len(members), 'manifest_rows_verified': len(rows),
                     'uncompressed_bytes': sum(map(len, members.values()))}

objects = {}
object_audits = []
for path in sorted(READBACK.glob('READBACK_*.json')):
    index = int(path.stem.rsplit('_', 1)[1])
    receipt = json.loads(path.read_text())
    assert receipt['ref'] == REF and not receipt['response'].get('isError')
    value = receipt['response']['structuredContent']
    assert value['encoding'] == 'base64'
    data = base64.b64decode(''.join(value['content'].split()), validate=True)
    assert blob(data) == value['sha'] == receipt['expected']['sha']
    objects[index] = data
    object_audits.append({'index': index, 'path': receipt['expected']['path'],
                          'bytes': len(data), 'sha256': sha(data), 'git_blob': blob(data)})
assert set(objects) == set(range(15))

archives = {}
archive_audits = []
for index, (size, digest, count, manifest_name) in PINNED.items():
    data = objects[index]
    assert len(data) == size and sha(data) == digest
    members, audit = inspect_archive(data, count, manifest_name)
    archives[index] = members
    archive_audits.append({'object_index': index, 'bytes': size, 'sha256': digest, **audit})
assert archives[0]['MANIFEST.json'] == objects[1]
assert archives[2]['V1_FAILURE_MANIFEST.json'] == objects[3]
assert archives[2]['V1_PREPARATION_FAILURE_SUMMARY.json'] == objects[4]
assert archives[10]['PROBE_EVIDENCE.tar.xz'] == objects[9]

mac_native = archives[11]['MAC_PROBE_EVIDENCE.tar.xz']
assert len(mac_native) == 5480
assert sha(mac_native) == 'a5dfee42c5c096c67899e757859e041525a0299dbf150d6f07a4af1ef53189d5'
mac_members, mac_audit = inspect_archive(mac_native, 12, 'MEMBER_MANIFEST.json')
mac_result = json.loads(mac_members['RESULT.json'])
mac_fetch = json.loads(mac_members['dotslash-fetch.json'])
assert mac_result['controls'] == [] and mac_result['status'] == 'INCOMPLETE_OR_FAILED'
assert mac_fetch['timed_out'] and mac_fetch['exit_code'] == -9

original_mac = json.loads(archives[0]['TERMINAL_SUMMARY.json'])
assert original_mac['run_id'] == 42971470498
assert original_mac['job_id'] == 130374692350
assert original_mac['head'] == '2ae5215beaf8d7b7df111a090b82134beae2683d'
assert original_mac['job_conclusion'] == 'cancelled'
assert original_mac['bazel_test_command_exit'] == 3
assert original_mac['failed_target_count'] == 20 and original_mac['flaky_target_count'] == 3
assert sum(x['status'] == 'TIMEOUT' for x in original_mac['failed_targets']) == 4
assert sum(x['status'] == 'FAILED' for x in original_mac['failed_targets']) == 16

prep = json.loads(objects[4])
assert prep['tracked_deleted_count'] == 9 and not prep['clean_base_gate_passed']
assert prep['lock_commands_executed'] == prep['native_tests_executed'] == prep['model_requests_executed'] == 0
assert prep['original_driver_numeric_exit_code'] is None
linux = json.loads(archives[9]['RESULT.json'])
assert linux['status'] == 'INERT_LINUX_OBSERVATION_COMPLETE'
assert linux['donor_before'] == linux['donor_after']
assert linux['source_before'] == linux['source_after']
assert linux['source_after']['status'] == ''
controls = {x['name']: x['candidate_passed_to_wrapper'] for x in linux['observation_summary']}
assert controls == {'absolute_preflight': '/usr/bin/true', 'absolute': '/usr/bin/touch',
                    'dot_first': 'touch', 'empty_first': 'touch'}

audit = {
    'schema': 'hepta.mem8.original-evidence.independent-root-readback.v12',
    'verified_at': datetime.now(timezone.utc).isoformat(),
    'immutable_commit': REF,
    'objects': object_audits,
    'archives': archive_audits,
    'nested_mac_original_archive': mac_audit,
    'linux_review_embedded_native_archive_matches_separately_fetched_object': True,
    'direct_archive_members_verified': sum(x['members'] for x in archive_audits),
    'additional_nested_mac_members_verified': mac_audit['members'],
    'original_mac_test_exit': 3,
    'original_mac_failed_targets': 16,
    'original_mac_timed_out_targets': 4,
    'original_mac_flaky_targets': 3,
    'original_mac_job_conclusion': 'cancelled',
    'original_lock_preparation_failed_before_lock_command': True,
    'linux_inert_control_passed': True,
    'mac_inert_control_count': 0,
    'mac_original_child_path_and_request_file_spelling': 'UNKNOWN',
    'archived_programs_executed': 0,
    'native_tests_executed': 0,
    'model_requests_executed': 0,
    'source_refs_modified': False,
}
(ROOT / 'ROOT_ORIGINAL_EVIDENCE_READBACK_AUDIT.json').write_text(json.dumps(audit, indent=2) + '\n')
print(json.dumps({k: audit[k] for k in ('immutable_commit', 'direct_archive_members_verified',
                                      'additional_nested_mac_members_verified', 'native_tests_executed',
                                      'model_requests_executed')}, indent=2))
