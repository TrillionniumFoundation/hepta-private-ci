"""Reconcile actual H4 archive execution, small child bytes and owned release.

The H3 parent is still a separate required full-byte input. Reading its reported
member hashes here does not execute the dependent consumer or supply its bytes.
"""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

BASE = Path('/workspace/scratch/93bfcfe29fc8')
SRC = BASE / 'w1/h4-reference-export'
OUT = Path(__file__).resolve().parent / 'actual-elf-export/execution'
MANIFEST = '160b839fbbf3593d86256d9ff9a1304719f16494fd6429240e8222c00e848654'
ARCHIVE = '47d3c5efa6b9aa4b2f97ef06a606f2931d8065f068311303f8d079c18a7bbaa5'
INDEX = '3c4355fbd6293e631092c432557289ee770e34ae818c2ec68a590b7388d0041e'
COMPLETE = 'd3bda29c2ff27a18895e04ca672109298ca78bc9a9fd290d28a5d3db62930018'
RELEASE = '55defb131f12e3509222543d21e8bed0d77d6001fa307106a01e804fc2c56b8e'
JOB = '1a1ae17645d-fc05-5d51'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(name):
    return json.loads((SRC / name).read_bytes())


def unwrap(name):
    return json.loads(read(name)['content'][0]['text'])


manifest_raw = (SRC / 'H4-execution-delivery-manifest.json').read_bytes()
assert sha(manifest_raw) == MANIFEST
manifest = json.loads(manifest_raw)
assert len(manifest['files']) == manifest['file_count'] == 62
assert sum(x['bytes'] for x in manifest['files']) == manifest['file_bytes'] == 6201199
for entry in manifest['files']:
    path = BASE / entry['path']
    assert path.is_relative_to(SRC) and not path.is_symlink()
    raw = path.read_bytes()
    assert len(raw) == entry['bytes'] and sha(raw) == entry['sha256']
launch = unwrap('H4-archive-launch.raw.json')
terminal = unwrap('H4-archive-terminal.raw.json')
assert launch['job']['id'] == terminal['job_id'] == JOB
assert launch['job']['idempotency_key'] == '93bfc-hepta-h4-actual-reference-images-export-01'
assert launch['job']['created_unix_ms'] == 1793922131037 and not launch['reused']
assert terminal['state'] == 'succeeded' and terminal['exit_code'] == 0
assert terminal['at_unix_ms'] == 1793922176412
assert not terminal['timed_out'] and not terminal['automatic_retry'] and not terminal['cancelled']
assert terminal['output_complete'] and terminal['output_durable'] and terminal['terminal_publication_confirmed']
assert terminal['log_truncated'] == {'stdout': False, 'stderr': False}
streams = {'stdout': b'', 'stderr': b''}
for name in ('H4-streams-0.raw.json', 'H4-streams-16384.raw.json'):
    result = unwrap(name)
    assert result['job_id'] == JOB
    for stream in streams:
        part = result[stream]
        raw = bytes.fromhex(part['bytes_hex'])
        assert raw == part['text'].encode() and part['offset'] == len(streams[stream])
        assert part['next_offset'] == part['offset'] + len(raw)
        streams[stream] += raw
for stream, raw in streams.items():
    assert raw == (SRC / ('H4-archive.' + stream)).read_bytes()
    assert len(raw) == terminal['log_bytes'][stream]['stored'] == terminal['log_bytes'][stream]['seen']
assert len(streams['stdout']) == 23217 and len(streams['stderr']) == 0
completion_raw = (SRC / 'H4-export-completion.json').read_bytes()
assert len(completion_raw) == 27459 and sha(completion_raw) == COMPLETE
completion = json.loads(completion_raw)
assert json.loads(streams['stdout']) == completion and streams['stdout'] != completion_raw
assert completion['status'] == 'COMPLETE_WITH_REFERENCED_PARENT' and completion['standalone_archive'] is False
assert completion['elapsed_seconds'] == 43.75246265903115 < 900
assert completion['archive_sha256'] == ARCHIVE and completion['archive_bytes'] == 100964
assert completion['archive_index_sha256'] == INDEX
assert completion['plan_sha256'] == 'c917633ed8b22fa7a97455ea06c4a96fecc4a208375899bd3afededebf007619'
assert completion['exporter_sha256'] == 'ce96de09dc981311753d37312c1b254751cce3b40c4f950f603303a523508425'

