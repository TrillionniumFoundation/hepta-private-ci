"""A5 offline schema falsification; no external model weights are loaded."""
from copy import deepcopy

import pytest

from neuron_shared_encoder.a5_evidence import review_a5_execution
from test_abc_evidence import complete_a5_schema_fixture


def test_full_five_arm_schema_only_yields_unverified_review():
    report = review_a5_execution(complete_a5_schema_fixture())
    assert report['status'] == 'SCHEMA_COMPLETE_UNVERIFIED'
    assert report['arms_with_training_receipts'] == 5
    assert report['independent_model_load_verified'] is False
    assert report['production_admission'] == 'BLOCKED'


@pytest.mark.parametrize('failure', [
    'empty_arm', 'missing_model', 'duplicate_weight', 'missing_tokenizer',
    'altered_repo', 'unmeasured_encoder', 'different_input_count',
    'different_head_lr', 'missing_future', 'fake_ood', 'missing_head',
    'lost_laya_policy', 'wrong_projected_width', 'missing_dataset',
])
def test_five_real_model_evidence_cannot_be_replaced_with_schema_names(failure):
    source = complete_a5_schema_fixture()
    one = source['encoders']['mmbert-small']
    if failure == 'empty_arm':
        source['encoders']['mmbert-small'] = {}
    elif failure == 'missing_model':
        source['encoders'].pop('mmbert-small')
    elif failure == 'duplicate_weight':
        one['weights_sha256'] = source['encoders']['modernbert-base']['weights_sha256']
    elif failure == 'missing_tokenizer':
        one['tokenizer_sha256_claimed'] = 'unqualified'
    elif failure == 'altered_repo':
        one['upstream_repository'] = 'other/model'
    elif failure == 'unmeasured_encoder':
        one['encoder_seconds'] = 0
    elif failure == 'different_input_count':
        one['input_rows'] = 19
    elif failure == 'different_head_lr':
        one['trained_head_matrix']['same_train_lr'] = .5
    elif failure == 'missing_future':
        del one['trained_head_matrix']['candidates'][0]['future']
    elif failure == 'fake_ood':
        one['trained_head_matrix']['candidates'][0]['ood_auroc_msp'] = 12
    elif failure == 'missing_head':
        one['trained_head_matrix']['candidates'].pop(0)
    elif failure == 'lost_laya_policy':
        source['encoders']['laya-421m'].pop('original_laya_system_one')
    elif failure == 'wrong_projected_width':
        one['projected_width'] = 256
    else:
        source.pop('dataset_sha256')
    result = review_a5_execution(source)
    assert result['status'] == 'BLOCKED'
    assert result['issues']
    assert result['production_admission'] == 'BLOCKED'


def test_joint_review_blocks_empty_real_model_dicts_before_media_gate():
    from neuron_shared_encoder.abc_evidence import joint_abc_evidence_gate
    report = complete_a5_schema_fixture()
    for model in report['encoders']:
        report['encoders'][model] = {}
    result = joint_abc_evidence_gate({'A': report})
    assert result['status'] == 'BLOCKED'
    assert result['a5_execution_integrity']['status'] == 'BLOCKED'
    assert result['candidate_stem_selected'] is None
