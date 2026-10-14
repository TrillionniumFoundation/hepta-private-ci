"""No-weight exact tokenizer budget preflight, non-authorizing research only."""
from __future__ import annotations

from collections import UserDict
from copy import deepcopy
import hashlib

import pytest

from neuron_shared_encoder.physical_token_pair_v1 import _public_rows
from neuron_shared_encoder.physical_pooled_replay_v1 import MODEL
from neuron_shared_encoder import tokenizer_length_preflight_v1 as impl
from test_physical_token_pair_v1 import fake_public_rows


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def args():
    return dict(max_length=168, batch=8, model_id=MODEL['modernbert'][1],
                revision=MODEL['modernbert'][2], source_sha256=sha(b'source'),
                tokenizer_sha256=sha(b'tokenizer'))


class FakeTokenizer:
    def __init__(self, *, too_long=False, invalid=False, no_mask=False):
        self.calls = []
        self.too_long = too_long
        self.invalid = invalid
        self.no_mask = no_mask

    def __call__(self, texts, **kwargs):
        self.calls.append((list(texts), dict(kwargs)))
        assert kwargs == dict(truncation=False, padding=False,
                              return_attention_mask=True, add_special_tokens=True)
        sequences = [[50281] + [77] * (min(40, len(text) // 19) + 1) + [50282]
                     for text in texts]
        if self.too_long:
            sequences[0] = [50281] + [77] * 168 + [50282]
        masks = [[1] * len(seq) for seq in sequences]
        if self.invalid:
            sequences[0][-1] = True
        return UserDict({'input_ids': sequences, **({} if self.no_mask else {'attention_mask': masks})})


def test_complete_original_full_joint_rows_and_exact_tokenizer_args():
    tokenizer = FakeTokenizer()
    result = impl.audit_full_joint_token_lengths(tokenizer, _public_rows(fake_public_rows()), **args())
    assert result['production_admission'] == 'BLOCKED'
    assert result['model_weights_downloaded_by_this_step'] is False
    assert result['pretrained_encoder_forward_verified'] is False
    assert result['selection_authorized'] is False
    assert result['full_joint_untruncated_row_count'] == 128
    assert result['capture_max_length'] == 168
    assert result['capture_batch'] == 8
    assert len(tokenizer.calls) == 16
    assert len(result['per_cell']) == 2
    assert all(x['input_rows'] == 64 and x['tokenizer_batches'] == 8
               and x['maximum_untruncated_tokens'] <= 168 for x in result['per_cell'])
    assert len(result['ordered_real_token_id_stream_sha256']) == 64
    assert 'Genuine source not loaded' not in repr(result)
    assert 'input_ids' not in result and 'raw_text' not in result
    repeat = impl.audit_full_joint_token_lengths(FakeTokenizer(), _public_rows(fake_public_rows()), **args())
    assert repeat['ordered_real_token_id_stream_sha256'] == result['ordered_real_token_id_stream_sha256']


@pytest.mark.parametrize('variant,match', [
    ('overlong', 'exceeded model budget'), ('invalid', 'malformed mask'),
    ('no_mask', 'incomplete untruncated'),
    ('misbound', 'pinned original'), ('boolean_length', 'bounded full-token'),
    ('too_wide', 'bounded full-token'), ('zero_batch', 'bounded full-token'),
    ('missing_cell', 'two-Cell'), ('scope_mismatch', 'isolated source'),
])
def test_invalid_model_or_source_rejected_before_positive_receipt(variant, match):
    cfg = args()
    by_cell = _public_rows(fake_public_rows())
    tok = FakeTokenizer()
    if variant == 'overlong': tok.too_long = True
    if variant == 'invalid': tok.invalid = True
    if variant == 'no_mask': tok.no_mask = True
    if variant == 'misbound': cfg['revision'] = 'unapproved'
    if variant == 'boolean_length': cfg['max_length'] = True
    if variant == 'too_wide': cfg['max_length'] = 200
    if variant == 'zero_batch': cfg['batch'] = 0
    if variant == 'missing_cell': by_cell.pop(1)
    if variant == 'scope_mismatch': by_cell[0][0]['cell'] = 1
    with pytest.raises(ValueError, match=match):
        impl.audit_full_joint_token_lengths(tok, by_cell, **cfg)


def test_same_token_lengths_but_different_full_inputs_change_digest():
    a = _public_rows(fake_public_rows())
    b = deepcopy(a)
    b[0][0]['input_sha256'] = 'a' * 64
    left = impl.audit_full_joint_token_lengths(FakeTokenizer(), a, **args())
    right = impl.audit_full_joint_token_lengths(FakeTokenizer(), b, **args())
    assert left['ordered_real_token_id_stream_sha256'] != right['ordered_real_token_id_stream_sha256']


def test_partial_model_stage_requests_only_small_pinned_tokenizer_assets(monkeypatch, tmp_path):
    publisher = tmp_path / 'publisher'
    publisher.mkdir()
    expected = {}
    for name in sorted(impl.TOKENIZER_FILES):
        data = (name + '-signed-metadata-fixture').encode()
        (publisher / name).write_bytes(data)
        expected[name] = sha(data)
    expected['README.md'] = sha(b'not requested')
    expected['model.safetensors'] = sha(b'NEVER DOWNLOAD THIS')
    monkeypatch.setattr(impl, 'source_model_files', lambda *_: expected)
    monkeypatch.setattr(impl, 'read_public_physical_features',
                        lambda *_args, **_kwargs: (None, fake_public_rows(), {
                            'physical_source_verified_locally': True}))
    calls = []

    def fetch(**kw):
        calls.append(kw)
        return str(publisher)

    result = impl.execute_pinned_length_preflight(
        source_zip=tmp_path / 'source.zip', source_sha256=sha(b'source'),
        tokenizer_destination=tmp_path / 'small-only', receipt_file=tmp_path / 'receipt.json',
        download_fn=fetch, tokenizer_loader=lambda _: FakeTokenizer())
    assert result['production_admission'] == 'BLOCKED'
    assert result['model_weights_downloaded_by_this_step'] is False
    assert calls == [{'repo_id': MODEL['modernbert'][1], 'revision': MODEL['modernbert'][2],
                      'allow_patterns': sorted(impl.TOKENIZER_FILES)}]
    assert set(p.name for p in (tmp_path / 'small-only').iterdir()) == impl.TOKENIZER_FILES
    assert not (tmp_path / 'small-only' / 'model.safetensors').exists()
    assert (tmp_path / 'receipt.json').is_file()
    with pytest.raises(ValueError, match='pre-existing tokenizer'):
        impl.execute_pinned_length_preflight(
            source_zip=tmp_path / 'source.zip', source_sha256=sha(b'source'),
            tokenizer_destination=tmp_path / 'small-only', receipt_file=tmp_path / 'receipt.json',
            download_fn=lambda **_: (_ for _ in ()).throw(AssertionError('unexpected download')))


def test_bad_small_publisher_file_fails_before_creating_staged_snapshot(monkeypatch, tmp_path):
    publisher = tmp_path / 'publisher'
    publisher.mkdir()
    wrong = {name: sha((name + '-correct').encode()) for name in impl.TOKENIZER_FILES}
    for name in impl.TOKENIZER_FILES:
        (publisher / name).write_bytes((name + '-wrong').encode())
    monkeypatch.setattr(impl, 'source_model_files', lambda *_: wrong)
    monkeypatch.setattr(impl, 'read_public_physical_features',
                        lambda *_args, **_kwargs: (None, fake_public_rows(), {
                            'physical_source_verified_locally': True}))
    with pytest.raises(ValueError, match='publisher SHA mismatch'):
        impl.execute_pinned_length_preflight(
            source_zip=tmp_path / 'source.zip', source_sha256=sha(b'source'),
            tokenizer_destination=tmp_path / 'tokenizer', receipt_file=tmp_path / 'receipt.json',
            download_fn=lambda **_: str(publisher))
    assert not (tmp_path / 'tokenizer').exists()
    assert not (tmp_path / 'receipt.json').exists()
