"""Pinned AG News research inputs, not approved Hepta user data.

The public corpus describes research/non-commercial use. This diagnostic grants
no commercial or production approval. Acquisition is explicit and never uses
credentials. Raw articles stay local; CI should retain identities/results only.
"""
from __future__ import annotations

import csv
import hashlib
import heapq
import unicodedata
from pathlib import Path
from urllib.request import urlopen

from matrix_materials import file_sha256
from matrix_runtime import write_json_exclusive
from next_round_matrix import _digest

REVISION = '03836ce08fce38daac53e9b4255ef16e0b9f6303'
BASE_URL = f'https://raw.githubusercontent.com/mhjabreel/CharCnn_Keras/{REVISION}/data/ag_news_csv/'
FILES = {
    'train.csv': (29_470_338, '694aa19971315410e000404523796b76349d3c1d'),
    'test.csv': (1_857_427, '130b40c3329c993468b8ed8a22c331315e478e0a'),
    'readme.txt': (1795, 'ff8935df4b5e8788e8a2963bb4da6187de08e53e'),
    'classes.txt': (31, 'e0a3d189cb86add99438018b1e218d3177919dc5'),
}
CLASSES = ('World', 'Sports', 'Business', 'Science/Technology')


def verify_file(path, size, blob_sha):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        raise ValueError('pinned news file size/type changed')
    digest = hashlib.sha1(f'blob {size}\0'.encode())
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    if digest.hexdigest() != blob_sha:
        raise ValueError('news file differs from its pinned Git object')
    return file_sha256(path)


def acquire_news(root):
    root = Path(root)
    root.mkdir(exist_ok=False)
    lock = dict(schema='hepta.public-news-source.v1', revision=REVISION,
                files={k: dict(bytes=v[0], git_blob_sha1=v[1]) for k, v in FILES.items()},
                research_only=True, independent_material_approval=False)
    write_json_exclusive(root / 'source-lock.json', lock)
    try:
        for name, (size, blob) in FILES.items():
            url = BASE_URL + name
            # No auth, archive extraction, automatic scripts, or unbounded reads.
            with urlopen(url, timeout=45) as response, (root / name).open('xb') as target:
                if response.geturl() != url:
                    raise ValueError('news transport redirected outside the pinned resource')
                total = 0
                while block := response.read(min(1 << 20, size + 1 - total)):
                    total += len(block)
                    if total > size:
                        raise ValueError('news transfer exceeded pinned byte ceiling')
                    target.write(block)
            verify_file(root / name, size, blob)
        receipt = {name: verify_file(root / name, *spec) for name, spec in FILES.items()}
        write_json_exclusive(root / 'material.json', dict(files_sha256=receipt,
            source_lock_sha256=file_sha256(root / 'source-lock.json'), independent_material_approval=False))
        return root
    except Exception as exc:
        write_json_exclusive(root / 'FAILED.json', dict(error_type=type(exc).__name__, completed=False))
        raise


def select_split(path, split, per_class, *, expected_rows=None):
    """Select before modeling by fixed SHA256(row identity), balanced per class.

    No token length, loss, prediction, or success-based resampling. An excessive
    input later fails the experiment rather than silently selecting another row.
    """
    if split not in ('train', 'test') or type(per_class) is not int or not 1 <= per_class <= 32:
        raise ValueError('bounded declared news sample required')
    if Path(path).stat().st_size > 32_000_000:
        raise ValueError('news CSV exceeds local envelope')
    heaps = [[] for _ in CLASSES]
    count = 0
    with Path(path).open(encoding='utf-8', newline='') as stream:
        for index, values in enumerate(csv.reader(stream, strict=True)):
            count += 1
            if (count > 120_000 or len(values) != 3 or values[0] not in ('1', '2', '3', '4')
                    or not all(values[1:]) or any(len(v.encode()) > 65_536 for v in values[1:])):
                raise ValueError('malformed or excessive news record')
            label = int(values[0]) - 1
            sid = f'ag-news:{split}:{index}'
            priority = int(hashlib.sha256(('hepta-news-sample-v1:' + sid).encode()).hexdigest(), 16)
            entry = (-priority, index, dict(sample_id=sid, state=values[1] + '\n' + values[2],
                                           question='Choose the news topic.', options=list(CLASSES)))
            heap = heaps[label]
            heapq.heappush(heap, entry)
            if len(heap) > per_class:
                heapq.heappop(heap)
    if (expected_rows is not None and count != expected_rows) or any(len(h) != per_class for h in heaps):
        raise ValueError('incomplete pinned news split or class inventory')
    selected = sorted((index, row, label) for label, heap in enumerate(heaps) for _, index, row in heap)
    return [row for _, row, _ in selected], [label for _, _, label in selected]


def input_identity(row):
    return _digest(row)


def validate_disjoint(train, evaluation):
    seen_ids, seen_text = set(), set()
    for row in train + evaluation:
        if set(row) != {'sample_id', 'state', 'question', 'options'}:
            raise ValueError('model input must be label-free')
        sid = row['sample_id']
        normalized = ' '.join(unicodedata.normalize('NFKC', row['state']).casefold().split())
        key = hashlib.sha256(normalized.encode()).hexdigest()
        if sid in seen_ids or key in seen_text:
            raise ValueError('duplicate selected identity/text; do not silently resample')
        seen_ids.add(sid); seen_text.add(key)


def prepare_news(root, *, per_class=16):
    root = Path(root)
    if (root / 'FAILED.json').exists():
        raise ValueError('failed acquisition cannot be consumed')
    files = {name: verify_file(root / name, *spec) for name, spec in FILES.items()}
    train, targets = select_split(root / 'train.csv', 'train', per_class, expected_rows=120_000)
    evaluation, labels = select_split(root / 'test.csv', 'test', per_class, expected_rows=7600)
    validate_disjoint(train, evaluation)
    receipt = dict(schema='hepta.public-news-selection.v1', revision=REVISION,
        files_sha256=files, per_class=per_class,
        train=[dict(sample_id=r['sample_id'], input_digest=input_identity(r)) for r in train],
        evaluation=[dict(sample_id=r['sample_id'], input_digest=input_identity(r)) for r in evaluation],
        class_order=list(CLASSES), selection='fixed_identity_sha256_per_class',
        independent_source_groups_verified=False, pretraining_contamination_ruled_out=False,
        independent_material_approval=False, research_only=True)
    # Only the driver/scorer receives evaluation labels. The learner does not.
    return train, targets, evaluation, labels, receipt
