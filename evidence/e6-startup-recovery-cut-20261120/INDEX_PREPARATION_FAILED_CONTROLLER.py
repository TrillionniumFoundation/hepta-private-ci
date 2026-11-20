"""Append a finite local intake; no controller, network, host or gate execution."""
from __future__ import annotations

import collections
import importlib.util
import json
from pathlib import Path

ROOT = Path('/workspace/scratch/e9e051ab0825')
D = ROOT / 'metrics_integration/execution-readout-intake-diagnostic-6'
spec = importlib.util.spec_from_file_location('intake_helpers', D / 'prepare_input_index.py')
h = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(h)
OUT = D / 'input-index-preparation-2'


def dump(name, value):
    with (OUT / name).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def main():
    OUT.mkdir(exist_ok=False)
    parent, parent_pin = h.get_json(D / 'input-index-preparation-1/CURRENT_INPUT_INDEX.json')
    assert parent_pin['sha256'] == 'c63b33d3bfea4343a21c802ac3b4ac9d1f299296e14a54933656dbe12dddd306'
    baseline, baseline_pin = h.get_json(h.BASELINE_PATH)
    assert baseline_pin['sha256'] == h.EXPECTED_BASELINE_SHA
    baseline_by_key = collections.defaultdict(list)
    for row in baseline:
        assert row['git_blob'] == row['server_sha']
        baseline_by_key[h.key(row)].append(row)
    parent_by_key = collections.defaultdict(list)
    parent_by_path = {x['workspace_path']: x for x in parent['files']}
    for row in parent['files']:
        parent_by_key[h.key(row)].append(row)
    selected = {}
    manifest_checks = []

    def add(path, group, expected=None):
        _, pin = h.read_file(path)
        if expected:
            for k in ('bytes', 'sha256', 'git_blob'):
                if k in expected:
                    assert pin[k] == expected[k], (path, k)
        row = selected.setdefault(pin['workspace_path'], {**pin, 'groups': []})
        assert h.same_identity(row, pin)
        if group not in row['groups']:
            row['groups'].append(group)

    def add_manifest(dirname, name, group, extras=()):
        root = ROOT / dirname
        manifest, pin = h.get_json(root / name)
        add(root / name, group)
        for row in manifest['files']:
            rel = Path(row['path'])
            assert not rel.is_absolute() and '..' not in rel.parts
            add(root / rel, group, row)
        for extra in extras:
            add(root / extra, group)
        manifest_checks.append({'manifest': pin, 'members_verified': len(manifest['files']),
                                'extras_outside_original_manifest': list(extras)})

    resume_dir = 'e6_owner_work/historical_startup_recovery/material_resume_1'
    add_manifest(resume_dir, 'REVIEW_MANIFEST.json', 'resume1_static_blocked')
    # Retain existing synthetic mechanism fixture bytes without rerunning it.
    for p in sorted((ROOT / resume_dir / 'offline-controls-1').rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
            add(p, 'resume1_existing_offline_control_evidence')
    add_manifest('e6_material_resume_peer_1', 'MANIFEST.json', 'resume1_blocking_peer', ('ROOT_READBACK.json',))
    add_manifest('e6_ordinary_adopt_equivalence_helper_addendum_1', 'MANIFEST.json',
                 'adopt_direct_helper_static_addendum', ('ROOT_READBACK.json',))
    add(ROOT / 'metrics_integration/PR_REFRESH_PRE_STARTUP_1.json', 'root_actual_readonly_pr_refresh')

    # Verify the newly visible helper bodies against the original 1a inventory.
    addon = ROOT / 'e6_ordinary_adopt_equivalence_helper_addendum_1'
    pins, pins_pin = h.get_json(addon / 'SOURCE_PINS.json')
    inventory_path = Path(pins['inventory']['local_absolute_path'])
    inv, inv_pin = h.get_json(inventory_path)
    assert h.same_identity(inv_pin, pins['inventory'])
    invmap = {r['path']: r for r in inv}
    source_checks = []
    for row in pins['files']:
        _, actual = h.read_file(addon / row['relative_path'])
        original = invmap[row['repo_path']]
        assert all(actual[k] == original[k] for k in ('bytes', 'sha256'))
        source_checks.append({'path': row['repo_path'], 'actual': actual,
                              'matches_actual_1a_inventory': True})

    repo_reuse = {}
    prior_reuse = {}
    new_bodies = collections.defaultdict(list)
    for row in selected.values():
        k = h.key(row)
        if k in baseline_by_key:
            ref = sorted(baseline_by_key[k], key=lambda x: x['path'])[0]
            if ref['path'] not in repo_reuse:
                _, actual = h.read_file(Path(ref['local_path']))
                assert h.same_identity(actual, ref)
                repo_reuse[ref['path']] = ref
            row['storage'] = {'kind': 'existing_uploaded_repository_file',
                              'repository_path': ref['path'], 'server_sha': ref['server_sha']}
        elif k in parent_by_key:
            ref = sorted(parent_by_key[k], key=lambda x: x['workspace_path'])[0]
            if ref['workspace_path'] not in prior_reuse:
                _, actual = h.read_file(ROOT / ref['workspace_path'])
                assert h.same_identity(actual, ref)
                prior_reuse[ref['workspace_path']] = ref
            row['storage'] = {'kind': 'previous_preparatory_index_exact_body',
                              'prior_workspace_path': ref['workspace_path'],
                              'prior_storage_kind': ref['storage']['kind'],
                              'qualification_inherited': False}
        else:
            row['storage'] = {'kind': 'new_local_original_body_not_yet_archived',
                              'body_id': row['sha256'], 'future_repository_path': None}
            new_bodies[k].append(row['workspace_path'])
    for row in selected.values():
        if row['workspace_path'] in parent_by_path:
            assert h.same_identity(row, parent_by_path[row['workspace_path']])

    peer, peer_pin = h.get_json(ROOT / 'e6_material_resume_peer_1/REVIEW.json')
    assert peer['status'] == 'BLOCKED_TWO_IMPLEMENTATION_ISSUES'
    assert peer['controller_sha256'] == 'c9ecd949964ffc6956385ce1bc67a2f64f21b487f02b12619e63cdebe22340e6'
    assert peer['candidate_manifest_sha256'] == 'de88757d6f02a00c90d6204070c0b33adc79c81805a7a9d5e7e5c205ced754fa'
    resume_plan, resume_plan_pin = h.get_json(ROOT / resume_dir / 'REVIEW_MANIFEST.json')
    controls, controls_pin = h.get_json(ROOT / resume_dir / 'offline-controls-1/RESULT.json')
    assert len(controls['controls']) == 9 and controls['passed'] is True
    assert controls['host_actions'] == 0 and controls['network_requests'] == 0
    pr, pr_pin = h.get_json(ROOT / 'metrics_integration/PR_REFRESH_PRE_STARTUP_1.json')
    assert pr['read_at'] == '2026-11-20 17:07:51 UTC' and len(pr['prs']) == 8
    assert all(p['state'] == 'open' and p['draft'] is True and p['merged'] is False for p in pr['prs'])
    e6 = next(p for p in pr['prs'] if p['repository'] == 'hepta-private-ci' and p['number'] == 6776)
    assert e6['head_sha'] == 'bfea526e1cb9a2da718d835cd617e87c67181fe9'
    rows = sorted(selected.values(), key=lambda x: x['workspace_path'])
    add_paths = set(selected) - set(parent_by_path)
    composition = {'parent_input_index': parent_pin, 'parent_logical_file_count': len(parent['files']),
                   'additional_rows': len(rows), 'new_logical_paths': len(add_paths),
                   'overlap_paths_exact_and_not_double_counted': len(selected) - len(add_paths),
                   'composed_logical_file_count': len(parent['files']) + len(add_paths),
                   'parent_bytes_unchanged': True, 'final_pack_or_freeze': False}
    dump('ADDITIONAL_INPUT_INDEX.json', {
        'status': 'FINITE_PREPARATORY_INCREMENT_NOT_FINAL_ARCHIVE_PLAN',
        'composition': composition, 'baseline_uploaded557': baseline_pin, 'files': rows,
        'storage_counts': dict(collections.Counter(x['storage']['kind'] for x in rows)),
        'new_unique_body_count': len(new_bodies), 'new_unique_body_bytes': sum(k[0] for k in new_bodies),
        'oversized_originals_pending_exact_representation': [x['workspace_path'] for x in rows if x['bytes'] > 480000],
        'existing_repository_files_used': list(repo_reuse.values()),
        'previous_index_rows_used': list(prior_reuse.values()),
        'new_host_network_git_test_compile_native_model_actions': 0,
    })
    dump('RESUME1_AND_SUCCESSOR_SCOPE.json', {
        'status': 'OLD_STATIC_CANDIDATE_BLOCKED_NO_EXECUTION_RECEIPT',
        'old_candidate_manifest': resume_plan_pin, 'blocking_peer': peer_pin,
        'findings': peer['findings'],
        'existing_offline_controls': {'pin': controls_pin, 'cases': 9,
            'wall_seconds': controls['wall_seconds'], 'actual_https_or_host_qualification': False,
            'not_rerun_by_this_reviewer': True},
        'old_candidate_actual_owner': None, 'old_candidate_actual_result': None,
        'frozen_budget_record': resume_plan['budgets'],
        'successor_slot': {'known_directory': 'e6_owner_work/historical_startup_recovery/material_resume_2',
            'expected_minimal_scope': ['private retryable error only from actual network calls',
                                     'fatal STOP and notification before potentially failing log IO'],
            'review_manifest': None, 'payload': None, 'actual_owner': None, 'actual_result': None,
            'status': 'SEPARATE_PREPARATION_NOT_INCLUDED_IN_THIS_INCREMENT'},
        'actual_format_slot': None, 'actual_compile_slot': None,
        'original_attempt1_retry_count': 0,
    })
    dump('ADOPT_HELPER_READ_REVIEW.json', {
        'status': 'DIRECT_TWO_HELPER_SOURCE_SCOPE_CONFIRMED_NO_NEW_EXECUTION',
        'source_commit': '1a9799686243c2be0ee393ba364e091029cfb944',
        'source_pins': pins_pin, 'actual_inventory': inv_pin, 'source_checks': source_checks,
        'full_source_bodies_read': [
            'authority_host_learning_registration.rs::with_learning_profile:200-296',
            'authority_host_q24_evaluation_operation.rs::with_original_completed_evaluation and with_operation:48-360'],
        'confirmed': [
            'with_learning_profile checks real recipient/pidfd/logind, original writer proof, live leases and issuer revocations around a successful callback.',
            'Its action(initial, proof)? propagates callback errors before the subsequent successful-path checks.',
            'Completed B uses Readback, actual B owner/record/cell locks, restored learning checkpoint and Training cut, native receipt/attestation/output readback, current signatures and preserved owner/end.',
            'B captures the callback result, performs native Readback and checkpoint equality before propagating value?; later success checks are not claimed on every error path.',
        ],
        'narrow_remaining_proof_obligation': 'Whether retained B/helper checks equivalently dominate a fresh rejection specific to original A Source/Cell/RunStart/terminal-ledger/persistent-refusal before each next effect is unproved.',
        'must_not_claim': ['shared revocations/writer lease/pidfd are necessarily omitted',
                           'all uninspected lower helpers omit A',
                           'M1 equivalence or any historical request budget reduction has been established'],
        'conditional_existing_operation_total': 74, 'original_limit_unchanged': 64,
        'actual_adopt_runs': 0, 'additional_fetch_or_host_or_tests': 0,
    })
    dump('ROOT_PR_REFRESH_READOUT.json', {
        'source': pr_pin, 'actual_read_at': pr['read_at'], 'new_queries_by_this_reviewer': 0,
        'prs': [{k:p[k] for k in ('repository','number','url','head_sha','base_sha','state','draft','merged')}
                for p in pr['prs']],
        'e6_source_objects_or557_uploaded_evidence_not_equated_to_published_branch_head': True,
    })
    protected, _ = h.get_json(D / 'input-index-preparation-1/LOCAL_PREPARATION_READBACK.json')
    unchanged = []
    for name, old in protected['protected_formal_documents_and_535_557_inputs'].items():
        _, actual = h.read_file(ROOT / name)
        assert h.same_identity(old, actual)
        unchanged.append(actual)
    _, current_parent = h.read_file(D / 'input-index-preparation-1/CURRENT_INPUT_INDEX.json')
    assert h.same_identity(parent_pin, current_parent)
    dump('LOCAL_INCREMENT_READBACK.json', {
        'status': 'LOCAL_INDEX_AND_SOURCE_READBACK_ONLY', 'manifest_checks': manifest_checks,
        'original_1a_source_inventory_matches': len(source_checks), 'composition': composition,
        'protected_formal_reports_and535_557_unchanged': unchanged,
        'new_controller_or_offline_controls_executed': False, 'pack_executed': False,
        'final_narrative_or_inputs_frozen': False,
    })
    print(json.dumps({'output':str(OUT), 'composition':composition,
                      'storage_counts':dict(collections.Counter(x['storage']['kind'] for x in rows)),
                      'new_unique_body_count':len(new_bodies),
                      'new_unique_body_bytes':sum(k[0] for k in new_bodies)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
