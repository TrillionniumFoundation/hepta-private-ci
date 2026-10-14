"""Actual B/C audit behavior on synthetic contract fixtures (not model evidence)."""
from __future__ import annotations

from copy import deepcopy
import pytest

from neuron_shared_encoder.abc_evidence import (
    ROLES, STAGES, SCALES, _pinned_json, multimodal_cost_audit,
    threeway_prequential_audit, joint_abc_evidence_gate,
    paired_media_necessity_audit,
)
from neuron_shared_encoder.validation_v3 import canonical_digest

D = lambda x: x * 64


def b_fixture():
    rows = []
    for split, count in (('train', 4), ('validation', 4), ('future', 8), ('ood', 4)):
        for i in range(count):
            window = 'future_1' if i < 4 else 'future_2'
            day = 1 + i if split != 'future' else 20 + i
            rows.append({
                'row_id': f'{split}-{i}', 'source_group': f'g-{split}-{i}',
                'event_time': f'2026-09-{day:02d}T00:00:00+00:00',
                'split': split, 'principal': 'p', 'organ_id': 'o', 'cell_id': 'c',
                'state': 'input', 'question': 'choose', 'options': ['no', 'yes'],
                'label': i % 2, 'future_window': window if split == 'future' else None,
            })
    snapshots = {}
    for role, confidence, sha in zip(ROLES, (.6, .7, .95), ('a', 'b', 'c')):
        p = [[confidence, 1-confidence] if row['label'] == 0
             else [1-confidence, confidence] for row in rows]
        if role == 'learned_head':
            for idx, row in enumerate(rows):
                if row['split'] == 'ood':
                    p[idx] = [.5, .5]
                elif row['row_id'] == 'future-0':
                    # The first future event must match the untouched
                    # Frozen Head before any label is available.
                    p[idx] = ([.7, .3] if row['label'] == 0 else [.3, .7])
        snapshots[role] = {
            'role': role, 'dataset_sha256': D('d'),
            'source_commit': 'e' * 40,
            'cell_scope': ['p', 'o', 'c'],
            'artifact_digest': D(sha),
            'row_ids': [r['row_id'] for r in rows], 'probabilities': p,
        }
        if role in ('frozen_head', 'learned_head'):
            snapshots[role].update({
                'encoder_bundle_sha256': D('1'),
                'feature_pipeline_sha256': D('2'),
                'runtime_profile_sha256': D('3'),
                'input_contract_sha256': D('4'),
            })
    snapshots['frozen_head']['head_digest'] = D('f')
    snapshots['learned_head']['initial_head_digest'] = D('f')
    snapshots['learned_head']['head_digests_by_row'] = [D('9') for _ in rows]
    snapshots['learned_head']['head_digests_by_row'][8] = D('f')
    snapshots['learned_head']['final_head_digest'] = D('9')
    records = []
    updates = []
    for i, row in enumerate(rows):
        if row['split'] != 'future':
            continue
        records.append({
            'row_id': row['row_id'], 'future_window': row['future_window'],
            'frozen_head_digest': D('f'),
            'learned_head_digest_before': snapshots['learned_head']['head_digests_by_row'][i],
            'input_digest': canonical_digest({
                'state': row['state'], 'question': row['question'], 'options': row['options'],
            }),
            'prediction_digests': {
                role: canonical_digest({
                    'row_id': row['row_id'], 'probabilities': snapshots[role]['probabilities'][i],
                }) for role in ROLES
            },
            'predicted_at': row['event_time'],
        })
        event = records[-1]
        before = snapshots['learned_head']['head_digests_by_row'][i]
        after = D('9')
        updates.append({
            'row_id': row['row_id'],
            'head_digest_before': before,
            'head_digest_after': after,
            'prediction_record_digest': canonical_digest(event),
            'label_digest': canonical_digest({
                'row_id': row['row_id'], 'label': row['label'],
            }),
            'label_available_at': row['event_time'].replace('00:00:00', '01:00:00'),
            'updated_at': row['event_time'].replace('00:00:00', '02:00:00'),
            'update_kind': 'updated' if before != after else 'no_update',
        })
    return rows, {
        'dataset_sha256': D('d'), 'snapshots': snapshots,
        'prelabel_journal': {
            'frozen_head_digest': D('f'), 'acceptance_threshold': .8,
            'records': records,
        },
        'postlabel_updates': updates,
    }


