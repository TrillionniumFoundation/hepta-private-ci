"""Negative and positive unit tests for shadow-only checkpoint tuple identity."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import types

import pytest
import torch

from neuron_shared_encoder.checkpoint_integrity import (
    CheckpointIntegrityError, generate_inventory, verify_checkpoint,
)
from neuron_shared_encoder.experiment import _features, _parser
from neuron_shared_encoder.models import OfflineEncoder


REV = 'a' * 40


def fixture(tmp_path: Path, kind: str = 'laya-joint') -> tuple[Path, Path, str, str]:
    root = tmp_path / 'checkpoint'
    root.mkdir()
    (root / 'model.safetensors').write_bytes(b'fictional snapshot bytes, not model weights')
    if kind == 'laya-joint':
        (root / 'rl_agent_config.json').write_text('{"head_layers": 2, "encoder": "fixed"}\n')
        tok = root / 'tokenizer'
        tok.mkdir()
        (tok / 'tokenizer.json').write_text('{"model": "fixture"}\n')
    else:
        (root / 'config.json').write_text('{"model_type": "modernbert"}\n')
        (root / 'tokenizer.json').write_text('{"model": "fixture"}\n')
    output = tmp_path / 'manifest.json'
    body = generate_inventory(root, kind, REV)
    output.write_text(json.dumps(body, sort_keys=True, indent=2) + '\n')
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    weights_sha = hashlib.sha256((root / 'model.safetensors').read_bytes()).hexdigest()
    return root, output, digest, weights_sha


def verified(root: Path, manifest: Path, digest: str, weights: str, kind='laya-joint'):
    return verify_checkpoint(root, kind, manifest, digest, weights)


@pytest.mark.parametrize('kind', ['laya-joint', 'modernbert-joint'])
def test_complete_snapshot_bytes_and_source_revision(kind, tmp_path):
    root, manifest, digest, weights = fixture(tmp_path, kind)
    proof = verified(root, manifest, digest, weights, kind)
    assert proof.source_revision == REV
    assert proof.manifest_sha256 == digest
    assert proof.weight_sha256 == weights
    proof.verify_unchanged()


def test_weight_only_identity_does_not_admit_tokenizer_modification(tmp_path):
    root, manifest, digest, weights = fixture(tmp_path)
    proof = verified(root, manifest, digest, weights)
    (root / 'tokenizer/tokenizer.json').write_text('{"model": "mutated"}\n')
    with pytest.raises(CheckpointIntegrityError, match='digest mismatch'):
        proof.verify_unchanged()
    with pytest.raises(CheckpointIntegrityError, match='digest mismatch'):
        verified(root, manifest, digest, weights)


def test_additional_file_is_not_implicitly_trusted(tmp_path):
    root, manifest, digest, weights = fixture(tmp_path)
    (root / 'tokenizer/extra_config.json').write_text('{}')
    with pytest.raises(CheckpointIntegrityError, match='inventory drift'):
        verified(root, manifest, digest, weights)


def test_deleted_file_cannot_be_reconstructed_from_weights_digest(tmp_path):
    root, manifest, digest, weights = fixture(tmp_path)
    (root / 'rl_agent_config.json').unlink()
    with pytest.raises(CheckpointIntegrityError, match='inventory drift'):
        verified(root, manifest, digest, weights)


def test_manifest_digest_is_independent_and_required(tmp_path):
    root, manifest, digest, weights = fixture(tmp_path)
    with pytest.raises(CheckpointIntegrityError, match='manifest SHA-256 mismatch'):
        verified(root, manifest, 'f' * 64, weights)
    with pytest.raises(CheckpointIntegrityError, match='weight digest'):
        verified(root, manifest, digest, 'f' * 64)
    manifest.write_text(manifest.read_text().replace(REV, 'b' * 40))
    with pytest.raises(CheckpointIntegrityError, match='manifest SHA-256 mismatch'):
        verified(root, manifest, digest, weights)


def test_manifest_duplicate_json_keys_rejected(tmp_path):
    root, manifest, _, weights = fixture(tmp_path)
    doc = manifest.read_text()
    doc = doc.replace('"schema":', '"schema": "bad", "schema":', 1)
    manifest.write_text(doc)
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(CheckpointIntegrityError, match='duplicate JSON key'):
        verified(root, manifest, digest, weights)


@pytest.mark.parametrize('bad', ['../model.safetensors', '/etc/shadow', 'tokenizer/../model.safetensors',
                                 'model\\.safetensors', './model.safetensors'])
def test_untrusted_path_traversal_rejected(tmp_path, bad):
    root, manifest, _, weights = fixture(tmp_path)
    doc = json.loads(manifest.read_text())
    doc['files'][0]['path'] = bad
    manifest.write_text(json.dumps(doc))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(CheckpointIntegrityError, match='path'):
        verified(root, manifest, digest, weights)


def test_symlink_and_hardlink_snapshot_bytes_rejected(tmp_path):
    root, manifest, digest, weights = fixture(tmp_path)
    (root / 'tokenizer/tokenizer.json').unlink()
    (root / 'tokenizer/tokenizer.json').symlink_to(root / 'model.safetensors')
    with pytest.raises(CheckpointIntegrityError, match='symlink'):
        verified(root, manifest, digest, weights)
    (root / 'tokenizer/tokenizer.json').unlink()
    os.link(root / 'model.safetensors', root / 'tokenizer/tokenizer.json')
    with pytest.raises(CheckpointIntegrityError, match='hardlink'):
        verified(root, manifest, digest, weights)


def test_metadata_revision_and_file_length_type_fail_closed(tmp_path):
    root, manifest, _, weights = fixture(tmp_path)
    doc = json.loads(manifest.read_text())
    doc['source_revision'] = 'mutable-branch'
    manifest.write_text(json.dumps(doc))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(CheckpointIntegrityError, match='source revision'):
        verified(root, manifest, digest, weights)
    doc['source_revision'] = REV
    doc['files'][0]['bytes'] = True  # bool must not count as an integer byte length
    manifest.write_text(json.dumps(doc))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(CheckpointIntegrityError, match='file length'):
        verified(root, manifest, digest, weights)


def test_closed_inventory_requires_source_and_tokenizer(tmp_path):
    root, manifest, digest, weights = fixture(tmp_path)
    with pytest.raises(CheckpointIntegrityError, match='model kind mismatch'):
        verified(root, manifest, digest, weights, 'modernbert-joint')
    with pytest.raises(CheckpointIntegrityError, match='source revision'):
        generate_inventory(root, 'laya-joint', 'latest')
    (root / 'tokenizer/tokenizer.json').unlink()
    with pytest.raises(CheckpointIntegrityError, match='required model files'):
        generate_inventory(root, 'laya-joint', REV)


def test_manifest_inside_checkpoint_not_allowed(tmp_path):
    root, manifest, digest, weights = fixture(tmp_path)
    inside = root / 'manifest.json'
    inside.write_bytes(manifest.read_bytes())
    with pytest.raises(CheckpointIntegrityError, match='outside'):
        verified(root, inside, digest, weights)


def test_real_encoder_cli_requires_manifest_pin(tmp_path):
    root, manifest, digest, weights = fixture(tmp_path)
    args = _parser().parse_args(['head', '--encoder', 'laya-joint',
                                 '--checkpoint-dir', str(root), '--weights-sha256', weights,
                                 '--output', str(tmp_path / 'out.json')])
    with pytest.raises(ValueError, match='checkpoint-manifest'):
        _features(args, [{'state': 'a', 'question': 'b', 'options': ['x', 'y']}])
    with pytest.raises(ValueError, match='checkpoint manifest path'):
        OfflineEncoder('laya-joint', str(root), weights)


def test_upstream_loader_mutating_tokenizer_fails_even_if_weights_unchanged(tmp_path, monkeypatch):
    root, manifest, digest, weights = fixture(tmp_path)
    class MutatingAgent:
        def __init__(self, model_id_or_path, **kwargs):
            (Path(model_id_or_path) / 'tokenizer/tokenizer.json').write_text('{"model": "mutated"}\n')
            self.parallel_options = False
            encoder = torch.nn.Linear(2, 2)
            encoder.config = types.SimpleNamespace(hidden_size=2)
            self.model = types.SimpleNamespace(encoder=encoder)
    laya = types.ModuleType('laya')
    agent = types.ModuleType('laya.agent')
    agent.Agent = MutatingAgent
    laya.agent = agent
    monkeypatch.setitem(sys.modules, 'laya', laya)
    monkeypatch.setitem(sys.modules, 'laya.agent', agent)
    # Config is needed only if tampering was not detected; supply a cheap stub.
    with pytest.raises(CheckpointIntegrityError, match='digest mismatch'):
        OfflineEncoder('laya-joint', str(root), weights,
                       manifest_path=str(manifest), expected_manifest_sha256=digest)


def test_symlink_root_or_manifest_is_denied(tmp_path):
    root, manifest, digest, weights = fixture(tmp_path)
    alias = tmp_path / 'checkpoint-alias'
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(CheckpointIntegrityError, match='symlink'):
        verified(alias, manifest, digest, weights)
    manifest_alias = tmp_path / 'manifest-alias.json'
    manifest_alias.symlink_to(manifest)
    with pytest.raises(CheckpointIntegrityError, match='symlink'):
        verified(root, manifest_alias, digest, weights)


def test_sorted_unique_inventory_and_unknown_manifest_key_rejected(tmp_path):
    root, manifest, _, weights = fixture(tmp_path)
    data = json.loads(manifest.read_text())
    data['files'].append(dict(data['files'][0]))
    manifest.write_text(json.dumps(data))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(CheckpointIntegrityError, match='unique and sorted'):
        verified(root, manifest, digest, weights)
    data['files'].pop()
    data['new_critical_field'] = 'ignore me'
    manifest.write_text(json.dumps(data))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(CheckpointIntegrityError, match='manifest fields'):
        verified(root, manifest, digest, weights)


def test_manifest_oversize_is_rejected_before_json_parse(tmp_path):
    root, manifest, _, weights = fixture(tmp_path)
    manifest.write_bytes(b'x' * (1024 * 1024 + 1))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(CheckpointIntegrityError, match='file type or size invalid'):
        verified(root, manifest, digest, weights)


def test_inventory_cli_can_emit_and_verify_exact_pins(tmp_path, monkeypatch, capsys):
    from neuron_shared_encoder.checkpoint_integrity import main
    root, existing, _, weights = fixture(tmp_path)
    emitted = tmp_path / 'generated.json'
    monkeypatch.setattr(sys, 'argv', ['checkpoint_integrity', 'inventory',
        '--checkpoint-dir', str(root), '--kind', 'laya-joint',
        '--source-revision', REV, '--manifest', str(emitted)])
    main()
    info = json.loads(capsys.readouterr().out)
    assert info['status'] == 'UNSIGNED_INVENTORY_ONLY'
    assert info['weights_sha256'] == weights
    monkeypatch.setattr(sys, 'argv', ['checkpoint_integrity', 'verify',
        '--checkpoint-dir', str(root), '--kind', 'laya-joint',
        '--manifest', str(emitted), '--manifest-sha256', info['manifest_sha256'],
        '--weights-sha256', weights])
    main()
    proof = json.loads(capsys.readouterr().out)
    assert proof['status'] == 'SHADOW_INTEGRITY_ONLY'
    assert proof['manifest_sha256'] == info['manifest_sha256']
