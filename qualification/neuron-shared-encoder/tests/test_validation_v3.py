"""Adversarial E1–E5 shadow qualification tests, no external weights/network."""
from __future__ import annotations

from copy import deepcopy
import math
import pytest
import torch

from neuron_shared_encoder.validation_v3 import (
    BUDGETS, ENCODERS, KINDS, SmallHead, canonical_digest, digest_bytes,
    encoder_matrix_contract, evaluate_shadow, head_trials, reuse_keys, reuse_trial,
    scale_receipt_audit, _scores,
)

D = lambda c: c * 64


def dataset(n: int = 40):
    rows = []
    for split, count in [('train', n), ('validation', n), ('future', n), ('ood', n)]:
        for j in range(count):
            rows.append({'row_id': f'{split}-{j}', 'source_group': f'{split}-group-{j}',
                         'split': split, 'principal': 'tenant-1', 'organ_id': 'organ-1',
                         'cell_id': 'cell-1', 'question': 'Choose?', 'options': ['no', 'yes'],
                         'state': f'private-{j}', 'label': j % 2})
    return rows


def make_snapshots(rows, better: bool = True):
    truth = [[.95, .05] if r['label'] == 0 else [.05, .95] for r in rows]
    baseline_probs = [[.6, .4] if r['label'] == 0 else [.4, .6] for r in rows]
    if not better:
        truth = [[.05, .95] if r['label'] == 0 else [.95, .05] for r in rows]
    template = {'dataset_sha256': D('d'), 'source_commit': D('f'),
                'cell_scope': ['tenant-1', 'organ-1', 'cell-1'],
                'row_ids': [r['row_id'] for r in rows]}
    baseline = {**template, 'role': 'frozen_no_change', 'artifact_digest': D('a'),
                'probabilities': baseline_probs}
    candidate = {**template, 'role': 'candidate', 'artifact_digest': D('b'),
                 'probabilities': truth}
    return baseline, candidate


def test_parameter_budgets_all_head_types():
    for size in BUDGETS:
        for kind in KINDS:
            try:
                head = SmallHead(kind, 128, 4, size)
            except ValueError as exc:
                assert 'exceeds parameter budget' in str(exc)
                continue
            assert head.parameter_count <= size
            assert head(torch.randn(3, 128)).shape == (3, 4)


def test_static_gate_exact_fold_up_to_float_rounding():
    torch.manual_seed(17)
    head = SmallHead('static_gate', 128, 4, 2048)
    with torch.no_grad():
        head.static_gate.copy_(torch.rand(128))
    values = torch.randn(63, 128)
    torch.testing.assert_close(head(values), head.fold_static_gate()(values), atol=2e-6, rtol=2e-6)
    assert head.fold_static_gate().weight.shape == (4, 128)


def test_static_gate_fold_rejects_others():
    with pytest.raises(ValueError, match='only static'):
        SmallHead('linear', 16, 2, 2048).fold_static_gate()


def test_dynamic_gate_is_input_conditional_and_nonlinear():
    torch.manual_seed(55)
    head = SmallHead('dynamic_gate', 128, 4, 16384)
    x, y = torch.randn(128), torch.randn(128)
    with torch.no_grad():
        assert not torch.allclose(torch.sigmoid(head.gate(x)), torch.sigmoid(head.gate(y)))
        midpoint_error = (head((x+y)/2) - (head(x)+head(y))/2).abs().max().item()
        assert midpoint_error > 1e-5


def test_honest_head_learning_matrix():
    torch.manual_seed(8)
    features = torch.randn(28, 16)
    labels = torch.tensor([i % 2 for i in range(28)])
    splits = ['train'] * 16 + ['validation'] * 4 + ['future'] * 4 + ['ood'] * 4
    first = head_trials(features, labels, splits, budgets=(2048,), steps=1, batch=8)
    assert first['production_admission'] == 'BLOCKED'
    assert len(first['candidates']) == len(KINDS)
    assert all(item['status'] == 'EVALUATED_SHADOW' for item in first['candidates'])
    gate = next(r for r in first['candidates'] if r['kind'] == 'static_gate')
    assert gate['folded_linear_max_abs_error'] < 1e-5
    assert gate['folded_linear_parameters'] < gate['parameters']
    assert next(r for r in first['candidates'] if r['kind'] == 'dynamic_gate')['rank'] > 0