def c_fixture():
    tasks = {
        'text_decision': 0.7, 'image_text_retrieval': 0.8,
        'visual_relations': .6, 'audio_events': .7, 'temporal_order': .55,
    }
    stages = []
    for index, name in enumerate(STAGES):
        seen = list(tasks)[:[1,3,4,5][index]]
        stage = {
            'stage': name, 'artifact_sha256': D(chr(97 + index)),
            'model_revision': 'f'*40,
            'frozen_text_probe_sha256': D('a'),
            'shared_text_stem_sha256': D('4'),
            'modality_adapter_sha256': None if index == 0 else format(index+10, '064x'),
            'paired_media_dataset_sha256': None if index == 0 else format(index+20, '064x'),
            'total_parameters': 140000000 + index*1000000,
            'trainable_parameters': index*5000,
            'projection_parameters': index*1000,
            'resident_weights_bytes': 280000000 + index*2000000,
            'peak_training_memory_bytes': 1000000 + index*500,
            'training_seconds': 10 + index,
            'tasks': {k: {'dataset_sha256': canonical_digest(k), 'cases': 50, 'score': tasks[k]}
                      for k in seen},
            'scales': [],
        }
        for n in SCALES:
            stage['scales'].append({
                'cell_count': n, 'active_cell_count': n,
                'actually_executed_cell_count': n, 'requests': n,
                'run_id': f'{name}-{n}-actual-run',
                'recovery_trace_sha256': format(n + index + 1, '064x'),
                'encoder_forward_rows': n*2, 'encoder_batch_calls': n//2,
                'host_id': 'host-1', 'source_commit': 'f'*40,
                'paired_text_workload_sha256': D('c'),
                'device': 'cpu', 'gpu_peak_bytes': None,
                'throughput_rps': 10, 'cpu_seconds': 1, 'rss_peak_bytes': 10000000 + n,
                'request_p95_ms': 1, 'request_p99_ms': 2,
                'batch_p95_ms': 2, 'batch_p99_ms': 3,
                'active_modality_peak_bytes': index*1000000,
                'head_resident_bytes': n*4096, 'queue_peak_depth': n//2,
                'wal_fsync_count': 1,
                'wal_written_bytes': 500, 'recovery_seconds': 2,
                'failed_replay_count': 0, 'latency_cas_p99_ms': 0.5,
                'latency_signature_p99_ms': .5, 'latency_cns_p99_ms': .5,
                'unclean_crash_recovered': True,
            })
        stages.append(stage)
    return {
        'dataset_sha256': D('d'), 'protocol_sha256': D('b'),
        'paired_text_workload_sha256': D('c'),
        'source_commit': 'f'*40, 'host_id': 'host-1',
        'max_retained_task_score_drop': 0.01,
        'stages': stages,
    }


def test_b_threeway_both_future_windows_still_no_promotion():
    rows, bundle = b_fixture()
    report = threeway_prequential_audit(rows, D('d'), bundle,
                                        bootstrap=100, min_future_groups=2)
    assert report['future_brier_precheck_positive']
    assert report['production_admission'] == 'BLOCKED'
    assert not report['independent_no_change_and_ndu_verified']
    assert set(report['future_windows']) == {'future_1', 'future_2'}
    assert report['ood_false_acceptance_fraction']['learned_head'] == 0


