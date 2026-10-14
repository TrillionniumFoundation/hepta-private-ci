"""Explicit network acquisition of ONE historical ModernBERT publisher revision.

Separate from the offline training path. A local hash match is NOT a model-use
license, signer attestation, independent evaluator or deployment permission.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
from zipfile import ZipFile

from .physical_pooled_replay_v1 import (
    MODEL, PUBLIC_ZIP_SHA256, _member, _parsed, read_public_physical_features,
)
from .trained_head_artifacts_v1 import _canonical

FILES = frozenset({'README.md', 'config.json', 'model.safetensors',
                   'special_tokens_map.json', 'tokenizer.json', 'tokenizer_config.json'})
MAX_MODEL_BYTES = 1_610_612_736  # Fail before accepting unexpectedly large publisher files.


def source_model_files(archive_path: Path, exact_archive_sha256: str) -> dict:
    """Require the original immutable public dataset and ModernBERT manifest."""
    if exact_archive_sha256 != PUBLIC_ZIP_SHA256:
        raise ValueError('unapproved historical public ZIP source SHA256')
    _, _rows, source = read_public_physical_features(
        archive_path, exact_archive_sha256, arm='modernbert')
    if not source['physical_source_verified_locally']:
        raise ValueError('actual pretrained publisher source not verified')
    with ZipFile(archive_path) as archive:
        manifest = _parsed(_member(archive, 'hepta-modernbert-pair/manifest.json', 65_536))
    model = manifest.get('model')
    if (not isinstance(model, dict)
            or model.get('model_id') != MODEL['modernbert'][1]
            or model.get('revision') != MODEL['modernbert'][2]
            or model.get('conversion') is not None
            or set(model.get('files', {})) != FILES):
        raise ValueError('unexpected publisher source revision/asset set/conversion')
    files = model['files']
    if any(not isinstance(digest, str) or len(digest) != 64 or
           any(c not in '0123456789abcdef' for c in digest) for digest in files.values()):
        raise ValueError('invalid original publisher asset SHA256')
    return dict(files)


def stage_pinned_public_modernbert(*, source_zip: Path, source_sha256: str,
                                   destination: Path, receipt_file: Path,
                                   download_fn=None) -> dict:
    """Explicit offline-evidence job acquisition, NEVER invoked by inference."""
    publisher_files = source_model_files(source_zip, source_sha256)
    target = Path(destination)
    receipt_file = Path(receipt_file)
    if target.exists() or target.is_symlink() or receipt_file.exists() or receipt_file.is_symlink():
        raise ValueError('refuse overwriting or following staged model/report')
    # Network acquisition is intentionally explicit and confined to this function.
    if download_fn is None:
        from huggingface_hub import snapshot_download
        download_fn = snapshot_download
    snapshot = Path(download_fn(repo_id=MODEL['modernbert'][1],
                                revision=MODEL['modernbert'][2],
                                allow_patterns=sorted(FILES)))
    if not snapshot.is_dir():
        raise ValueError('pinned publisher snapshot is missing')
    # Check everything before first mutation; copy symlink targets as normal
    # files to a private create-only directory (bundle scanner forbids symlinks).
    sizes = {}
    total = 0
    for name, expected in publisher_files.items():
        original = snapshot / name
        if not original.is_file():
            raise ValueError(f'missing immutable publisher asset {name}')
        size = original.stat().st_size
        if not 0 < size <= MAX_MODEL_BYTES - total:
            raise ValueError('publisher model asset byte ceiling exceeded')
        digest = hashlib.sha256()
        with original.open('rb') as reader:
            for blob in iter(lambda: reader.read(1 << 20), b''):
                digest.update(blob)
        if digest.hexdigest() != expected:
            raise ValueError(f'publisher asset digest mismatch: {name}')
        total += size
        sizes[name] = size
    target.mkdir(mode=0o700, parents=False)
    for name, expected in publisher_files.items():
        original = snapshot/name
        staged = target/name
        handle = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(handle, 'wb') as writer, original.open('rb') as reader:
            shutil.copyfileobj(reader, writer, length=1 << 20)
            writer.flush()
            os.fsync(writer.fileno())
        # Detect publisher cache drift even during the copy.
        with staged.open('rb') as reader:
            if hashlib.sha256(reader.read()).hexdigest() != expected:
                raise ValueError('staged model file changed during copy')
    from .bundle import checkpoint_bundle_sha256
    bundle_sha256 = checkpoint_bundle_sha256(target, 'modernbert-joint')
    report = {
        'schema':'hepta.modernbert.public-explicit-acquisition.shadow.v1',
        'model_id':MODEL['modernbert'][1],
        'revision':MODEL['modernbert'][2],
        'publisher_files':publisher_files,
        'staged_file_bytes':sizes,
        'bundle_sha256':bundle_sha256,
        'historical_source_zip_sha256':source_sha256,
        'network_acquisition_explicit':True,
        'model_loaded_or_forward_observed':False,
        'source_license_independently_granted':False,
        'independent_signature_verified':False,
        'production_admission':'BLOCKED',
    }
    payload = _canonical(report)
    fd = os.open(receipt_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd,'wb') as writer:
        writer.write(payload)
        writer.flush()
        os.fsync(writer.fileno())
    return report


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--source-zip', type=Path, required=True)
    args.add_argument('--source-sha256', required=True)
    args.add_argument('--destination', type=Path, required=True)
    args.add_argument('--receipt', type=Path, required=True)
    value=args.parse_args()
    stage_pinned_public_modernbert(source_zip=value.source_zip,
         source_sha256=value.source_sha256,destination=value.destination,
         receipt_file=value.receipt)


if __name__=='__main__':
    main()
