from pathlib import Path

import pytest

from neuron_shared_encoder.bundle import checkpoint_bundle_sha256, verify_checkpoint_bundle


def make_bundle(root: Path, kind='modernbert-joint'):
    root.mkdir()
    required = ['model.safetensors', 'config.json', 'tokenizer.json'] if kind == 'modernbert-joint' else [
        'model.safetensors', 'rl_agent_config.json', 'encoder/config.json', 'tokenizer/tokenizer.json']
    for name in required:
        path = root / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes((name + ' content').encode())
    return root


def test_bundle_hash_frozen_inputs(tmp_path):
    root = make_bundle(tmp_path / 'model')
    a = checkpoint_bundle_sha256(root, 'modernbert-joint')
    assert verify_checkpoint_bundle(root, 'modernbert-joint', a) == a
    (root / 'tokenizer.json').write_text('different')
    with pytest.raises(ValueError, match='mismatch'):
        verify_checkpoint_bundle(root, 'modernbert-joint', a)
    assert checkpoint_bundle_sha256(root, 'modernbert-joint') != a


def test_bundle_refuses_missing_symlink_and_wrong_kind(tmp_path):
    root = make_bundle(tmp_path / 'laya', 'laya-joint')
    a = checkpoint_bundle_sha256(root, 'laya-joint')
    with pytest.raises(ValueError):
        verify_checkpoint_bundle(root, 'laya-joint', 'z' * 64)
    with pytest.raises(ValueError):
        checkpoint_bundle_sha256(root, 'modernbert-joint')
    assert verify_checkpoint_bundle(root, 'laya-joint', a) == a
    outside = tmp_path / 'outside'
    outside.write_bytes(b'foo')
    (root / 'extra.json').symlink_to(outside)
    with pytest.raises(ValueError, match='symlinks'):
        checkpoint_bundle_sha256(root, 'laya-joint')


def test_bundle_directory_member_change_is_detected(tmp_path):
    root = make_bundle(tmp_path / 'm')
    a = checkpoint_bundle_sha256(root, 'modernbert-joint')
    (root / 'preprocessing.json').write_text('{}')
    assert checkpoint_bundle_sha256(root, 'modernbert-joint') != a


@pytest.mark.parametrize('kind', ['mmbert-joint', 'granite-joint'])
def test_new_offline_checkpoint_kinds_are_bundle_pinned(tmp_path, kind):
    root = make_bundle(tmp_path / kind, kind)
    pinned = checkpoint_bundle_sha256(root, kind)
    assert verify_checkpoint_bundle(root, kind, pinned) == pinned
    (root / 'tokenizer.json').write_bytes(b'changed-tokenizer')
    with pytest.raises(ValueError, match='mismatch'):
        verify_checkpoint_bundle(root, kind, pinned)
