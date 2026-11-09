"""Append exact, reviewed packets to the explicit current evidence checkpoint."""

import argparse
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile


def main():
    if not __debug__:
        raise RuntimeError('Run without Python optimization; all admission assertions are required')
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--phase', required=True)
    parser.add_argument('--expected-index', required=True)
    parser.add_argument('--require-clean', action='store_true')
    args = parser.parse_args()
    assert args.phase.replace('-', '').isalnum()
    records = Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e')
    helper = records / 'append-evidence-increment-002-v1.py'
    import hashlib
    assert hashlib.sha256(helper.read_bytes()).hexdigest() == '3282737cc2d660a95a157ea43c222922a3753e3dd6ed5a39456d7ea36615f660'
    spec = importlib.util.spec_from_file_location('immutable_packet_helpers', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root, work = module.ROOT, module.WORK
    expected_head = 'e781fbebad63968adf18cce97dd04657b3854917'
    initial_index_sha256 = '6a1a7c2ed7cf55f72b0e9beff24b01be09c326a7097fdd32af6ab09352b89aed'
    common_sha = 'bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d'
    common_tree = 'f7b65a747a1d2f585be38a4665ab2b4f1b07efb6'
    common = Path('/home/qian-qi/worktrees/hepta-cell-s0-common-20261108-898e')

    def common_identity():
        def git(*argv):
            return subprocess.check_output(['git', *argv], cwd=common, text=True).strip()
        identity = {'source_sha': git('rev-parse', 'HEAD'),
                    'source_tree': git('rev-parse', 'HEAD^{tree}'),
                    'branch': git('branch', '--show-current'),
                    'status': git('status', '--porcelain=v1', '--untracked-files=all'),
                    'current_sha256': module.sha((common / 'qualification/cell-research-stages-20261108/CURRENT_RESULT.json').read_bytes())}
        assert identity == {'source_sha': common_sha, 'source_tree': common_tree,
                            'branch': 'codex/cell-s0-common-20261108-898e', 'status': '',
                            'current_sha256': 'c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4'}
        return identity

    common_before = common_identity()
    assert module.git('rev-parse', 'HEAD') == expected_head
    assert module.git('branch', '--show-current') == 'codex/cell-s0-evidence-20261108-898e'
    if args.require_clean or args.expected_index == initial_index_sha256:
        assert not module.git('status', '--porcelain=v1', '--untracked-files=all')
    relative_root = root.relative_to(work).as_posix() + '/'
    original_index_bytes = subprocess.check_output(['git', 'show', expected_head + ':' + relative_root + 'manifest.json'], cwd=work)
    assert module.sha(original_index_bytes) == initial_index_sha256
    original_index = json.loads(original_index_bytes)
    assert len(original_index['packets']) == 83
    protected_prefixes = tuple(relative_root + 'packets/' + row['packet_id'] + '/' for row in original_index['packets'])
    for argv in (['git', 'diff', '--no-renames', '--name-only', '-z', 'HEAD'], ['git', 'ls-files', '--others', '--exclude-standard', '-z']):
        changed = subprocess.check_output(argv, cwd=work).split(b'\0')
        assert all(path.decode().startswith(relative_root) for path in changed if path)
        assert not any(path.decode().startswith(protected_prefixes) for path in changed if path), 'Original 83 packet paths must match the committed checkpoint'
    assert module.sha((root / 'manifest.json').read_bytes()) == args.expected_index
    assert module.sha((root / 'verify_packets.py').read_bytes()) == '50e086000bf0a2a414a00e0afb6010bec0394c9b5553e159b80fa9526f3846d7'
    input_bytes = args.inputs.read_bytes()
    inputs = json.loads(input_bytes)
    index = json.loads((root / 'manifest.json').read_bytes())
    assert inputs['phase'] == args.phase and inputs['expected_index_sha256'] == args.expected_index
    assert inputs['expected_evidence_head'] == expected_head
    assert inputs['expected_common_source_sha'] == common_sha and inputs['expected_common_source_tree'] == common_tree
    assert len(index['packets']) == inputs['expected_prior_packet_count']
    assert index['packets'][:83] == original_index['packets']
    assert inputs['current_common_validation']['source_sha'] == common_sha
    assert inputs['current_common_validation']['source_tree'] == common_tree
    def same_typed(left, right):
        if type(left) is not type(right):
            return False
        if isinstance(left, dict):
            return left.keys() == right.keys() and all(same_typed(left[k], right[k]) for k in left)
        if isinstance(left, list):
            return len(left) == len(right) and all(same_typed(a, b) for a, b in zip(left, right))
        return left == right

    retained_validation = json.loads(json.dumps(inputs['current_common_validation']))
    failed_core = retained_validation['separate_source_observations'].pop('core_output_45a_failed_history')
    blocked_timer = retained_validation['separate_source_observations'].pop('remote_timer_6ec_dependency_failure_history')
    assert same_typed(retained_validation, original_index['current_common_validation'])
    assert failed_core['source_sha'] == '45a50bffd1631d502889069fc3f713b8a5e775d8'
    assert failed_core['source_tree'] == '60fd0cc181f3f34dbbb3a4a9a63226b920260ce2'
    assert failed_core['original_native_execution_status'] == 'FAIL'
    assert same_typed(failed_core['counts'], {
        'executed': 3827, 'passed': 3274, 'failed_exit101': 6, 'signal_aborted': 545,
        'timed_out': 2, 'failed_including_timeouts': 553, 'original_ignored_not_executed': 9,
        'retries': 0, 'leaks': 0})
    assert blocked_timer['source_sha'] == '6ec5993fec3dcd6a3c569498a1d5b4c277f1c142'
    assert blocked_timer['source_tree'] == 'b0ddbe6b6f83dc42657260b266774f79c9d1ed90'
    assert blocked_timer['dependency_attempt_count'] == 2
    assert blocked_timer['explicit_recovery_count'] == 1
    for count_key in ('helper_executed', 'lint_executed', 'native_executed'):
        assert type(blocked_timer[count_key]) is int and blocked_timer[count_key] == 0
    for observation in (failed_core, blocked_timer):
        assert observation['common_source_advanced'] is False and observation['scientific_acceptance'] is False
        assert observation['physical_cost'] is None and observation['full_history_cost'] is None
    observations = inputs['supplementary_observations']
    assert len(observations) == 7 and len({row['relative_path'] for row in observations}) == 7
    json_observation_paths = {
        'observations/evidence-increment007-publication-v1/RESULT.json',
        'observations/evidence-increment007-publication-v1/commands.json',
        'observations/evidence-increment007-independent-readback-v1/RESULT.json',
        'observations/evidence-increment007-independent-readback-v1/commands.json',
    }
    reviewed_patch_pins = {
        'reviewed_changes/core-output-45a-reviewed.patch': (
            'core-output-summary-3fc-draft-v2/core-output-owner-transcript.patch',
            25852, 'b7e4cfb754a4c0bad55dc15ad9ee67a2932dc4a386223845a5686be275e04e6f'),
        'reviewed_changes/remote-timer-6ec-reviewed.patch': (
            'core-output-remote-timer-oracle-45a-preparation-v1/remote-collector-clock-oracle.patch',
            1651, '4b7a8813bd83b07a26050d9859bbbf5d0f20a914ca1d378804cf5530dae88a42'),
        'reviewed_changes/remote-timer-6ec-frozen.patch': (
            'core-output-clock-oracle-source-freeze-v1/formatted.patch',
            1919, '4a5b2dba27bc88ca5ad16a909dc66a7368f08c23096917e3139618a609fb3866'),
    }
    assert {row['relative_path'] for row in observations} == json_observation_paths | set(reviewed_patch_pins)
    assert inputs['supplementary_observation_scope']['source_commit'] == expected_head
    assert inputs['supplementary_observation_scope']['complete_stdout_stderr_prefixes_archived_here'] is False
    assert 'increment008a_supplementary_metadata_observations' not in index
    out = records / ('evidence-addendum-' + args.phase)
    out.mkdir(exist_ok=False)
    (out / 'driver.py').write_bytes(Path(__file__).read_bytes())
    (out / 'INPUTS.json').write_bytes(input_bytes)
    (out / 'ORIGINAL_INDEX.json').write_bytes(original_index_bytes)
    (out / 'COMMON_BEFORE.json').write_text(json.dumps(common_before, indent=2) + '\n')
    existing = {entry['packet_id'] for entry in index['packets']}
    before_existing_files = {path.relative_to(root).as_posix(): module.sha(path.read_bytes())
                      for path in root.rglob('*') if path.is_file() and path != root / 'manifest.json'}
    prepared, findings, inspected = [], [], []
    for packet in inputs['packets']:
        assert packet['packet_id'].replace('-', '').isalnum()
        assert packet['packet_id'] not in existing
        existing.add(packet['packet_id'])
        original = Path(packet['archive_path']).read_bytes()
        assert len(original) == packet['bytes'] and module.sha(original) == packet['sha256']
        required = {binding['path']: binding for binding in packet['required_json_members']}
        assert required and len(required) == len(packet['required_json_members'])
        verified_bindings = set()
        members = []
        with tarfile.open(fileobj=io.BytesIO(original)) as archive:
            names = set()
            for member in archive.getmembers():
                module.safe_name(member.name)
                assert member.name not in names
                names.add(member.name)
                assert member.isfile() or member.isdir(), member.name
                if member.isfile():
                    data = archive.extractfile(member).read()
                    members.append({'path': member.name, 'bytes': len(data), 'sha256': module.sha(data)})
                    if member.name in required:
                        binding = required[member.name]
                        assert len(data) == binding['bytes'] and module.sha(data) == binding['sha256'], member.name
                        value = json.loads(data)
                        for check in binding['equals']:
                            actual = value
                            for key in check['path']:
                                actual = actual[key]
                            assert type(actual) is type(check['value']) and actual == check['value'], (member.name, check['path'])
                        verified_bindings.add(member.name)
                    module.scan(packet['packet_id'] + '!/' + member.name, data, findings, inspected)
        assert len(members) == packet['file_member_count'], packet['packet_id']
        assert verified_bindings == set(required), packet['packet_id']
        prepared.append((packet, original, members))
    assert len(prepared) == 4
    assert len(index['packets']) + len(prepared) == inputs['expected_final_packet_count'] == 87
    prepared_observations = []
    observation_objects = {}
    for observation in observations:
        relative = Path(observation['relative_path'])
        source = Path(observation['source_path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        if relative.as_posix() in json_observation_paths:
            assert observation['kind'] == 'original_json_observation'
            assert source == records / relative.relative_to('observations')
        else:
            assert observation['kind'] == 'reviewed_source_patch'
            source_relative, expected_bytes, expected_sha256 = reviewed_patch_pins[relative.as_posix()]
            assert source == records / source_relative
            assert (observation['bytes'], observation['sha256']) == (expected_bytes, expected_sha256)
        assert source.is_file() and not source.is_symlink() and source.stat().st_nlink == 1
        data = source.read_bytes()
        assert len(data) == observation['bytes'] and module.sha(data) == observation['sha256']
        assert len(data) <= 512000 and not (root / relative).exists()
        if relative.as_posix() in json_observation_paths:
            observation_objects[relative.as_posix()] = json.loads(data)
        else:
            assert data.startswith(b'diff --git ') or data.startswith(b'--- a/')
            assert inputs['supplementary_observation_scope']['source_patch_bytes_not_execution_or_native_pass'] is True
        module.scan('supplementary-observation!/' + relative.as_posix(), data, findings, inspected)
        prepared_observations.append((observation, data))
    pub_key = 'observations/evidence-increment007-publication-v1/'
    read_key = 'observations/evidence-increment007-independent-readback-v1/'
    pub, readback = observation_objects[pub_key + 'RESULT.json'], observation_objects[read_key + 'RESULT.json']
    observation_pins = {row['relative_path']: row['sha256'] for row in observations}
    assert pub['commit'] == readback['commit'] == expected_head
    assert pub['status'] == 'published_and_all_new_metadata_commit_blobs_remote_readback_verified'
    assert readback['status'] == 'independent_007_remote_and_exact_committed_metadata_readback_verified'
    assert pub['commands_receipt_sha256'] == observation_pins[pub_key + 'commands.json']
    assert readback['commands_sha256'] == observation_pins[read_key + 'commands.json']
    assert readback['publication_receipt_sha256'] == observation_pins[pub_key + 'RESULT.json']
    assert readback['publication_commands_sha256'] == observation_pins[pub_key + 'commands.json']
    assert readback['new_metadata_observations_complete_in_index_and_commit'] == 21
    assert pub['packet_count'] == readback['packet_count'] == 83
    assert pub['published_file_count'] == readback['published_actual_committed_files'] == 1281
    assert pub['manifest_sha256'] == readback['manifest_sha256'] == initial_index_sha256
    for key in (pub_key, read_key):
        commands = observation_objects[key + 'commands.json']
        assert commands and all(type(row.get('exit_code')) is int and row['exit_code'] == 0 for row in commands)
    review = {'phase': args.phase, 'input_sha256': module.sha(input_bytes),
              'inspected_member_count_with_overlap': len(inspected), 'patterns': list(module.PATTERNS),
              'findings': findings, 'not_a_complete_secret_detection_claim': True}
    (out / 'PATTERN_REVIEW.json').write_text(json.dumps(review, indent=2) + '\n')
    assert not findings, 'Review required before modifying the publication tree'
    assert common_identity() == common_before
    assert module.sha((root / 'manifest.json').read_bytes()) == args.expected_index
    assert all(module.sha((root / path).read_bytes()) == digest for path, digest in before_existing_files.items())
    additions = []
    for packet, original, members in prepared:
        directory = root / 'packets' / packet['packet_id']
        directory.mkdir(exist_ok=False)
        chunks = []
        for number, offset in enumerate(range(0, len(original), module.CHUNK_BYTES), 1):
            data = original[offset:offset + module.CHUNK_BYTES]
            path = directory / f'archive.part{number:03}'
            with path.open('xb') as output:
                output.write(data)
            chunks.append({'sequence': number, 'path': path.relative_to(root).as_posix(),
                           'offset': offset, 'bytes': len(data), 'sha256': module.sha(data)})
        manifest = {**packet, 'file_members': members, 'publication_chunks': chunks,
                    'reassembled_original_bytes_verified': True, 'all_original_file_members_verified': True,
                    'required_json_member_bindings_verified': True}
        path = directory / 'manifest.json'
        path.write_text(json.dumps(manifest, indent=2) + '\n')
        additions.append({'packet_id': packet['packet_id'], 'scope': packet['scope'],
                          'archive_bytes': len(original), 'archive_sha256': module.sha(original),
                          'file_member_count': len(members), 'manifest_path': path.relative_to(root).as_posix(),
                          'manifest_sha256': module.sha(path.read_bytes())})
    for name, data in ((args.phase + '-inputs.json', input_bytes),
                       (args.phase + '-pattern-review.json', (out / 'PATTERN_REVIEW.json').read_bytes())):
        with (root / name).open('xb') as output:
            output.write(data)
    for observation, data in prepared_observations:
        target = root / observation['relative_path']
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            output.write(data)
    index['increment008a_supplementary_metadata_observations'] = [
        {'path': row['relative_path'], 'bytes': row['bytes'], 'sha256': row['sha256']}
        for row in observations
    ]
    index['increment008a_supplementary_metadata_scope'] = inputs['supplementary_observation_scope']
    index['packets'].extend(additions)
    if 'preceding_checkpoint_successor_status' not in index:
        historical_names = [key for key in index if key.startswith('latest_successor_') or key.startswith('isolated_followup_source_') or key == 'first_successor_bazel_observer_native_execution']
        assert {key: index[key] for key in historical_names} == {key: original_index[key] for key in historical_names}
        index['preceding_checkpoint_successor_status'] = {
            'evidence_commit': expected_head, 'index_sha256': initial_index_sha256,
            'source_sha': 'd1b32a67cbe9ada0b7d911bdc7d08820253bb1ca',
            'source_tree': 'f95a33684df6aac0a32326e20b63d4017d7b1968',
            'original_fields': {key: index.pop(key) for key in historical_names}}
        historical_native = index.pop('common_original_native_ci')
        assert historical_native == original_index['common_original_native_ci']
        assert historical_native['source_sha'] == 'ba4e1e42b6a8cbab724e1755bddfb9b5b8f298a1'
        index['historical_ba4_original_native_ci'] = historical_native
        index['historical_ba4_repository_ci_status'] = {
            'source_sha': historical_native['source_sha'], 'index_sha256': initial_index_sha256,
            'common_full_repository_ci_green': index.pop('common_full_repository_ci_green')}
        assert index['historical_ba4_repository_ci_status']['common_full_repository_ci_green'] == original_index['common_full_repository_ci_green']
    full_repository_green = inputs['current_common_validation']['full_repository_ci']['green']
    assert full_repository_green is None or full_repository_green is False, 'A full repository pass requires separate reviewed evidence'
    index.update(status='bounded_checkpoint_append_pending_verification',
                 preceding_evidence_commit=expected_head, complete_execution_history=False,
                 full_history_cost=None, full_history_cost_known=False,
                 stages={f'S{i}': 'HOLD' for i in range(6)}, stage_advancement_claimed=False,
                 latest_reviewed_common_source_sha=common_sha,
                 latest_reviewed_common_source_tree=common_tree,
                 current_common_validation=inputs['current_common_validation'],
                 common_full_repository_ci_green=full_repository_green)
    (root / 'manifest.json').write_text(json.dumps(index, indent=2) + '\n')
    assert index['packets'][:83] == original_index['packets']
    assert all(module.sha((root / path).read_bytes()) == digest for path, digest in before_existing_files.items())
    assert all(path.stat().st_size <= 512000 for path in root.rglob('*') if path.is_file())
    check = subprocess.run(['python3', str(root / 'verify_packets.py')], cwd=work, capture_output=True)
    (out / 'VERIFY.log').write_bytes(check.stdout + check.stderr)
    assert check.returncode == 0
    for observation, data in prepared_observations:
        assert Path(observation['source_path']).read_bytes() == data
        assert (root / observation['relative_path']).read_bytes() == data
    assert all(module.sha((root / path).read_bytes()) == digest for path, digest in before_existing_files.items())
    common_after = common_identity()
    assert common_after == common_before
    assert args.inputs.read_bytes() == input_bytes
    assert module.git('rev-parse', 'HEAD') == expected_head
    index['status'] = 'bounded_checkpoint_verified_pending_increment_publication'
    (root / 'manifest.json').write_text(json.dumps(index, indent=2) + '\n')
    result = {'phase': args.phase, 'status': 'appended_verified_not_committed',
              'prior_head': expected_head, 'packet_count': len(index['packets']),
              'added_packets': additions, 'prior_packet_bytes_unchanged': True,
              'manifest_sha256': module.sha((root / 'manifest.json').read_bytes()), 'pattern_review': review,
              'original_83_packet_index_entries_unchanged': True,
              'common_before': common_before, 'common_after': common_after,
              'required_json_bindings_verified': True,
              'original_83_packet_and_all_existing_nonmanifest_file_bytes_unchanged': True,
              'supplementary_observations': index['increment008a_supplementary_metadata_observations'],
              'supplementary_observation_scope': inputs['supplementary_observation_scope'],
              'supplementary_original_result_commands_links_verified': True,
              'new_metadata_still_requires_index_and_commit_blob_verification_at_publication': True,
              'new_tests_executed': False,
              'full_history_cost': None, 'stage_advancement_claimed': False}
    (out / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
