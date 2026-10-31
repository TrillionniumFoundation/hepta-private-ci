"""Assemble the final evidence catalog from validated, immutable run receipts.

This report-only helper neither fits a model nor reruns native inference. Large
published archive copies may already be evicted locally; their recorded Git blob
identities must then agree with the separately obtained remote-tree readback.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from .. import freeze
from .package_evidence import sha


PREFIX = 'experiments/analytic_event_neuron/round3/evidence/'
PART_BYTES = 8 * 1024 * 1024
SEEDS = [607, 701, 809, 907, 1009]
LAWS = ['gaussian', 'drift_shift', 'student_t']
GROUPS = {
    'preconfirmation': ['CORE_PREPARED', 'CALIBRATION_PREPARED'] + [f'FEEDBACK_PREPARED_{s}' for s in SEEDS],
    'calibration': [f'CALIBRATION_CONFIRMATION_{s}' for s in SEEDS],
    'feedback-runtime': ['RUNTIME_CONFIRMATION'] + [f'FEEDBACK_CONFIRMATION_{s}' for s in SEEDS],
    'main': [f'MAIN_seed_{s}_{law}' for s in SEEDS for law in LAWS],
    'main-operational': ['main_seed_1009_gaussian_attempt1'],
    'main-analysis': ['MAIN_ANALYSIS'],
    'development': ['DEVELOPMENT_AND_FAILED_ATTEMPTS'],
    'report': ['RUN_REPORTS'],
}


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def safe(relative):
    require(isinstance(relative, str) and relative and '\\' not in relative,
            'A nonempty POSIX-relative path is required')
    path = PurePosixPath(relative)
    require(bool(path.parts) and not path.is_absolute() and '..' not in path.parts and '.' not in path.parts
            and str(path) == relative, 'Noncanonical or escaping path: ' + relative)
    return relative


def digest_format(value, length=64):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(length) + '}', value),
            'Invalid digest encoding')


def positive_integer(value):
    require(type(value) is int and value > 0, 'Expected a positive integer')


def validate_descriptor(item, group):
    name = item['name']
    require(name in GROUPS[group], 'Unexpected logical archive: ' + name)
    digest_format(item['sha256'])
    positive_integer(item['bytes'])
    positive_integer(item['data_members'])
    require(item.get('all_member_hashes_verified') is True
            and item.get('scientific_data_regenerated') is False, 'Unverified or regenerated archive')
    expected_root = 'run/main/unpacked/' + name.removeprefix('MAIN_') if group == 'main' else 'run'
    require(safe(item['restore_root']) == expected_root, 'Incorrect restore root')
    expected_manifest = 'ARCHIVE_MANIFEST.json' if group == 'main' else '_bundle_manifests/' + name + '.json'
    require(safe(item['member_manifest']) == expected_manifest, 'Incorrect member manifest')
    require(('path' in item) != ('parts' in item), 'Archive must have exactly one physical representation')
    folder = 'preconfirmation' if group == 'preconfirmation' else ('operational' if group == 'main-operational' else 'confirmation')
    stem = PREFIX + folder + '/' + name + '.tar.gz'
    physical = item.get('parts') or [item]
    if 'parts' in item:
        require(isinstance(item['parts'], list) and len(item['parts']) >= 2, 'Invalid byte partition list')
    for number, part in enumerate(physical):
        positive_integer(part['bytes']); digest_format(part['sha256'])
        wanted = stem + f'.part{number:03d}' if 'parts' in item else stem
        require(safe(part['path']) == wanted, 'Physical archive paths or part order differ')
        require(part['bytes'] <= PART_BYTES, 'Physical blob exceeds the registered partition size')
        if 'parts' in item and number < len(physical) - 1:
            require(part['bytes'] == PART_BYTES, 'Nonfinal byte partition has the wrong size')
    require(sum(p['bytes'] for p in physical) == item['bytes'], 'Partition bytes do not sum to archive bytes')
    return [{k: p[k] for k in ('path', 'bytes', 'sha256')} for p in physical]


def main_bindings(root, repo, archives, source_commit):
    index = read(root / 'main/RUN_INDEX.json')
    require(index['complete'] is True and index['source_commit'] == source_commit, 'Incomplete main index')
    expected = {(s, law) for s in SEEDS for law in LAWS}
    actual = [(e['seed'], e['law']) for e in index['scopes']]
    require(len(actual) == 15 and set(actual) == expected, 'Main seed/law coverage differs')
    rows = []
    for entry in index['scopes']:
        scope = f"seed_{entry['seed']}_{entry['law']}"
        require(entry['scope'] == scope and entry['audit_passed'] is True, 'Invalid main scope binding')
        archive = archives['MAIN_' + scope]
        require(entry['archive_receipt']['sha256'] == archive['sha256']
                and entry['archive_receipt']['compressed_bytes'] == archive['bytes']
                and entry['archive_receipt']['file_count'] == archive['data_members'] + 1
                and entry['archive_receipt']['all_member_hashes_verified'] is True, 'Main archive/index binding differs')
        review_path = root / 'independent_main_review' / (scope + '.json')
        review = read(review_path)
        require(sha(review_path) == archive['independent_review_sha256'], 'Independent review changed')
        require(review['passed'] is True and review['scope'] == scope
                and review['source_commit'] == source_commit and review['seed'] == entry['seed']
                and review['law'] == entry['law'] and review['archive_sha256'] == archive['sha256']
                and review['analysis_sha256'] == entry['analysis_sha256']
                and review['archive_members'] == archive['data_members'] + 1,
                'Main review/index/archive binding differs')
        digest_format(entry['analysis_sha256']); safe(entry['analysis'])
        analysis_path = root / entry['analysis']
        if analysis_path.exists():
            require(sha(analysis_path) == entry['analysis_sha256'], 'Main analysis bytes changed')
        audit_path = root / 'main/reports' / scope / 'AUDIT.json'
        audit = read(audit_path)
        require(audit['passed'] is True and audit['full_frozen_inference_replay'] is True
                and audit['frozen_model_binding'] is True and audit['native_replay_accounting']['requests'] > 0
                and audit['native_replay_accounting']['ticks'] > 0, 'Frozen/native replay not established')
        require(review['unique_trajectories'] == entry['unique_trajectories'] == audit['unique_trajectories'] == 384,
                'Main trajectory count differs')
        rows.append({'scope': scope, 'archive_sha256': archive['sha256'],
            'analysis_sha256': entry['analysis_sha256'], 'independent_review_sha256': sha(review_path),
            'frozen_audit_sha256': sha(audit_path), 'archive_data_members': archive['data_members'],
            'archive_members_including_manifest': review['archive_members'],
            'frozen_native_replay_requests': audit['native_replay_accounting']['requests'],
            'frozen_native_replay_ticks': audit['native_replay_accounting']['ticks']})
    final_path = repo / (PREFIX + 'MAIN_CONFIRMATION_REVIEW.json')
    final = read(final_path)
    require(final['passed'] is True and final['source_commit'] == source_commit and final['scopes'] == 15
            and final['archive_members'] == sum(x['archive_members_including_manifest'] for x in rows)
            and final['main_results_sha256'] == sha(root / 'MAIN_RESULTS.json'), 'Final main review binding differs')
    return {'run_index_sha256': sha(root / 'main/RUN_INDEX.json'), 'all_15_independent_member_reviews_passed': True,
        'all_15_frozen_model_and_native_replays_passed': True,
        'native_inference_rerun_by_manifest_assembler': False,
        'final_independent_review_path': PREFIX + 'MAIN_CONFIRMATION_REVIEW.json',
        'final_independent_review_sha256': sha(final_path), 'scopes': rows}


def failed_attempt_binding(root, archives, frozen):
    recovery_path = root / 'MAIN_OPERATIONAL_RECOVERY.json'
    recovery = read(recovery_path)
    identity_path = root / 'MAIN_RESUME1_IDENTITY.json'
    identity = read(identity_path)
    require(recovery['archive'] == archives['main_seed_1009_gaussian_attempt1']
            and recovery['source_commit'] == frozen['source_commit']
            and recovery['freeze_sha256'] == sha(root / 'FREEZE.json')
            and recovery['all_original_failed_files_retained'] is True
            and recovery['archive_verified_before_deleting_uncompressed_failed_attempt'] is True
            and recovery['original_file_count'] + 4 == recovery['archive']['data_members'],
            'Failed attempt evidence binding differs')
    require(identity['operational_recovery_sha256'] == sha(recovery_path)
            and identity['all_original_data_and_model_identities_exact'] is True
            and identity['original'] == identity['observed'] == recovery['data_identity']
            and identity['new_independent_sample'] is False and recovery['new_independent_sample'] is False
            and recovery['included_in_utility_estimation'] is False
            and recovery['scientific_source_models_seeds_or_gates_changed'] is False,
            'Operational retry identity binding differs')
    require(all(recovery['failed_attempt_costs'][key] is None for key in
                ('child_cpu_ns', 'native_requests', 'native_ticks', 'parent_cpu_ns', 'wall_ns')),
            'Failed attempt full-cost status differs')
    return {'archive': recovery['archive']['name'], 'original_failed_files': recovery['original_file_count'],
        'operational_metadata_members': 4, 'failed_attempt_included_as_new_independent_sample': False,
        'recovery_receipt_restored_path': 'run/MAIN_OPERATIONAL_RECOVERY.json',
        'recovery_receipt_sha256': sha(recovery_path),
        'retry_identity_receipt_restored_path': 'run/MAIN_RESUME1_IDENTITY.json',
        'retry_identity_receipt_sha256': sha(identity_path),
        'same_data_model_and_trajectory_identities': True,
        'failed_attempt_full_cost_is_unknown_not_zero': True}


def restoration_bindings(root, archives, frozen):
    rows = []
    source_commit = frozen['source_commit']

    def receipt(relative):
        data = read(root / relative)
        require(data['passed'] is True and data.get('scientific_data_regenerated') is False, 'Restoration failed or regenerated data')
        require(data.get('source_commit', source_commit) == source_commit, 'Restoration source binding differs')
        return data

    def add(name, relative, standalone=False):
        row = {'archive': name, 'data_members': archives[name]['data_members'],
               'actual_safe_disk_extraction_verified': True}
        if standalone:
            row.update(receipt_repository_path=PREFIX + 'results/restoration/RUN_REPORTS_RESTORE.json',
                       receipt_published_after_report_snapshot=True,
                       receipt_digest_intentionally_not_embedded_to_avoid_recursive_publication_bindings=True)
        else:
            row.update(receipt_restored_path='run/' + safe(relative), receipt_sha256=sha(root / relative))
        rows.append(row)

    relative = 'reviews/PREPARED_RESTORATION.json'
    prepared = receipt(relative)
    require(prepared['frozen_prepared_artifacts_restored_and_verified'] == 329
            and prepared['frozen_sources_verified'] == 83 and prepared['source_and_original_prepared_bytes_unchanged'] is True,
            'Prepared restoration counts or identity differ')
    core_log = root / 'operational_logs/aen-r3-core-restore.log'
    require(sha(core_log) == prepared['core_and_calibration_restore_log_sha256'], 'Prepared core restore log changed')
    core_rows = [json.loads(line) for line in core_log.read_text().splitlines() if line.strip()]
    core_rows = [row for row in core_rows if 'archive' in row]
    require({r['archive'] for r in core_rows} == {'CORE_PREPARED', 'CALIBRATION_PREPARED'}
            and len(core_rows) == 2, 'Core restore log coverage differs')
    for row in core_rows:
        a = archives[row['archive']]
        require(row['sha256'] == a['sha256'] and row['data_files'] == a['data_members']
                and row['member_hashes_verified'] is True and row['restored'] is True, 'Core archive was not restored')
        add(row['archive'], relative)
    feedback_prepared = prepared['feedback_preparation_archives']
    require({r['name'] for r in feedback_prepared} == {f'FEEDBACK_PREPARED_{s}' for s in SEEDS}
            and len(feedback_prepared) == 5, 'Feedback prepared restoration coverage differs')
    for row in feedback_prepared:
        a = archives[row['name']]
        require(row['archive_sha256'] == a['sha256'] and row['restored_files'] == a['data_members']
                and row['exact_published_part_bytes_verified'] is True, 'Prepared feedback restoration binding differs')
        add(row['name'], relative)
    relative = 'reviews/CALIBRATION_RESTORATION.json'
    calibration = receipt(relative)
    require(calibration['archives_verified'] == 5 and len(calibration['archives']) == 5
            and {r['archive'] for r in calibration['archives']} == set(GROUPS['calibration']), 'Calibration restoration coverage differs')
    for row in calibration['archives']:
        a = archives[row['archive']]
        require(row['archive_sha256'] == a['sha256'] and row['actual_disk_extraction_performed'] is True
                and row['data_files_restored_and_sha256_verified'] == a['data_members']
                and row['temporary_restored_copy_removed_after_verification'] is True, 'Calibration actual restore binding differs')
        add(row['archive'], relative)
    for name in GROUPS['feedback-runtime']:
        relative = 'archival_reviews/' + name + '_RESTORE.json'
        data = receipt(relative); a = archives[name]
        require(data['restored'] is True and data['archive_sha256'] == a['sha256']
                and data['archive_bytes'] == a['bytes'] and data['data_members'] == a['data_members']
                and data['source_manifest_matches_completed_phase_index'] is True
                and data['file_bytes_and_modes_match_original'] is True, 'Feedback/runtime actual restore binding differs')
        phase = 'RUNTIME' if name == 'RUNTIME_CONFIRMATION' else 'FEEDBACK'
        index = read(root / (phase + '_INDEX.json'))
        selected = index['scopes'] if phase == 'RUNTIME' else [s for s in index['scopes'] if s['seed'] == int(name.rsplit('_', 1)[1])]
        expected = {p: digest for s in selected for p, digest in s['files_sha256'].items()}
        require(index['complete'] is True and index['source_commit'] == source_commit
                and data['restored_file_hashes'] == expected, 'Restored feedback/runtime file inventory differs')
        add(name, relative)
    for name, relative in [('MAIN_ANALYSIS', 'archival_reviews/MAIN_ANALYSIS_RESTORE_AND_RECOMPUTE.json'),
                           ('DEVELOPMENT_AND_FAILED_ATTEMPTS', 'archival_reviews/DEVELOPMENT_AND_FAILED_ATTEMPTS_RESTORE.json')]:
        data = receipt(relative)
        require(data['archive'] == archives[name] and data['all_member_bytes_exact'] is True
                and data['all_member_modes_exact'] is True, 'Actual restoration descriptor or bytes differ')
        if name == 'MAIN_ANALYSIS':
            require(data['restored_members'] == archives[name]['data_members']
                    and data['recompute']['returncode'] == 0 and data['recompute']['result_bytes_exact'] is True
                    and data['recompute']['restored_result_sha256'] == sha(root / 'MAIN_RESULTS.json'), 'Restored statistics differ')
        else:
            require(data['actual_safe_restore_performed'] is True and data['restored_data_members'] == archives[name]['data_members'],
                    'Development archive was not physically restored')
        add(name, relative)
    relative = 'archival_reviews/MAIN_FULL_SCOPE_RESTORE.json'
    full = receipt(relative); name = 'MAIN_' + full['scope']; a = archives[name]
    require(name in GROUPS['main'] and full['actual_safe_restore_performed'] is True
            and full['archive_sha256'] == a['sha256'] and full['archive_bytes'] == a['bytes']
            and full['data_members_excluding_manifest'] == a['data_members']
            and full['all_extracted_files_including_manifest'] == a['data_members'] + 1
            and full['all_member_bytes_exact'] is True and full['all_member_modes_exact'] is True
            and full['representative_full_scope_actual_extractions'] == 1
            and full['all_registered_main_scopes_actually_extracted_by_this_check'] is False
            and full['independent_review_sha256'] == a['independent_review_sha256'], 'Representative MAIN restoration binding differs')
    add(name, relative)
    relative = 'archival_reviews/RUN_REPORTS_RESTORE.json'
    data = receipt(relative); a = archives['RUN_REPORTS']
    require(data['archive'] == a['name'] and data['archive_sha256'] == a['sha256']
            and data['compressed_bytes'] == a['bytes'] and data['data_members'] == a['data_members']
            and data['ordinary_files_actually_extracted'] is True and data['file_bytes_and_modes_match_original'] is True
            and data['snapshot_excludes_its_own_restore_receipt_and_later_manifest_qa_publication_receipts'] is True,
            'Report snapshot restoration binding differs')
    add('RUN_REPORTS', relative, standalone=True)
    require(len(rows) == 22 and len({r['archive'] for r in rows}) == 22, 'Actual extraction coverage differs')
    return {'actual_disk_extraction_tested_logical_bundles': 22, 'registered_logical_bundles': 37,
        'representative_main_full_scopes_extracted': 1, 'registered_main_full_scopes': 15,
        'all_main_scopes_member_hashes_checked_and_frozen_native_replayed': True,
        'archive_restoration_regenerated_scientific_data': False,
        'operational_retry_distinction': 'The separate recorded MAIN operational retry reran the deterministic generator and produced identical DATA/model bytes; archive restoration did not regenerate data.',
        'outer_bundle_extraction_does_not_claim_recursive_extraction_of_every_nested_archive': True,
        'frozen_prepared_artifacts_verified': 329, 'prepared_outer_data_members': 331,
        'prepared_additional_metadata_members': 2,
        'core_restore_log_restored_path': 'run/operational_logs/aen-r3-core-restore.log',
        'core_restore_log_sha256': sha(core_log), 'core_restore_records': core_rows,
        'actual_restore_receipts': rows,
        'full_bundles_not_separately_disk_extracted_in_this_restore_exercise': sorted(set(archives) - {r['archive'] for r in rows}),
        'restored_main_statistics_byte_identical': True}


def assemble(run_dir, repo, descriptor_dir, output):
    root, repo, descriptor_dir, output = map(lambda p: Path(p).resolve(), (run_dir, repo, descriptor_dir, output))
    require(output.is_relative_to(repo / PREFIX), 'Output must remain inside Round 3 evidence')
    require(not output.exists(), 'Refusing to replace a previously assembled manifest')
    frozen = freeze.verify(root)
    require(len(frozen['sources_sha256']) == 83 and len(frozen['artifacts_sha256']) == 329, 'Frozen inventory counts differ')
    digest_format(frozen['source_commit'], 40); digest_format(frozen['base_commit'], 40)
    protocol_path = repo / 'experiments/analytic_event_neuron/round3/PROTOCOL.json'
    protocol = read(protocol_path)
    require(protocol['training_seeds'] == SEEDS and [protocol['laws']['primary'], *protocol['laws']['mismatch']] == LAWS
            and protocol['base_commit'] == frozen['base_commit'] and sha(protocol_path) == frozen['protocol_sha256'], 'Registration differs')
    archives, physical, sources, summaries = {}, [], [], {}
    for group, expected_names in GROUPS.items():
        path = descriptor_dir / ('aen-r3-' + group + '-archives.json')
        data = read(path)
        if isinstance(data, dict):
            require(data['source_commit'] == frozen['source_commit'], 'Descriptor source differs')
            items = data['archives']
        else:
            items = data
        require(len(items) == len(expected_names) and {a['name'] for a in items} == set(expected_names), 'Logical archive coverage differs: ' + group)
        parts = []
        for item in items:
            require(item['name'] not in archives, 'Duplicate logical archive')
            parts.extend(validate_descriptor(item, group)); archives[item['name']] = item
        physical.extend(parts)
        sources.append({'descriptor_filename': path.name, 'sha256': sha(path), 'logical_archives': len(items)})
        summaries[group] = {'logical_archives': len(items), 'physical_files': len(parts),
            'compressed_logical_archive_bytes': sum(a['bytes'] for a in items),
            'physical_file_bytes': sum(p['bytes'] for p in parts),
            'outer_data_members_excluding_manifests': sum(a['data_members'] for a in items),
            'outer_manifest_members': len(items), 'names': expected_names}
    require(len(archives) == 37 and len({p['path'] for p in physical}) == len(physical), 'Duplicate physical paths or wrong bundle count')
    state = read(descriptor_dir / 'aen-r3-publication-state.json')
    remote_path = descriptor_dir / 'aen-r3-remotely-verified-archives.json'
    remote = read(remote_path)
    local_count = remote_count = 0
    for part in physical:
        path = repo / part['path']; git_blob = state['blobs'].get(part['path'])
        verified_git_blob = remote['blobs'].get(part['path'])
        if verified_git_blob is not None:
            digest_format(verified_git_blob, 40)
            require(git_blob == verified_git_blob, 'Publication state and remote-tree proof differ')
            part.update(git_blob_sha1=git_blob, present_in_verified_remote_tree=True)
            remote_count += 1
        else:
            require(part['path'].endswith('/RUN_REPORTS.tar.gz') and path.is_file(), 'Unpublished or unproven physical archive')
            part['present_in_verified_remote_tree'] = False
        if path.exists():
            require(path.resolve().is_relative_to(repo) and path.is_file() and not path.is_symlink() and path.stat().st_size == part['bytes']
                    and sha(path) == part['sha256'], 'Local physical archive bytes differ')
            if git_blob is not None:
                h = hashlib.sha1(('blob ' + str(part['bytes']) + '\0').encode())
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
                require(h.hexdigest() == git_blob, 'Local bytes and recorded Git blob differ')
            part['local_sha256_verified_during_assembly'] = True; local_count += 1
        else:
            require(verified_git_blob is not None, 'Locally absent archive lacks a remote identity proof')
            part['local_sha256_verified_during_assembly'] = False
    main = main_bindings(root, repo, archives, frozen['source_commit'])
    restores = restoration_bindings(root, archives, frozen)
    logical_bytes = sum(a['bytes'] for a in archives.values())
    require(logical_bytes == sum(p['bytes'] for p in physical), 'Logical/physical byte totals differ')
    result = {'schema': 'hepta.analytic-event.round3.evidence-manifest.v1',
        'created_utc': datetime.now(timezone.utc).isoformat(), 'source_commit': frozen['source_commit'],
        'base_commit': frozen['base_commit'], 'protocol_sha256': frozen['protocol_sha256'],
        'freeze_sha256': sha(root / 'FREEZE.json'), 'freeze_repository_path': PREFIX + 'FREEZE.json',
        'frozen_inventory': {'scientific_source_files': 83, 'prepared_artifacts': 329,
            'all_current_source_and_prepared_bytes_verified': True,
            'binding_source': 'sources_sha256 and artifacts_sha256 in the immutable FREEZE.json'},
        'descriptor_inputs': sources, 'archives': list(archives.values()), 'archive_groups': summaries,
        'physical_files': physical,
        'summary': {'logical_archives': len(archives), 'physical_files': len(physical),
            'compressed_logical_archive_bytes': logical_bytes, 'physical_file_bytes': sum(p['bytes'] for p in physical),
            'outer_data_members_excluding_manifests': sum(a['data_members'] for a in archives.values()),
            'outer_manifest_members': len(archives),
            'outer_regular_members_including_manifests': sum(a['data_members'] + 1 for a in archives.values()),
            'main_data_members_excluding_manifests': summaries['main']['outer_data_members_excluding_manifests'],
            'main_members_including_manifests': summaries['main']['outer_data_members_excluding_manifests'] + 15,
            'counting_scope': 'Outer archive entries, with one manifest per logical bundle. Nested archive members are not recursively added. Repeated paths across bundles are not deduplicated. Members, model outputs, controls and horizons are not independent sample counts.'},
        'main_review_bindings': main, 'failed_main_attempt_binding': failed_attempt_binding(root, archives, frozen),
        'restoration_verification': restores,
        'publication_snapshot': {'verified_remote_commit_before_final_publication': remote['head'],
            'verified_remote_tree': remote['tree'], 'remote_readback_proof_sha256': sha(remote_path),
            'physical_files_in_that_verified_tree': remote_count,
            'physical_files_rehashed_locally_during_manifest_assembly': local_count,
            'local_absence_permitted_only_with_recorded_remote_git_identity': True,
            'remote_github_requests_performed_by_manifest_assembler': False,
            'final_all_file_publication_verification_is_a_separate_receipt': True},
        'post_snapshot_standalone_receipts': [
            {'repository_path': PREFIX + 'results/restoration/RUN_REPORTS_RESTORE.json', 'status_at_assembly': 'actual_restore_passed; standalone_receipt_excluded_from_report_snapshot'},
            {'repository_path': PREFIX + 'results/reviews/FINAL_REPORT_QA.json', 'status_at_assembly': 'issued_after_manifest; no recursive hash binding'},
            {'repository_path': PREFIX + 'FINAL_PUBLICATION_RECEIPT.json', 'status_at_assembly': 'issued_after_publication; no recursive hash binding'}],
        'restore_tool': 'experiments/analytic_event_neuron/round2/restore_evidence.py',
        'restore_tool_sha256': sha(repo / 'experiments/analytic_event_neuron/round2/restore_evidence.py'),
        'assembler_repository_path': PREFIX + 'assemble_manifest.py', 'assembler_sha256': sha(Path(__file__)),
        'scientific_data_regenerated_by_assembly_or_archive_restoration': False,
        'production_promotion': False, 'all_manifest_integrity_checks_passed': True}
    freeze.verify(root)
    with output.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2); stream.write('\n')
    return {'path': str(output), 'sha256': sha(output), 'summary': result['summary'],
            'actual_restore_bundles': restores['actual_disk_extraction_tested_logical_bundles']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=Path('/tmp/aen-round3-20261028'))
    parser.add_argument('--repo', type=Path, default=freeze.REPO)
    parser.add_argument('--descriptor-dir', type=Path, default=Path('/tmp'))
    parser.add_argument('--output', type=Path, default=freeze.PROJECT / 'evidence/EVIDENCE_MANIFEST.json')
    args = parser.parse_args()
    print(json.dumps(assemble(args.run_dir, args.repo, args.descriptor_dir, args.output), sort_keys=True))