@pytest.mark.parametrize('change', ['digest', 'label', 'time', 'frozen', 'missing', 'windows'])
def test_b_rejects_postlabel_edit_or_missing_matching_control(change):
    rows, bundle = b_fixture()
    if change == 'digest':
        bundle['prelabel_journal']['records'][0]['prediction_digests']['learned_head'] = D('z')
    elif change == 'label':
        bundle['prelabel_journal']['records'][0]['label'] = 1
    elif change == 'time':
        bundle['prelabel_journal']['records'][0]['predicted_at'] = '2026-10-01T00:00:00+00:00'
    elif change == 'frozen':
        bundle['prelabel_journal']['records'][0]['frozen_head_digest'] = D('z')
    elif change == 'missing':
        bundle['snapshots'].pop('frozen_head')
    else:
        rows[8]['future_window'] = 'future_2'
    with pytest.raises(ValueError):
        threeway_prequential_audit(rows, D('d'), bundle,
                                   bootstrap=100, min_future_groups=1)


def test_c_all_stages_complete_is_only_unverified_schema():
    report = multimodal_cost_audit(c_fixture())
    assert report['status'] == 'SCHEMA_COMPLETE_UNVERIFIED'
    assert len(report['stage_deltas']) == 3
    assert report['selection'] == 'NOT_AUTHORIZED'
    assert not report['target_host_attested']


@pytest.mark.parametrize('change', ['probe', 'missing_task', 'partial', 'batch', 'p99', 'wal', 'workload'])
def test_c_rejects_fake_or_incompatible_modality_bench(change):
    m = c_fixture()
    if change == 'probe':
        m['stages'][1]['frozen_text_probe_sha256'] = D('f')
    elif change == 'missing_task':
        del m['stages'][2]['tasks']['visual_relations']
    elif change == 'partial':
        m['stages'][3]['scales'][3]['actually_executed_cell_count'] = 3
    elif change == 'batch':
        m['stages'][2]['scales'][1]['encoder_batch_calls'] = 999999
    elif change == 'p99':
        m['stages'][0]['scales'][0]['request_p99_ms'] = 0
    elif change == 'wal':
        m['stages'][1]['scales'][1]['unclean_crash_recovered'] = False
    else:
        m['stages'][0]['scales'][0]['paired_text_workload_sha256'] = D('e')
    assert multimodal_cost_audit(m)['status'] == 'BLOCKED'


def test_abc_missing_real_models_never_selects_winner():
    b_rows, b = b_fixture()
    b_report = threeway_prequential_audit(
        b_rows, D('d'), b, bootstrap=100, min_future_groups=2)
    c_report = multimodal_cost_audit(c_fixture())
    blocked = joint_abc_evidence_gate({
        'A': {'experiment': 'A5', 'encoders': {}}, 'B': b_report, 'C': c_report})
    assert blocked['status'] == 'BLOCKED'
    assert blocked['candidate_stem_selected'] is None
    assert blocked['production_admission'] == 'BLOCKED'



def media_policy():
    return {
        'schema': 'hepta.stem.media-review-policy.v1',
        'protocol_sha256': D('b'),
        'minimum_pairs_per_group': 1,
        'minimum_distinct_source_groups_per_group': 1,
        'minimum_both_correct_fraction': .95,
        'maximum_unresponsive_fraction': 0,
    }


def media_truth_flip_report():
    return {
        'schema': 'hepta.stem.paired-modality-audit.v1',
        'prediction_sha256': D('c'),
        'observer_receipt_sha256': D('e'),
        'actual_independent_observer_verified': False,
        'production_accepted': False,
        'groups': {name: {
            'pairs': 1, 'both_correct': 1, 'original_correct': 1,
            'changed_correct': 1, 'prediction_changed': 1,
            'unresponsive_to_truth_flip': 0,
            'distinct_source_groups': 1,
        } for name in (
            'holdout/image/media_substitution',
            'holdout/audio/media_substitution',
            'holdout/video/temporal_reordering',
        )},
    }


