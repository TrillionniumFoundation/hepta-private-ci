"""V27 source-first bounded original archive admission for a real two-Reader CPU trial.

No model inference here. Every original question, publisher label, Reader weight
and prompt remains in a create-once 0700 operator-local workspace. A successful
input rebuild is NOT evidence of model task correctness or release authority.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tarfile
import zipfile

from v19_original_archive_preflight import (
    ARTIFACT_SHA256, EXPECTED, MAX_ZIP_BYTES, audit_archive,
)
from v21_original_plan_rebuilder import rebuild, V16_PLAN_SHA

SCHEMA = 'hepta.stem.v27.original-paired-qwen-host.shadow.v1'
TARGETS = {
    'memory-inputs/reader/model.safetensors': 'reader/model.safetensors',
    'memory-inputs/reader/tokenizer.json': 'reader/tokenizer.json',
    'memory-inputs/reader/config.json': 'reader/config.json',
    'memory-inputs/locomo.json': 'locomo.json',
}
MAX_MEMBER_BYTES = 300_000_000
CHUNK = 1024 * 1024


def write_new(path: Path, obj):
    raw = (json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False) + '\n').encode()
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())


def extract_pinned(path, out):
    """Perform a fully bounded, no-symlink selective extraction, never `extractall`."""
    path = Path(path)
    out = Path(out)
    if out.exists() or out.is_symlink() or not out.parent.is_dir():
        raise ValueError('original private workspace must not already exist')
    # Unlike trusting a prior public digest receipt, reread the actual ZIP.
    audit_archive(path)
    out.mkdir(mode=0o700)
    (out / 'reader').mkdir(mode=0o700)
    found = set()
    try:
        with zipfile.ZipFile(path) as z:
            entries = z.infolist()
            if len(entries) != 1 or entries[0].filename != 'memory-inputs.tar.gz':
                raise ValueError('original zip entry changed')
            with z.open(entries[0]) as stream:
                with tarfile.open(fileobj=stream, mode='r|gz') as t:
                    for member in t:
                        if member.name not in TARGETS:
                            continue
                        if (member.name in found or not member.isfile()
                            or not 0 < member.size <= MAX_MEMBER_BYTES):
                            raise ValueError('unregistered, repeated or unbounded source bytes')
                        found.add(member.name)
                        src = t.extractfile(member)
                        if src is None:
                            raise ValueError('missing original source payload')
                        dest = out / TARGETS[member.name]
                        fhash = sha256()
                        copied = 0
                        with os.fdopen(os.open(dest, os.O_CREAT | os.O_WRONLY | os.O_EXCL,
                                              0o600), 'wb') as f:
                            while chunk := src.read(CHUNK):
                                copied += len(chunk)
                                if copied > member.size:
                                    raise ValueError('original extracted bytes too large')
                                fhash.update(chunk)
                                f.write(chunk)
                            f.flush()
                            os.fsync(f.fileno())
                        expected_hash, expected_bytes = EXPECTED[member.name]
                        if copied != expected_bytes or fhash.hexdigest() != expected_hash:
                            raise ValueError('original unpacked model/corpus source drift')
        if found != set(TARGETS):
            raise ValueError('incomplete original fixed source/model roster')
        return {name: {'sha256': EXPECTED[name][0], 'bytes': EXPECTED[name][1]}
                for name in sorted(found)}
    except BaseException:
        # Incomplete workspace may not be reused as an accepted original cohort.
        import shutil
        shutil.rmtree(out)
        raise


def prepare(zip_path, out_root):
    private = Path(out_root)
    targets = extract_pinned(zip_path, private)
    result, source, ranks, plan = rebuild(private / 'locomo.json')
    if result['sha256_v16_plan'] != V16_PLAN_SHA or len(plan['requests']) != 128:
        raise ValueError('missing original frozen reference questions')
    for filename, payload in (('source-only.json', source), ('bm25-routes.json', ranks),
                              ('v16-plan.json', plan)):
        write_new(private / filename, payload)
    return {
        'schema': SCHEMA + '.original-source-preflight',
        'original_zip_sha256': ARTIFACT_SHA256,
        'registered_original_files': len(targets),
        'source_sha256': result['sha256_source_only'],
        'rank_sha256': result['sha256_rank_rows'],
        'source_roots': 4, 'original_questions': 1986,
        'request_plan_sha256': V16_PLAN_SHA,
        'logical_requests': 128,
        'original_model_forwards': 0,
        'reference_model_forwards': 0,
        'raw_original_source_logged': False,
        'private_labels_exposed_to_model': False,
        'independent_semantic_accuracy': None,
        'production_authorized': False,
        'decision': 'SOURCE_BYTES_ADMITTED_NO_MODEL_RESULT',
    }


def cli():
    p = argparse.ArgumentParser()
    p.add_argument('--zip', required=True)
    p.add_argument('--private-root', required=True)
    a = p.parse_args()
    print(json.dumps(prepare(a.zip, a.private_root), sort_keys=True))


if __name__ == '__main__':
    cli()
