"""One real training cell, or an independent cold test of a sealed COCO intervention."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import resource
import sys
import time

START = time.perf_counter()
ROOT = Path(os.environ.get('HEPTA_FLICKR_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT))
import numpy as np
import torch
from torch.nn import functional as F
from model import Captioner
from panel import score, Samples

METHODS = ('fixed', 'untied_edit16', 'tied_edit16', 'tied_gradient', 'full_gradient')
ARMS = ('hcsn', 'dense')
ORIGINS = ('random', 'flickr20')
SEEDS = (17011, 24203, 39827)
SCALES = (1., 4., 16., 64.)
RATES = (.0001, .0003, .001, .003)
BASE = ROOT/'tied_edit'
RESULT = BASE/'results'


def sha(p):
    with p.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(p, x):
    temp = p.with_name(p.name + '.part')
    temp.write_text(json.dumps(x, indent=2, sort_keys=True, allow_nan=False))
    temp.replace(p)


def store_model(model, p):
    tmp = p.with_suffix('.part')
    torch.save(model.state_dict(), tmp)
    tmp.replace(p)
    return sha(p)


def sample(split):
    meta = json.loads((BASE/'data/manifest.json').read_text())
    path = BASE/'data'/f'{split}.npz'
    assert sha(path) == meta['splits'][split]['sha256']
    with np.load(path) as z:
        s = Samples.__new__(Samples)
        s.pix = z['images']
        s.cap = z['tokens']
        s.ids = z['ids']
    return s


def parent(arm, seed, origin):
    torch.manual_seed(seed)
    m = Captioner(arm, 3490)
    if origin == 'flickr20':
        k = f'{arm}-{seed}'
        p = ROOT/'caption_external20'/k/'selected.pt'
        seal = json.loads((ROOT/'caption_external20/seal.json').read_text())
        assert sha(p) == seal['states'][k]['selected']
        m.load_state_dict(torch.load(p, map_location='cpu', weights_only=True))
    assert m.pred.weight.data_ptr() == m.embed.weight.data_ptr()
    return m


def indices(seed, size):
    return np.random.default_rng(seed + 10483).permutation(size)


def batches(data, order):
    for i in range(0, len(order), 16):
        ids = order[i:i+16]
        yield data.batch(ids, np.zeros(len(ids), dtype=int), torch.device('cpu'))


def timing():
    return time.perf_counter(), time.process_time()


def elapsed(before):
    return {'wall': time.perf_counter() - before[0], 'cpu': time.process_time() - before[1]}


@torch.no_grad()
def closed_direction(model, support, order):
    start = timing()
    model.eval()
    d = model.pred.in_features
    v = model.pred.out_features
    c = torch.zeros(d, d, dtype=torch.double)
    b = torch.zeros(d, v, dtype=torch.double)
    n = 0
    keys = []
    def hook(module, inputs):
        keys.append(inputs[0])
    handle = model.pred.register_forward_pre_hook(hook)
    for im, tx in batches(support, order):
        logits = model(im, tx[:, :-1])
        target = tx[:, 1:]
        mask = target != 0
        assert len(keys) == 1
        h = keys.pop()[mask].double()
        y = target[mask]
        prob = logits[mask].softmax(dim=1).double()
        c += h.T @ h
        b -= h.T @ prob
        b.index_add_(1, y, h.T.contiguous())
        n += len(y)
    handle.remove()
    assert not keys and n > 0
    extract = elapsed(start)
    start = timing()
    c /= n
    b /= n
    reg = .05 * c.trace().item() / d
    g = c + reg * torch.eye(d, dtype=torch.double)
    chol = torch.linalg.cholesky(g)
    whitened = torch.linalg.solve_triangular(chol, b, upper=False)
    vals, basis = torch.linalg.eigh(whitened @ whitened.T)
    u = basis[:, -16:]
    projected = u @ (u.T @ whitened)
    direction = torch.linalg.solve_triangular(chol.T, projected, upper=True).T.contiguous()
    rr = (chol.T @ direction.T - projected).norm() / projected.norm().clamp_min(1e-16)
    assert rr.item() < 1e-8 and torch.isfinite(direction).all()
    return direction.float(), dict(extraction=extract, solve=elapsed(start), support_tokens=n, ridge=reg,
        numerical_residual=rr.item(), ranks=16, largest_singular=vals[-1].clamp_min(0).sqrt().item(),
        retained_mass=(vals[-16:].clamp_min(0).sum()/vals.clamp_min(0).sum()).item(), delta_frobenius=direction.norm().item())


def candidate(base, method, tuning, delta, support, order):
    model = copy.deepcopy(base)
    start = timing()
    if method.endswith('edit16'):
        if method == 'untied_edit16':
            model.pred.weight = torch.nn.Parameter(model.pred.weight.detach().clone())
        with torch.no_grad():
            model.pred.weight.add_(delta, alpha=tuning)
        assert (model.pred.weight.data_ptr() == model.embed.weight.data_ptr()) == (method == 'tied_edit16')
        return model, elapsed(start)
    if method == 'fixed':
        return model, elapsed(start)
    if method == 'tied_gradient':
        for p in model.parameters():
            p.requires_grad_(False)
        model.pred.weight.requires_grad_(True)
    assert model.pred.weight.data_ptr() == model.embed.weight.data_ptr()
    active = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(active, lr=tuning, weight_decay=.01)
    model.train()
    for im, tx in batches(support, order):
        optimizer.zero_grad(set_to_none=True)
        logits = model(im, tx[:, :-1])
        loss = F.cross_entropy(logits.transpose(1, 2), tx[:, 1:], ignore_index=0)
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(active, 1)
        if not torch.isfinite(norm) or not torch.isfinite(loss):
            raise ValueError('Non-finite gradient step')
        optimizer.step()
    return model, elapsed(start)


def fit(arm, seed, origin):
    location = RESULT/f'{arm}-{seed}-{origin}'
    location.mkdir(exist_ok=True, parents=True)
    if (location/'fit.json').exists():
        j = json.loads((location/'fit.json').read_text())
        assert all(sha(location/k/'selected.pt')==v['sha256'] for k,v in j['selected'].items())
        return
    base = parent(arm, seed, origin)
    tr, dv = sample('train'), sample('val')
    order = indices(seed, len(tr.pix))
    delta, costs = closed_direction(base, tr, order)
    meta = dict(arm=arm, seed=seed, origin=origin, closed_form=costs, selected={}, candidates={},
        support_photos=len(tr.pix), development_photos=len(dv.pix), torch=str(torch.__version__), device='cpu',
        order_sha256=hashlib.sha256(order.astype('<i4').tobytes()).hexdigest(),
        data_manifest=sha(BASE/'data/manifest.json'), source=sha(Path(__file__)),
        parent_unique_parameters=sum(p.numel() for p in base.parameters()),
        parent_tied_shape=list(base.pred.weight.shape), parent_tied_norm=base.pred.weight.detach().norm().item())
    for method in METHODS:
        folder = location/method
        folder.mkdir(exist_ok=True)
        settings = [0.] if method == 'fixed' else (SCALES if method.endswith('edit16') else RATES)
        smallest = float('inf')
        meta['candidates'][method] = []
        for tuning in settings:
            m, cost = candidate(base, method, tuning, delta, tr, order)
            start = timing()
            val, count = score(m, dv, np.arange(len(dv.pix)), torch.device('cpu'))
            validation = elapsed(start)
            nll = float(val.sum() / count.sum())
            setting = dict(tuning=tuning, update=cost, development=validation, dev_nll=nll)
            if nll < smallest:
                model_sha = store_model(m, folder/'selected.pt')
                smallest = nll
                meta['selected'][method] = dict(tuning=tuning, dev_nll=nll, sha256=model_sha)
            meta['candidates'][method].append(setting)
        print('dev', arm, seed, origin, method, meta['selected'][method]['dev_nll'], flush=True)
    meta['process_elapsed_wall'] = time.perf_counter()-START
    meta['process_cpu'] = time.process_time()
    meta['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write(location/'fit.json', meta)


def test(arm, seed, origin, method):
    k = f'{arm}-{seed}-{origin}'
    folder = RESULT/k/method
    seal = json.loads((RESULT/'seal.json').read_text())
    assert len(seal['states']) == 60 and seal['states'][f'{k}/{method}'] == sha(folder/'selected.pt')
    assert seal['source'] == sha(Path(__file__)) and seal['data'] == sha(BASE/'data/manifest.json')
    if (folder/'test.json').exists():
        assert sha(folder/'scores.npz') == json.loads((folder/'test.json').read_text())['scores_sha256']
        return
    m = parent(arm, seed, origin)
    if method == 'untied_edit16':
        m.pred.weight = torch.nn.Parameter(m.pred.weight.detach().clone())
    m.load_state_dict(torch.load(folder/'selected.pt', map_location='cpu', weights_only=True))
    data = sample('test')
    start = timing()
    ix = np.arange(len(data.pix))
    l, c = score(m, data, ix, torch.device('cpu'))
    s, sc = score(m, data, ix, torch.device('cpu'), True)
    assert np.array_equal(c,sc)
    np.savez_compressed(folder/'scores.npz', paired=l, shifted=s, tokens=c, ids=data.ids)
    write(folder/'test.json', dict(nll=float(l.sum()/c.sum()), shifted_penalty=float((s-l).sum()/c.sum()),
        score_cost=elapsed(start), selected=seal['states'][f'{k}/{method}'], scores_sha256=sha(folder/'scores.npz'),
        process_elapsed_wall=time.perf_counter()-START, process_cpu=time.process_time()))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('phase', choices=['fit', 'test'])
    p.add_argument('arm', choices=ARMS)
    p.add_argument('seed', type=int, choices=SEEDS)
    p.add_argument('origin', choices=ORIGINS)
    p.add_argument('method', nargs='?', choices=METHODS)
    args = p.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if args.phase == 'fit':
        fit(args.arm, args.seed, args.origin)
    else:
        test(args.arm, args.seed, args.origin, args.method)


if __name__ == '__main__':
    main()