def test_abc_even_self_reported_complete_never_grants_permission():
    from neuron_shared_encoder.validation_v3 import FIVE_ARM_CANDIDATES
    b_rows, b = b_fixture()
    observed = joint_abc_evidence_gate({
        'A': {'experiment': 'A5', 'dataset_sha256': D('d'),
              'evidence_class': 'REAL_MODEL_LOCAL_SHADOW',
              'encoders': {name: {} for name, _, _, _ in FIVE_ARM_CANDIDATES}},
        'B': threeway_prequential_audit(b_rows, D('d'), b,
                                        bootstrap=100, min_future_groups=2),
        'C': multimodal_cost_audit(c_fixture()),
        'media_counterfactual': media_truth_flip_report(),
        'media_policy': media_policy(),
    })
    assert observed['status'] == 'RESEARCH_REVIEW_CANDIDATE_UNVERIFIED'
    assert not observed['independent_ndu_and_final_use_verified']
    assert observed['candidate_stem_selected'] is None


def test_c_rejects_impossible_projector_budget():
    m = c_fixture()
    m['stages'][1]['projection_parameters'] = 999999999999
    assert multimodal_cost_audit(m)['status'] == 'BLOCKED'


def test_b_precommit_unknown_fields_fail_closed():
    rows, bundle = b_fixture()
    bundle['prelabel_journal']['records'][0]['gold_answer'] = 1
    with pytest.raises(ValueError):
        threeway_prequential_audit(rows, D('d'), bundle,
                                   bootstrap=100, min_future_groups=1)


def test_b_learned_head_must_start_with_exact_frozen_initial_weights():
    rows, evidence = b_fixture()
    evidence['snapshots']['learned_head']['initial_head_digest'] = D('9')
    with pytest.raises(ValueError, match='identical initialization'):
        threeway_prequential_audit(rows, D('d'), evidence,
                                   bootstrap=100, min_future_groups=1)


def test_c_retention_regression_above_preregistered_limit_blocks():
    m = c_fixture()
    m['stages'][3]['tasks']['text_decision']['score'] = .65
    result = multimodal_cost_audit(m)
    assert result['status'] == 'BLOCKED'
    assert any('negative transfer' in x for x in result['issues'])


def test_c_missing_retention_limit_blocks_even_with_full_telemetry():
    m = c_fixture()
    del m['max_retained_task_score_drop']
    assert multimodal_cost_audit(m)['status'] == 'BLOCKED'


def test_evidence_loader_rejects_duplicate_json_keys(tmp_path):
    from hashlib import sha256
    path = tmp_path / 'bad.json'
    body = b'{"dataset_sha256":"a","dataset_sha256":"b"}'
    path.write_bytes(body)
    with pytest.raises(ValueError, match='duplicate'):
        _pinned_json(str(path), sha256(body).hexdigest())


def test_c_cumulative_negative_transfer_does_not_roll_the_baseline_forward():
    m = c_fixture()
    m['stages'][1]['tasks']['text_decision']['score'] = .694
    m['stages'][2]['tasks']['text_decision']['score'] = .688
    assert multimodal_cost_audit(m)['status'] == 'BLOCKED'


def test_b_postlabel_updates_chain_valid_and_brier_units_match():
    rows, evidence = b_fixture()
    result = threeway_prequential_audit(
        rows, D('d'), evidence, bootstrap=100, min_future_groups=2)
    assert result['postlabel_update_count'] == 1
    assert result['postlabel_no_update_count'] == 7
    assert result['postlabel_head_update_chain_consistent']
    for window in result['future_windows'].values():
        for summary in window['scores'].values():
            assert summary['brier_normalized'] == pytest.approx(summary['brier'] / 2)