reconstructed = {}
for role in ('archive', 'part'):
    collected, version = b'', None
    for offset in (0, 65536):
        request = read(f'H4-child-{role}-request-{offset}.json')
        result = unwrap(f'H4-child-{role}-response-{offset}.raw.json')
        raw = base64.b64decode(result['data_base64'], validate=True)
        assert result['path'] == request['path'] and result['offset'] == offset == len(collected)
        assert len(raw) == min(65536, 100964 - offset) and sha(raw) == result['chunk_sha256']
        assert raw == (SRC / f'H4-child-{role}-chunk-{offset}.bin').read_bytes()
        assert result['size'] == 100964 and result['next_offset'] == offset + len(raw)
        assert result['eof'] == (offset == 65536)
        if version is None:
            version = result['version']
        else:
            assert request['expected_version'] == result['version'] == version
        collected += raw
    assert sha(collected) == ARCHIVE
    reconstructed[role] = collected
archive = SRC / 'H4-actual-retained-image-references.tar.xz'
assert reconstructed['archive'] == reconstructed['part'] == archive.read_bytes()
assert len(completion['parts']) == 1 and completion['parts'][0] == {
    'index': 0, 'offset': 0, 'bytes': 100964, 'sha256': ARCHIVE,
    'name': 'H4-actual-retained-image-references.tar.xz.part-0000',
}
assert (SRC / 'H4-child-parts' / completion['parts'][0]['name']).read_bytes() == archive.read_bytes()
members = {}
with tarfile.open(archive, 'r:xz') as opened:
    for entry in opened:
        assert entry.isfile() and entry.name not in members
        raw = opened.extractfile(entry).read()
        assert len(raw) == entry.size
        assert raw == (SRC / 'H4-child-extracted' / entry.name).read_bytes()
        members[entry.name] = raw
assert len(members) == 8 and sum(map(len, members.values())) == 2848290
assert sha(members['export-index.json']) == INDEX and len(members['export-index.json']) == 690778
assert members['export-index.json'] == (SRC / 'H4-actual-export-index.json').read_bytes()
index = json.loads(members['export-index.json'])
expected = dict(index['embedded_metadata_files'])
expected['export-index.json'] = {'bytes': 690778, 'sha256': INDEX}
assert set(expected) == set(members)
for name, raw in members.items():
    assert expected[name] == {'bytes': len(raw), 'sha256': sha(raw)}
assert members['export-plan.json'] == (SRC / 'H4-reference-export-plan.json').read_bytes()
assert members['exporter.py'] == (BASE / 'w1/h4-content-reference-draft/archive_reference.py').read_bytes()
assert members['owned-release-proof.json'] == (BASE / 'w1/H4-owned-release-probe/proof.json').read_bytes()
assert members['H4/original-source-map.json'] == (BASE / 'model_storage/h4-capture-repair/native/joint-h4-native-attempt-1/h4-actual-image-inventory.json').read_bytes()
assert members['H4/referenced-H3-index.json'] == (BASE / 'w1/h3-elf-export/H3-actual-export-index.json').read_bytes()
assert members['H4/referenced-H3-completion.json'] == (BASE / 'w1/h3-elf-export/H3-export-completion.json').read_bytes()
plan = json.loads(members['export-plan.json'])
assert index['original_run_outcome'] == plan['original_run_outcome'] == completion['original_run_outcome']
assert index['source_commit'] == completion['source_commit'] == plan['source_commit'] == '6db78eca53a5acdda0d96873d3f4cd65863426f0'
assert index['source_tree'] == completion['source_tree'] == plan['source_tree'] == 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
assert len(index['files']) == len(plan['files']) == 11
for row, original in zip(index['files'], plan['files']):
    assert all(row[key] == value for key, value in original.items())
    assert row['representation'] == 'referenced-complete-image'
    assert row['first_read_metadata'] == row['second_read_metadata']
    assert row['second_read_metadata']['bytes'] == row['bytes'] and row['second_read_metadata']['nlink'] == 1
    assert row['second_read_sha256'] == row['sha256'] and row['other_aliases_reopened_by_this_export'] is False
