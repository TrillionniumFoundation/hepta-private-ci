"""Fail-closed local publisher staging gates; no live model download in tests."""
from pathlib import Path
import pytest
from neuron_shared_encoder.stage_modernbert_public_v1 import (
    source_model_files, stage_pinned_public_modernbert, FILES,
)
from neuron_shared_encoder.physical_pooled_replay_v1 import PUBLIC_ZIP_SHA256


def test_actual_historical_publisher_manifest_is_safetensors_only():
    """The full historical ZIP is a local optional fixture, not shipped to CI."""
    file=Path('/mnt/data/hepta-public-pretrained-38534349397.zip')
    if not file.is_file():
        pytest.skip('historical archived ZIP not installed in test runner')
    manifest=source_model_files(file,PUBLIC_ZIP_SHA256)
    assert set(manifest)==FILES
    assert manifest['model.safetensors']=='340ac08b74eef0d7bdec2d7981a6a3d4249bf0e6aab60634b72ad02c2b8023a9'


def test_unapproved_archive_rejected_without_downloading(tmp_path):
    hit=[]
    def forbidden(**kwargs):
        hit.append(kwargs)
        raise AssertionError('network call forbidden on unapproved source')
    with pytest.raises(ValueError,match='unapproved historical public ZIP'):
        stage_pinned_public_modernbert(source_zip=tmp_path/'missing.zip',
            source_sha256='a'*64,destination=tmp_path/'weights',
            receipt_file=tmp_path/'receipt',download_fn=forbidden)
    assert not hit and not (tmp_path/'weights').exists()


def test_external_asset_not_silently_downloaded_or_certified(monkeypatch,tmp_path):
    from neuron_shared_encoder import stage_modernbert_public_v1 as impl
    import hashlib
    # Stub only the publisher manifest; fail a mismatched byte digest before
    # even creating a private staging directory.
    monkeypatch.setattr(impl,'source_model_files',lambda *_: {
        name: hashlib.sha256((name+'-correct').encode()).hexdigest() for name in FILES})
    published=tmp_path/'publisher'; published.mkdir()
    for name in FILES: (published/name).write_bytes((name+'-wrong').encode())
    with pytest.raises(ValueError,match='publisher asset digest mismatch'):
        stage_pinned_public_modernbert(source_zip=tmp_path/'source.zip',
          source_sha256='a'*64,destination=tmp_path/'staged',
          receipt_file=tmp_path/'receipt.json',download_fn=lambda **kw: published)
    assert not (tmp_path/'staged').exists() and not (tmp_path/'receipt.json').exists()


def test_model_stage_rejects_existing_target_even_when_publisher_validated(monkeypatch,tmp_path):
    from neuron_shared_encoder import stage_modernbert_public_v1 as impl
    monkeypatch.setattr(impl,'source_model_files',lambda *_: {})
    existing=tmp_path/'occupied';existing.mkdir()
    with pytest.raises(ValueError,match='overwriting'):
        stage_pinned_public_modernbert(source_zip=tmp_path/'missing',source_sha256='a'*64,
            destination=existing,receipt_file=tmp_path/'receipt.json',
            download_fn=lambda **kw: tmp_path/'no-use')
