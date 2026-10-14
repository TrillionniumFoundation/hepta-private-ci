from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
import torch
from neuron_shared_encoder.strict_e2 import equal_parameter_nonlinear_trial


def sample(n: int = 12):
    records, labels = [], []
    anchor = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for split, offset in [('train', 0), ('validation', 100), ('future', 200), ('ood', 300)]:
        for j in range(n):
            y = j % 2
            records.append({'principal': 'principal-A', 'organ_id': 'organ-A', 'cell_id': 'cell-A',
                            'row_id': f'{split}-{j}', 'source_group': f'{split}-source-{j}',
                            'event_time': (anchor + timedelta(days=offset + j)).isoformat(),
                            'split': split, 'label': y, 'options': ['no', 'yes']})
            labels.append(y)
    torch.manual_seed(987)
    return torch.randn(len(records), 12), torch.tensor(labels, dtype=torch.long), records


def test_equal_parameter_training_and_report_is_not_authorizing():
    x, y, rows = sample()
    report = equal_parameter_nonlinear_trial(x, y, rows, seeds=(7, 19), steps=2, batch=8)
    assert report['production_admission'] == 'BLOCKED'
    assert report['selection_authorized'] is False
    assert report['causal_learning_verified'] is False
    assert report['future_used_to_select_winner'] is False
    assert report['parameter_count'] <= 16384
    assert report['validation_only_descriptive_winner'] == 'INCONCLUSIVE_INSUFFICIENT_REPLICATION'
    assert report['paired_validation_diagnostic']['training_seed_replicates'] == 2
    assert report['actual_parameters_equal_but_compute_cost_not_verified']
    assert report['joint_question_option_feature_binding_independently_verified'] is False
    for run in report['runs']:
        a, b = run['candidates']['dynamic_gate'], run['candidates']['swiglu']
        assert a['parameter_count'] == b['parameter_count'] == report['parameter_count']
        assert len(run['train_sampling_sha256']) == 64
    again = equal_parameter_nonlinear_trial(x, y, rows, seeds=(7, 19), steps=2, batch=8)
    assert [r['candidates'] for r in report['runs']] == [r['candidates'] for r in again['runs']]
    assert [r['train_sampling_sha256'] for r in report['runs']] == [r['train_sampling_sha256'] for r in again['runs']]


def test_future_labels_do_not_change_training_or_validation_winner():
    x, y, rows = sample()
    a = equal_parameter_nonlinear_trial(x, y, rows, seeds=(2,), steps=2)
    changed = y.clone()
    modified = deepcopy(rows)
    for i, row in enumerate(modified):
        if row['split'] == 'future':
            changed[i] = 1 - changed[i]
            row['label'] = int(changed[i])
    b = equal_parameter_nonlinear_trial(x, changed, modified, seeds=(2,), steps=2)
    assert a['validation_only_descriptive_winner'] == b['validation_only_descriptive_winner']
    assert a['validation_mean_brier'] == b['validation_mean_brier']
    assert a['runs'][0]['train_sampling_sha256'] == b['runs'][0]['train_sampling_sha256']


@pytest.mark.parametrize('corrupt,match', [
    ('source_split', 'source group leakage'),
    ('principal', 'cross-Cell'),
    ('naive_future', 'timezone-aware'),
    ('future_before', 'future must begin'),
    ('validation_before', 'validation must begin'),
    ('option_width', 'option geometry'),
    ('class_mismatch', 'tensor labels differ'),
    ('duplicate_row', 'duplicate row'),
    ('no_train_class', 'all classes'),
])
def test_fail_closed_dataset_invariants(corrupt, match):
    x, y, records = sample()
    rows = deepcopy(records)
    if corrupt == 'source_split': rows[-2]['source_group'] = rows[1]['source_group']
    if corrupt == 'principal': rows[-2]['principal'] = 'principal-B'
    if corrupt == 'naive_future': rows[24]['event_time'] = '2026-03-01T00:00:00'
    if corrupt == 'future_before': rows[24]['event_time'] = '2026-01-01T00:00:00+00:00'
    if corrupt == 'validation_before': rows[12]['event_time'] = '2026-01-01T00:00:00+00:00'
    if corrupt == 'option_width': rows[5]['options'] = ['no', 'yes', 'maybe']
    if corrupt == 'class_mismatch': rows[3]['label'] = 1 - rows[3]['label']
    if corrupt == 'duplicate_row': rows[-1]['row_id'] = rows[0]['row_id']
    if corrupt == 'no_train_class':
        for i in range(12): y[i] = 0; rows[i]['label'] = 0
    with pytest.raises(ValueError, match=match):
        equal_parameter_nonlinear_trial(x, y, rows, seeds=(2,), steps=1)


