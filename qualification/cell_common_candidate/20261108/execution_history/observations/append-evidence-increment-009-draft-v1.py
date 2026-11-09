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
    expected_head = '8ca3f19c69f2f14a42aa5fbe3ff72af807c65ff2'
    initial_index_sha256 = 'e2cf90360430c0db3dde19f3ef1e00466469b363f23b338e1f9db24a114edd7b'
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
    assert len(original_index['packets']) == 87
    protected_prefixes = tuple(relative_root + 'packets/' + row['packet_id'] + '/' for row in original_index['packets'])
    for argv in (['git', 'diff', '--no-renames', '--name-only', '-z', 'HEAD'], ['git', 'ls-files', '--others', '--exclude-standard', '-z']):
        changed = subprocess.check_output(argv, cwd=work).split(b'\0')
        assert all(path.decode().startswith(relative_root) for path in changed if path)
        assert not any(path.decode().startswith(protected_prefixes) for path in changed if path), 'Original 87 packet paths must match the committed checkpoint'
    assert module.sha((root / 'manifest.json').read_bytes()) == args.expected_index
    assert module.sha((root / 'verify_packets.py').read_bytes()) == '50e086000bf0a2a414a00e0afb6010bec0394c9b5553e159b80fa9526f3846d7'
    input_bytes = args.inputs.read_bytes()
    inputs = json.loads(input_bytes)
    index = json.loads((root / 'manifest.json').read_bytes())
    assert inputs['phase'] == args.phase and inputs['expected_index_sha256'] == args.expected_index
    assert inputs['expected_evidence_head'] == expected_head
    assert inputs['expected_common_source_sha'] == common_sha and inputs['expected_common_source_tree'] == common_tree
    assert len(index['packets']) == inputs['expected_prior_packet_count']
    assert index['packets'][:87] == original_index['packets']
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
    added_keys = (
        'desktop_6ec_dependency_strict_history',
        'desktop_6ec_core_owning_history',
        'desktop_6ec_appserver_failed_owning_history',
        'desktop_6ec_agentd_root_owning_history',
        'desktop_6ec_posthoc_diagnostics_history',
        'quiet_6ec_source_publication_history',
    )
    added = {key: retained_validation['separate_source_observations'].pop(key) for key in added_keys}
    assert same_typed(retained_validation, original_index['current_common_validation'])
    source_sha = '6ec5993fec3dcd6a3c569498a1d5b4c277f1c142'
    source_tree = 'b0ddbe6b6f83dc42657260b266774f79c9d1ed90'
    for observation in added.values():
        assert observation['source_sha'] == source_sha and observation['source_tree'] == source_tree
        assert observation['common_source_advanced'] is False and observation['scientific_acceptance'] is False
        assert observation['physical_cost'] is None and observation['full_history_cost'] is None
    strict = added['desktop_6ec_dependency_strict_history']
    assert strict['strict_preparation_status'] == 'prepared_clean' and strict['strict_phase_count'] == 9
    assert same_typed(strict['all_original_phase_returncodes'], [0] * 9) and strict['native_cases_in_this_packet'] == 0
    core = added['desktop_6ec_core_owning_history']
    assert core['status'] == 'PASS' and same_typed(core['counts'], {
        'selected_executed_unique': 3827, 'passed': 3827, 'failed': 0,
        'original_ignored': 9, 'retries': 0, 'leaks': 0, 'required_passed_subset': 4})
    app = added['desktop_6ec_appserver_failed_owning_history']
    assert app['status'] == 'FAIL' and app['driver_returncode'] == app['collect_returncode'] == 1
    assert app['test_returncode'] == 100 and same_typed(app['counts'], {
        'selected_executed_unique': 1348, 'passed': 1345, 'failed_exit101': 3,
        'original_ignored': 2, 'retries': 0, 'leaks': 0, 'required_passed_subset': 5})
    assert app['original_required_five_overall_passed_field'] is False and app['root_cause_all_failures'] is None
    agentd = added['desktop_6ec_agentd_root_owning_history']
    assert agentd['agentd_status'] == 'PASS' and same_typed(agentd['agentd_counts'], {
        'selected_executed_unique': 781, 'passed': 781, 'failed': 0, 'original_ignored': 71,
        'retries': 0, 'leaks': 0, 'required_checkpoint_passed_subset': 13})
    assert same_typed(agentd['Root_counts'], {'separate_ignored_parent_executed': 1, 'parent_passed': 1,
        'child_summaries_additional_acceptance': False})
    assert agentd['host_only_binary_count'] == 29 and agentd['binary_bytes_archived'] is False
    posthoc = added['desktop_6ec_posthoc_diagnostics_history']
    assert posthoc['new_native_tests'] == 0 and posthoc['appserver_original_status'] == 'FAIL'
    assert posthoc['all_appserver_failures_assigned_one_environment_cause'] is False
    publication = added['quiet_6ec_source_publication_history']
    assert publication['status'] == 'existing_frozen_source_normally_published_and_readback_verified'
    assert publication['actual_normal_push_count'] == 1 and publication['source_publication_claimed_by_this_observation'] is True
    assert publication['new_native_tests'] == 0 and publication['actions_count_at_original_observation'] == 0
    assert publication['actions_zero_is_not_CI_success'] is True and publication['workspace_v2_result_not_read_or_inferred'] is True
    observations = inputs['supplementary_observations']
    assert len(observations) == 19 and len({row['relative_path'] for row in observations}) == 19
    json_observation_paths = {
        'observations/evidence-increment008-publication-v1/RESULT.json',
        'observations/evidence-increment008-publication-v1/commands.json',
        'observations/evidence-increment008-independent-readback-v1/RESULT.json',
        'observations/evidence-increment008-independent-readback-v1/commands.json',
        'observations/core-output-6ec5993-desktop-dependency-strict-independent-verification-v1/RESULT.json',
        'observations/core-output-6ec5993-desktop-core-history-independent-verification-v1/RESULT.json',
        'observations/core-output-6ec5993-desktop-appserver-failed-history-independent-verification-v1/RESULT.json',
        'observations/core-output-6ec5993-desktop-agentd-root-history-independent-verification-v2/RESULT.json',
        'observations/core-output-6ec5993-desktop-posthoc-history-independent-verification-v1/RESULT.json',
        'observations/core-output-6ec5993-source-publication-history-independent-verification-v2/RESULT.json',
        'observations/core-output-6ec5993-source-publication-history-independent-verification-v1/RESULT.json',
        'observations/core-output-6ec5993-source-publication-history-independent-verification-v1/H_PTY_READ_ORIGINAL.json',
        'observations/desktop-6ec-source-publication-history-seal-launch-v1/RESULT.json',
        'observations/pr5397-status009-v6-publication-observation-v1.json',
    }
    original_text_observation_paths = {
        'observations/core-output-6ec5993-source-publication-history-independent-verification-v1/v1-to-v2.patch',
        'observations/verify-desktop-6ec-source-publication-history-v1.py',
        'observations/verify-desktop-6ec-source-publication-history-v2.py',
        'observations/desktop-6ec-source-publication-history-seal-launch-v1/stdout',
        'observations/desktop-6ec-source-publication-history-seal-launch-v1/stderr',
    }
    assert {row['relative_path'] for row in observations} == json_observation_paths | original_text_observation_paths
    assert inputs['supplementary_observation_scope']['source_commit'] == expected_head
    assert inputs['supplementary_observation_scope']['complete_stdout_stderr_prefixes_archived_here'] is False
    assert 'increment009a_supplementary_metadata_observations' not in index
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
        nul_bindings = {row['path']: row for row in packet.get('nul_delimited_git_stdout', [])}
        assert len(nul_bindings) == len(packet.get('nul_delimited_git_stdout', []))
        assert len(nul_bindings) == (13 if packet['packet_id'] == 'core-output-6ec5993-quiet-source-publication-history-v1' else 0)
        nul_seen, archived_command_records = set(), {}
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
                    if b'\0' in data:
                        assert member.name in nul_bindings, member.name
                        binding = nul_bindings[member.name]
                        assert len(data) == binding['bytes'] and module.sha(data) == binding['sha256']
                        producer = binding['producer']
                        assert producer['argv'][0] == 'git' and '-z' in producer['argv']
                        assert producer['stdout'] == {'bytes': len(data), 'sha256': module.sha(data)}
                        nul_seen.add(member.name)
                    if member.name in {row['commands_member'] for row in nul_bindings.values()}:
                        archived_command_records[member.name] = json.loads(data)
                    if member.name in required:
                        binding = required[member.name]
                        assert len(data) == binding['bytes'] and module.sha(data) == binding['sha256'], member.name
                        value = json.loads(data)
                        for check in binding['equals']:
                            actual = value
                            for key in check['path']:
                                actual = actual[key]
                            assert same_typed(actual, check['value']), (member.name, check['path'])
                        verified_bindings.add(member.name)
                    module.scan(packet['packet_id'] + '!/' + member.name, data, findings, inspected)
        assert len(members) == packet['file_member_count'], packet['packet_id']
        assert verified_bindings == set(required), packet['packet_id']
        assert nul_seen == set(nul_bindings)
        for row in nul_bindings.values():
            producer = row['producer']
            matches = [command for command in archived_command_records[row['commands_member']] if command['label'] == producer['command_label']]
            assert len(matches) == 1 and matches[0]['argv'] == producer['argv'] and matches[0]['stdout'] == producer['stdout']
        prepared.append((packet, original, members))
    assert len(prepared) == 6
    assert len(index['packets']) + len(prepared) == inputs['expected_final_packet_count'] == 93
    assert sum(row[0]['file_member_count'] for row in prepared) == 1004
    prepared_observations = []
    observation_objects = {}
    for observation in observations:
        relative = Path(observation['relative_path'])
        source = Path(observation['source_path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        assert observation['kind'] == ('original_json_observation' if relative.as_posix() in json_observation_paths else 'original_text_observation')
        assert source == records / relative.relative_to('observations')
        assert source.is_file() and not source.is_symlink() and source.stat().st_nlink == 1
        data = source.read_bytes()
        assert len(data) == observation['bytes'] and module.sha(data) == observation['sha256']
        assert len(data) <= 512000 and not (root / relative).exists()
        if relative.as_posix() in json_observation_paths:
            observation_objects[relative.as_posix()] = json.loads(data)
        else:
            data.decode('utf-8')
            assert b'\0' not in data
        module.scan('supplementary-observation!/' + relative.as_posix(), data, findings, inspected)
        prepared_observations.append((observation, data))
    pub_key = 'observations/evidence-increment008-publication-v1/'
    read_key = 'observations/evidence-increment008-independent-readback-v1/'
    pub, readback = observation_objects[pub_key + 'RESULT.json'], observation_objects[read_key + 'RESULT.json']
    observation_pins = {row['relative_path']: row['sha256'] for row in observations}
    assert pub['commit'] == readback['commit'] == expected_head
    assert pub['status'] == 'published_and_all_new_metadata_commit_blobs_remote_readback_verified'
    assert readback['status'] == 'independent_008_remote_and_exact_committed_metadata_readback_verified'
    assert pub['commands_receipt_sha256'] == observation_pins[pub_key + 'commands.json']
    assert readback['commands_sha256'] == observation_pins[read_key + 'commands.json']
    assert readback['publication_receipt_sha256'] == observation_pins[pub_key + 'RESULT.json']
    assert readback['publication_commands_sha256'] == observation_pins[pub_key + 'commands.json']
    assert readback['new_metadata_observations_complete_in_index_and_commit'] == 33
    assert pub['packet_count'] == readback['packet_count'] == 87
    assert pub['published_file_count'] == readback['published_actual_committed_files'] == 1348
    assert pub['manifest_sha256'] == readback['manifest_sha256'] == initial_index_sha256
    for key in (pub_key, read_key):
        commands = observation_objects[key + 'commands.json']
        assert commands and all(type(row.get('exit_code')) is int and row['exit_code'] == 0 for row in commands)
    for row in observations:
        assert row['bytes'] >= 0 and len(row['sha256']) == 64
    verifier_failure = observation_objects['observations/core-output-6ec5993-source-publication-history-independent-verification-v1/RESULT.json']
    assert verifier_failure['observed_python_subprocess_returncode'] == 1 and verifier_failure['native_tests'] == 0
    assert observation_objects['observations/core-output-6ec5993-source-publication-history-independent-verification-v2/RESULT.json']['returncode'] == 0
    pr = observation_objects['observations/pr5397-status009-v6-publication-observation-v1.json']
    assert pr['body_bytes'] == 9876 and pr['body_sha256'] == '9fd94488525dfc61aecbf8fd7b0cc94d461107d7d2a413ec95232ee15698d5d0'
    assert pr['body_exactly_equal'] is True and pr['draft'] is True and pr['head_unchanged'] is True
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
    index['increment009a_supplementary_metadata_observations'] = [
        {'path': row['relative_path'], 'bytes': row['bytes'], 'sha256': row['sha256']}
        for row in observations
    ]
    index['increment009a_supplementary_metadata_scope'] = inputs['supplementary_observation_scope']
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
    assert index['packets'][:87] == original_index['packets']
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
              'original_87_packet_index_entries_unchanged': True,
              'common_before': common_before, 'common_after': common_after,
              'required_json_bindings_verified': True,
              'original_87_packet_and_all_existing_nonmanifest_file_bytes_unchanged': True,
              'supplementary_observations': index['increment009a_supplementary_metadata_observations'],
              'supplementary_observation_scope': inputs['supplementary_observation_scope'],
              'supplementary_original_result_commands_links_verified': True,
              'new_metadata_still_requires_index_and_commit_blob_verification_at_publication': True,
              'new_tests_executed': False,
              'full_history_cost': None, 'stage_advancement_claimed': False}
    (out / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