def test_bad_probabilities_cannot_appear_as_metrics():
    with pytest.raises(ValueError, match='normalized'):
        _scores(torch.tensor([[.5, .6]]), torch.tensor([0]))
    with pytest.raises(ValueError, match='nonfinite'):
        _scores(torch.tensor([[float('nan'), 1.]]), torch.tensor([0]))


def test_reuse_counts_physical_encoder_calls_and_rows():
    rows = dataset(8)
    calls = []
    def fake_encoder(batch):
        calls.append([b['row_id'] for b in batch])
        return torch.stack([torch.tensor([float(len(r['state'])), 1.]) for r in batch])
    joint_f, joint = reuse_trial(rows, fake_encoder, encoder_digest=D('a'),
                                 tokenizer_digest=D('b'), normalizer_digest=D('c'),
                                 mode='joint', batch_size=8)
    public_f, public = reuse_trial(rows, fake_encoder, encoder_digest=D('a'),
                                   tokenizer_digest=D('b'), normalizer_digest=D('c'),
                                   mode='public', batch_size=8)
    assert joint_f.shape == public_f.shape == (32, 2)
    assert joint['distinct_input_keys'] == 32
    assert joint['encoder_forward_rows'] == 32
    assert public['distinct_input_keys'] == 4  # one public input per temporal split
    assert public['encoder_forward_rows'] == 4
    assert joint['encoder_forward_invocations'] == 4
    assert public['encoder_forward_invocations'] == 1
    assert sum(len(batch) for batch in calls) == 36
    assert public['authorization_verified'] is False


def test_reuse_key_fences_scope_and_artifacts():
    row = dataset(8)[0]
    opts = dict(encoder_digest=D('a'), tokenizer_digest=D('b'), normalizer_digest=D('c'), mode='public')
    initial = reuse_keys(row, **opts)
    assert initial != reuse_keys({**row, 'principal': 'tenant-2'}, **opts)
    assert initial != reuse_keys({**row, 'split': 'future'}, **opts)
    assert initial != reuse_keys(row, **{**opts, 'generation': 2})
    assert initial != reuse_keys(row, **{**opts, 'authority_epoch': 2})
    assert initial != reuse_keys(row, **{**opts, 'purpose': 'prediction'})
    assert initial != reuse_keys(row, **{**opts, 'tokenizer_digest': D('d')})
    assert initial == reuse_keys({**row, 'state': 'different private value'}, **opts)
    assert initial != reuse_keys({**row, 'state': 'different private value'}, **{**opts, 'mode': 'joint'})


def test_reuse_disallows_unpinned_artifacts_and_invalid_encoder_output():
    row = dataset(8)[0]
    with pytest.raises(ValueError, match='digests required'):
        reuse_keys(row, encoder_digest='bad', tokenizer_digest=D('b'), normalizer_digest=D('c'))
    with pytest.raises(ValueError, match='malformed'):
        reuse_trial([row], lambda _: torch.tensor([[float('nan')]]),
                    encoder_digest=D('a'), tokenizer_digest=D('b'), normalizer_digest=D('c'), mode='joint')


def test_e4_good_future_signal_never_promotes():
    rows = dataset(40)
    baseline, candidate = make_snapshots(rows)
    result = evaluate_shadow(rows, D('d'), baseline, candidate, bootstrap_repeats=100)
    assert result['future_groups'] == 40
    assert result['shadow_signal'] == 'POSITIVE'
    assert result['negative_transfer_group_fraction'] == 0
    assert result['bootstrap_95pct_group_mean_improvement'][0] > 0
    assert result['selection'] == 'NOT_AUTHORIZED'
    assert result['production_admission'] == 'BLOCKED'


def test_e4_negative_transfer_blocks_positive_signal():
    rows = dataset(40)
    baseline, candidate = make_snapshots(rows, better=False)
    result = evaluate_shadow(rows, D('d'), baseline, candidate, bootstrap_repeats=100)
    assert result['negative_transfer_group_count'] == 40
    assert result['shadow_signal'] == 'INCONCLUSIVE_OR_NEGATIVE'


