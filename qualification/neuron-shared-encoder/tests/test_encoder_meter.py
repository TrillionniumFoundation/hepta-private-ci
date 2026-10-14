"""Non-authorizing Encoder module-forward measurement contract tests."""
import pytest
import torch
from torch import nn

from neuron_shared_encoder.encoder_meter import EncoderModuleForwardMeter
from neuron_shared_encoder.validation_v3 import reuse_trial, digest_bytes


class TokenModel(nn.Module):
    def __init__(self, fail_on_negative=False):
        super().__init__()
        self.lin = nn.Linear(3, 2, bias=False)
        self.fail_on_negative = fail_on_negative

    def forward(self, input_ids, attention_mask=None):
        if self.fail_on_negative and bool((input_ids < 0).any()):
            raise RuntimeError('simulated physical forward error')
        return self.lin(input_ids.float())


def test_meters_module_forwards_not_outer_adapter_calls():
    model = TokenModel()
    def adapter(records):
        # A single public adapter request may execute multiple model forwards.
        return torch.cat([model(input_ids=torch.ones(1, 3)) for _ in records])
    with EncoderModuleForwardMeter(model) as meter:
        out = adapter([{}, {}, {}])
    rec = meter.receipt()
    assert out.shape == (3, 2)
    assert rec['module_forward_attempts'] == 3
    assert rec['module_forward_completions'] == 3
    assert rec['rows_completed'] == 3
    assert rec['padded_token_slots_completed'] == 9
    assert rec['physical_gpu_kernels_verified'] is False
    assert rec['production_admission'] == 'BLOCKED'
    # Hooks removed after context exit, even if module is reused.
    model(input_ids=torch.ones(4, 3))
    assert meter.receipt()['module_forward_attempts'] == 3


def test_batched_rows_distinct_from_call_count():
    model = TokenModel()
    with EncoderModuleForwardMeter(model) as meter:
        model(input_ids=torch.ones(4, 3))
        model(input_ids=torch.ones(2, 3))
    rec = meter.receipt()
    assert rec['module_forward_attempts'] == 2
    assert rec['rows_completed'] == 6
    assert rec['padded_token_slots_completed'] == 18


def test_failed_forward_is_counted_and_hooks_are_removed():
    model = TokenModel(fail_on_negative=True)
    meter = EncoderModuleForwardMeter(model)
    with pytest.raises(RuntimeError, match='simulated'):
        with meter:
            model(input_ids=torch.ones(2, 3))
            model(input_ids=-torch.ones(1, 3))
    rec = meter.receipt()
    assert rec['module_forward_attempts'] == 2
    assert rec['module_forward_completions'] == 1
    assert rec['module_forward_failures_or_incomplete'] == 1
    assert rec['rows_attempted'] == 3
    assert rec['rows_completed'] == 2
    model(input_ids=torch.ones(1, 3))
    assert meter.receipt() == rec


def test_invalid_model_and_geometry_fail_closed():
    with pytest.raises(TypeError):
        EncoderModuleForwardMeter(object())
    model = TokenModel()
    with pytest.raises(ValueError, match='rank-2'):
        with EncoderModuleForwardMeter(model):
            model(input_ids=torch.ones(3))
    assert len(model._forward_pre_hooks) == len(model._forward_hooks) == 0


def test_reuse_trial_and_meter_counter_are_not_confused():
    model = TokenModel()
    rows = []
    for j in range(12):
        rows.append({'principal': 'scope-a', 'source_group': f'g{j // 3}',
                     'split': 'train', 'question': 'Choose?', 'options': ['no', 'yes'],
                     'state': f'private-{j}', 'row_id': f'r{j}'})
    d = digest_bytes(b'shadow-pinned')
    def adapter(batch):
        # Physical module receives one forward per row, despite one adapter call.
        return torch.cat([model(input_ids=torch.ones(1, 3)) for _ in batch], dim=0)
    with EncoderModuleForwardMeter(model) as met:
        _, result = reuse_trial(rows, adapter, encoder_digest=d, tokenizer_digest=d,
                                normalizer_digest=d, mode='joint', batch_size=12)
    assert result['encoder_forward_invocations'] == 1
    assert met.receipt()['module_forward_completions'] == 12
    assert result['encoder_forward_rows'] == met.receipt()['rows_completed']
    assert not met.receipt()['production_worker_execution_verified']
