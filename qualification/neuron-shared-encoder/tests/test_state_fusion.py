"""Adversarial learned Cell-state fusion tests, no real checkpoint downloads."""
import pytest
import torch

from neuron_shared_encoder.state_fusion import (
    LearnedCellStateFusion, fixed_state_ngram_features, learned_state_fusion_trials,
    private_width,
)


def rows():
    out = []
    for split in ('train', 'validation', 'future', 'ood'):
        for idx in range(8):
            out.append({'split': split, 'state': {
                'cell': 'c', 'counter': idx, 'signal': 'up' if idx % 2 else 'down'}})
    return out


def test_real_label_blind_cell_state_features_deterministic_and_bounded():
    data = rows()
    first, cost = fixed_state_ngram_features(data, bins=64)
    second, other_cost = fixed_state_ngram_features(data, bins=64)
    assert torch.equal(first, second)
    assert cost == other_cost > 0
    assert first.shape == (32, 64)
    assert not torch.equal(first[0], first[1])
    assert torch.isfinite(first).all()


@pytest.mark.parametrize('bad', ['', 'z' * 16385, None, 10])
def test_local_state_bytes_limit_fail_closed(bad):
    with pytest.raises(ValueError):
        fixed_state_ngram_features([{'state': bad}])


def test_malformed_or_nonfinite_state_rejected():
    with pytest.raises(ValueError):
        fixed_state_ngram_features([{'state': {'x': float('nan')}}])


def test_adapter_counts_exactly_include_trainable_projection():
    for budget in (2048, 16384):
        width = private_width(128, budget, 64)
        model = LearnedCellStateFusion(total_dim=128, width=width, bins=64,
                                       classes=2, head_kind='dynamic_gate', budget=budget)
        assert model.parameter_count <= budget
        assert model.adapter_parameters == 64 * width
        assert model.parameter_count == model.adapter_parameters + model.head.parameter_count
        with torch.no_grad():
            assert model(torch.randn(3, 128-width), torch.randn(3, 64)).shape == (3, 2)


def test_train_a_real_lightweight_state_adapter_not_synthetic_embeddings():
    data = rows()
    torch.manual_seed(1)
    shared = torch.randn(32, 96)
    labels = torch.tensor([i % 2 for i in range(32)])
    output = learned_state_fusion_trials(shared, data, labels, [r['split'] for r in data],
                                          total_dim=128, budgets=(2048, 16384),
                                          kinds=('linear', 'dynamic_gate'), steps=2,
                                          batch=8, seed=42)
    assert output['production_admission'] == 'BLOCKED'
    assert output['additional_private_state_encoder_forward_rows'] == 0
    assert output['additional_private_state_transformer_calls'] == 0
    assert output['state_bytes_processed'] > 0
    assert len(output['candidates']) == 4
    assert all(x['status'] == 'TRAINED_LEARNED_STATE_SHADOW' for x in output['candidates'])
    assert all(x['trainable_parameters_total'] <= x['budget'] for x in output['candidates'])
    assert all(x['state_adapter_parameters'] > 0 for x in output['candidates'])


def test_future_and_ood_labels_cannot_affect_train_updates():
    data = rows()
    torch.manual_seed(5)
    features = torch.randn(32, 96)
    splits = [r['split'] for r in data]
    labels = torch.tensor([i % 2 for i in range(32)])
    a = learned_state_fusion_trials(features, data, labels, splits,
                                     total_dim=128, budgets=(2048,),
                                     kinds=('linear',), steps=3, seed=9)
    flipped = labels.clone()
    flipped[8:] = 1 - flipped[8:]
    b = learned_state_fusion_trials(features, data, flipped, splits,
                                     total_dim=128, budgets=(2048,),
                                     kinds=('linear',), steps=3, seed=9)
    assert a['candidates'][0]['trainable_parameters_total'] == b['candidates'][0]['trainable_parameters_total']
    assert a['candidates'][0]['train_seconds'] >= 0
    # Independent labels from validation/future/OOD may change reported
    # metrics but never the TRAIN-ONLY optimizer trajectory.
    assert a['candidates'][0]['trained_weights_digest'] == b['candidates'][0]['trained_weights_digest']
    assert a['candidates'][0]['trained_state_adapter_digest'] == b['candidates'][0]['trained_state_adapter_digest']
    assert a['candidates'][0]['trained_cell_head_digest'] == b['candidates'][0]['trained_cell_head_digest']
    assert a['state_feature_extractor'] == b['state_feature_extractor']


def test_cross_cell_state_is_not_a_shared_encoder_cache_entry():
    a, _ = fixed_state_ngram_features([{'state': {'local': 'a'}}])
    b, _ = fixed_state_ngram_features([{'state': {'local': 'b'}}])
    assert not torch.equal(a, b)


def test_train_label_changes_really_update_the_cell_head_weights():
    data = rows()
    torch.manual_seed(11)
    features = torch.randn(32, 96)
    split = [r['split'] for r in data]
    truth = torch.tensor([i % 2 for i in range(32)])
    common = dict(total_dim=128, budgets=(2048,), kinds=('linear',),
                  seed=9, steps=3, batch=8)
    a = learned_state_fusion_trials(features, data, truth, split, **common)
    changed = truth.clone()
    changed[:8] = 1-changed[:8]
    b = learned_state_fusion_trials(features, data, changed, split, **common)
    assert a['candidates'][0]['trained_weights_digest'] != b['candidates'][0]['trained_weights_digest']


def test_stable_weight_digest_is_sensitive_to_numeric_updates():
    from neuron_shared_encoder.state_fusion import _model_weights_digest
    model = LearnedCellStateFusion(total_dim=128, width=8, bins=64,
                                   classes=2, head_kind='linear', budget=2048)
    original = _model_weights_digest(model)
    with torch.no_grad():
        model.adapter.weight[0, 0] += 0.1
    assert _model_weights_digest(model) != original


def test_e3_future_only_new_class_does_not_infer_head_width():
    data = rows()
    torch.manual_seed(24)
    features = torch.randn(len(data), 96)
    splits = [r['split'] for r in data]
    labels = torch.tensor([i % 2 for i in range(len(data))])
    labels[16] = 2   # new option only in future, never in training
    with pytest.raises(ValueError, match='future truth cannot resize Head'):
        learned_state_fusion_trials(features, data, labels, splits,
                                    budgets=(2048,), kinds=('linear',),
                                    steps=1)
    result = learned_state_fusion_trials(
        features, data, labels, splits, num_classes=3,
        budgets=(2048,), kinds=('linear',), steps=1)
    assert result['frozen_output_class_count'] == 3
    assert result['class_count_source'] == 'frozen_registered_option_width'
    assert result['candidates'][0]['status'] == 'TRAINED_LEARNED_STATE_SHADOW'
