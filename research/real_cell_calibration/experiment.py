"""Offline frozen-feature pilot; no network, process control, or scientific pass flag."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import time

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[key] = '4'
import numpy as np
from scipy.special import expit
from sklearn.metrics import f1_score, recall_score, log_loss, balanced_accuracy_score

SEED = 20261023
HISTORICAL_BANK_SHA256 = '1a4458c0d065d697ae491190ec00c0d30b29b8bc853cb96400d9ed1d432941ae'
# Deterministic import_history.py output from the pinned, verified archive.
# Pin labels, endpoints, source groups and original splits as well as features.
HISTORICAL_MANIFEST_SHA256 = '3fae2bd29e33c390424ee00638d341cd9c0f4146f540c8f132152c69ae7b2189'
CONFIG = dict(seed=SEED, dimension=32, steps=300, lr=0.03, l2=0.001,
              threads=4, block_size=5, alpha=0.1, temperatures=[0.5, 1, 2, 4, 8],
              confidence=0.8, minimum_coverage=0.5, minimum_minority_recall=0.7,
              minimum_test_blocks=50, improvement=0.02, bootstrap=1000)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + '\n')


def norm(x):
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)


def fixture(out):
    """Synthetic plumbing input, deliberately not evidence of natural generalization."""
    out.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(SEED)
    a = norm(rng.normal(size=(600, 64)))
    b = norm(a + rng.normal(scale=0.14, size=a.shape))
    np.savez(out / 'features.npz', image=a, text=b)
    rows = [dict(id=str(i), source_id=f'synthetic-{i}', page_id=f'page-{i}',
                 image_sha256=hashlib.sha256(f'fixture-{i}'.encode()).hexdigest())
            for i in range(len(a))]
    save(out / 'manifest.json', dict(kind='synthetic_engineering_only', rows=rows))


def components(rows):
    parent = list(range(len(rows)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, row in enumerate(rows):
        for key in ('source_id', 'page_id', 'image_sha256'):
            value = row[key]
            if not value:
                raise ValueError(f'Empty {key}')
            token = (key, value)
            if token in seen:
                parent[root(i)] = root(seen[token])
            seen[token] = i
    groups = {}
    for i in range(len(rows)):
        groups.setdefault(root(i), []).append(i)
    return sorted(groups.values(), key=lambda g: min(rows[i]['id'] for i in g))


def inputs(folder):
    manifest = json.loads((folder / 'manifest.json').read_text())
    rows = manifest['rows']
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate row IDs')
    if manifest['kind'] == 'historical_P39_development_only':
        if digest(folder / 'manifest.json') != HISTORICAL_MANIFEST_SHA256:
            raise ValueError('Historical manifest mismatch')
        if digest(folder / 'features.npz') != HISTORICAL_BANK_SHA256:
            raise ValueError('Historical bank mismatch')
    elif manifest['kind'] != 'synthetic_engineering_only':
        # A manifest assertion is insufficient evidence: the referenced local bytes must exist.
        if manifest.get('encoder') != 'OpenAI CLIP ViT-B/32':
            raise ValueError('Frozen natural encoder mismatch')
        weights = folder / manifest['weights_path']
        expected = '40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af'
        if digest(weights) != expected:
            raise ValueError('Official checkpoint hash mismatch')
        for row in rows:
            for key in ('source_url', 'author', 'image_license', 'text_license',
                        'license_evidence_path', 'image_path', 'caption'):
                if not row.get(key):
                    raise ValueError(f'Missing provenance {key}')
            if digest(folder / row['image_path']) != row['image_sha256']:
                raise ValueError('Image hash mismatch')
            if digest(folder / row['license_evidence_path']) != row['license_evidence_sha256']:
                raise ValueError('License evidence hash mismatch')
        raise ValueError('Natural execution locked: extraction/audit and exact data freeze pending')
    with np.load(folder / 'features.npz', allow_pickle=False) as bank:
        a, b = bank['image'], bank['text']
    if a.shape != b.shape or a.shape[0] != len(rows) or a.shape[1] < 32:
        raise ValueError('Feature shape mismatch')
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('Nonfinite features')
    return manifest, norm(a), norm(b)


def design(manifest, a, b):
    """Cluster before split; negative donors stay inside disjoint five-component blocks."""
    rows = manifest['rows']
    if manifest['kind'] == 'historical_P39_development_only':
        examples = manifest['historical_examples']
        assigned = {}
        for item in examples:
            for index in (item['image'], item['text']):
                if assigned.setdefault(index, item['split']) != item['split']:
                    raise ValueError('Historical endpoint crosses splits')
        for group in components(rows):
            if len({assigned[i] for i in group}) != 1:
                raise ValueError('Historical source cluster crosses splits')
        return examples
    groups = components(rows)
    rng = np.random.default_rng(SEED)
    rng.shuffle(groups)
    examples = []
    for start in range(0, len(groups), CONFIG['block_size']):
        chunk = groups[start:start + CONFIG['block_size']]
        if len(chunk) < 3:
            continue
        ids = [i for g in chunk for i in g]
        block = hashlib.sha256('|'.join(sorted(rows[i]['id'] for i in ids)).encode()).hexdigest()
        bucket = int(block[:8], 16) % 100
        split = 'train' if bucket < 60 else 'temperature' if bucket < 70 else 'calibration' if bucket < 85 else 'test'
        for g in chunk:
            donors = [i for h in chunk if h is not g for i in h]
            for i in g:
                hard = sorted(donors, key=lambda j: (-float(a[i] @ b[j]), rows[j]['id']))[0]
                random = int(rng.choice([j for j in donors if j != hard]))
                for j, label, kind in [(i, 1, 'paired'), (hard, 0, 'hard_negative'), (random, 0, 'random_negative')]:
                    examples.append(dict(image=i, text=j, y=label, kind=kind, split=split, block=block))
    return examples


def freeze(folder, out):
    manifest, a, b = inputs(folder)
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'freeze.json', dict(config=CONFIG, code_sha256=digest(__file__),
         manifest_sha256=digest(folder / 'manifest.json'), bank_sha256=digest(folder / 'features.npz'),
         kind=manifest['kind'], examples=design(manifest, a, b)))


def forward(w, a, b, kind, state=None):
    d = a.shape[1]
    u, v, c = w[:d], w[d:2*d], w[-1]
    if kind == 'linear':
        return a @ u + b @ v + c, np.column_stack((a, b, np.ones(len(a))))
    if kind == 'gated':
        s = np.sum(a*b, axis=1) if state is None else state
        g = expit(c*s)
        x, y = a @ u, b @ v
        return g*x+(1-g)*y, np.column_stack((g[:, None]*a, (1-g[:, None])*b, g*(1-g)*s*(x-y)))
    if kind == 'mlp':
        x = np.column_stack((a, b))
        h = np.tanh(x @ w[:-1])
        return c*h, np.column_stack((c*(1-h*h)[:, None]*x, h))
    if kind == 'lowrank':
        x, y = a @ u, b @ v
        return x*y+c, np.column_stack((y[:, None]*a, x[:, None]*b, np.ones(len(a))))
    raise ValueError(kind)


def train(a, b, y, kind):
    rng = np.random.default_rng(SEED)
    w = rng.normal(scale=0.1, size=2*a.shape[1]+1)
    m, v = np.zeros_like(w), np.zeros_like(w)
    for step in range(1, CONFIG['steps']+1):
        logits, jac = forward(w, a, b, kind)
        grad = jac.T @ (expit(logits)-y)/len(y) + CONFIG['l2']*w
        m, v = 0.9*m+0.1*grad, 0.999*v+0.001*grad*grad
        w -= CONFIG['lr']*(m/(1-0.9**step))/(np.sqrt(v/(1-0.999**step))+1e-8)
    return w


def metrics(y, p, groups, q):
    pred = (p >= 0.5).astype(int)
    confidence = np.maximum(p, 1-p)
    accepted = confidence >= CONFIG['confidence']
    true_score = np.where(y == 1, 1-p, p)
    bins = np.minimum((confidence*10).astype(int), 9)
    ece = sum(np.mean(bins == k)*abs(np.mean(confidence[bins == k])-np.mean(pred[bins == k] == y[bins == k]))
              for k in range(10) if np.any(bins == k))
    return dict(n=len(y), macro_f1=float(f1_score(y, pred, average='macro', zero_division=0)),
        balanced_accuracy=float(balanced_accuracy_score(y, pred)),
        positive_recall=float(recall_score(y, pred, pos_label=1, zero_division=0)),
        minority_recall=(float(recall_score(y, pred, pos_label=int(np.argmin(np.bincount(y, minlength=2))), zero_division=0))
                         if np.sum(y == 0) != np.sum(y == 1) else None),
        per_class_recall=recall_score(y, pred, labels=[0, 1], average=None, zero_division=0).tolist(),
        nll=float(log_loss(y, np.column_stack((1-p, p)), labels=[0, 1])),
        brier=float(np.mean((p-y)**2)), ece=float(ece), coverage=float(accepted.mean()),
        selective_risk=float(np.mean(pred[accepted] != y[accepted])) if accepted.any() else None,
        conformal_row_coverage=float(np.mean(true_score <= q)),
        conformal_block_coverage=float(np.mean([np.all(true_score[groups == g] <= q) for g in np.unique(groups)])),
        mean_set_size=float(np.mean((p <= q).astype(int)+(1-p <= q).astype(int))))


def run(folder, out):
    start = time.perf_counter()
    frozen = json.loads((out / 'freeze.json').read_text())
    for actual, expected in [(digest(__file__), frozen['code_sha256']),
                             (digest(folder / 'manifest.json'), frozen['manifest_sha256']),
                             (digest(folder / 'features.npz'), frozen['bank_sha256'])]:
        if actual != expected:
            raise ValueError('Frozen input/code drift')
    if frozen['config'] != CONFIG:
        raise ValueError('Frozen config drift')
    manifest, raw_a, raw_b = inputs(folder)
    examples = frozen['examples']
    if examples != design(manifest, raw_a, raw_b):
        raise ValueError('Split/example drift')
    split = np.array([x['split'] for x in examples])
    blocks = np.array([x['block'] for x in examples])
    y = np.array([x['y'] for x in examples])
    ix, tx = np.array([x['image'] for x in examples]), np.array([x['text'] for x in examples])
    full_a, full_b = raw_a[ix], raw_b[tx]
    projection = np.linalg.qr(np.random.default_rng(SEED).normal(size=(raw_a.shape[1], 32)))[0]
    a, b = norm(full_a @ projection), norm(full_b @ projection)
    masks = {s: split == s for s in ('train', 'temperature', 'calibration', 'test')}
    if any(not mask.any() for mask in masks.values()):
        raise ValueError('Empty split')
    train_mask, temp_mask, cal_mask, test_mask = [masks[k] for k in masks]
    models = {}
    training = {}
    for kind in ('linear', 'gated', 'lowrank', 'mlp', 'text_only', 'image_only', 'full_linear'):
        aa, bb = (full_a, full_b) if kind == 'full_linear' else (a, b)
        aa = np.zeros_like(aa) if kind == 'text_only' else aa
        bb = np.zeros_like(bb) if kind == 'image_only' else bb
        family = kind if kind in ('gated', 'lowrank', 'mlp') else 'linear'
        tick = time.perf_counter()
        w = train(aa[train_mask], bb[train_mask], y[train_mask], family)
        models[kind] = (w, family)
        training[kind] = dict(parameters=len(w), seconds=time.perf_counter()-tick, steps=CONFIG['steps'])
    # Store trained weights before accessing evaluation predictions.
    np.savez(out / 'heads.npz', **{k: v[0] for k, v in models.items()}, projection=projection)
    cache = norm(np.column_stack((full_a[train_mask], full_b[train_mask])))
    cache_labels = 2*y[train_mask]-1  # Pair correspondence, never answer positions.
    def predict(kind, aa, bb, fa, fb, state=None):
        cosine = 20*(np.sum(fa*fb, axis=1)-0.25)
        if kind == 'cosine':
            return cosine
        if kind == 'cache_inspired':
            affinity = norm(np.column_stack((fa, fb))) @ cache.T
            return cosine + np.exp(-5*(1-affinity)) @ cache_labels
        if kind == 'full_linear':
            aa, bb = fa, fb
        if kind == 'text_only':
            aa = np.zeros_like(aa)
        if kind == 'image_only':
            bb = np.zeros_like(bb)
        w, family = models[kind]
        return forward(w, aa, bb, family, state)[0]
    summary, predictions, probabilities = {}, [], {}
    for kind in list(models)+['cosine', 'cache_inspired']:
        clean = predict(kind, a, b, full_a, full_b)
        temperature = min(CONFIG['temperatures'], key=lambda t: float(np.mean(np.logaddexp(0, clean[temp_mask]/t)-y[temp_mask]*clean[temp_mask]/t)))
        cal_p = expit(clean[cal_mask]/temperature)
        scores = np.where(y[cal_mask] == 1, 1-cal_p, cal_p)
        cal_groups = blocks[cal_mask]
        maxima = sorted(max(scores[cal_groups == g]) for g in np.unique(cal_groups))
        rank = int(np.ceil((len(maxima)+1)*(1-CONFIG['alpha'])))
        q = maxima[rank-1] if rank <= len(maxima) else 1.0
        for condition in ('paired', 'shuffle_text', 'missing_text', 'missing_image', 'constant_state', 'shuffle_state'):
            aa, bb, fa, fb = a.copy(), b.copy(), full_a.copy(), full_b.copy()
            order = np.arange(len(y))
            for g in np.unique(blocks[test_mask]):
                indexes = np.flatnonzero(test_mask & (blocks == g))
                order[indexes] = np.roll(indexes, 1)
            state = None
            if condition == 'shuffle_text':
                bb, fb = bb[order], fb[order]
            elif condition == 'missing_text':
                bb, fb = bb*0, fb*0
            elif condition == 'missing_image':
                aa, fa = aa*0, fa*0
            elif condition == 'constant_state':
                state = np.ones(len(y))
            elif condition == 'shuffle_state':
                state = np.sum(aa*bb, axis=1)[order]
            p = expit(predict(kind, aa, bb, fa, fb, state)/temperature)[test_mask]
            key = f'{kind}/{condition}'
            summary[key] = dict(metrics(y[test_mask], p, blocks[test_mask], q), temperature=temperature, conformal_q=float(q))
            probabilities[key] = p
            for idx, prob in zip(np.flatnonzero(test_mask), p):
                predictions.append(dict(examples[idx], model=kind, condition=condition, probability=float(prob),
                    prediction=int(prob >= 0.5), accepted=bool(max(prob, 1-prob) >= CONFIG['confidence']),
                    prediction_set=[label for label, score in [(0, prob), (1, 1-prob)] if score <= q]))
    # Paired block bootstrap; three predeclared comparisons with Bonferroni 98.333% intervals.
    groups = np.unique(blocks[test_mask])
    rng = np.random.default_rng(SEED+2)
    contrasts = {}
    for candidate in ('gated', 'lowrank', 'mlp'):
        deltas = []
        for _ in range(CONFIG['bootstrap']):
            selected = rng.choice(groups, size=len(groups), replace=True)
            ids = np.concatenate([np.flatnonzero(blocks[test_mask] == g) for g in selected])
            truth = y[test_mask][ids]
            deltas.append(f1_score(truth, probabilities[candidate+'/paired'][ids] >= 0.5, average='macro', zero_division=0)-
                          f1_score(truth, probabilities['linear/paired'][ids] >= 0.5, average='macro', zero_division=0))
        contrasts[candidate] = dict(delta_macro_f1=summary[candidate+'/paired']['macro_f1']-summary['linear/paired']['macro_f1'],
                                  interval=np.quantile(deltas, [0.05/6, 1-0.05/6]).tolist())
    save(out / 'metrics.json', dict(status='ENGINEERING_ONLY_NO_SCIENTIFIC_PASS', input_kind=manifest['kind'], metrics=summary,
         comparisons=contrasts, training=training, split_blocks={s: len(np.unique(blocks[m])) for s, m in masks.items()},
         wall_seconds=time.perf_counter()-start, max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
         numpy=np.__version__, freeze_sha256=digest(out / 'freeze.json')))
    with (out / 'predictions.jsonl').open('w') as handle:
        for row in predictions:
            handle.write(json.dumps(row, sort_keys=True)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['fixture', 'freeze', 'run'])
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'fixture':
        fixture(args.input)
    elif args.action == 'freeze':
        freeze(args.input, args.output)
    else:
        run(args.input, args.output)
