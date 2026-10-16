"""Stage a SHA-pinned public Qwen reference as private regular files.

No inference, private user data or model files are sent to GitHub by this code.
Network access is only for the explicit staging command on an admitted host.
The resulting model manifest records local bytes; it is not a signed publisher
attestation, model efficacy certificate or production grant.
"""
from __future__ import annotations

import argparse
from hashlib import sha1, sha256
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
    """Bind each official file to its content, not just its local cache path.

    The Hub's `blob_id` is the Git blob OID; for an LFS/Xet payload the OID
    addresses its pointer, not the downloaded bytes. In that case require the
    publisher's separate SHA256 of the real object. Ordinary Git-managed files
    must reproduce the publisher's Git blob OID. All files must match the
    publisher's byte length, whether LFS/Xet or Git-managed.
    """
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
        size = getattr(item, 'size', None)
        blob_id = getattr(item, 'blob_id', None)
        if (type(size) is not int or not 0 < size <= MAX_FILE_BYTES
            or type(blob_id) is not str or re.fullmatch(r'[0-9a-f]{40}', blob_id) is None):
            raise ValueError('publisher size or Git blob identity unavailable')
        lfs = getattr(item, 'lfs', None)
        publisher_sha = (lfs.get('sha256') if isinstance(lfs, dict)
                         else getattr(lfs, 'sha256', None))
        if lfs is not None and (type(publisher_sha) is not str
            or re.fullmatch(r'[0-9a-f]{64}', publisher_sha) is None):
            raise ValueError('malformed publisher LFS sha256')
        files[name] = {'size': size, 'blob_id': blob_id,
                       'lfs_sha256': publisher_sha}
    if not set(REQUIRED).issubset(files):
        raise ValueError('required model files missing at pinned revision')
    if not files['model.safetensors']['lfs_sha256']:
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
    """Stream publisher digest and Git blob digest without trusting cache metadata."""
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    physical_hash = sha256()
    total = 0
    try:
        with os.fdopen(fd, 'wb') as fout, Path(source).open('rb') as fin:
            while True:
                block = fin.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_FILE_BYTES or total > expected['size']:
                    raise ValueError('model file exceeded publisher size')
                physical_hash.update(block)
                fout.write(block)
            fout.flush()
            os.fsync(fout.fileno())
        if total != expected['size']:
            raise ValueError('model file size differs from publisher revision')
        actual = physical_hash.hexdigest()
        if expected['lfs_sha256'] is not None:
            if actual != expected['lfs_sha256']:
                raise ValueError('publisher LFS bytes differ: ' + str(target))
        else:
            git_hash = sha1()
            git_hash.update(b'blob ' + str(total).encode('ascii') + b'\x00')
            with Path(target).open('rb') as f:
                for part in iter(lambda: f.read(1024 * 1024), b''):
                    git_hash.update(part)
            if git_hash.hexdigest() != expected['blob_id']:
                raise ValueError('publisher Git blob bytes differ: ' + str(target))
        return actual
    except BaseException:
        Path(target).unlink(missing_ok=True)
        raise


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