@pytest.mark.parametrize('field,setting,expected', [
    ('role', 'candidate', 'role'),
    ('dataset_sha256', D('e'), 'dataset'),
    ('artifact_digest', 'no', 'provenance'),
    ('row_ids', ['missing'], 'row order'),
    ('cell_scope', ['tenant-2','organ-1','cell-1'], 'cross-cell'),
])
def test_e4_snapshot_identity_violations_rejected(field, setting, expected):
    rows = dataset(8)
    baseline, candidate = make_snapshots(rows)
    baseline[field] = setting
    with pytest.raises(ValueError, match=expected):
        evaluate_shadow(rows, D('d'), baseline, candidate, bootstrap_repeats=100)


def test_e4_identical_candidate_digest_rejected():
    rows = dataset(8)
    baseline, candidate = make_snapshots(rows)
    candidate['artifact_digest'] = baseline['artifact_digest']
    with pytest.raises(ValueError, match='cannot'):
        evaluate_shadow(rows, D('d'), baseline, candidate, bootstrap_repeats=100)


def test_e1_missing_real_artifacts_keeps_blocked():
    report = encoder_matrix_contract({'dataset_sha256': D('a')})
    assert report['status'] == 'BLOCKED'
    assert len(report['missing_or_invalid']) >= 4
    assert report['production_admission'] == 'BLOCKED'


def test_e1_complete_schema_still_unverified():
    report = encoder_matrix_contract({
        'dataset_sha256': D('a'), 'split_manifest_sha256': D('b'),
        'frozen_no_change_sha256': D('c'),
        'training': {'seed': 1, 'steps': 20, 'batch': 8, 'optimizer': 'AdamW', 'learning_rate': 1e-3},
        'encoders': {name: {'bundle_sha256': D('a'), 'weights_sha256': D('b'),
                            'tokenizer_sha256': D('c')} for name in ENCODERS},
        'question_option_layout': 'joint q/options/state'},
    )
    assert report['status'] == 'SCHEMA_COMPLETE_UNVERIFIED'
    assert report['real_encoder_runs_completed'] is False


def test_e5_no_host_evidence_blocks():
    report = scale_receipt_audit({})
    assert report['schema_status'] == 'BLOCKED'
    assert len(report['issues']) == 4


def test_e5_forged_complete_schema_cannot_authorize():
    source = {key: 1 for key in (
        'requests', 'distinct_input_keys', 'encoder_forward_rows',
        'encoder_forward_invocations', 'throughput_rps', 'cpu_seconds',
        'rss_peak_bytes', 'request_p95_ms', 'request_p99_ms', 'batch_p95_ms',
        'batch_p99_ms', 'wal_written_bytes', 'recovery_seconds',
        'failed_replay_count', 'latency_cas_p99_ms',
        'latency_signature_p99_ms', 'latency_cns_p99_ms')}
    rows = [{**source, 'cell_count': count, 'run_id': 'fake-run',
             'source_commit': D('f'), 'host_id': 'fake-host',
             'device': 'cpu', 'gpu_peak_bytes': None} for count in [64,256,1024,4096]]
    report = scale_receipt_audit({'results': rows})
    assert report['schema_status'] == 'COMPLETE_UNVERIFIED'
    assert report['target_host_verified'] is False
    assert report['production_admission'] == 'BLOCKED'
    rows[0]['encoder_forward_rows'] = 10
    assert scale_receipt_audit({'results': rows})['schema_status'] == 'BLOCKED'


def test_e1_real_run_refuses_missing_staged_weights_without_mock_fallback():
    from neuron_shared_encoder.validation_v3 import run_real_encoder_matrix
    rows = dataset(8)
    matrix = {'dataset_sha256': D('d'), 'split_manifest_sha256': D('b'),
              'frozen_no_change_sha256': D('c'),
              'training': {'seed': 0, 'steps': 1, 'batch': 4,
                           'optimizer': 'AdamW', 'learning_rate': 1e-3},
              'encoders': {kind: {'bundle_sha256': D('a'), 'weights_sha256': D('b'),
                                 'tokenizer_sha256': D('c'), 'local_path': '/not/a/staged/checkpoint'}
                           for kind in ENCODERS},
              'question_option_layout': 'explicit-laya-vs-generic-controls'}
    assert encoder_matrix_contract(matrix)['status'] == 'SCHEMA_COMPLETE_UNVERIFIED'
    with pytest.raises(FileNotFoundError, match='missing local'):
        run_real_encoder_matrix(rows, D('d'), matrix)



