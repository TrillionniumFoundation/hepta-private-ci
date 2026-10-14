"""Synthetic local contract tests: NOT a pretrained model observation."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest
import torch

from test_token_reader_v1 import sample
from neuron_shared_encoder.token_reader_offline import _joint_text, run_pinned_offline


class FakeTokenizer:
    def __init__(self, *, oversize=False):
        self.oversize = oversize

    def __call__(self, texts, *, padding, truncation, max_length, return_tensors):
        assert padding == 'max_length' and truncation is False
        assert return_tensors == 'pt'
        length = max_length + 1 if self.oversize else max_length
        ids = torch.zeros((len(texts), length), dtype=torch.long)
        mask = torch.zeros_like(ids)
        for i, text in enumerate(texts):
            for j, ch in enumerate(text[:max_length // 2]):
                ids[i, j] = ord(ch) % 307
                mask[i, j] = 1
        return {'input_ids': ids, 'attention_mask': mask}


class FakeModel(torch.nn.Module):
    def __init__(self, *, malformed=False):
        super().__init__()
        self.malformed = malformed

    def forward(self, input_ids, attention_mask):
        values = input_ids.float()
        width = 11 if self.malformed else 12
        hidden = torch.stack([(values + i).sin() for i in range(width)], dim=-1)
        return SimpleNamespace(last_hidden_state=hidden)


class Meter:
    def __init__(self, model):
        self.model = model
        self.attempts = self.completions = self.attempted_rows = self.completed_rows = 0

    def __enter__(self):
        def before(_, _args, kw):
            self.attempts += 1
            self.attempted_rows += len(kw['input_ids'])
        def after(_, _args, kw, output):
            if output is not None:
                self.completions += 1
                self.completed_rows += len(kw['input_ids'])
        self.a = self.model.register_forward_pre_hook(before, with_kwargs=True)
        self.b = self.model.register_forward_hook(after, with_kwargs=True)
        return self

    def __exit__(self, *_):
        self.a.remove()
        self.b.remove()

    def receipt(self):
        return {'meter_kind': 'SYNTHETIC_TEST_STUB_NOT_REAL_ENCODER',
                'module_forward_attempts': self.attempts,
                'module_forward_completions': self.completions,
                'rows_completed': self.completed_rows}


def harness(tmp_path, monkeypatch, *, oversize=False, malformed=False):
    _tokens, _mask, _labels, rows, _pins = sample()
    raw = []
    for i, row in enumerate(rows):
        raw.append({key: deepcopy(val) for key, val in row.items() if key not in ('input_sha256', 'purpose')})
        raw[-1]['state'] = 'private payload not allowed in output'
        raw[-1]['question'] = f'Which option for record {i}?'
    data = tmp_path / 'approved.jsonl'
    data.write_text(''.join(json.dumps(v, sort_keys=True) + '\n' for v in raw), encoding='utf-8')
    directory = tmp_path / 'pinned'
    directory.mkdir()
    tokenizer = directory / 'tokenizer.json'
    tokenizer.write_text('{}', encoding='utf-8')
    data_sha = hashlib.sha256(data.read_bytes()).hexdigest()
    tok_sha = hashlib.sha256(tokenizer.read_bytes()).hexdigest()
    fake_contracts = ModuleType('neuron_shared_encoder.contracts')
    fake_contracts.sha256_file = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def load_dataset(path, *, expected_sha256):
        assert fake_contracts.sha256_file(path) == expected_sha256
        return [json.loads(v) for v in Path(path).read_text().splitlines()], {}

    fake_contracts.load_dataset = load_dataset
    fake_models = ModuleType('neuron_shared_encoder.models')
    calls = []

    class FakeBackend:
        def __init__(self, kind, root, expected_weights_sha256, device,
                     max_length, expected_bundle_sha256):
            calls.append('load')
            assert kind == 'modernbert-joint' and device == 'cpu'
            self.bundle_sha256 = expected_bundle_sha256
            self.dimension = 12
            self.tok = FakeTokenizer(oversize=oversize)
            self.model = FakeModel(malformed=malformed)

        def _check_bundle_unchanged(self):
            calls.append('check')

    fake_models.OfflineEncoder = FakeBackend
    fake_meter = ModuleType('neuron_shared_encoder.encoder_meter')
    fake_meter.EncoderModuleForwardMeter = Meter
    monkeypatch.setitem(sys.modules, fake_contracts.__name__, fake_contracts)
    monkeypatch.setitem(sys.modules, fake_models.__name__, fake_models)
    monkeypatch.setitem(sys.modules, fake_meter.__name__, fake_meter)
    kwargs = dict(dataset=str(data), dataset_sha256=data_sha,
                  checkpoint_dir=str(directory), tokenizer_sha256=tok_sha,
                  weights_sha256='a' * 64, bundle_sha256='b' * 64,
                  kind='modernbert-joint', purpose='approved-offline-study',
                  generation=1, authority_epoch=2, max_length=16,
                  encoder_batch=8, rank=4, head_budget=2048,
                  steps=2, head_batch=8, seeds=(7, 19))
    return kwargs, raw, data, calls


def test_real_offline_shape_protocol_with_synthetic_injected_backend(tmp_path, monkeypatch):
    kw, _, _, calls = harness(tmp_path, monkeypatch)
    result = run_pinned_offline(**kw)
    assert result['experiment'] == 'E2_REAL_PINNED_TOKEN_READER_SHADOW'
    assert result['production_admission'] == 'BLOCKED'
    assert result['selection_authorized'] is False
    assert result['real_model_independently_attested'] is False
    assert result['source_and_final_use_independently_authorized'] is False
    assert result['encoder_execution_verified'] is False  # independent evidence absent
    assert result['observed_encoding']['total_encoder_batches'] == 6
    assert result['observed_encoding']['model_forward_observation']['rows_completed'] == 48
    assert result['pooled_feature_cache_minimum_bytes'] == 48 * 12 * 4
    assert result['whole_token_snapshot_bytes'] == 48 * 16 * 12 * 4 + 48 * 16
    assert calls == ['load', 'check', 'check']
    assert len(result['runs']) == 2
    assert 'private payload' not in json.dumps(result)


def test_nonambiguous_joint_payload_and_disallows_oversize():
    a = {'question': 'A', 'options': ['x | y', 'z'], 'state': 'hi'}
    b = {'question': 'A', 'options': ['x', 'y | z'], 'state': 'hi'}
    text_a, sha_a = _joint_text(a)
    text_b, sha_b = _joint_text(b)
    assert text_a != text_b and sha_a != sha_b
    assert json.loads(text_a)['options'] == a['options']
    a['state'] = 'A' * 32769
    with pytest.raises(ValueError, match='bounded canonical input'):
        _joint_text(a)


@pytest.mark.parametrize('corrupt,match', [
    ('kind', 'only qualified'),
    ('weightsha', 'exact pinned'),
    ('tokenizer', 'tokenizer file hash mismatch'),
    ('no_dir', 'physical checkpoint directory'),
    ('purpose', 'dataset scope/purpose conflict'),
    ('scope', 'cross-Cell'),
    ('future_leak', 'source group leakage'),
    ('future_time', 'future not strictly'),
    ('bad_label', 'label/option'),
])
def test_fails_before_model_load_on_invalid_sources(tmp_path, monkeypatch, corrupt, match):
    kw, records, file, calls = harness(tmp_path, monkeypatch)
    if corrupt == 'kind': kw['kind'] = 'laya-joint'
    if corrupt == 'weightsha': kw['weights_sha256'] = 'not-a-digest'
    if corrupt == 'tokenizer': kw['tokenizer_sha256'] = '1' * 64
    if corrupt == 'no_dir': kw['checkpoint_dir'] = str(tmp_path / 'nonexistent')
    if corrupt == 'purpose': records[0]['purpose'] = 'different-use'
    if corrupt == 'scope': records[1]['principal'] = 'another-scope'
    if corrupt == 'future_leak': records[24]['source_group'] = records[0]['source_group']
    if corrupt == 'future_time': records[24]['event_time'] = '2026-01-01T00:00:00+00:00'
    if corrupt == 'bad_label': records[24]['label'] = 3
    if corrupt in ('purpose', 'scope', 'future_leak', 'future_time', 'bad_label'):
        file.write_text(''.join(json.dumps(v, sort_keys=True) + '\n' for v in records))
        kw['dataset_sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match=match):
        run_pinned_offline(**kw)
    assert calls == []


@pytest.mark.parametrize('fault,match', [
    ('oversize', 'tokenizer exceeded max_length'),
    ('model_shape', 'real model returned malformed'),
])
def test_fails_closed_for_token_or_model_geometry(tmp_path, monkeypatch, fault, match):
    kw, _, _, calls = harness(tmp_path, monkeypatch, oversize=fault == 'oversize',
                               malformed=fault == 'model_shape')
    with pytest.raises(ValueError, match=match):
        run_pinned_offline(**kw)
    assert calls[0] == 'load'


def test_real_offline_test_stub_can_meter_pooled_cached_vs_token_query(tmp_path, monkeypatch):
    """The optional measurement piggybacks on the SAME captured token snapshot."""
    kw, _, _, calls = harness(tmp_path, monkeypatch)
    kw.update(cost_cells=4, cost_rounds=3, cost_warmups=1)
    result = run_pinned_offline(**kw)
    cost = result['optional_readout_cost_probe']
    assert result['production_admission'] == cost['production_admission'] == 'BLOCKED'
    assert not cost['physical_worker_batch_verified']
    assert not cost['real_encoder_forward_measured_by_this_probe']
    assert cost['cell_count'] == 4
    assert cost['head_parameters_per_cell'] <= kw['head_budget']
    assert cost['snapshot_sha256'] == result['snapshot_sha256']
    assert cost['cached_pooled_feature_bytes'] == 12 * 4
    assert result['observed_encoding']['total_encoder_batches'] == 6
    assert calls == ['load', 'check', 'check']
    assert 'private payload' not in json.dumps(cost)


def test_optional_readout_cost_denies_nonbounded_cell_count_before_dispatch(tmp_path, monkeypatch):
    kw, _, _, calls = harness(tmp_path, monkeypatch)
    kw.update(cost_cells=4097)
    with pytest.raises(ValueError, match='bounded optional readout cost'):
        run_pinned_offline(**kw)
    assert calls[0] == 'load'
