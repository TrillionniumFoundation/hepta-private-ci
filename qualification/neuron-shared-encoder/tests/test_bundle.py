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

def test_bundle_rejects_hardlinks_into_external_mutable_files(tmp_path):
    import os
    root = make_bundle(tmp_path / 'model')
    external = tmp_path / 'linked'
    external.write_bytes(b'attack')
    (root / 'tokenizer.json').unlink()
    os.link(external, root / 'tokenizer.json')
    with pytest.raises(ValueError, match='hardlink'):
        checkpoint_bundle_sha256(root, 'modernbert-joint')


def test_bundle_rejects_root_parent_symlink(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    make_bundle(real / 'model')
    alias = tmp_path / 'alias'
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        checkpoint_bundle_sha256(alias / 'model', 'modernbert-joint')


def test_bundle_rejects_excessive_directories_before_hashing(tmp_path, monkeypatch):
    from neuron_shared_encoder import bundle
    root = make_bundle(tmp_path / 'model')
    (root / 'extra').mkdir()
    (root / 'extra' / 'nested').mkdir()
    monkeypatch.setattr(bundle, 'MAX_BUNDLE_DIRECTORIES', 1)
    with pytest.raises(ValueError, match='directory count'):
        checkpoint_bundle_sha256(root, 'modernbert-joint')


def test_real_model_requires_bundle_check_before_encoder_inference():
    from neuron_shared_encoder.models import OfflineEncoder
    # The backend is deliberately not initialized: if validation is delayed,
    # this test would access the absent encoder/model instead of refusing.
    encoder = OfflineEncoder.__new__(OfflineEncoder)
    encoder.kind = 'modernbert-joint'

    def deny_stale_model():
        raise ValueError('checkpoint bundle SHA-256 mismatch before inference')

    encoder._check_bundle_unchanged = deny_stale_model
    with pytest.raises(ValueError, match='before inference'):
        encoder.encode([{'state': 'test', 'question': 'x', 'options': ['a', 'b']}])


def test_laya_teacher_baseline_refuses_model_drift_before_agent_call():
    from neuron_shared_encoder.models import OfflineEncoder
    encoder = OfflineEncoder.__new__(OfflineEncoder)
    encoder.kind = 'laya-joint'

    def deny_stale_model():
        raise ValueError('checkpoint bundle SHA-256 mismatch before Laya baseline')

    encoder._check_bundle_unchanged = deny_stale_model
    with pytest.raises(ValueError, match='before Laya baseline'):
        encoder.laya_baseline_probabilities([
            {'state': 'test', 'question': 'x', 'options': ['a', 'b']}
        ])
