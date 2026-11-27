"""Independent-person twelve-activity training and sealed, cold confirmation."""
import time
STARTED = time.perf_counter()
import argparse
import copy
import hashlib
import json
import os
import resource
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from prepare import digest
from qualification.hcsn_closure_20261124.boundary_fix import BoundaryControlHCSN
from qualification.hcsn_smallnet_20261124.model import ModelConfig

ARMS = ('qvi_joint', 'qvi_boundary', 'smooth', 'gru', 'lif', 'attention', 'ridge')
SEEDS = (1729, 2718)
FOLDS = {'A': ([1, 3, 5], [7, 9], [2, 4, 6, 8, 10]),
         'B': ([2, 4, 6], [8, 10], [1, 3, 5, 7, 9])}


def write(path, x):
    path.write_text(json.dumps(x, indent=2, allow_nan=False) + '\n')


class Smooth(nn.Module):
    def __init__(self):
        super().__init__()
        self.input = nn.Linear(18, 40)
        self.rec = nn.Linear(20, 40)
        self.head = nn.Linear(20, 12)

    def forward(self, x):
        h = x.new_zeros(len(x[0]), 20)
        for t in x:
            value, gate = (self.input(t) + self.rec(h)).chunk(2, dim=-1)
            h = torch.lerp(h, value.tanh(), gate.sigmoid())
        return self.head(h)


class Lif(nn.Module):
    def __init__(self):
        super().__init__()
        self.input = nn.Linear(18, 20)
        self.rec = nn.Linear(20, 20, bias=False)
        self.decay = nn.Parameter(torch.zeros(20))
        self.threshold = nn.Parameter(torch.zeros(20))
        self.head = nn.Linear(20, 12)

    def forward(self, x):
        h = x.new_zeros(len(x[0]), 20)
        spike = torch.zeros_like(h)
        read = torch.zeros_like(h)
        thresh = .1 + F.softplus(self.threshold)
        for t in x:
            h = self.decay.sigmoid() * h + self.input(t) + self.rec(spike)
            margin = h - thresh
            surrogate = (4 * margin).sigmoid()
            spike = (margin >= 0).to(h) + (surrogate - surrogate.detach())
            h = h - thresh * spike
            read = read + spike
        return self.head(read / len(x))


class Attention(nn.Module):
    def __init__(self):
        super().__init__()
        self.input = nn.Linear(18, 20)
        self.pos = nn.Parameter(torch.randn(8, 1, 20) * .02)
        self.attn = nn.MultiheadAttention(20, 1, dropout=0.)
        self.norm = nn.LayerNorm(20)
        self.mlp = nn.Sequential(nn.Linear(20, 40), nn.GELU(), nn.Linear(40, 20))
        self.out_norm = nn.LayerNorm(20)
        self.head = nn.Linear(20, 12)

    def forward(self, x):
        h = self.input(x) + self.pos[:len(x)]
        mask = torch.ones(len(x), len(x), device=x.device, dtype=torch.bool).triu(1)
        y, _ = self.attn(h, h, h, attn_mask=mask, need_weights=False)
        h = self.norm(h + y)
        return self.head(self.out_norm(h + self.mlp(h))[-1])


class Gru(nn.Module):
    def __init__(self):
        super().__init__()
        self.gru = nn.GRU(18, 20)
        self.head = nn.Linear(20, 12)

    def forward(self, x):
        y, _ = self.gru(x)
        return self.head(y[-1])


def make(arm):
    if arm in ('qvi_joint', 'qvi_boundary'):
        config = ModelConfig(input_size=18, neurons=8, dt=.32, precision='mixed',
                             backend='uniformized', message_mode='full')
        model = BoundaryControlHCSN(config, channel='boundary_signed' if arm == 'qvi_joint'
                                    else 'boundary_only', control_mode='accumulate', boundary_mode='centered')
        model.readout = nn.Linear(model.feature_dim, 12)
        return model
    return {'gru': Gru, 'attention': Attention, 'smooth': Smooth, 'lif': Lif}[arm]()


