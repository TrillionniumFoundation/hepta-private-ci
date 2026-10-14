"""Complete bounded preflight→forward token ID binding, research/no grants."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
import torch

from neuron_shared_encoder.physical_pooled_replay_v1 import MODEL
from neuron_shared_encoder.physical_token_pair_v1 import _public_rows
from neuron_shared_encoder.token_reader_offline import _tokenize_and_capture
from neuron_shared_encoder.token_stream_binding_v2 import (
    PREFLIGHT_SCHEMA, read_checked_preflight,
)
from neuron_shared_encoder.tokenizer_length_preflight_v1 import audit_full_joint_token_lengths
from neuron_shared_encoder.trained_head_artifacts_v1 import _canonical
from test_physical_token_pair_v1 import fake_public_rows
from test_token_reader_offline import Meter


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ExactTokenStub:
    def __init__(self, *, alter_padded=False, broken_padding=False):
        self.alter_padded = alter_padded
        self.broken_padding = broken_padding

    def __call__(self, texts, **opts):
        actual = [[501] + [((ord(c) * 17 + index) % 4000) for index, c in enumerate(t[:24])] + [502]
                  for t in texts]
        if opts['padding'] is False:
            assert opts['truncation'] is False and opts['add_special_tokens'] is True
            assert opts['return_attention_mask'] is True
            return {'input_ids': actual, 'attention_mask': [[1] * len(row) for row in actual]}
        assert opts['padding'] == 'max_length' and opts['truncation'] is False
        assert opts['add_special_tokens'] is True and opts['return_attention_mask'] is True
        limit = opts['max_length']
        result = []
        masks = []
        for i, original in enumerate(actual):
            assert len(original) <= limit
            row = original[:] + [0] * (limit - len(original))
            mask = [1] * len(original) + [0] * (limit - len(original))
            if self.alter_padded and i == 0:
                row[1] += 1
            if self.broken_padding and i == 0:
                mask[len(original)-1] = 0
                mask[-1] = 1
            result.append(row)
            masks.append(mask)
        return {'input_ids': torch.tensor(result, dtype=torch.long),
                'attention_mask': torch.tensor(masks, dtype=torch.long)}


class FakeEncoder(torch.nn.Module):
    def forward(self, input_ids, attention_mask):
        data = input_ids.float()
        return SimpleNamespace(last_hidden_state=torch.stack([
            (data + j).cos() for j in range(16)], dim=-1))


def inputs():
    data = _public_rows(fake_public_rows())
    return data, {'max_length': 80, 'batch': 8,
                  'model_id': MODEL['modernbert'][1],
                  'revision': MODEL['modernbert'][2],
                  'source_sha256': sha(b'original-public-zip'),
                  'tokenizer_sha256': sha(b'publisher-tokenizer')}


def receipt(tmp_path):
    rows, kwargs = inputs()
    r = audit_full_joint_token_lengths(ExactTokenStub(), rows, **kwargs)
    path = tmp_path / 'preflight.json'
    path.write_bytes(_canonical(r))
    return path, r, rows, kwargs


def capture(monkeypatch, rows, *, alter_padded=False, broken_padding=False):
    meter = ModuleType('neuron_shared_encoder.encoder_meter')
    meter.EncoderModuleForwardMeter = Meter
    monkeypatch.setitem(sys.modules, meter.__name__, meter)
    backend = SimpleNamespace(tok=ExactTokenStub(alter_padded=alter_padded,
                                                   broken_padding=broken_padding),
                              model=FakeEncoder(), dimension=16)
    result = []
    for cell in (0, 1):
        meta = rows[cell]
        values = _tokenize_and_capture(
            backend, [row['joint_text'] for row in meta],
            max_length=80, batch=8, cell_index=cell,
            input_sha256=[r['input_sha256'] for r in meta])
        result.append(values[2]['ordered_active_token_ids_sha256'])
    return result


def test_actual_forward_token_ids_match_original_preflight(monkeypatch,tmp_path):
    p, r, rows, kwargs = receipt(tmp_path)
    assert r['schema'] == PREFLIGHT_SCHEMA
    assert r['production_admission'] == 'BLOCKED'
    verified = read_checked_preflight(p, **kwargs)
    assert verified['production_admission'] == 'BLOCKED'
    assert not verified['real_encoder_independently_verified']
    assert len(verified['preflight_file_sha256']) == 64
    assert capture(monkeypatch, rows) == verified['cell_stream_sha256']
    assert r['ordered_real_token_id_stream_sha256'] != verified['cell_stream_sha256'][0]


def test_same_lengths_but_changed_model_call_token_ids_must_fail_comparison(monkeypatch,tmp_path):
    p, _r, rows, kwargs = receipt(tmp_path)
    claimed = read_checked_preflight(p, **kwargs)['cell_stream_sha256']
    actually_used = capture(monkeypatch, rows, alter_padded=True)
    assert actually_used != claimed


def test_non_contiguous_right_padding_rejected_before_any_model_forward(monkeypatch,tmp_path):
    _p,_r,rows,_cfg = receipt(tmp_path)
    with pytest.raises(ValueError, match='not contiguous right-padding'):
        capture(monkeypatch,rows,broken_padding=True)


@pytest.mark.parametrize('change,match',[
    ('source','binding mismatch'),('tokenizer','binding mismatch'),
    ('capture_length','binding mismatch'),('batch','binding mismatch'),
    ('missing_cell','incomplete per-Cell'),('swapped_cell','Cell tokenizer'),
    ('changed_stream','Cell tokenizer'),('bad_counts','Cell tokenizer'),
    ('grant','binding mismatch'),('unknown_flag','unexpected or incomplete'),
    ('partial_publisher','unexpected or incomplete'),('bad_publisher','original publisher'),
    ('duplicate_json','canonical tokenizer preflight'),
    ('noncanonical','noncanonical'),('symlink','bounded regular'),
])
def test_preflight_record_cannot_silently_drift(tmp_path,change,match):
    p,r,rows,kwargs=receipt(tmp_path)
    arguments = dict(kwargs)
    if change == 'source': arguments['source_sha256'] = sha(b'other-source')
    if change == 'tokenizer': arguments['tokenizer_sha256'] = sha(b'other-tokenizer')
    if change == 'capture_length': arguments['max_length'] = 72
    if change == 'batch': arguments['batch'] = 16
    if change == 'missing_cell': r['per_cell'].pop()
    if change == 'swapped_cell': r['per_cell'][1]['cell'] = 0
    if change == 'changed_stream': r['per_cell'][0]['ordered_active_token_ids_sha256'] = 'f'*64
    if change == 'bad_counts': r['per_cell'][1]['total_active_token_slots'] = 0
    if change == 'grant': r['selection_authorized'] = True
    if change == 'unknown_flag': r['independent_signed'] = True
    if change == 'partial_publisher': r['publisher_tokenizer_total_bytes'] = 1024
    if change == 'bad_publisher':
        r['publisher_tokenizer_files_sha256'] = {name:sha(name.encode()) for name in (
            'config.json', 'special_tokens_map.json', 'tokenizer.json', 'tokenizer_config.json')}
        r['publisher_tokenizer_total_bytes'] = 1024
    if change == 'noncanonical': p.write_text(json.dumps(r,indent=2))
    if change == 'duplicate_json': p.write_text(p.read_text().replace('"production_admission":', '"production_admission":"BLOCKED","production_admission":'))
    if change == 'symlink':
        raw=tmp_path/'data.json';raw.write_bytes(p.read_bytes());p.unlink();p.symlink_to(raw)
    elif change not in ('noncanonical','duplicate_json'):
        p.write_bytes(_canonical(r))
    if change=='changed_stream':
        # A self-reported digest of attacker-modified token IDs is only a
        # consistency claim, not cryptographic attestation. It must be
        # compared against the actual forward stream separately.
        assert read_checked_preflight(p,**arguments)['cell_stream_sha256'][0]=='f'*64
        return
    with pytest.raises(ValueError,match=match):
        read_checked_preflight(p,**arguments)


def test_no_automatic_preflight_identity_for_synthetic_capture(monkeypatch,tmp_path):
    # Existing synthetic tests remain explicitly non-pretrained and untrusted.
    from test_physical_token_pair_v1 import fixture_trial
    report=fixture_trial(tmp_path,steps=1,seeds=(11,))
    assert 'pinned_tokenizer_preflight_sha256' not in report['encoder_observation']
    assert report['production_admission']=='BLOCKED'
