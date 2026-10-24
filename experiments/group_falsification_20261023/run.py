"""Synthetic diagnostic: never evidence of natural-data or neural reasoning gain."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '4'
import argparse
import hashlib
import json
from pathlib import Path
import resource
import time
import warnings
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.exceptions import ConvergenceWarning

ROOT = Path(__file__).resolve().parent
PROTO = json.loads((ROOT / 'protocol.json').read_text())
EYE = np.eye(8)


def seed_for(*parts):
    return int.from_bytes(hashlib.sha256('|'.join(map(str, parts)).encode()).digest()[:4], 'big')


def dataset(seed, split, size):
    # Each record is a separate generated source root; never split its members.
    pairs = np.array([np.random.default_rng(seed_for(seed, split, i)).integers(8, size=2)
                      for i in range(size)])
    return pairs, pairs.sum(axis=1) % 8


def features(pairs, relation=False):
    a, b = EYE[pairs[:, 0]], EYE[pairs[:, 1]]
    if relation:
        # Task-aligned explicit pair interaction, NOT learned general reasoning.
        return np.stack([sum(a[:, j] * b[:, (k-j) % 8] for j in range(8))
                         for k in range(8)], axis=1)
    return a + b


def probabilities(model, name, pairs):
    if name == 'cosine':
        scores = features(pairs)
        exp = np.exp(scores - scores.max(axis=1, keepdims=True))
        return exp / exp.sum(axis=1, keepdims=True)
    return model.predict_proba(features(pairs, name == 'relation'))


def model_flops(model, name, n):
    # Dense multiply-add estimate only; softmax, tokenization, hashing excluded.
    if name == 'cosine':
        return n * 8 * 2
    if name == 'mlp':
        return n * sum(2 * w.size for w in model.coefs_)
    return n * (2 * model.coef_.size + (128 if name == 'relation' else 8))


def bootstrap(delta, seed):
    rng = np.random.default_rng(seed)
    d = np.array(delta, dtype=float)
    means = d[rng.integers(len(d), size=(2000, len(d)))].mean(axis=1)
    return [float(x) for x in np.quantile(means, [.025, .975])]


def summary(rows):
    n = len(rows)
    answered = sum(r['answered'] for r in rows)
    correct = sum(r['correct'] for r in rows)
    return {'n': n, 'correct': correct, 'accuracy': correct/n,
            'coverage': answered/n, 'selective_risk': (answered-correct)/answered if answered else None,
            'calls': sum(r['calls'] for r in rows),
            'cpu_seconds': sum(r['cpu_seconds'] for r in rows),
            'wall_seconds': sum(r['wall_seconds'] for r in rows)}


class World:
    """Only retrieve exposes node members. Wrong edges are dead ends, discovered on read."""
    def __init__(self, seed, episode, depth):
        self.root = (seed, 'search_holdout', episode, depth)
        self.depth = depth
        self.answer = int(np.random.default_rng(seed_for(*self.root, 'answer')).integers(8))

    def retrieve(self, path):
        if path:
            previous = path[:-1]
            a, b = self.members(previous)
            if path[-1] != (a+b) % 8:
                return {'kind': 'dead'}
        if len(path) == self.depth:
            return {'kind': 'terminal', 'answer': self.answer}
        return {'kind': 'node', 'members': self.members(path)}

    def members(self, path):
        return np.random.default_rng(seed_for(*self.root, 'members', path)).integers(8, size=2).tolist()


def solve(seed, episode, budget, policy, variant, models, majority):
    wall, cpu = time.perf_counter(), time.process_time()
    world = World(seed, episode, budget // 4)
    events, path, stack, calls, prediction = [], (), [], 0, None
    estimated_flops, candidate_evals, retrievals, verifications, backs = 0, 0, 0, 0, 0
    attempt = 0

    def log(kind, **fields):
        nonlocal calls
        calls += 1
        events.append({'step': calls, 'kind': kind, **fields})

    if policy == 'direct':
        prediction = majority  # no hidden node facts available
    while policy != 'direct' and calls < budget:
        observation = world.retrieve(path)
        retrievals += 1
        log('retrieve', path=list(path), observation=observation)
        if observation['kind'] == 'terminal':
            prediction = observation['answer']
            break
        if observation['kind'] == 'dead':
            if policy == 'bounded' and stack and calls < budget:
                parent, alternatives = stack.pop()
                next_edge = alternatives.pop(0)
                if alternatives:
                    stack.append((parent, alternatives))
                backs += 1
                log('backtrack', failed_path=list(path), parent=list(parent), edge=next_edge)
                path = parent + (next_edge,)
                continue
            if policy == 'best_of_2' and attempt == 0 and calls < budget:
                attempt += 1
                backs += 1
                log('restart', failed_path=list(path))
                path = ()
                continue
            break
        if calls >= budget:
            break
        members = observation['members'].copy()
        rng = np.random.default_rng(seed_for(seed, episode, budget, 'noise', path, attempt))
        if variant == 'member_order':
            members.reverse()
        if variant == 'member_corrupt':
            members[1] = int(np.random.default_rng(seed_for(seed, episode, 'other_root', path)).integers(8))
        if variant == 'masked':
            members[1] = 0  # deletes information using fixed neutral symbol, not gold
        head = 'relation' if policy in ('bounded', 'fixed_relation') else 'mlp'
        if policy == 'best_of_2':
            head = 'linear'
        raw = probabilities(models.get(head), head, np.array([members]))[0]
        sigma = rng.uniform(.1, .8, size=8)
        noise = rng.normal(size=8) * sigma
        if variant == 'zero_noise':
            sigma[:] = 0
            noise[:] = 0
        score = raw + noise
        if policy in ('bounded', 'fixed_relation') and variant != 'risk_neutral':
            score -= .25 * sigma**2
        order = np.argsort(-score, kind='stable').tolist()
        if variant == 'edge_shuffle':
            mapping = np.random.default_rng(seed_for(seed, episode, 'edges', path)).permutation(8)
            order = [int(mapping[i]) for i in order]
        selected = order[0]
        verifications += 1
        candidate_evals += 8
        estimated_flops += model_flops(models.get(head), head, 1)
        log('verify', path=list(path), visible_members=members, head=head,
            scores=score.tolist(), selected_edge=selected, candidate_evaluations=8)
        if policy == 'bounded':
            stack.append((path, order[1:]))
        path = path + (selected,)
    return {'seed': seed, 'episode': episode, 'budget': budget, 'policy': policy,
            'variant': variant, 'answer': world.answer, 'prediction': prediction,
            'answered': prediction is not None, 'correct': prediction == world.answer,
            'calls': calls, 'retrieval_calls': retrievals, 'verifier_calls': verifications,
            'backtrack_calls': backs, 'candidate_evaluations': candidate_evals,
            'flops_dense_estimate': estimated_flops,
            'failure': None if prediction is not None else 'unresolved_or_exhausted',
            'events': events, 'cpu_seconds': time.process_time()-cpu,
            'wall_seconds': time.perf_counter()-wall,
            'process_peak_rss_KiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    frozen = hashlib.sha256((ROOT/'protocol.json').read_bytes()).hexdigest()
    (out/'protocol.sha256').write_text(frozen+'\n')
    training, head_rows, search_rows, model_states = [], [], [], []
    for seed in PROTO['seeds']:
        x, y = dataset(seed, 'train', PROTO['split_sizes']['train'])
        dx, dy = dataset(seed, 'development', PROTO['split_sizes']['development'])
        cx, cy = dataset(seed, 'calibration', PROTO['split_sizes']['calibration'])
        majority = int(np.bincount(y, minlength=8).argmax())
        models, thresholds = {}, {}
        for name in PROTO['heads']:
            t, c = time.perf_counter(), time.process_time()
            model = None
            with warnings.catch_warnings(record=True) as ws:
                warnings.simplefilter('always', ConvergenceWarning)
                if name in ('linear', 'relation'):
                    model = LogisticRegression(C=1., max_iter=200, random_state=seed)
                    model.fit(features(x, name == 'relation'), y)
                if name == 'mlp':
                    model = MLPClassifier(hidden_layer_sizes=(32,), max_iter=120,
                                          random_state=seed, early_stopping=False)
                    model.fit(features(x), y)
            models[name] = model
            conf = probabilities(model, name, dx).max(axis=1)
            thresholds[name] = float(np.quantile(conf, .8))
            cal = probabilities(model, name, cx)
            training.append({'seed': seed, 'head': name, 'wall_seconds': time.perf_counter()-t,
                'cpu_seconds': time.process_time()-c, 'warnings': [str(w.message) for w in ws],
                'calibration_accuracy': float(np.mean(cal.argmax(1) == cy)),
                'threshold': thresholds[name], 'train_flops': None,
                'train_flops_reason': 'sklearn optimizer not instrumented; no fabricated total'})
            if model is not None:
                arrays = model.coefs_ + model.intercepts_ if name == 'mlp' else [model.coef_, model.intercept_]
                weights = out/f'weights_{seed}_{name}.npz'
                np.savez(weights, *arrays)
                model_states.append({'file': weights.name, 'sha256': hashlib.sha256(weights.read_bytes()).hexdigest()})
        # Freeze trained model bytes and thresholds BEFORE generating held-out roots.
        (out/f'frozen_{seed}.json').write_text(json.dumps({'protocol': frozen, 'thresholds': thresholds,
            'models': [r for r in model_states if f'_{seed}_' in r['file']]}, indent=2))
        hx, hy = dataset(seed, 'holdout', PROTO['split_sizes']['holdout'])
        for variant in ('normal', 'member_order', 'member_corrupt', 'masked'):
            v = hx.copy()
            if variant == 'member_order': v = v[:, ::-1]
            if variant == 'member_corrupt':
                v[:, 1] = dataset(seed, 'foreign_roots', len(hx))[0][:, 1]
            if variant == 'masked': v[:, 1] = 0
            for name in PROTO['heads']:
                t, c = time.perf_counter(), time.process_time()
                probs = probabilities(models[name], name, v)
                elapsed, cpu = time.perf_counter()-t, time.process_time()-c
                for i, (p, gold) in enumerate(zip(probs, hy)):
                    pred = int(p.argmax())
                    head_rows.append({'seed': seed, 'episode': i, 'head': name, 'variant': variant,
                        'gold': int(gold), 'prediction': pred, 'correct': pred == gold,
                        'confidence': float(p.max()), 'accepted': bool(p.max() >= thresholds[name]),
                        'answered': True, 'calls': 1, 'cpu_seconds': cpu/len(hx),
                        'wall_seconds': elapsed/len(hx), 'flops_dense_estimate': model_flops(models[name], name, 1)})
        for budget in PROTO['action_budgets']:
            for episode in range(PROTO['search_episodes_per_seed_budget']):
                for policy in PROTO['policies']:
                    for variant in PROTO['search_variants']:
                        search_rows.append(solve(seed, episode, budget, policy, variant, models, majority))
    for name, rows in [('training', training), ('heads', head_rows), ('trajectories', search_rows)]:
        with (out/f'{name}.jsonl').open('w') as f:
            for r in rows: f.write(json.dumps(r, default=lambda x: x.item())+'\n')
    groups = []
    for seed in PROTO['seeds']:
        for head in PROTO['heads']:
            for variant in ('normal', 'member_order', 'member_corrupt', 'masked'):
                rows = [r for r in head_rows if (r['seed'],r['head'],r['variant']) == (seed,head,variant)]
                accepted = [r for r in rows if r['accepted']]
                groups.append({'kind':'head','seed':seed,'method':head,'variant':variant,
                    **summary(rows), 'accepted_coverage':len(accepted)/len(rows),
                    'accepted_risk':1-np.mean([r['correct'] for r in accepted]) if accepted else None})
        for budget in PROTO['action_budgets']:
            for policy in PROTO['policies']:
                for variant in PROTO['search_variants']:
                    rows = [r for r in search_rows if (r['seed'],r['budget'],r['policy'],r['variant']) == (seed,budget,policy,variant)]
                    groups.append({'kind':'search','seed':seed,'budget':budget,'method':policy,
                                   'variant':variant, **summary(rows)})
    comparisons = []
    for seed in PROTO['seeds']:
        a = [r for r in head_rows if (r['seed'],r['head'],r['variant']) == (seed,'relation','normal')]
        for base in ('cosine','linear','mlp'):
            b = [r for r in head_rows if (r['seed'],r['head'],r['variant']) == (seed,base,'normal')]
            delta = [int(x['correct'])-int(y['correct']) for x,y in zip(a,b)]
            comparisons.append({'seed':seed,'kind':'head','comparison':'relation-'+base,
                'delta':float(np.mean(delta)),'ci95':bootstrap(delta,seed)})
        for budget in PROTO['action_budgets']:
            a = [r for r in search_rows if (r['seed'],r['budget'],r['policy'],r['variant']) == (seed,budget,'bounded','normal')]
            for base in ('direct','best_of_2','fixed_depth','fixed_relation'):
                b = [r for r in search_rows if (r['seed'],r['budget'],r['policy'],r['variant']) == (seed,budget,base,'normal')]
                delta = [int(x['correct'])-int(y['correct']) for x,y in zip(a,b)]
                comparisons.append({'seed':seed,'kind':'search','budget':budget,'comparison':'bounded-'+base,
                    'delta':float(np.mean(delta)),'ci95':bootstrap(delta,seed),
                    'equal_nominal_cap_only':True,'actual_call_difference':sum(x['calls']-y['calls'] for x,y in zip(a,b))})
    (out/'summary.json').write_text(json.dumps({'groups':groups,'comparisons':comparisons},indent=2,default=lambda x: x.item()))
    (out/'ledger.json').write_text(json.dumps({'protocol_sha256':frozen,
        'wall_seconds':time.perf_counter()-start_wall,'cpu_seconds':time.process_time()-start_cpu,
        'peak_rss_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'download_payload_bytes':0,
        'head_evaluations':len(head_rows),'trajectory_count':len(search_rows),
        'search_calls':sum(r['calls'] for r in search_rows),
        'failed_trajectories':sum(not r['answered'] for r in search_rows),
        'backtrack_restart_calls':sum(r['backtrack_calls'] for r in search_rows),
        'inference_dense_flops_estimate':sum(r['flops_dense_estimate'] for r in head_rows+search_rows),
        'total_flops':None,'total_flops_limitation':'training and scalar/environment overhead not instrumented',
        'model_jobs':1,'threads_cap':4},indent=2))
    print(json.dumps(json.loads((out/'ledger.json').read_text()),indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
