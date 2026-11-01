"""Disjoint public text partitions; raw payload encoding is invoked only on READ."""

import hashlib
import json
from pathlib import Path
import time
import unicodedata
from zipfile import ZipFile

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent
PROTOCOL = json.loads((ROOT / 'PROTOCOL.json').read_text())


def corpus(archive):
    archive = Path(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != PROTOCOL['dataset']['sha256']:
        raise ValueError('Dataset identity mismatch')
    with ZipFile(archive) as handle:
        lines = handle.read('SMSSpamCollection').decode('utf-8').splitlines()
    identities = {}
    for line in lines:
        label, text = line.split('\t', 1)
        if label not in ('ham', 'spam'):
            raise ValueError('Unknown dataset label')
        normalized = ' '.join(unicodedata.normalize('NFKC', text).casefold().split())
        key = hashlib.sha256(normalized.encode()).hexdigest()
        entry = identities.setdefault(key, {'text': text, 'labels': set()})
        entry['labels'].add(int(label == 'spam'))
    result = {part: [[], []] for part in ('encoder_train', 'core_train', 'validation', 'confirmation')}
    keys = {part: [] for part in result}
    conflicts = 0
    for key, entry in sorted(identities.items()):
        if len(entry['labels']) != 1:
            conflicts += 1
            continue
        bucket = int(key[:8], 16) % 100
        part = ('encoder_train' if bucket < 50 else 'core_train' if bucket < 65 else
                'validation' if bucket < 75 else 'confirmation')
        label = next(iter(entry['labels']))
        result[part][label].append(entry['text'])
        keys[part].append(key)
    metadata = {'raw_lines': len(lines), 'unique_normalized': len(identities),
        'conflicting_identities_removed': conflicts,
        'partition_counts': {p: [len(x) for x in pools] for p, pools in result.items()},
        'partition_identity_sha256': {p: hashlib.sha256('\n'.join(v).encode()).hexdigest()
                                      for p, v in keys.items()},
        'partition_disjoint': len(set(sum(keys.values(), []))) == sum(map(len, keys.values()))}
    return result, metadata


class TextEncoder:
    """Shared trained text frontend with an explicit, uncached batch encode call."""

    def __init__(self, coefficients, intercept):
        self.vectorizer = HashingVectorizer(ngram_range=(1, 2), n_features=2**14,
                                            alternate_sign=False, norm='l2')
        self.coefficients = np.asarray(coefficients, dtype=np.float64)
        self.intercept = float(intercept)
        self.edges = np.array(PROTOCOL['dataset']['evidence_logit_edges'])
        self.encode_calls, self.encode_cpu_seconds = 0, 0.0

    def encode(self, texts):
        if not texts:
            return np.empty(0, dtype=np.int64)
        tick = time.process_time()
        scores = self.vectorizer.transform(texts) @ self.coefficients + self.intercept
        result = np.searchsorted(self.edges, scores, side='right').astype(np.int64)
        self.encode_calls += len(texts)
        self.encode_cpu_seconds += time.process_time() - tick
        return result

    @classmethod
    def load(cls, path):
        payload = json.loads(Path(path).read_text())
        return cls(payload['coefficients'], payload['intercept'])


def fit_frontend(archive, output):
    start = time.process_time()
    pools, metadata = corpus(archive)
    vectorizer = HashingVectorizer(ngram_range=(1, 2), n_features=2**14,
                                   alternate_sign=False, norm='l2')
    examples = pools['encoder_train']
    texts = examples[0] + examples[1]
    labels = np.r_[np.zeros(len(examples[0])), np.ones(len(examples[1]))]
    classifier = LogisticRegression(C=1, max_iter=300, random_state=130001)
    classifier.fit(vectorizer.transform(texts), labels)
    encoder = TextEncoder(classifier.coef_[0], classifier.intercept_[0])
    # Only development partitions are encoded. Confirmation text stays unread.
    counts = {p: [np.bincount(encoder.encode(group), minlength=6).tolist()
                  for group in pools[p]] for p in ('core_train', 'validation')}
    payload = {'schema': 'hcsn-r13-text-frontend-v1', 'dataset': metadata,
        'coefficients': classifier.coef_[0].tolist(), 'intercept': float(classifier.intercept_[0]),
        'training_iterations': classifier.n_iter_.tolist(), 'development_counts': counts,
        'frontend_cpu_seconds': time.process_time()-start,
        'confirmation_encoded': False, 'trained_partition': 'encoder_train'}
    output = Path(output)
    if output.exists():
        raise FileExistsError('Never overwrite a fitted frontend')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(',', ':'))+'\n')
    return payload


class TextSensor:
    """The world owns class pools; actors see only the acquired encoded evidence."""

    def __init__(self, pools, encoder, n_active):
        self.pools, self.encoder, self.n_active = pools, encoder, n_active
        self.reset_counters()

    def reset_counters(self):
        self.raw_reads = self.recovery_reads = 0
        self.encoder.encode_calls = 0
        self.encoder.encode_cpu_seconds = 0.0

    def read(self, states, uniforms):
        states, uniforms = np.asarray(states), np.asarray(uniforms)
        nphase = self.n_active + 2
        active = np.flatnonzero(states % nphase < self.n_active)
        tokens = np.full(len(states), 6, dtype=np.int64)
        texts = []
        for row in active:
            label = int(states[row] // nphase)
            pool = self.pools[label]
            index = min(int(uniforms[row]*len(pool)), len(pool)-1)
            texts.append(pool[index])
        tokens[active] = self.encoder.encode(texts)
        self.raw_reads += len(active)
        self.recovery_reads += len(states)-len(active)
        return tokens
