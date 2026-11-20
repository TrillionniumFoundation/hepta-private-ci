"""Prepare a finite, local evidence intake; never pack, publish or run a host.

The resulting index is an observation of the listed existing files, not the final
archive plan.  Future continuation/format/compile inputs remain explicit slots.
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import json
import stat
import tarfile
from pathlib import Path


ROOT = Path('/workspace/scratch/e9e051ab0825')
INTAKE = ROOT / 'metrics_integration/execution-readout-intake-diagnostic-6'
OUT = INTAKE / 'input-index-preparation-1'
RECOVERY = 'e6_owner_work/historical_startup_recovery'
ARCHIVE_ROOT = ROOT / 'e6_c_generation_cloud_archive_1'
BASELINE_PATH = ROOT / 'metrics_integration/final_evidence_publication_work/FROZEN_557_FILES.json'
EXPECTED_BASELINE_SHA = 'a740c2f0d1ccd1d7e78d506db436778d230cc984de1aefc4f86c71eae3367a44'


def identity(data: bytes) -> dict:
    return {
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
    }


def key(row: dict) -> tuple:
    return row['bytes'], row['sha256'], row['git_blob']


def same_identity(a: dict, b: dict) -> bool:
    return all(a[k] == b[k] for k in ('bytes', 'sha256', 'git_blob'))


def read_file(path: Path) -> tuple[bytes, dict]:
    path = path.absolute()
    path.relative_to(ROOT)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f'nonregular input: {path}')
    data = path.read_bytes()
    after = path.lstat()
    sig = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if sig(before) != sig(after) or len(data) != before.st_size:
        raise ValueError(f'input changed while read: {path}')
    return data, {
        'workspace_path': str(path.relative_to(ROOT)),
        **identity(data),
        'local_stat': {
            'device': before.st_dev, 'inode': before.st_ino,
            'bytes': before.st_size, 'mtime_ns': before.st_mtime_ns,
            'ctime_ns': before.st_ctime_ns,
        },
    }


def get_json(path: Path):
    raw, pin = read_file(path)
    return json.loads(raw), pin


def write_json(name: str, value) -> None:
    with (OUT / name).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def main() -> None:
    OUT.mkdir(exist_ok=False)
    baseline, baseline_pin = get_json(BASELINE_PATH)
    assert baseline_pin['sha256'] == EXPECTED_BASELINE_SHA
    assert len(baseline) == 557
    assert len({r['path'] for r in baseline}) == 557
    assert all(r['git_blob'] == r['server_sha'] for r in baseline)
    baseline_by_key = collections.defaultdict(list)
    for row in baseline:
        baseline_by_key[key(row)].append(row)

    original_docs = [
        'metrics_integration/EXECUTION_READOUT_20261120.md',
        'metrics_integration/execution-readout-publication/evidence/e1e6-execution-readout-20261120/EXECUTION_READOUT_20261120.md',
        'metrics_integration/execution-readout-publication/evidence/e1e6-execution-readout-20261120/REFERENCE_MANIFEST.json',
        'metrics_integration/final_evidence_publication_work/FROZEN_535_FILES.json',
        str(BASELINE_PATH.relative_to(ROOT)),
    ]
    protected_before = {n: read_file(ROOT / n)[1] for n in original_docs}

    selected: dict[str, dict] = {}
    exclusions = []
    manifest_checks = []
    input_groups = []

    def add(path: Path, group: str, role: str, expected: dict | None = None) -> None:
        raw, pin = read_file(path)
        if expected is not None:
            assert pin['bytes'] == expected['bytes']
            assert pin['sha256'] == expected['sha256']
            if 'git_blob' in expected:
                assert pin['git_blob'] == expected['git_blob']
        item = selected.setdefault(pin['workspace_path'], {**pin, 'groups': [], 'roles': []})
        assert same_identity(item, pin)
        if group not in item['groups']:
            item['groups'].append(group)
        if role not in item['roles']:
            item['roles'].append(role)

    def manifest_group(dirname: str, group: str, extras: tuple[str, ...] = ()) -> None:
        directory = ROOT / dirname
        doc, pin = get_json(directory / 'MANIFEST.json')
        add(directory / 'MANIFEST.json', group, 'original_frozen_manifest')
        for row in doc['files']:
            rel = Path(row['path'])
            assert not rel.is_absolute() and '..' not in rel.parts
            add(directory / rel, group, 'original_manifest_member', row)
        for name in extras:
            add(directory / name, group, 'subsequent_root_review_outside_original_manifest')
        manifest_checks.append({'group': group, 'manifest': pin, 'members_verified': len(doc['files'])})
        input_groups.append({'id': group, 'selection': 'original_manifest_members_plus_named_extras',
                             'root': dirname, 'extras': list(extras)})

    def finite_tree(dirname: str, group: str, status: str) -> None:
        directory = ROOT / dirname
        paths = sorted(p for p in directory.rglob('*') if p.is_file() or p.is_symlink())
        for path in paths:
            if '__pycache__' in path.parts or path.suffix == '.pyc':
                exclusions.append({'path': str(path.relative_to(ROOT)), 'reason': 'generated_python_bytecode_not_an_input'})
                continue
            add(path, group, status)
        input_groups.append({'id': group, 'selection': 'finite_list_observed_under_named_completed_directory',
                             'root': dirname, 'meaning': status, 'atomic_directory_snapshot_claimed': False})

    manifest_group('e6_startup_policy_candidate_1', 'startup_policy_1', ('ROOT_FROZEN_POLICY_REVIEW.json',))
    manifest_group('e6_startup_policy_candidate_2', 'startup_policy_2', ('ROOT_QA_FORMAT_REVIEW.json',))
    manifest_group('e6_noupdate13_startup_policy_peer_1', 'startup_policy_peer')
    manifest_group('e6_noupdate13_startup_candidate_peer_1', 'startup_product_peer')
    manifest_group('e6_noupdate13_startup_lane_review_1', 'startup_lane_diagnosis')
    manifest_group('e6_dependency_material_recovery_peer_1', 'material_controller_peer')
    finite_tree('e6_owner_work/historical_startup_candidate/rev1', 'startup_product_1', 'static_product_candidate_and_exact_before_sources')
    finite_tree('e6_owner_work/historical_startup_candidate/rev2', 'startup_qa_initial_draft', 'unexecuted_initial_qa_draft_retained')
    for version in (1, 2, 3):
        finite_tree(f'{RECOVERY}/rev{version}', f'recovery_preflight_{version}', 'actual_bounded_metadata_preflight_and_original_readback')
    finite_tree(f'{RECOVERY}/primary_cargo', 'cargo_primary_source_support', 'previously_retrieved_primary_source_support_no_new_network')
    for version in (1, 2):
        finite_tree(f'{RECOVERY}/material_plan_{version}', f'material_controller_design_{version}',
                    'historical_design_and_existing_offline_mechanism_evidence_no_host_material_qualification')
    finite_tree(f'{RECOVERY}/material_plan_3', 'material_attempt_1',
                'actual_failed_material_attempt_plus_controller_readbacks_and_existing_offline_controls')
    finite_tree('e6_owner_work/historical_startup_format/rev1', 'format_template_only',
                'reviewed_template_no_actual_format_execution_in_this_intake')
    for name in ['PUBLICATION_FILES.json', 'ROOT_PUBLICATION_REVIEW.json']:
        add(ARCHIVE_ROOT / name, 'existing_1a_archive_publication', 'existing_archive_and_root_independent_review')
    old_intake, old_intake_pin = get_json(
        INTAKE / 'history-before-material-attempt1-intake/REFERENCE_INTAKE_PENDING.json'
    )
    for row in old_intake['references']:
        add(Path(row['local_path']), 'prior_intake6_references', 'previous_unfinalized_primary_reference', row)

    # The 1a finite archive is already verified and uploaded as 22 objects.
    # Reuse only an exact body identity; storage reuse never carries qualification.
    logical, logical_pin = get_json(ARCHIVE_ROOT / 'publication/INPUT_MANIFEST.json')
    archive_parts, archive_parts_pin = get_json(ARCHIVE_ROOT / 'publication/archive-parts.json')
    dependencies, dependency_pin = get_json(ARCHIVE_ROOT / 'publication/DEPENDENCIES.json')
    archive_files = {'1a979-finite': {
        'local_archive': str(ARCHIVE_ROOT / 'pack-1/cloud-1a979-finite-originals.tar.xz'),
        'identity': {k: archive_parts[k] for k in ('bytes', 'sha256', 'git_blob')},
        'parts_index': archive_parts_pin,
    }}
    for archive in dependencies['archives']:
        archive_files[archive['id']] = {
            'local_archive': archive['local_archive'],
            'identity': {k: archive[k] for k in ('bytes', 'sha256', 'git_blob')},
            'part_index_repository_file': archive['part_index_repository_file'],
        }
    archive_by_key = collections.defaultdict(list)
    for row in logical['files']:
        storage = row['storage']
        if storage['kind'] == 'new_archive_object':
            archive_by_key[key(row)].append({'archive_id': '1a979-finite', 'member': storage['member']})
        elif storage['kind'] == 'existing_archive_member':
            archive_by_key[key(row)].append({'archive_id': storage['archive_id'], 'member': storage['member']})

    used_repository = {}
    used_archive_members = collections.defaultdict(dict)
    new_object_keys = collections.defaultdict(list)
    for row in selected.values():
        k = key(row)
        if k in baseline_by_key:
            candidate = sorted(baseline_by_key[k], key=lambda x: x['path'])[0]
            if candidate['path'] not in used_repository:
                _, observed = read_file(Path(candidate['local_path']))
                assert same_identity(observed, candidate)
                used_repository[candidate['path']] = candidate
            row['storage'] = {'kind': 'existing_uploaded_repository_file',
                              'repository_path': candidate['path'], 'server_sha': candidate['server_sha']}
        elif k in archive_by_key:
            loc = sorted(archive_by_key[k], key=lambda x: (x['archive_id'], x['member']))[0]
            row['storage'] = {'kind': 'existing_uploaded_archive_member', **loc}
            prior = used_archive_members[loc['archive_id']].setdefault(loc['member'], row)
            assert same_identity(prior, row)
        else:
            row['storage'] = {'kind': 'new_local_original_body_not_yet_archived',
                              'body_id': row['sha256'], 'future_repository_path': None}
            new_object_keys[k].append(row['workspace_path'])

    archive_reads = []
    for archive_id, needed in used_archive_members.items():
        info = archive_files[archive_id]
        data, pin = read_file(Path(info['local_archive']))
        assert same_identity(pin, info['identity'])
        remaining = set(needed)
        seen = set()
        with tarfile.open(info['local_archive'], mode='r|xz') as archive:
            for member in archive:
                if member.name not in needed:
                    continue
                assert member.name not in seen and member.isfile()
                assert not Path(member.name).is_absolute() and '..' not in Path(member.name).parts
                stream = archive.extractfile(member)
                assert stream is not None
                body = stream.read()
                assert same_identity(identity(body), needed[member.name])
                seen.add(member.name)
                remaining.discard(member.name)
        assert not remaining
        archive_reads.append({'archive_id': archive_id, 'archive': pin,
                              'selected_member_count': len(seen), 'all_selected_member_bytes_sha_git_verified': True,
                              'full_archive_members_reverified': False})

    material = ROOT / RECOVERY / 'material_plan_3'
    result, result_pin = get_json(material / 'actual/RESULT.json')
    worker, worker_pin = get_json(material / 'actual/WORKER_RESULT.json')
    root_review, root_review_pin = get_json(material / 'ROOT_ACTUAL_FAILURE_READBACK.json')
    assert root_review_pin['sha256'] == 'b580455a5491057a2365b95447841548d6c37625632cbd721900de180bbf1270'
    events_raw, events_pin = read_file(material / 'actual/EVENTS.jsonl')
    events = [json.loads(x) for x in events_raw.splitlines()]
    complete = [x for x in events if x['stage'] == 'registry-complete']
    failed = [x for x in events if x['stage'] == 'registry-failure']
    assert result['successful'] is False and result['automatic_retry'] is False
    assert result['worker_exit_code'] == 1 and result['timed_out'] is False
    assert worker['source_unchanged'] is None and 'source_after' not in worker
    assert root_review['source_after'] is None and root_review['source_unchanged'] is None
    assert len(complete) == 168 and len(failed) == 4
    assert all(x['get_attempts'] == 1 for x in complete + failed)
    assert sum(x['actual_bytes'] for x in complete) == 28091720
    assert sum(x['actual_bytes'] for x in complete + failed) == 28101366
    assert len({x['filename'] for x in complete + failed}) == 172
    assert [x['filename'] for x in failed if x['error_class'] == 'TimeoutError'] == ['color_quant-1.1.0.crate']
    assert root_review['failures'] == failed
    copies, copies_pin = get_json(material / 'actual/INDEX_COPIES.json')
    git_materials, git_materials_pin = get_json(material / 'actual/GIT_MATERIALS.json')
    assert len(copies) == 1170 and sum(x['relative_path'] == 'config.json' for x in copies) == 1
    assert sum(x['relative_path'].startswith('.cache/') for x in copies) == 1169
    assert len(git_materials) == 5
    assert sum(len(x['objects']) for x in git_materials) == 5205

    material_readout = {
        'status': 'ACTUAL_ATTEMPT_1_FAIL_LOCAL_PRIMARY_READBACK_ONLY',
        'pins': {'result': result_pin, 'worker': worker_pin, 'root_independent_readback': root_review_pin,
                 'events': events_pin, 'copied_index_metadata': copies_pin, 'git_material_metadata': git_materials_pin},
        'owner': 'dpty-8bc71e23ddb6757582498a79603af5ee9e074d3d14cfd6984ff1e6d919ee6ef7',
        'source': result['source'], 'owner_wall_seconds': result['owner_wall_seconds'],
        'worker_wall_seconds_nested_not_additive': worker['work_wall_seconds'],
        'worker_exit_code': 1, 'overall_successful': False, 'owner_timed_out': False,
        'original_automatic_retry': False, 'attempts_per_started_package': 1,
        'https_attempts': 172, 'completed_archives': 168,
        'complete_body_bytes': 28091720, 'all_returned_body_bytes': 28101366,
        'partial_failed_body_bytes': 9646, 'failures': failed,
        'source_before': worker['source_before'], 'source_after': None,
        'source_after_phase_executed': False, 'source_unchanged': None,
        'index_sparse_entries': 1169, 'index_config_json_entries': 1,
        'copied_index_bytes': worker['counters']['index_bytes'],
        'git_repositories': 5, 'git_objects': 5205,
        'git_object_bytes': worker['counters']['git_object_bytes'], 'git_commands_used': 69,
        'version_only_probes': len(worker['tool_version_probes']),
        'material_seal_complete': False, 'new_target_created': False,
        'format_compile_native_model_actions_in_attempt': 0,
        'scope': 'Local review of retained receipts and metadata; downloaded archive/Git/cache bodies are not copied into this intake and are not independently revalidated here.',
    }

    future_slots = {
        'status': 'PREPARATORY_SLOTS_NOT_EXECUTION_RECEIPTS',
        'root_session_amendment': {
            'source': 'Explicit parent task message; this transcription is not a credential, controller or source protocol modification.',
            'scope': 'Dependency material continuation only; original native/model/experiment budgets unchanged.',
            'remaining_work_seconds': 500, 'cumulative_returned_body_bytes_limit': 536870912,
            'body_bytes_already_consumed': 28101366, 'body_bytes_remaining_arithmetic': 508769546,
            'cumulative_git_command_limit': 80, 'git_commands_already_consumed': 69,
            'git_commands_remaining_arithmetic': 11,
            'maximum_get_attempts_per_exact_package_across_two_owners': 2,
            'eligible_retry_errors': 'Only the specifically reviewed transport failures; exact controller/error set still to be bound.',
            'original_attempt1_retry_history': 0,
        },
        'slots': [
            {'id': 'material_continuation', 'known_preparation_directory': f'{RECOVERY}/material_resume_1',
             'controller_manifest': None, 'payload': None, 'owner_start': None, 'actual_result': None,
             'status': 'CLOUD_PREPARATION_ONLY_AS_OF_PARENT_HANDOFF_NOT_INCLUDED'},
            {'id': 'actual_format_and_precise_policy_rebind', 'source_manifest': None,
             'owner_start': None, 'actual_result': None, 'format_delta': None,
             'status': 'PENDING_SUCCESSFUL_MATERIAL_SEAL_AND_EXACT_PAYLOAD'},
            {'id': 'actual_compile_lint', 'source_manifest': None, 'owner_start': None,
             'actual_result': None, 'status': 'NOT_ADMITTED_BY_MATERIAL_OR_FOCUSED_QA_RESULTS'},
            {'id': 'full_original_source_gates_freeze_native', 'source_manifest': None,
             'owner_start': None, 'actual_result': None, 'status': 'PENDING_ORIGINAL_GATES_WITHOUT_INHERITED_QUALIFICATION'},
        ],
    }

    rows = sorted(selected.values(), key=lambda x: x['workspace_path'])
    storage_counts = dict(collections.Counter(x['storage']['kind'] for x in rows))
    oversized = [dict(workspace_path=x['workspace_path'], **{k:x[k] for k in ('bytes','sha256','git_blob')},
                      storage_kind=x['storage']['kind']) for x in rows if x['bytes'] > 480000]
    group_counts = {g['id']: sum(g['id'] in r['groups'] for r in rows) for g in input_groups}
    protected_after = {n: read_file(ROOT / n)[1] for n in original_docs}
    assert all(same_identity(protected_before[n], protected_after[n]) for n in original_docs)
    assert all(read_file(ROOT / x['workspace_path'])[1]['sha256'] == x['sha256'] for x in rows)

    write_json('CURRENT_INPUT_INDEX.json', {
        'status': 'FINITE_PREPARATORY_INDEX_NOT_FINAL_ARCHIVE_PLAN_OR_FREEZE',
        'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'baseline_uploaded_objects': baseline_pin, 'old_intake_reference_input': old_intake_pin,
        'files': rows, 'logical_file_count': len(rows), 'logical_bytes': sum(r['bytes'] for r in rows),
        'storage_counts': storage_counts, 'new_unique_body_count': len(new_object_keys),
        'new_unique_body_bytes': sum(k[0] for k in new_object_keys),
        'group_counts': group_counts, 'no_final_publication_paths_allocated': True,
        'pack_executed': False, 'git_operations': 0, 'host_actions': 0,
        'new_native_model_build_or_test_actions': 0,
    })
    write_json('SCOPE_AND_FUTURE_SLOTS.json', {
        'input_groups': input_groups, 'excluded_generated_files': exclusions,
        'future': future_slots,
        'explicit_limits': [
            'The original 1a NoUpdate13 failure is not changed by receipt restoration or dependency material retrieval.',
            'The 256 finite previous host paths include 6 actual missing observations; this is not a business physical closure.',
            'Local file/index copies are an evidence selection, not a complete host/cache or original-private-material snapshot.',
            'Reviewed format templates and offline source controls grant no compile or native qualification.',
            'Future inputs, final pack, source identity and publication remain pending.',
        ],
    })
    write_json('REUSE_CATALOG.json', {
        'baseline_uploaded557': baseline_pin,
        'existing_uploaded_repository_files_used': sorted(used_repository.values(), key=lambda x:x['path']),
        'logical_archive_mapping': logical_pin, 'archive_dependency_mapping': dependency_pin,
        'archives_used': {k:archive_files[k] for k in used_archive_members},
        'selected_archive_member_readbacks': archive_reads,
        'meaning': 'Exact body storage reuse only; no runtime/source/authority qualification is inherited.',
    })
    write_json('OVERSIZED_ORIGINALS_PENDING_REPRESENTATION.json', {
        'threshold_bytes': 480000, 'files': oversized,
        'policy': 'Preserve all original bytes. Later reviewed archive/metadata splitting must restore them exactly; no truncation or gate increase.',
        'split_or_pack_executed': False,
    })
    write_json('MATERIAL_ATTEMPT1_READOUT.json', material_readout)
    write_json('LOCAL_PREPARATION_READBACK.json', {
        'status': 'LOCAL_FINITE_INDEX_PREPARATION_COMPLETE_NOT_FINAL_FREEZE',
        'manifest_member_checks': manifest_checks,
        'actual_material_result_and_root_receipt_consistent': True,
        'events_complete_168_failure_4_body_sum_matches_result': True,
        'all_selected_local_bytes_sha_git_stable_across_preparation': True,
        'protected_formal_documents_and_535_557_inputs': protected_after,
        'protected_documents_unchanged': True,
        'selected_archive_members_verified': sum(x['selected_member_count'] for x in archive_reads),
        'existing_uploaded_repository_bodies_verified': len(used_repository),
        'host_network_git_build_native_model_test_actions': 0,
        'final_narrative_or_pack_frozen': False,
    })
    print(json.dumps({'output':str(OUT),'logical_files':len(rows), 'storage_counts':storage_counts,
                      'new_unique_bodies':len(new_object_keys),'new_unique_bytes':sum(k[0] for k in new_object_keys),
                      'oversized_originals':len(oversized),'groups':group_counts}, ensure_ascii=False))


if __name__ == '__main__':
    main()
