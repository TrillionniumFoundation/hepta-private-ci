"""Fixed public BANKING77 four-intent subset, not the 77-intent benchmark.

Original data: PolyAI Limited, CC BY 4.0, Casanueva et al. (ACL 2020),
Efficient Intent Detection with Dual Sentence Encoders. Downloaded CSV bytes are
unmodified. Normalized-text deduplication, deterministic stratification and label
separation below are our transformations. No source independence is asserted.
"""
from __future__ import annotations

import csv
import hashlib
import io
import unicodedata
import urllib.request
from pathlib import Path

from matrix_runtime import write_json_exclusive
from next_round_matrix import _digest

REVISION = '57ec275d8078af65b7731c2a98be812d844a6d6b'
ORIGIN = 'https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/' + REVISION + '/'
BLOBS = {'banking_data/train.csv': '98e2543cf482d0dca7bfb175ebe35d98efad95be',
         'banking_data/test.csv': '799687a8367359432985b8b13d85a2baf73f92dd',
         'LICENSE': '2f244ac814036ecd9ba9f69782e89ce6b1dca9eb'}
INTENTS = ('card_arrival', 'cash_withdrawal_not_recognised', 'exchange_rate', 'lost_or_stolen_phone')
PER_CLASS = {'fit': 16, 'heldout': 8}
MAX_BYTES = 2_000_000


def acquire(root):
    """Explicit acquisition of three pinned files; hashes checked before parsing."""
    root = Path(root); root.mkdir(exist_ok=False)
    lock = dict(schema='hepta.banking77-source.v1', revision=REVISION, blobs=BLOBS,
                license='CC-BY-4.0', copyright='PolyAI Limited', origin=ORIGIN)
    write_json_exclusive(root / 'SOURCE.json', lock)
    try:
        digests = {}
        for name, expected in BLOBS.items():
            url = ORIGIN + name
            with urllib.request.urlopen(url, timeout=30) as response:
                if response.geturl() != url:
                    raise ValueError('unexpected public-data redirect')
                data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('public data exceeds acquisition bound')
            blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if blob != expected:
                raise ValueError('public data differs from fixed Git blob')
            dest = root / name; dest.parent.mkdir(exist_ok=True)
            with dest.open('xb') as stream:
                stream.write(data)
            digests[name] = hashlib.sha256(data).hexdigest()
        write_json_exclusive(root / 'MATERIAL.json', {'source': lock, 'sha256': digests})
        return root
    except Exception as exc:
        write_json_exclusive(root / 'FAILED.json', {'error_type': type(exc).__name__, 'completed': False})
        raise


def text_key(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def _rows(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise ValueError('bounded CSV bytes required')
    reader = csv.DictReader(io.StringIO(data.decode('utf-8')))
    if reader.fieldnames != ['text', 'category']:
        raise ValueError('expected original text/category CSV')
    rows, duplicates = {}, 0
    for i, row in enumerate(reader):
        if i >= 20_000 or set(row) != {'text', 'category'} or any(not isinstance(v, str) or not v for v in row.values()):
            raise ValueError('invalid CSV row or row bound exceeded')
        text, category = row['text'], row['category']
        if len(text.encode()) > 4096 or not text_key(text):
            raise ValueError('invalid utterance')
        key = text_key(text)
        if key in rows:
            if rows[key]['category'] != category:
                raise ValueError('conflicting labels on the same normalized utterance')
            duplicates += 1
            text = min(text, rows[key]['text'])  # Independent of file ordering.
        rows[key] = {'text': text, 'category': category}
    return rows, duplicates


def prepare(train_bytes, test_bytes):
    """Freeze subset before training; no model score participates in selection."""
    train, train_dups = _rows(train_bytes)
    test, test_dups = _rows(test_bytes)
    overlap = set(train) & set(test)
    inputs = {'schema': 'hepta.banking77-four-intent-inputs.v1', 'intents': list(INTENTS), 'fit': [], 'heldout': []}
    answers, selected_ids, pool_sizes = [], {}, {}
    for split, source in (('fit', train), ('heldout', test)):
        selected_ids[split], pool_sizes[split] = [], {}
        for label, category in enumerate(INTENTS):
            keys = [k for k, r in source.items() if r['category'] == category and (split == 'fit' or k not in train)]
            keys.sort(key=lambda k: hashlib.sha256(('hepta-banking77-subset-v1\0' + k).encode()).hexdigest())
            pool_sizes[split][category] = len(keys)
            if len(keys) < PER_CLASS[split]:
                raise ValueError('insufficient source examples; never shrink the denominator')
            for key in keys[:PER_CLASS[split]]:
                identity = split + ':' + hashlib.sha256(key.encode()).hexdigest()
                row = {'id': identity, 'text': source[key]['text']}
                if split == 'fit':
                    row['label'] = label
                else:
                    answers.append({'id': identity, 'label': label})
                inputs[split].append(row); selected_ids[split].append(identity)
    inputs['input_id'] = _digest(inputs)
    observer = {'schema': 'hepta.banking77-four-intent-labels.v1', 'input_id': inputs['input_id'], 'rows': answers}
    selection = {'schema': 'hepta.banking77-subset-selection.v1', 'input_id': inputs['input_id'],
                 'raw_sha256': {'train': hashlib.sha256(train_bytes).hexdigest(), 'test': hashlib.sha256(test_bytes).hexdigest()},
                 'duplicate_rows': {'train': train_dups, 'test': test_dups}, 'excluded_test_overlap': len(overlap),
                 'pool_sizes': pool_sizes, 'selected_ids': selected_ids, 'task_subset_not_full_benchmark': True}
    return inputs, observer, selection
