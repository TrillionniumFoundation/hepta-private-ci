"""Actual B/C audit behavior on synthetic contract fixtures (not model evidence)."""
from __future__ import annotations

from copy import deepcopy
import pytest

from neuron_shared_encoder.abc_evidence import (
    ROLES, STAGES, SCALES, _pinned_json, multimodal_cost_audit,
    threeway_prequential_audit, joint_abc_evidence_gate,
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
        snapshots[role] = {
            'role': role, 'dataset_sha256': D('d'),
            'source_commit': 'e' * 40,
            'cell_scope': ['p', 'o', 'c'],
            'artifact_digest': D(sha),
            'row_ids': [r['row_id'] for r in rows], 'probabilities': p,
        }
    snapshots['frozen_head']['head_digest'] = D('f')
    snapshots['learned_head']['head_digests_by_row'] = [D('9') for _ in rows]
    records = []
    for i, row in enumerate(rows):
        if row['split'] != 'future':
            continue
        records.append({
            'row_id': row['row_id'], 'future_window': row['future_window'],
            'frozen_head_digest': D('f'),
            'learned_head_digest_before': D('9'),
            'input_digest': canonical_digest({
                'state': row['state'], 'question': row['question'], 'options': row['options'],
            }),
            'prediction_digests': {
                role: canonical_digest({
                    'row_id': row['row_id'], 'probabilities': snapshots[role]['probabilities'][i],
                }) for role in ROLES
            },
            'predicted_at': row['event_time'],
            'label_available_at': row['event_time'].replace('00:00:00', '01:00:00'),
        })
    return rows, {
        'dataset_sha256': D('d'), 'snapshots': snapshots,
        'prelabel_journal': {
            'frozen_head_digest': D('f'), 'acceptance_threshold': .8,
            'records': records,
        },
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
                'encoder_forward_rows': n*2, 'encoder_batch_calls': n//2,
                'host_id': 'host-1', 'source_commit': 'f'*40,
                'paired_text_workload_sha256': D('c'),
                'device': 'cpu', 'gpu_peak_bytes': None,
                'throughput_rps': 10, 'cpu_seconds': 1, 'rss_peak_bytes': 10000000 + n,
                'request_p95_ms': 1, 'request_p99_ms': 2,
                'batch_p95_ms': 2, 'batch_p99_ms': 3,
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