def test_private_state_encoder_is_called_and_cost_is_counted():
    rows = dataset(4)
    seen = []
    def frozen_encoder(batch):
        seen.extend((r['question'], r['state']) for r in batch)
        return torch.tensor([[float(len(r['state'])), float(len(r['question']))]
                             for r in batch])
    kw = dict(encoder_digest=D('a'), tokenizer_digest=D('b'),
              normalizer_digest=D('c'), batch_size=16)
    _, joint = reuse_trial(rows, frozen_encoder, mode='joint', **kw)
    _, public = reuse_trial(rows, frozen_encoder, mode='public', **kw)
    _, state = reuse_trial(rows, frozen_encoder, mode='private_state', **kw)
    assert state['encoder_forward_rows'] == 16  # four states per split
    assert public['encoder_forward_rows'] == 4
    assert joint['encoder_forward_rows'] == 16
    assert sum(r[1] != '' for r in seen) == 32
    assert all(q == 'Encode the Cell-local state only.'
               for q, _ in seen if q.startswith('Encode the Cell-local'))
    assert state['authorization_verified'] is False
    assert public['encoder_forward_rows'] + state['encoder_forward_rows'] > joint['encoder_forward_rows']


def test_private_state_cache_does_not_cross_cell_scope_or_question_identity():
    row = dataset(4)[0]
    opts = dict(encoder_digest=D('a'), tokenizer_digest=D('b'),
                normalizer_digest=D('c'), mode='private_state')
    original = reuse_keys(row, **opts)
    assert original == reuse_keys({**row, 'question': 'different',
                                   'options': ['X', 'Y']}, **opts)
    assert original != reuse_keys({**row, 'state': 'different'}, **opts)
    assert original != reuse_keys({**row, 'cell_id': 'cell-other'}, **opts)
    assert original != reuse_keys({**row, 'organ_id': 'organ-other'}, **opts)
    assert original != reuse_keys({**row, 'split': 'future'}, **opts)
    assert original != reuse_keys({**row, 'principal': 'other'}, **opts)
    with pytest.raises(ValueError, match='scope'):
        reuse_keys({**row, 'cell_id': ''}, **opts)


def five_arm_plan():
    from neuron_shared_encoder.validation_v3 import FIVE_ARM_CANDIDATES
    return {
        'dataset_sha256': D('a'), 'split_manifest_sha256': D('b'),
        'frozen_no_change_sha256': D('c'), 'data_use_approved': True,
        'question_option_layout': 'common-state-question-options-v1',
        'training': {'seed': 42, 'steps': 100, 'batch': 16,
                     'optimizer': 'AdamW', 'learning_rate': 1e-3},
        'encoders': {
            name: {'backend_kind': backend, 'repository': repo or 'reviewed-laya-package',
                   'revision': 'd' * 40,
                   'bundle_sha256': format(100 + index, '064x'),
                   'weights_sha256': format(1 + index, '064x'),
                   'tokenizer_sha256': D('a'),
                   'license_approved': True, 'local_code_reviewed': True,
                   'local_path': '/models/not-provisioned'}
            for index, (name, backend, repo, _) in enumerate(FIVE_ARM_CANDIDATES)
        },
    }


def test_a5_exact_five_model_pins_are_required_without_claiming_load():
    from neuron_shared_encoder.validation_v3 import five_arm_matrix_contract
    manifest = five_arm_plan()
    audit = five_arm_matrix_contract(manifest)
    assert audit['status'] == 'SCHEMA_COMPLETE_UNVERIFIED'
    assert not audit['real_encoder_runs_completed']
    assert audit['production_admission'] == 'BLOCKED'
    assert len(manifest['encoders']) == 5
    for dropped in manifest['encoders']:
        bad = deepcopy(manifest)
        bad['encoders'].pop(dropped)
        assert five_arm_matrix_contract(bad)['status'] == 'BLOCKED'


def test_a5_wrong_gte_identity_revision_or_license_blocks():
    from neuron_shared_encoder.validation_v3 import five_arm_matrix_contract
    for field, invalid in [('repository', 'answerdotai/ModernBERT-base'),
                           ('revision', 'floating-main'), ('license_approved', False),
                           ('weights_sha256', None), ('backend_kind', 'mmbert-joint')]:
        bad = deepcopy(five_arm_plan())
        bad['encoders']['gte-modernbert-base'][field] = invalid
        assert five_arm_matrix_contract(bad)['status'] == 'BLOCKED', field


