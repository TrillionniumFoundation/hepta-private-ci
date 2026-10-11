"""Original public intent labels and label-free partial-text acquisition views.

The eight banking intents are new to the four-intent composition studies.
They are public historical data, NOT independent future Hepta observations.
"""
import hashlib
from collections import defaultdict
from pathlib import Path
import re

from four_gate_common import digest, require, strict_loads
from four_gate_public_replay import DATA_PINS, DATA_REV, read_public_data

INTENTS = ('freeze_account', 'routing', 'pin_change', 'pay_bill',
           'interest_rate', 'transfer', 'balance', 'report_fraud')
PARTITIONS = (('fit', 'train', 0, 60), ('kernel', 'train', 60, 100),
              ('selection', 'val', 0, 10), ('validation', 'val', 10, 20),
              ('test', 'test', 0, 30))


def load_publisher(directory):
    """Read unchanged publisher bytes, or fetch the existing pinned public source."""
    directory = Path(directory)
    if not directory.exists(): read_public_data(directory)
    for name, (size, blob) in DATA_PINS.items():
        path = directory/name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == size,
                'missing/changed original publisher file')
        raw = path.read_bytes()
        require(hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest() == blob,
                'original publisher Git blob mismatch')
    return strict_loads((directory/'data/data_full.json').read_bytes())


def partition(data):
    grouped = defaultdict(list)
    for origin in ('train', 'val', 'test'):
        for ordinal, (text, label) in enumerate(data[origin]):
            if label in INTENTS:
                require(type(text) is str and 0 < len(text) <= 4096, 'bounded original text')
                grouped[(origin, label)].append({'id': f'{origin}:{ordinal}', 'text': text,
                    'label': INTENTS.index(label), 'text_sha256': digest(text)})
    result, seen = {}, set()
    for split, origin, begin, end in PARTITIONS:
        result[split] = []
        for label in INTENTS:
            rows = grouped[(origin, label)]
            require(len(rows) >= end, 'publisher count mismatch')
            result[split].extend(rows[begin:end])
        hashes = [r['text_sha256'] for r in result[split]]
        require(len(set(hashes)) == len(hashes) and not seen.intersection(hashes),
                'source overlap; do not silently discard difficult/duplicate rows')
        seen.update(hashes)
        result[split].sort(key=lambda r: r['id'])
    return result


def text_view(text, view):
    require(type(text) is str and 0 < len(text) <= 4096 and
            type(view) is int and view in (0, 1, 2), 'text/view contract')
    words = re.findall(r'\S+', text)
    require(words, 'empty utterance')
    return ' '.join(words[:3]) if view == 0 else ' '.join(words[-3:]) if view == 1 else text


def hashed_reference(texts, torch):
    """Deterministic, untrained 384-d lexical reference. NEVER labelled mmBERT."""
    rows = torch.zeros(len(texts), 384)
    for i, text in enumerate(texts):
        value = ' '+text.lower()+' '
        terms = value.split()+[value[j:j+3] for j in range(max(0, len(value)-2))]
        for term in terms:
            key = hashlib.sha256(term.encode()).digest()
            rows[i, int.from_bytes(key[:4], 'little') % 384] += 1. if key[4] & 1 else -1.
    return torch.nn.functional.normalize(rows, dim=1)
