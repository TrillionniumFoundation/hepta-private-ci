"""Actual optimizer and sealed safetensors replay tests; never production authority."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
import torch
from safetensors.torch import load as safe_load

from neuron_shared_encoder.token_reader_v1 import CellHead, snapshot_sha256
from neuron_shared_encoder.trained_head_artifacts_v1 import (
    PinnedHeadArtifactV1, load_pinned_trained_bank_v1, seal_head_v1,
    train_and_seal_head_v1,
)
from test_token_reader_v1 import sample


def _inputs(cell: str):
    tokens, mask, labels, rows, pins = sample()
    for row in rows:
        row['cell_id'] = cell
    return tokens, mask, labels, rows, pins


def _train(root: Path, cell: str, *, kind='token_query_prepared', steps=3):
    inputs = _inputs(cell)
    tokens, mask, labels, rows, pins = inputs
    ref = train_and_seal_head_v1(root, *inputs,
                                 snapshot_sha256(tokens, mask, rows, pins),
                                 kind=kind, rank=4, seed=23, steps=steps, batch=6,
                                 lr=0.003)
    return ref, inputs


def _load(refs, pins, *, kind='token_query_prepared', **kw):
    return load_pinned_trained_bank_v1(refs, expected_principal='principal-A',
                                     expected_purpose='offline-study',
                                     expected_organ='organ-A', expected_pins=pins,
                                     kind=kind, **kw)


@pytest.mark.parametrize('kind', ('token_query_prepared', 'pooled_cached'))
def test_actual_training_safetensors_readback_and_full_packed_parity(tmp_path, kind):
    ref_a, inputs = _train(tmp_path / 'cell-a', 'cell-A', kind=kind)
    ref_b, _ = _train(tmp_path / 'cell-b', 'cell-B', kind=kind)
    assert ref_a.manifest_sha256 != ref_b.manifest_sha256
    state = safe_load((ref_a.directory / 'head.safetensors').read_bytes())
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(23)
        fresh = CellHead(12, 4, 2)
    assert not torch.equal(fresh.down.weight, state['down.weight'])
    assert not any(p.suffix == '.pt' for p in tmp_path.rglob('*'))
    bank = _load([ref_a, ref_b], inputs[4], kind=kind)
    receipt = bank.verify_parity(inputs[0][0], inputs[1][0])
    assert receipt['cell_ids'] == ['cell-A', 'cell-B']
    assert receipt['kind'] == kind
    assert receipt['cell_count'] == 2
    assert receipt['safetensors_weight_readback_verified'] is True
    assert receipt['independent_training_verified'] is False
    assert receipt['maximum_prediction_difference'] <= 1e-5
    assert receipt['production_admission'] == 'BLOCKED'
    assert receipt['selection_authorized'] is False
    assert receipt['independent_source_and_signature_verified'] is False
    assert receipt['native_q24_or_worker_verified'] is False
    again = _load([ref_a, ref_b], inputs[4], kind=kind)
    assert bank.verify_parity(inputs[0][0], inputs[1][0])['bank_sha256'] == (
        again.verify_parity(inputs[0][0], inputs[1][0])['bank_sha256'])


def test_checkpoint_digest_and_scope_mismatch_fail_closed(tmp_path):
    ref, (_, _, _, _, pins) = _train(tmp_path / 'cell-a', 'cell-A')
    with pytest.raises(ValueError, match='expected scope'):
        load_pinned_trained_bank_v1([ref], expected_principal='principal-A',
                                   expected_purpose='', expected_organ='organ-A',
                                   expected_pins=pins, kind='token_query_prepared')
    with pytest.raises(ValueError, match='cross-scope'):
        load_pinned_trained_bank_v1([ref], expected_principal='principal-B',
                                   expected_purpose='offline-study', expected_organ='organ-A',
                                   expected_pins=pins, kind='token_query_prepared')
    changed = dict(pins, authority_epoch=3)
    with pytest.raises(ValueError, match='selected artifact'):
        _load([ref], changed)
    with pytest.raises(ValueError, match='selected artifact'):
        _load([ref], pins, kind='pooled_cached')
    with pytest.raises(ValueError, match='duplicate Cell'):
        _load([ref, ref], pins)
    with pytest.raises(ValueError, match='exact externally pinned'):
        _load([PinnedHeadArtifactV1(ref.directory, 'wrong')], pins)


def test_bytes_tamper_rejected_without_unpickling(tmp_path):
    ref, (_, _, _, _, pins) = _train(tmp_path / 'cell-a', 'cell-A')
    blob = ref.directory / 'head.safetensors'
    raw = bytearray(blob.read_bytes())
    raw[-3] ^= 1
    blob.write_bytes(raw)
    with pytest.raises(ValueError, match='Head weights bytes conflict'):
        _load([ref], pins)


def test_manifest_tamper_rejected_even_for_valid_json(tmp_path):
    ref, (_, _, _, _, pins) = _train(tmp_path / 'cell-a', 'cell-A')
    file = ref.directory / 'manifest.json'
    record = json.loads(file.read_text())
    record['scope']['principal'] = 'principal-B'
    file.write_text(json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n')
    with pytest.raises(ValueError, match='manifest SHA256 mismatch'):
        _load([ref], pins)
    new_ref = PinnedHeadArtifactV1(ref.directory, hashlib.sha256(file.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='cross-scope'):
        _load([new_ref], pins)


def test_corrupt_checkpoint_even_with_new_self_reported_hash_rejected(tmp_path):
    ref, (_, _, _, _, pins) = _train(tmp_path / 'cell-a', 'cell-A')
    path = ref.directory / 'head.safetensors'
    path.write_bytes(b'pickle payload must not execute')
    mf = ref.directory / 'manifest.json'
    record = json.loads(mf.read_bytes())
    record['weights_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    record['weights_bytes'] = path.stat().st_size
    mf.write_text(json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n')
    updated = PinnedHeadArtifactV1(ref.directory, hashlib.sha256(mf.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='invalid safetensors'):
        _load([updated], pins)


def test_future_label_change_cannot_affect_actual_optimizer_checkpoint(tmp_path):
    inputs = _inputs('cell-A')
    tokens, mask, labels, rows, pins = inputs
    ref1 = train_and_seal_head_v1(tmp_path / 'original', *inputs,
                                  snapshot_sha256(tokens, mask, rows, pins),
                                  steps=3, batch=6, rank=4, seed=23, lr=0.003)
    rows_b = deepcopy(rows)
    labels_b = labels.clone()
    for idx, row in enumerate(rows_b):
        if row['split'] == 'future':
            labels_b[idx] = 1 - labels_b[idx]
            row['label'] = int(labels_b[idx])
    ref2 = train_and_seal_head_v1(tmp_path / 'alternate', tokens, mask, labels_b, rows_b, pins,
                                  snapshot_sha256(tokens, mask, rows_b, pins),
                                  steps=3, batch=6, rank=4, seed=23, lr=0.003)
    assert (ref1.directory / 'head.safetensors').read_bytes() == (
        ref2.directory / 'head.safetensors').read_bytes()
    assert ref1.manifest_sha256 != ref2.manifest_sha256


def test_no_overwrite_incompatible_shape_and_symlink(tmp_path):
    ref, (_, _, _, _, pins) = _train(tmp_path / 'cell-a', 'cell-A')
    with pytest.raises(ValueError, match='already exist'):
        _train(tmp_path / 'cell-a', 'cell-A')
    external = tmp_path / 'external'
    external.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(ref.directory, target_is_directory=True)
    with pytest.raises(ValueError, match='regular checkpoint directory'):
        _load([PinnedHeadArtifactV1(link, ref.manifest_sha256)], pins)
    with pytest.raises(ValueError, match='same-kind model roster'):
        _load([], pins)


def test_reject_bad_geometry_and_training_controls(tmp_path):
    inputs = _inputs('cell-A')
    frozen = snapshot_sha256(inputs[0], inputs[1], inputs[3], inputs[4])
    with pytest.raises(ValueError, match='bounded training'):
        train_and_seal_head_v1(tmp_path / 'zero', *inputs, frozen, steps=0)
    with pytest.raises(ValueError, match='bounded training'):
        train_and_seal_head_v1(tmp_path / 'rank', *inputs, frozen, rank=100)
    with pytest.raises(ValueError, match='frozen token snapshot digest mismatch'):
        train_and_seal_head_v1(tmp_path / 'wrong', *inputs, '0' * 64)
    assert not any(p.is_file() for p in tmp_path.iterdir())


def test_different_principal_or_organ_never_comingle(tmp_path):
    ref, (_, _, _, _, pins) = _train(tmp_path / 'cell-a', 'cell-A')
    head = CellHead(12, 4, 2)
    bad_scope = {'principal': 'principal-B', 'purpose': 'offline-study',
                 'organ_id': 'organ-A', 'cell_id': 'cell-B'}
    record = json.loads((ref.directory / 'manifest.json').read_bytes())
    second = seal_head_v1(tmp_path / 'other-principal', head,
                          kind='token_query_prepared', scope=bad_scope,
                          pins=pins, training_snapshot_sha256=record['training_snapshot_sha256'],
                          training=record['training'])
    with pytest.raises(ValueError, match='cross-scope'):
        _load([ref, second], pins)


def test_created_artifacts_are_private_on_posix(tmp_path):
    import os
    ref, _ = _train(tmp_path / 'private-cell', 'cell-A')
    if os.name != 'nt':
        assert ref.directory.stat().st_mode & 0o077 == 0
        assert (ref.directory / 'manifest.json').stat().st_mode & 0o077 == 0
        assert (ref.directory / 'head.safetensors').stat().st_mode & 0o077 == 0


def test_new_python_process_reopens_pinned_trained_checkpoint(tmp_path):
    import subprocess
    import sys
    from safetensors.torch import save_file

    ref, (tokens, mask, _, _, pins) = _train(tmp_path / 'cell-a', 'cell-A')
    expected = _load([ref], pins).verify_parity(tokens[0], mask[0])
    observation = tmp_path / 'observation.safetensors'
    save_file({'tokens': tokens[0].contiguous(), 'mask': mask[0].contiguous()}, str(observation))
    code = '''
import json, sys
from pathlib import Path
from safetensors.torch import load_file
from neuron_shared_encoder.trained_head_artifacts_v1 import (
    PinnedHeadArtifactV1, load_pinned_trained_bank_v1)
folder, manifest_sha, observation, pins_json = sys.argv[1:]
ref = PinnedHeadArtifactV1(Path(folder), manifest_sha)
bank = load_pinned_trained_bank_v1(
    [ref], expected_principal='principal-A', expected_purpose='offline-study',
    expected_organ='organ-A', expected_pins=json.loads(pins_json),
    kind='token_query_prepared')
item = load_file(observation)
print(json.dumps(bank.verify_parity(item['tokens'], item['mask'])))
'''
    result = subprocess.run(
        [sys.executable, '-c', code, str(ref.directory), ref.manifest_sha256,
         str(observation), json.dumps(pins)],
        check=True, capture_output=True, text=True, cwd=Path.cwd(), timeout=15,
    )
    restarted = json.loads(result.stdout)
    assert restarted['bank_sha256'] == expected['bank_sha256']
    assert restarted['maximum_prediction_difference'] == pytest.approx(
        expected['maximum_prediction_difference'], abs=1e-6)
    assert restarted['production_admission'] == 'BLOCKED'