@pytest.mark.parametrize('mutation', [
    'omit_update', 'update_before_label', 'unsealed_prediction',
    'fork_head', 'false_noop', 'false_update', 'wrong_final',
    'changed_label', 'extra_postlabel_field',
])
def test_b_postlabel_chain_rejects_spoofed_learning(mutation):
    rows, bundle = b_fixture()
    updates = bundle['postlabel_updates']
    if mutation == 'omit_update':
        updates.pop()
    elif mutation == 'update_before_label':
        updates[0]['updated_at'] = rows[8]['event_time']
    elif mutation == 'unsealed_prediction':
        updates[0]['prediction_record_digest'] = D('a')
    elif mutation == 'fork_head':
        bundle['snapshots']['learned_head']['head_digests_by_row'][9] = D('c')
        bundle['prelabel_journal']['records'][1]['learned_head_digest_before'] = D('c')
    elif mutation == 'false_noop':
        updates[0]['update_kind'] = 'no_update'
    elif mutation == 'false_update':
        updates[1]['update_kind'] = 'updated'
    elif mutation == 'wrong_final':
        bundle['snapshots']['learned_head']['final_head_digest'] = D('c')
    elif mutation == 'changed_label':
        updates[0]['label_digest'] = D('c')
    else:
        updates[0]['target_answer'] = 1
    with pytest.raises(ValueError):
        threeway_prequential_audit(
            rows, D('d'), bundle, bootstrap=100, min_future_groups=2)


def test_b_rejects_different_initial_prediction_despite_matching_weights():
    rows, evidence = b_fixture()
    evidence['snapshots']['learned_head']['probabilities'][8] = [.95, .05]
    # An update to its signed self-report would still not explain a
    # disagreement before the first future supervision is available.
    evidence['prelabel_journal']['records'][0]['prediction_digests']['learned_head'] = (
        canonical_digest({'row_id': rows[8]['row_id'],
                          'probabilities': [.95, .05]}))
    with pytest.raises(ValueError, match='prediction differs'):
        threeway_prequential_audit(
            rows, D('d'), evidence, bootstrap=100, min_future_groups=2)


@pytest.mark.parametrize('field', [
    'encoder_bundle_sha256', 'feature_pipeline_sha256',
    'runtime_profile_sha256', 'input_contract_sha256',
])
def test_b_refuses_changed_feature_pipeline_or_runtime(field):
    rows, evidence = b_fixture()
    evidence['snapshots']['learned_head'][field] = D('e')
    with pytest.raises(ValueError, match='feature-runtime mismatch'):
        threeway_prequential_audit(
            rows, D('d'), evidence, bootstrap=100, min_future_groups=2)


@pytest.mark.parametrize('mutation', [
    'shared_stem', 'missing_adapter', 'missing_media_source',
    'missing_active_modality_memory', 'zero_head', 'missing_wal_fsync',
    'missing_recovery_trace', 'bad_queue', 'missing_run_id',
])
def test_c_requires_actual_differentiation_and_recovery_identity(mutation):
    m = c_fixture()
    stage = m['stages'][1]
    scale = stage['scales'][0]
    if mutation == 'shared_stem':
        stage['shared_text_stem_sha256'] = D('e')
    elif mutation == 'missing_adapter':
        stage['modality_adapter_sha256'] = None
    elif mutation == 'missing_media_source':
        stage['paired_media_dataset_sha256'] = None
    elif mutation == 'missing_active_modality_memory':
        scale['active_modality_peak_bytes'] = 0
    elif mutation == 'zero_head':
        scale['head_resident_bytes'] = 0
    elif mutation == 'missing_wal_fsync':
        scale['wal_fsync_count'] = 0
    elif mutation == 'missing_recovery_trace':
        scale['recovery_trace_sha256'] = None
    elif mutation == 'bad_queue':
        scale['queue_peak_depth'] = scale['requests'] + 1
    else:
        scale['run_id'] = ''
    assert multimodal_cost_audit(m)['status'] == 'BLOCKED'


def test_c_malformed_queue_metric_is_blocked_not_crash():
    m = c_fixture()
    m['stages'][1]['scales'][0]['queue_peak_depth'] = 'unknown'
    report = multimodal_cost_audit(m)
    assert report['status'] == 'BLOCKED'
    assert any('queue_peak_depth' in issue for issue in report['issues'])


def test_b_future_label_availability_cannot_be_embedded_into_prelabel_seal():
    rows, evidence = b_fixture()
    evidence['prelabel_journal']['records'][0]['label_available_at'] = (
        rows[8]['event_time'].replace('00:00:00', '01:00:00'))
    with pytest.raises(ValueError, match='precommit fields'):
        threeway_prequential_audit(
            rows, D('d'), evidence, bootstrap=100, min_future_groups=2)