def test_bad_seeds_and_budget_refused():
    x, y, rows = sample()
    with pytest.raises(ValueError, match='seeds'):
        equal_parameter_nonlinear_trial(x, y, rows, seeds=(1, 1), steps=1)
    with pytest.raises(ValueError, match='budget'):
        equal_parameter_nonlinear_trial(x, y, rows, budget=3000, steps=1)
    with pytest.raises(ValueError, match='training budget'):
        equal_parameter_nonlinear_trial(x, y, rows, steps=0)
    with pytest.raises(ValueError, match='finite CPU'):
        z = x.clone(); z[0,0] = float('nan')
        equal_parameter_nonlinear_trial(z, y, rows, steps=1)


def test_cli_synthetic_and_actual_jsonl_identity(tmp_path):
    import json
    pytest.importorskip('neuron_shared_encoder.contracts')
    pytest.importorskip('neuron_shared_encoder.models')
    pytest.importorskip('neuron_shared_encoder.experiment')
    from neuron_shared_encoder.strict_e2 import main
    from neuron_shared_encoder.contracts import sha256_file
    _x, _y, records = sample(12)
    for row in records:
        row['question'] = 'Which option?'
        row['state'] = 'synthetic research input'
    dataset = tmp_path / 'records.jsonl'
    dataset.write_text(''.join(json.dumps(row) + '\n' for row in records))
    dest = tmp_path / 'out.json'
    args = ['--dataset', str(dataset), '--dataset-sha256', sha256_file(dataset),
            '--output', str(dest), '--dimension', '16', '--steps', '2',
            '--budget', '2048', '--seeds', '7', '19']
    main([*args, '--allow-synthetic'])
    result = json.loads(dest.read_text())
    assert result['production_admission'] == 'BLOCKED'
    assert result['encoder_kind'] == 'synthetic-hash'
    assert result['evidence_class'] == 'SYNTHETIC_SMOKE'
    assert result['physical_encoder_kernel_count_verified'] is False
    with pytest.raises(ValueError, match='synthetic test requires'):
        main(args)
    with pytest.raises(ValueError, match='pinned offline real'):
        main([*args, '--encoder', 'mmbert-joint'])


def test_position_labels_allow_per_question_option_text_but_reject_duplicates():
    from neuron_shared_encoder.strict_e2 import _audit_dataset
    x, y, rows = sample()
    modified = deepcopy(rows)
    modified[1]['options'] = ['yes', 'no']
    assert _audit_dataset(x, y, modified)['train'].numel() == 12
    modified[1]['options'] = ['same', 'same']
    with pytest.raises(ValueError, match='invalid per-question options'):
        _audit_dataset(x, y, modified)


def test_paired_group_bootstrap_two_axis_determinism():
    from neuron_shared_encoder.strict_e2 import paired_validation_bootstrap
    observations = []
    for seed_index in range(3):
        lhs = torch.tensor([.4 + .01 * seed_index] * 16)
        rhs = torch.tensor([.7] * 16)
        observations.append((lhs, rhs))
    sources = [f'g{i // 2}' for i in range(16)]
    report = paired_validation_bootstrap(observations, sources, repeats=200, seed=23)
    assert report == paired_validation_bootstrap(observations, sources, repeats=200, seed=23)
    assert report['descriptive_winner'] == 'dynamic_gate'
    assert report['validation_source_groups'] == 8
    assert report['training_seed_replicates'] == 3
    assert report['paired_bootstrap_95pct_interval'][1] < 0
    assert report['independent_causal_test'] is False


def test_paired_group_bootstrap_inconclusive_on_mixed_source_deltas():
    from neuron_shared_encoder.strict_e2 import paired_validation_bootstrap
    sources = [f'g{i}' for i in range(12)]
    dynamic = torch.tensor([.35 if i % 2 else .65 for i in range(12)])
    swiglu = torch.tensor([.5] * 12)
    report = paired_validation_bootstrap([(dynamic, swiglu)] * 3, sources)
    assert report['descriptive_winner'] == 'INCONCLUSIVE_PAIRED_INTERVAL'
    assert report['paired_bootstrap_95pct_interval'][0] < 0
    assert report['paired_bootstrap_95pct_interval'][1] > 0


def test_paired_group_bootstrap_preserves_correlated_rows_and_rejects_nan():
    from neuron_shared_encoder.strict_e2 import paired_validation_bootstrap
    sources = ['a'] * 50 + ['b'] * 2 + ['c'] * 2
    delta = torch.tensor([.8] * 50 + [-.1] * 4)
    zero = torch.zeros(54)
    report = paired_validation_bootstrap([(delta, zero)] * 3, sources, repeats=100)
    assert report['validation_source_groups'] == 3
    assert report['descriptive_winner'] == 'INCONCLUSIVE_INSUFFICIENT_REPLICATION'
    assert abs(report['mean_paired_validation_brier_delta'] - float(delta.mean())) < 1e-6
    with pytest.raises(ValueError, match='invalid paired validation losses'):
        paired_validation_bootstrap([(torch.tensor([.1]), torch.tensor([float('nan')]))], ['a'])
    with pytest.raises(ValueError, match='invalid validation source groups'):
        paired_validation_bootstrap([(torch.tensor([.1]), torch.tensor([.2]))], [''])