def logits(model, x):
    result = model(x.transpose(0, 1))
    return result[-1] if result.ndim == 3 else result


def load(data, persons):
    receipts = json.loads((data / 'data.json').read_text())['participant']
    xx, yy, pp, ss = [], [], [], []
    for person in persons:
        path = data / f'p{person:02d}.npz'
        if digest(path) != receipts[str(person)]['prepared_sha256']:
            raise ValueError(f'altered input for {person}')
        with np.load(path) as z:
            xx.append(torch.from_numpy(z['x']))
            yy.append(torch.from_numpy(z['y']))
            pp.extend([person] * len(yy[-1]))
            ss.extend(z['starts'])
    return torch.cat(xx), torch.cat(yy), np.asarray(pp), np.asarray(ss)


def scale(x, m, s):
    return ((x - m) / s).clamp(-6, 6)


def scores(p, y):
    yp = p.argmax(1)
    return {'accuracy': float((yp == y).mean()),
            'macro': float(np.mean([(yp[y == k] == k).mean() for k in np.unique(y)])),
            'brier': float(np.mean(np.sum((p - np.eye(12)[y]) ** 2, axis=1))),
            'ce': float(-np.mean(np.log(p[np.arange(len(y)), y].clip(1e-12, 1))))}


@torch.no_grad()
def neural_preds(model, x):
    model.eval()
    return torch.cat([logits(model, z).softmax(1) for z in x.split(8)]).cpu().numpy()


def batch_order(y, updates, classes, seed):
    rng = np.random.default_rng(seed)
    ids = {k: np.flatnonzero(y.numpy() == k) for k in classes}
    draws = []
    for _ in range(updates):
        # Uniform class sampling, with replacement, in both learning stages.
        keys = rng.choice(classes, size=24)
        draws.append(torch.tensor([rng.choice(ids[int(k)]) for k in keys], dtype=torch.long))
    return draws


def dense_features(x):
    h = x.double().reshape(len(x), -1)
    return torch.cat((h, torch.ones(len(h), 1, dtype=h.dtype)), 1)


def ridge_candidate(x, y, alpha):
    h = dense_features(x)
    reg = torch.eye(h.shape[1], dtype=h.dtype) * alpha
    reg[-1, -1] = 0
    v = F.one_hot(y, num_classes=12).to(h)
    return torch.linalg.solve(h.T @ h + reg, h.T @ v)


def ridge_predictions(x, w):
    return (dense_features(x) @ w).softmax(1).numpy()


