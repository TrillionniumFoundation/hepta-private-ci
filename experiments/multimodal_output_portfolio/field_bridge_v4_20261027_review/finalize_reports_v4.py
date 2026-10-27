"""Bind completed V4 evidence and write reports without evaluating any new outcome."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path('/workspace/scratch/9b2cd2b58376')
PORTFOLIO = ROOT / 'bridge_repo/experiments/multimodal_output_portfolio'
SCIENCE = PORTFOLIO / 'field_bridge_v4_20261027'
REVIEW = PORTFOLIO / 'field_bridge_v4_20261027_review'
RUN = Path('/tmp/hepta-field-v4-run')
FREEZES = ROOT / 'bridge_v4_freezes'
EVIDENCE = SCIENCE / 'evidence'
STUDY = 'hepta.field-bridge.v4.panel-origin-qualification.20261027.1'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


def identity(path):
    path = Path(path)
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


def main():
    q = read(RUN / 'QUALIFICATION.json')
    training = read(RUN / 'INDEPENDENT_V4_TRAINING_AUDIT.json')
    media = read(RUN / 'INDEPENDENT_V4_ENDPOINT_HARD_SCORE_AUDIT.json')
    mechanism = read(RUN / 'mechanism/MECHANISM.json')
    protocol = read(SCIENCE / 'PROTOCOL.json')
    freeze = read(FREEZES / 'TRAINING_FREEZE.json')
    old_protocol = read(PORTFOLIO / 'field_bridge_v3_20261027/PROTOCOL.json')
    assert protocol['training'] == old_protocol['training']
    assert q['study_id'] == STUDY and q['status'] == 'QUALIFICATION_FAILED'
    assert not q['passed'] and sum(c['passed'] for c in q['comparisons']) == 4
    assert training['passed'] and media['passed'] and media['maximum_value_error'] == 0.0
    assert mechanism['inputs_unchanged'] and mechanism['new_model_calls'] == 0
    assert sha(RUN / 'QUALIFICATION.json') == '0634e0f89ad5c07dfa36c74c475b593b8b9aa8c29990bb86b078995ab63b3b58'
    for relative, expected in freeze['source_files'].items():
        assert sha(PORTFOLIO / relative) == expected, relative
    for relative, expected in freeze['old_artifacts'].items():
        assert sha(Path('/tmp/hepta-field-v3-run') / relative) == expected, relative
    receipts = {p.name: read(p) for p in sorted((RUN / 'PHASE_RECEIPTS').glob('*.json'))}
    assert len(receipts) == 8
    for phase in ('train', 'evaluate'):
        for seed in (17, 29, 43):
            assert receipts[f'{phase}-{seed}.json']['complete_sha256'] == sha(RUN / phase / str(seed) / 'COMPLETE.json')
    eval_resources = {}
    for seed in (17, 29, 43):
        for key, value in read(RUN / 'evaluate' / str(seed) / 'COMPLETE.json')['resources'].items():
            eval_resources[key] = eval_resources.get(key, 0) + value
    assert sum(v for k, v in eval_resources.items() if k.endswith('_observer_digit_examples')) == 1363968
    disposition = {
        'schema': 'hepta.field-bridge.v4.terminal-disposition.1', 'study_id': STUDY,
        'terminal': True, 'status': q['status'], 'qualification_passed': False,
        'qualification_sha256': sha(RUN / 'QUALIFICATION.json'),
        'qualification_checks_passed': 4, 'qualification_checks_registered': 6,
        'failed_checks': [c['name'] for c in q['comparisons'] if not c['passed']],
        'ordinary_gain_and_qualification_clean_noninferiority_passed': True,
        'all_model_phases_and_registered_checks_complete': True,
        'training_paths_complete': 108, 'endpoint_paths_complete': 108,
        'scientific_retries': 0, 'formal_outcome_looks': 1,
        'final_or_new_runtime_executed': False,
        'final_or_new_runtime_authorized': False,
        'stop_reason': 'The single registered panel-origin candidate failed both incremental-gain checks. The fixed failure policy stops final/runtime access and forbids outcome-driven retuning or resampling.',
        'all_original_substantive_blockers_closed': False,
        'original_closure_criteria_unchanged': True,
        'authority': 'DENY_ALL', 'requires_calibration': True, 'native_owner_integration': False,
        'persistence': {'raw_archives_saved_to_library': False, 'automatic_approval_review_blocked_upload': True,
                        'no_further_retry_or_alternate_egress': True,
                        'requires': 'Explicit user-authored named archive/report files and ChatGPT Library destination.'},
        'archive_verification': 'External postpackage receipt binds complete archive and exact literal-restored reanalysis; it is deliberately outside the archive it verifies.',
        'claim_limits': protocol['claim_limits'],
    }
    write(RUN / 'STUDY_DISPOSITION.json', disposition)
    bindings = {str(p.relative_to(RUN)): identity(p) for p in sorted(RUN.rglob('*'))
                if p.is_file() and '__pycache__' not in p.parts and p.name != 'V4_EXECUTION_LEDGER.json'}
    verification = {
        'training_audit': {k: training[k] for k in ['wall_ns', 'cpu_ns', 'weights_only_checkpoint_loads', 'independent_head_predictions', 'generator_calls', 'observer_calls', 'gradient_or_optimizer_updates', 'native_tick_calls', 'network_calls']},
        'endpoint_hard_score_audit': {k: media[k] for k in ['verification_wall_ns', 'verification_cpu_ns', 'hard_output_rows_verified', 'observer_values_verified', 'actual_observer_digit_examples', 'logical_observer_digit_examples', 'actual_observer_batch_calls', 'attempted_observer_forwards', 'observer_batch_cache_hits', 'maximum_value_error', 'generator_forward_calls', 'native_calls', 'network_calls']},
        'mechanism': {'analysis_wall_ns': mechanism['analysis_wall_ns'], 'new_model_calls': 0, 'diagnostic_only': True, 'endpoint_numeric_arrays_or_media_read': False},
    }
    ledger = {
        'schema': 'hepta.field-bridge.v4.complete-execution-ledger.1', 'study_id': STUDY,
        'status': 'COMPLETE_REGISTERED_EXECUTION_WITH_FAILED_SCIENTIFIC_GATE',
        'model_phase_processes': 6, 'model_phase_normal_exit_codes': [0] * 6,
        'cli_phase_receipts': receipts, 'cli_completed_phases': 8,
        'training_paths': 108, 'endpoint_paths': 108, 'original_endpoint_baselines': 3,
        'scientific_retries': 0, 'formal_outcome_looks': 1,
        'future_final_runtime_steps': {'executed': 0, 'status': 'NOT_AUTHORIZED_AFTER_FAILED_GATE', 'not_failed_processes': True},
        'preexecution_source_registration_commit': 'd40343fc8c08828461463664cba9a594422ccd9f',
        'training_freeze_publication_commit': '28cb77a30f713e4efde91edf550b9bbe15fffcd4',
        'training_seal_and_endpoint_freeze_publication_commit': '46b21d7e5af9a485c27a232e3ef1a4b9237b18d7',
        'phase_freezes': {p.name: identity(p) for p in sorted(FREEZES.glob('*FREEZE.json'))},
        'qualification_binding_freeze_scope': 'Created locally after endpoint completion and independent media audit, before the one statistical invocation. This data-binding freeze was not Git-published before endpoint outcomes; policy/protocol/source and endpoint opening barrier were.',
        'frozen_source_count': len(freeze['source_files']), 'frozen_source_identities_unchanged': True,
        'old_input_count': len(freeze['old_artifacts']), 'old_input_identities_unchanged': True,
        'training_resource_totals': training['resources'], 'endpoint_resource_totals': eval_resources,
        'independent_verification_resources': verification, 'qualification_analysis_resources': q['resources'],
        'timing_scope': 'Receipt phase clocks start after argument parsing and end after postflight checks; interpreter startup and the final phase-receipt write are excluded. Concurrent phase wall times are not summed as latency. CPU work is distinct from elapsed time.',
        'phase_cpu_ns_sum_work_only': sum(r['phase_cpu_ns'] for r in receipts.values()),
        'training_reward_observer_digit_examples': 1660416,
        'training_audit_observer_digit_examples': 0, 'training_endpoint_observer_work': 0,
        'endpoint_observer_digit_examples_both_observers': 1363968,
        'new_controller_fits': 0, 'new_native_ticks': 0,
        'verification_cost_is_additional_to_scientific_cost': True,
        'logical_cached_verification_is_not_new_independent_data': True,
        'historical_fit_cost': 'V3 response banks, reference policies, heads and normalizers are reused byte-for-byte. Their original exploration/fit costs remain charged in V3_EXECUTION_LEDGER.json, not relabelled as zero-cost new discovery or charged again as V4 training.',
        'preparatory_attempts': 'Synthetic contracts, dependency restoration, old-data diagnosis/pilots and their prelaunch failures are preserved in the review directory. They are not additional V4 research paths or hidden retries.',
        'active_calibration_array': {'float64_values_per_path': 14, 'bytes_per_path': 112,
                                     'not_total_state_or_memory': True, 'separate_calibration_timing_measured': False},
        'binding_count': len(bindings), 'bindings': bindings,
        'inventory_exclusions': ['V4_EXECUTION_LEDGER.json (self)', '__pycache__ / bytecode', 'Postpackage archive verification receipts, Git publication receipts and PR update, which bind this terminal package externally'],
        'archive_scope': 'The archive separately inventories the entire terminal V4 run, science/review, all frozen dependencies/old inputs, original model/corpus assets, source registries, freezes and declared operational receipts. V2/V3 historical archives are referenced, not nested.',
        'all_original_substantive_blockers_closed': False,
    }
    write(RUN / 'V4_EXECUTION_LEDGER.json', ledger)
    copied = []
    selection = ['QUALIFICATION.json', 'QUALIFICATION_START.json', 'STUDY_DISPOSITION.json', 'V4_EXECUTION_LEDGER.json',
                 'INDEPENDENT_V4_ENDPOINT_HARD_SCORE_AUDIT.json', 'mechanism/MECHANISM.json', 'mechanism/MECHANISM.md']
    selection += [str(p.relative_to(RUN)) for p in sorted((RUN / 'PHASE_RECEIPTS').glob('*.json'))]
    for phase in ('train', 'evaluate'):
        for seed in (17, 29, 43):
            selection += [f'{phase}/{seed}/{n}' for n in ['START.json', 'COMPLETE.json', 'ASSET_IDENTITIES.json']]
    for relative in selection:
        dest = EVIDENCE / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            assert sha(dest) == sha(RUN / relative)
        else:
            shutil.copyfile(RUN / relative, dest)
        copied.append(relative)
    shutil.copyfile(FREEZES / 'QUALIFICATION_FREEZE.json', EVIDENCE / 'QUALIFICATION_FREEZE.json')
    old_path = PORTFOLIO / 'field_bridge_v3_20261027_review/BLOCKERS.json'
    old = read(old_path)
    blockers = json.loads(json.dumps(old))
    blockers.update(schema='hepta.field-bridge.v4.original-criteria-and-new-evidence.1',
                    prior_ledger_path='../field_bridge_v3_20261027_review/BLOCKERS.json', prior_ledger_sha256=sha(old_path),
                    terminal_disposition_sha256=sha(RUN / 'STUDY_DISPOSITION.json'))
    updates = {
        'B01': ('prior_bounded_development_scope_preserved', 'No new response-bank fit. Previously demonstrated hard-response identification retains its bounded scope.'),
        'B02': ('prior_local_trajectory_scope_preserved', '108 complete V4 paths and all policy/rollback/checkpoint identities are verified; this is not a new sufficient-state or optimal-value claim.'),
        'B03': ('not_established_for_original_final_joint_criterion', 'V4 ordinary-frozen task gain and qualification clean NI pass both observers. This is positive evidence within the new qualification scope; original final ordinary-gain/independent-retention closure remains unmet.'),
        'B04': ('not_established', 'origin_field-ordinary and origin_field-origin_richer fail both adjusted lower endpoints and strict model-wise positivity. No final C-B or E-G was executed.'),
        'B05': ('not_established', 'No new runtime holdout. Old-data honest-stage pilot is worse in all six model/controller comparisons. The prior dual-observer runtime gain failures stand.'),
        'B06': ('not_established', 'No new Hepta-versus-history confirmatory comparison. Active state and different actions do not establish incremental value.'),
        'B07': ('partially_closed_original_scope_unchanged', 'Three V4 qualification clean NI comparisons pass both observers at -0.01. They do not replace original independent final retention requirements.'),
        'B08': ('prior_transport_scope_preserved', 'No new native/owner integration or latency superiority claim. DENY_ALL is preserved.'),
        'B09': ('v4_source_and_access_boundary_verified_prior_limit_preserved', '6,352 new official-train image identities exclude the full prior 57,048 identities, including unused V3 allocations. Protocol/source precede model execution and all 108 training paths are sealed before endpoint opening. Historical shared-panel limitation and unknown pretraining/writers are unchanged.'),
        'B10': ('partially_closed_pending_explicit_persistence_authorization', 'Actual training identities, hard-media scores and statistical decision are preserved. Complete archive integrity/literal-restored exact reanalysis are bound by the external postpackage receipt. Automatic review rejected named-archive Library persistence; no further retry or alternate raw-data egress is authorized.'),
    }
    for item in blockers['items']:
        status, resolution = updates[item['id']]
        item['v4_update'] = {'status': status, 'resolution': resolution, 'gate_failure_not_relabelled_as_success': True}
    assert [i['closure_criteria'] for i in blockers['items']] == [i['closure_criteria'] for i in old['items']]
    blockers['v4_qualification'] = {'status': q['status'], 'passed': False, 'checks_passed': 4, 'checks_registered': 6,
                                     'result_sha256': sha(RUN / 'QUALIFICATION.json'), 'original_six_experiment_families_relabelled_as_checks': False}
    blockers['remaining_operational_blockers'] = ['Explicit named V2/V3/V4 archive and verification-report authorization for ChatGPT Library; automatic approval rejection is preserved and no further upload is attempted.']
    blockers['inherited_evidence_paths_base'] = 'Inherited V1/V2/V3 evidence references retain the originating ledger context; new V4 evidence lives in ../field_bridge_v4_20261027/evidence/.'
    write(REVIEW / 'BLOCKERS.json', blockers)
    table = ['| 比较 | reward 差值 [校正区间] | audit 差值 [校正区间] | 两观察者联合条件 |', '|---|---:|---:|---|']
    for c in q['comparisons']:
        cells = []
        for observer in ('reward', 'audit'):
            v = c['observers'][observer]
            cells.append(f"{v['mean']:+.6f} [{v['interval'][0]:+.6f}, {v['interval'][1]:+.6f}]")
        table.append(f"| {c['name']} | {cells[0]} | {cells[1]} | {'通过' if c['passed'] else '未通过'} |")
    (SCIENCE / 'RESULTS.md').write_text('# V4 qualification：完整执行，参数场候选未通过\n\n' + '\n'.join(table) + '\n\n六项比较是新资格协议的三个增益与三个 clean 非劣效检查，不是最初六个实验臂的最终成功计数。每观察者双侧区间覆盖率为 99.1666667%，固定 4,000 次层次配对 bootstrap，种子 271042；增益还要求三个固定模型的均值都严格为正。两个观察者必须同时通过。clean NI 阈值为 -0.01。\n\norigin_field−ordinary 的逐模型 reward/audit 差值：17 为 -0.0021969349/+0.0003055065，29 为 0/0，43 为 +0.0026783964/+0.0035511992。模型 29 的平局不满足严格正向条件。未通过不构成等价性、确定劣势或理论反证。\n\n108 条训练路径和全部端点已完成；独立训练审计通过，340,992 个媒体输出的 681,984 个观察者效用值逐项精确重算一致。唯一正式判定为 QUALIFICATION_FAILED；按原协议不开放 final 或新的 runtime holdout。完整原始结果见 [QUALIFICATION.json](evidence/QUALIFICATION.json)，机制诊断见 [MECHANISM.md](evidence/mechanism/MECHANISM.md)，逐项条件见 [BLOCKERS.json](../field_bridge_v4_20261027_review/BLOCKERS.json)。\n')
    write(REVIEW / 'TERMINAL_REPORT_BINDINGS.json', {
        'study_id': STUDY, 'qualification': identity(RUN / 'QUALIFICATION.json'),
        'disposition': identity(RUN / 'STUDY_DISPOSITION.json'), 'execution_ledger': identity(RUN / 'V4_EXECUTION_LEDGER.json'),
        'blockers': identity(REVIEW / 'BLOCKERS.json'), 'copied_run_evidence': copied,
        'postpackage_receipts_excluded_from_terminal_self_binding': True,
        'new_model_calls': 0, 'new_statistical_looks': 0, 'new_policy_selection': False,
    })
    print(json.dumps({'passed': True, 'binding_count': len(bindings), 'copied_files': len(copied),
                      'qualification': q['status'], 'disposition': identity(RUN / 'STUDY_DISPOSITION.json'),
                      'ledger': identity(RUN / 'V4_EXECUTION_LEDGER.json')}))


if __name__ == '__main__':
    main()