def test_b_delayed_actual_label_arrival_blocks_premature_update():
    rows, evidence = b_fixture()
    evidence['postlabel_updates'][0]['label_available_at'] = (
        rows[8]['event_time'].replace('00:00:00', '03:00:00'))
    with pytest.raises(ValueError, match='before label availability'):
        threeway_prequential_audit(
            rows, D('d'), evidence, bootstrap=100, min_future_groups=2)


def test_abc_without_image_audio_video_truth_flips_never_advances():
    from neuron_shared_encoder.validation_v3 import FIVE_ARM_CANDIDATES
    b_rows, b = b_fixture()
    without_media = joint_abc_evidence_gate({
        'A': {'experiment': 'A5', 'dataset_sha256': D('d'),
              'evidence_class': 'REAL_MODEL_LOCAL_SHADOW',
              'encoders': {name: {} for name, _, _, _ in FIVE_ARM_CANDIDATES}},
        'B': threeway_prequential_audit(
            b_rows, D('d'), b, bootstrap=100, min_future_groups=2),
        'C': multimodal_cost_audit(c_fixture()),
    })
    assert without_media['status'] == 'BLOCKED'
    assert without_media['media_necessity']['status'] == 'BLOCKED'
    assert without_media['candidate_stem_selected'] is None


def test_c_media_semantic_shadow_pass_still_no_authority():
    result = paired_media_necessity_audit(
        media_truth_flip_report(), media_policy(),
        expected_protocol_sha256=D('b'))
    assert result['status'] == 'SCHEMA_COMPLETE_UNVERIFIED'
    assert len(result['media_groups']) == 3
    assert result['independent_media_truth_verified'] is False
    assert result['production_admission'] == 'BLOCKED'


@pytest.mark.parametrize('mutation', [
    'missing_image', 'missing_audio', 'missing_video_order',
    'wrong_protocol', 'incorrect_truth_flip', 'unresponsive_media',
    'inconsistent_counts', 'forged_observer', 'unbound_prediction',
])
def test_c_semantic_necessity_rejects_mocked_media_success(mutation):
    report = media_truth_flip_report()
    policy = media_policy()
    key = 'holdout/video/temporal_reordering'
    if mutation == 'missing_image':
        report['groups'].pop('holdout/image/media_substitution')
    elif mutation == 'missing_audio':
        report['groups'].pop('holdout/audio/media_substitution')
    elif mutation == 'missing_video_order':
        report['groups'].pop(key)
        report['groups']['holdout/video/media_substitution'] = {
            'pairs': 1, 'both_correct': 1, 'original_correct': 1,
            'changed_correct': 1, 'prediction_changed': 1,
            'unresponsive_to_truth_flip': 0, 'distinct_source_groups': 1}
    elif mutation == 'wrong_protocol':
        policy['protocol_sha256'] = D('f')
    elif mutation == 'incorrect_truth_flip':
        report['groups'][key]['both_correct'] = 0
    elif mutation == 'unresponsive_media':
        report['groups'][key]['prediction_changed'] = 0
        report['groups'][key]['unresponsive_to_truth_flip'] = 1
    elif mutation == 'inconsistent_counts':
        report['groups'][key]['both_correct'] = 2
    elif mutation == 'forged_observer':
        report['actual_independent_observer_verified'] = True
    else:
        report['prediction_sha256'] = 'unbound'
    result = paired_media_necessity_audit(
        report, policy, expected_protocol_sha256=D('b'))
    assert result['status'] == 'BLOCKED'


def test_abc_manifest_overflow_float_rejected_at_pinned_decode(tmp_path):
    from hashlib import sha256
    payload = '{"stages":[{"peak_rss_bytes":1e9999}]}'
    path = tmp_path / 'huge-exponent.json'
    path.write_text(payload)
    with pytest.raises(ValueError, match='nonfinite JSON float exponent'):
        _pinned_json(str(path), sha256(payload.encode()).hexdigest())