assert sum(len(x['original_observations']) for x in index['files']) == 597
assert sum(len(x['aliases']) for x in index['files']) == 32
assert sum(x['bytes'] for x in index['files']) == 1674575368
assert index['embedded_elf_bytes'] == 0 and index['referenced_elf_bytes'] == 1674575368
assert completion['selected_sources_actually_read_twice'] and completion['actual_parent_archive_and_all_members_verified']
assert not completion['native_reexecution'] and not completion['binary_rebuilt'] and not completion['capture_gaps_filled']
assert len(completion['logical_complete_views']) == 11
for row in completion['logical_complete_views']:
    assert row['actual_member_bytes_fully_hashed'] and row['parent_native_credit_transferred'] is False
release_raw = (SRC / 'H4-archive-owned-release-proof.json').read_bytes()
assert len(release_raw) == 2774 and sha(release_raw) == RELEASE
release = json.loads(release_raw)
assert release['job_id'] == JOB and release['owned_processes_clear'] and not release['failures']
assert release['original_launch_nonce'] == terminal['launch_nonce']
assert release['processes_killed'] is False and release['mutations_performed'] is False
assert release['systemctl']['fields']['LoadState'] == 'not-found'
assert release['original_pid_and_invocation_observed_before_terminal'] is False
assert release['original_root_processes'] == []
assert all(not c['exists'] and not c['owned_pids'] for c in release['exact_cgroups'])
released = unwrap('H4-archive-release-terminal.raw.json')
assert released['job_id'] == '1a1ae1a4c05-fc05-5d6c' and released['state'] == 'succeeded' and released['exit_code'] == 0
assert released['at_unix_ms'] == 1793922323042 and not released['timed_out']

OUT.mkdir(parents=True, exist_ok=True)
for entry in manifest['files']:
    source = BASE / entry['path']
    target = OUT / source.relative_to(SRC)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
shutil.copyfile(SRC / 'H4-execution-delivery-manifest.json', OUT / 'H4-execution-delivery-manifest.json')
report = {
    'schema': 'root-H4-actual-reference-archive-execution-review-v1',
    'delivery_sha256': MANIFEST, 'files_verified': 62, 'file_bytes': 6201199,
    'job_id': JOB, 'authoritative_result': 'SUCCEEDED exit0', 'outer_seconds': 45.375, 'budget_seconds': 900,
    'completion_sha256': COMPLETE, 'archive_sha256': ARCHIVE, 'archive_bytes': 100964,
    'independent_original_range_responses_verified': 4, 'complete_original_parts_verified': 1,
    'actual_members': {name: {'bytes': len(raw), 'sha256': sha(raw)} for name, raw in members.items()},
    'actual_index_bytes': 690778, 'actual_index_sha256': INDEX,
    'recorded_selected_source_twice_read_identities_verified': 11, 'original_observations': 597, 'aliases': 32,
    'other_aliases_reopened': False, 'exact_owned_release_sha256': RELEASE,
    'original_pid_invocation_unobserved_and_not_guessed': True,
    'parent_remote_full_verification_receipt_preserved': True,
    'parent_full_archive_locally_read_by_this_review': False, 'dependent_consumer_executed': False,
    'remaining_byte_requirement': 'Full exact H3 parent archive and all 68 original parts, then ce96 consumer of both complete packages.',
    'native_pass_or_capture_credit_added_by_archiving': False,
}
target = OUT / 'root-review.json'
target.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'path': str(target), 'sha256': sha(target.read_bytes()), 'archive_result': 'SUCCEEDED', 'child_actual_bytes': 100964, 'members': 8, 'dependent_closure': 'PENDING_ACTUAL_H3_PARENT'}))
