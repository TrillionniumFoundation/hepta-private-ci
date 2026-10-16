"""Stage a SHA-pinned public Qwen reference as private regular files.

No inference, private user data or model files are sent to GitHub by this code.
Network access is only for the explicit staging command on an admitted host.
The resulting model manifest records local bytes; it is not a signed publisher
attestation, model efficacy certificate or production grant.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat

from v17_reference_reader_physical import (
    REPO, REVISION, REQUIRED, OPTIONAL, SCHEMA, file_sha,
    verify_model_files, write_private,
)

MAX_FILE_BYTES = 2_500_000_000
NAMES = set(REQUIRED + OPTIONAL)


def frozen_roster(info):
    """Reject a changed revision or incomplete weight provenance before download."""
    if getattr(info, 'sha', None) != REVISION:
        raise ValueError('publisher revision not the requested immutable commit')
    siblings = getattr(info, 'siblings', None)
    if not isinstance(siblings, (list, tuple)):
        raise ValueError('publisher file listing absent')
    files = {}
    for item in siblings:
        name = getattr(item, 'rfilename', None)
        if name not in NAMES:
            continue
        if name in files:
            raise ValueError('duplicate publisher file entry')
        if type(name) is not str or '/' in name or '\\' in name:
            raise ValueError('unsafe publisher path')
        lfs = getattr(item, 'lfs', None)
        publisher_sha = (lfs.get('sha256') if isinstance(lfs, dict)
                         else getattr(lfs, 'sha256', None))
        if publisher_sha is not None and (type(publisher_sha) is not str
            or re.fullmatch(r'[0-9a-f]{64}', publisher_sha) is None):
            raise ValueError('malformed publisher LFS sha256')
        files[name] = publisher_sha
    if not set(REQUIRED).issubset(files):
        raise ValueError('required model files missing at pinned revision')
    # For the weight bytes specifically, the official immutable revision must
    # provide a publisher-recorded LFS object hash. Text configs still get
    # independently recorded local SHA256, not a false publisher SHA256.
    if not files['model.safetensors']:
        raise ValueError('weight publisher LFS SHA256 unavailable')
    return files


def safe_cache_file(source, cache_root, limit=MAX_FILE_BYTES):
    candidate = Path(source)
    root = Path(cache_root).resolve(strict=True)
    original = candidate.resolve(strict=True)
    if original == root or root not in original.parents:
        raise ValueError('source escaped dedicated model cache')
    if (not original.is_file() or not stat.S_ISREG(original.stat().st_mode)
        or not 0 < original.stat().st_size <= limit):
        raise ValueError('unsafe publisher cache material')
    return original


def _copy_regular(source, target, expected):
    # Destination is private, exclusive, regular and never a symlink.
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    hashed = sha256()
    total = 0
    try:
        with os.fdopen(fd, 'wb') as fout, Path(source).open('rb') as fin:
            while True:
                block = fin.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_FILE_BYTES:
                    raise ValueError('model file exceeded allowed size')
                hashed.update(block)
                fout.write(block)
            fout.flush()
            os.fsync(fout.fileno())
    except BaseException:
        Path(target).unlink(missing_ok=True)
        raise
    if total == 0:
        raise ValueError('empty model file')
    actual = hashed.hexdigest()
    if expected is not None and actual != expected:
        raise ValueError('publisher LFS bytes differ: ' + str(target))
    return actual


def materialize(fetch_info, download_file, directory, cache_dir, spec_path):
    """Fetch only the pinned allowed public files; do not accept private inputs.

    Network clients are injected so standard-lib test fixtures can validate
    the admission contract without any model download.
    """
    roster = frozen_roster(fetch_info())
    dst = Path(directory)
    cache = Path(cache_dir)
    spec_dest = Path(spec_path)
    if (dst.exists() or dst.is_symlink() or cache == dst or spec_dest.exists()
        or spec_dest.is_symlink() or dst == spec_dest or not cache.is_dir()
        or cache.is_symlink() or not dst.parent.is_dir()
        or not spec_dest.parent.is_dir()
        or dst in spec_dest.parents
        or cache.resolve(strict=True) in dst.resolve().parents):
        raise ValueError('staging outputs must be new and cache preexisting')
    # Abort early rather than ever mixing an old partial snapshot with new bytes.
    dst.mkdir(mode=0o700, parents=False)
    hashes = {}
    try:
        for filename in sorted(roster):
            cached = download_file(filename)
            source = safe_cache_file(cached, cache)
            hashes[filename] = _copy_regular(source, dst / filename, roster[filename])
        spec = {
            'schema': SCHEMA + '.frozen-model-v1',
            'repo_id': REPO,
            'revision': REVISION,
            'files_sha256': hashes,
            'thinking': False,
            'decoding': 'greedy-24-new-tokens',
            'production_authorized': False,
        }
        verify_model_files(dst, spec)
        write_private(spec_dest, spec)
        return spec
    except BaseException:
        # No half-sealed source is an acceptable selected snapshot.
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        raise


def main():
    p = argparse.ArgumentParser(description='Private Qwen3 reference-model staging only')
    p.add_argument('--cache-dir', required=True)
    p.add_argument('--model-dir', required=True)
    p.add_argument('--model-spec', required=True)
    a = p.parse_args()
    # Optional network dependency is deliberately not imported by source-only CI.
    from huggingface_hub import HfApi, hf_hub_download
    cache = Path(a.cache_dir)
    if not cache.is_dir():
        raise ValueError('dedicated cache directory must preexist')
    api = HfApi()
    spec = materialize(
        lambda: api.model_info(REPO, revision=REVISION, files_metadata=True),
        lambda fname: hf_hub_download(REPO, filename=fname, revision=REVISION,
                                       cache_dir=str(cache), token=False),
        a.model_dir, a.cache_dir, a.model_spec,
    )
    print(json.dumps({'status': 'PRIVATE_MODEL_BYTES_STAGED_NOT_EXECUTED',
                      'pinned_revision': REVISION,
                      'file_count': len(spec['files_sha256']),
                      'production_authorized': False}, sort_keys=True))


if __name__ == '__main__':
    main()