def train(args):
    out = args.output
    out.mkdir(exist_ok=False, parents=True)
    train_p, dev_p, _ = FOLDS[args.fold]
    tx, ty, _, _ = load(args.data, train_p)
    dx, dy, _, _ = load(args.data, dev_p)
    mean = tx.mean((0, 1))
    std = tx.std((0, 1), unbiased=False).clamp_min(1e-4)
    tx, dx = scale(tx, mean, std), scale(dx, mean, std)
    dev_samples = len(dy)
    front = {'mean': mean, 'std': std}
    history = []
    if args.arm == 'ridge':
        states = {}
        for phase, use in [('parent', ty < 6), ('candidate', torch.ones_like(ty, dtype=torch.bool))]:
            ix = dy < 6 if phase == 'parent' else torch.ones_like(dy, dtype=torch.bool)
            options = []
            for a in [.01, .1, 1., 10.]:
                w = ridge_candidate(tx[use], ty[use], a)
                metrics = scores(ridge_predictions(dx[ix], w), dy[ix].numpy())
                options.append((metrics['ce'], a, w))
                history.append({'stage': phase, 'alpha': a, **metrics, 'wall': time.perf_counter() - STARTED})
            states[phase] = min(options, key=lambda item: (item[0], item[1]))[2]
        chosen = None
        parameters = int(states['candidate'].numel())
    else:
        model = make(args.arm)
        parameters = sum(v.numel() for v in model.parameters() if v.requires_grad)
        optimizer = torch.optim.AdamW(model.parameters(), lr=.01)
        old = batch_order(ty, 32, np.arange(6), args.seed + 101)
        new = batch_order(ty, 96, np.arange(12), args.seed + 307)
        best_ce = float('inf')
        states = {}
        for phase, batches in [('parent', old), ('candidate', new)]:
            for step in range(len(batches) + 1):
                if phase == 'candidate' and step % 16 == 0:
                    metrics = scores(neural_preds(model, dx), dy.numpy())
                    history.append({'stage': phase, 'step': step, **metrics,
                                    'wall': time.perf_counter() - STARTED})
                    if metrics['ce'] < best_ce:
                        best_ce = metrics['ce']
                        states['candidate'] = copy.deepcopy(model.state_dict())
                        chosen = step
                if step == len(batches):
                    break
                rows = batches[step]
                optimizer.zero_grad()
                model.train()
                for micro in rows.split(4):
                    loss = F.cross_entropy(logits(model, tx[micro]), ty[micro])
                    (loss * (len(micro) / len(rows))).backward()
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 2.)
                if not torch.isfinite(loss) or not torch.isfinite(norm):
                    raise FloatingPointError('nonfinite training loss/derivative')
                optimizer.step()
            if phase == 'parent':
                states['parent'] = copy.deepcopy(model.state_dict())
    torch.save({**front, **states}, out / 'states.pt')
    write(out / 'fit.json', {'fold': args.fold, 'seed': args.seed, 'arm': args.arm,
        'train': train_p, 'dev': dev_p, 'n_train': len(ty), 'n_dev': dev_samples,
        'selected_step': chosen, 'history': history, 'parameters': parameters,
        'state_sha256': digest(out / 'states.pt'), 'inner_wall': time.perf_counter() - STARTED,
        'maxrss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})


def evaluate(args):
    out = args.output
    seal = json.loads((out.parent / 'seal.json').read_text())
    if seal['states'][out.name] != digest(out / 'states.pt'):
        raise ValueError('evaluation weights differ from sealed fit')
    if seal['source'][Path(__file__).name] != digest(__file__):
        raise ValueError('evaluation code changed following seal')
    state = torch.load(out / 'states.pt', map_location='cpu', weights_only=True)
    xx, yy, people, starts = load(args.data, FOLDS[args.fold][2])
    xx = scale(xx, state['mean'], state['std'])
    predictions = {'y': yy.numpy(), 'people': people, 'starts': starts}
    model = None if args.arm == 'ridge' else make(args.arm)
    for tag in ('parent', 'candidate'):
        if model is not None:
            model.load_state_dict(state[tag], strict=True)
        for view in ('all', 'no_acc', 'no_gyro') if tag == 'candidate' else ('all',):
            xview = xx
            if view != 'all':
                xview = xx.clone()
                channels = [0,1,2,9,10,11] if view == 'no_acc' else [3,4,5,6,7,8,12,13,14,15,16,17]
                xview[:, :, channels] = 0
            p = ridge_predictions(xview, state[tag]) if model is None else neural_preds(model, xview)
            predictions[f'{tag}_{view}'] = p
    np.savez_compressed(out / 'predictions.npz', **predictions)
    write(out / 'eval.json', {'test_people': FOLDS[args.fold][2], 'n': len(yy),
        'inner_wall': time.perf_counter() - STARTED,
        'prediction_sha256': digest(out / 'predictions.npz'),
        'maxrss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('train', 'evaluate'))
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--fold', choices=FOLDS, required=True)
    p.add_argument('--arm', choices=ARMS, required=True)
    p.add_argument('--seed', type=int, choices=SEEDS, required=True)
    args = p.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(args.seed)
    train(args) if args.mode == 'train' else evaluate(args)


if __name__ == '__main__':
    main()