def test_a5_no_checkpoint_refuses_to_run_before_mock_substitution():
    from neuron_shared_encoder.validation_v3 import run_real_encoder_matrix
    with pytest.raises(FileNotFoundError, match='missing local'):
        run_real_encoder_matrix(dataset(4), D('a'), five_arm_plan(), five_arm=True)


def test_a5_same_weights_under_five_names_rejected():
    from neuron_shared_encoder.validation_v3 import five_arm_matrix_contract
    spec = five_arm_plan()
    for arm in spec['encoders'].values():
        arm['weights_sha256'] = D('f')
    report = five_arm_matrix_contract(spec)
    assert report['status'] == 'BLOCKED'
    assert any('independent model weight' in s for s in report['missing_or_invalid'])


def test_a5_bad_optimizer_type_fails_closed():
    from neuron_shared_encoder.validation_v3 import five_arm_matrix_contract
    spec = five_arm_plan()
    spec['training']['optimizer'] = None
    assert five_arm_matrix_contract(spec)['status'] == 'BLOCKED'


def test_e2_future_labels_cannot_resize_option_schema():
    # Two choices were visible in TRAIN. A future-only third answer is
    # not allowed to silently change the architecture after training.
    torch.manual_seed(17)
    features = torch.randn(16, 8)
    splits = ['train']*8 + ['validation']*2 + ['future']*3 + ['ood']*3
    labels = torch.tensor([0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 2, 2, 2, 0, 1, 2])
    from neuron_shared_encoder.validation_v3 import head_trials
    with pytest.raises(ValueError, match='outside frozen option space'):
        head_trials(features, labels, splits, kinds=('linear',),
                    budgets=(2048,), steps=1)
    report = head_trials(features, labels, splits, kinds=('linear',),
                         budgets=(2048,), num_classes=3, steps=1)
    assert report['frozen_output_class_count'] == 3
    assert report['class_count_source'] == 'frozen_registered_option_width'
    assert report['candidates'][0]['status'] == 'EVALUATED_SHADOW'


def test_e2_declared_options_not_replaced_with_future_label_max():
    torch.manual_seed(20)
    features = torch.randn(16, 8)
    splits = ['train']*8 + ['validation']*2 + ['future']*3 + ['ood']*3
    labels = torch.tensor([0, 1]*8)
    report = head_trials(features, labels, splits, kinds=('linear',),
                         budgets=(2048,), num_classes=4, steps=1)
    assert report['frozen_output_class_count'] == 4
    with pytest.raises(ValueError, match='2..16'):
        head_trials(features, labels, splits, kinds=('linear',),
                    budgets=(2048,), num_classes=17, steps=1)


def test_v3_identical_option_width_is_not_enough_for_head_comparison():
    from neuron_shared_encoder.validation_v3 import frozen_option_count
    rows = dataset(8)
    assert frozen_option_count(rows) == 2
    altered = deepcopy(rows)
    altered[-1]['options'] = ['yes', 'no']
    with pytest.raises(ValueError, match='identical ordered choices'):
        frozen_option_count(altered)
    altered[-1]['options'] = ['no', 'new option']
    with pytest.raises(ValueError, match='identical ordered choices'):
        frozen_option_count(altered)


def test_v3_fixed_option_inventory_validated_before_real_model_attempt():
    from neuron_shared_encoder.validation_v3 import run_real_encoder_matrix
    rows = dataset(8)
    rows[0]['options'] = ['yes', 'no']
    with pytest.raises(ValueError, match='identical ordered choices'):
        run_real_encoder_matrix(rows, D('a'), five_arm_plan(), five_arm=True)


def test_e1_manifest_nonfinite_exponent_rejected_before_qualification(tmp_path):
    from hashlib import sha256
    from neuron_shared_encoder.validation_v3 import _read_pinned_json
    path = tmp_path / 'in.json'
    content = '{"training":{"learning_rate":1e9999}}'
    path.write_text(content)
    with pytest.raises(ValueError, match='nonfinite JSON evidence float exponent'):
        _read_pinned_json(str(path), sha256(content.encode()).hexdigest())
