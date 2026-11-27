"""Prospectively fixed random-feature / fully paired encoder BP comparison."""
import argparse
import hashlib
import json
from pathlib import Path
import time

START = time.perf_counter()
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from qualification.hcsn_closure_20261124.boundary_fix import BoundaryControlHCSN
from qualification.hcsn_smallnet_20261124.model import ModelConfig

IMPORT_SECONDS = time.perf_counter() - START
ARMS = ('hcsn_frozen', 'hcsn_bp', 'gru_frozen', 'gru_bp', 'flat')
SEEDS = (107, 211, 431)
ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, obj):
    with path.open('x') as out:
        json.dump(obj, out, indent=2, allow_nan=False, sort_keys=True)
        out.write('\n')


def rows(path, partition, source):
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == source['data'][path.name]
    blocks, block = [], []
    for line in raw.splitlines():
        if line.strip():
            block.append(line)
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    per_digit = 660 if partition == 'train' else 220
    if len(blocks) != 10 * per_digit:
        raise ValueError(f'Unexpected {partition} row count {len(blocks)}')
    positions = np.arange(0, len(blocks), 10 if partition == 'train' else 1)
    hashes = [hashlib.sha256(b'\n'.join(block)).hexdigest() for block in blocks]
    result = []
    for pos in positions:
        row = np.fromstring(b' '.join(blocks[pos]), dtype=np.float64, sep=' ').reshape(-1, 13)
        if len(row) != len(blocks[pos]) or not np.isfinite(row).all():
            raise ValueError('Bad MFCC data')
        t = np.linspace(0, len(row) - 1, 6)
        a = np.floor(t).astype(int)
        b = np.ceil(t).astype(int)
        result.append(row[a] + (row[b] - row[a]) * (t-a)[:, None])
    return np.array(result), torch.from_numpy(positions // per_digit), positions, hashes


def normalize(values, mean, scale):
    return torch.from_numpy(((values-mean)/scale).clip(-5, 5).astype(np.float32))


def make(arm, seed):
    torch.manual_seed(seed)
    if arm == 'flat':
        return None
    if arm.startswith('gru'):
        return nn.GRU(13, 32, batch_first=True)
    config = ModelConfig(input_size=13, neurons=32, precision='mixed', backend='uniformized',
                         boundary_mode='qvi', message_mode='full', feature_bank='value_risk')
    return BoundaryControlHCSN(config, channel='boundary_only', control_mode='accumulate', boundary_mode='centered')


def features(model, x):
    if model is None:
        return x.flatten(1)
    if isinstance(model, nn.GRU):
        return model(x)[0].flatten(1)
    latent = model(x.transpose(0, 1), return_features=True)[1].transpose(0, 1)
    return latent.flatten(1)


@torch.no_grad()
def embed(model, x):
    z = torch.cat([features(model, block) for block in x.split(24)])
    if not torch.isfinite(z).all():
        raise FloatingPointError('Invalid encoder output')
    return z


def tune(model, x, y, initial, seed):
    center = initial.mean(0)
    scale = initial.std(0, unbiased=False).clamp_min(.001)
    torch.manual_seed(seed + 991)
    head = nn.Linear(len(center), 10)
    params = list(model.parameters()) + list(head.parameters())
    optimizer = torch.optim.Adam(params, lr=.001)
    order = torch.Generator().manual_seed(seed + 553)
    first = last = None
    for _ in range(64):
        ids = torch.randperm(len(y), generator=order)[:24]
        z = features(model, x[ids])
        logits = head(8 * ((z-center)/(8*scale)).tanh())
        loss = F.cross_entropy(logits, y[ids])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(params, 2.)
        if not torch.isfinite(norm) or not torch.isfinite(loss):
            raise FloatingPointError('Invalid training step')
        optimizer.step()
        last = float(loss.detach())
        if first is None:
            first = last
    return [first, last]


def ridge(z, y):
    values = z.double()
    mean, scale = values.mean(0), values.std(0, unbiased=False).clamp_min(1e-5)
    design = (values-mean)/scale
    target = F.one_hot(y, 10).double()
    bias = target.mean(0)
    gram = design.T@design/len(y) + .01*torch.eye(design.shape[1], dtype=torch.float64)
    weight = torch.linalg.solve(gram, design.T@(target-bias)/len(y))
    residual = (gram@weight-design.T@(target-bias)/len(y)).abs().max().item()
    return dict(weight=weight, bias=bias, mean=mean, scale=scale), residual


def digest_state(model):
    h = hashlib.sha256()
    if model is not None:
        for k, v in sorted(model.state_dict().items()):
            h.update(k.encode())
            h.update(v.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def train(args, source):
    out = args.out/f'{args.arm}-{args.seed}'
    out.mkdir(exist_ok=False)
    stamp = time.perf_counter()
    raw, y, positions, hashes = rows(args.data/'Train_Arabic_Digit.txt', 'train', source)
    mean = raw.mean(axis=(0,1))
    scale = raw.std(axis=(0,1)).clip(1e-6)
    x = normalize(raw, mean, scale)
    parsed = time.perf_counter()
    model = make(args.arm, args.seed)
    initial_hash = digest_state(model)
    torch.save({} if model is None else model.state_dict(), out/'initial.pt')
    initial_time = time.perf_counter()
    initial = embed(model, x)
    embedded = time.perf_counter()
    if args.arm.endswith('_bp'):
        losses = tune(model, x, y, initial, args.seed)
        trained = time.perf_counter()
        z = embed(model, x)
    else:
        losses = []
        trained = embedded
        z = initial
    recalculated = time.perf_counter()
    fitted, residual = ridge(z, y)
    solved = time.perf_counter()
    torch.save(dict(model={} if model is None else model.state_dict(), ridge=fitted,
                    input_mean=torch.from_numpy(mean), input_scale=torch.from_numpy(scale)), out/'selected.pt')
    record = dict(arm=args.arm, seed=args.seed, dimensions=z.shape[1], positions=positions.tolist(),
                  official_train_rows=len(hashes), train_rows=len(y), source=sha(ROOT/'SOURCE.json'),
                  program=sha(Path(__file__)), protocol=sha(ROOT/'PROTOCOL.md'), data_hash=source['data']['Train_Arabic_Digit.txt'],
                  torch=str(torch.__version__), numpy=np.__version__, initial_state=initial_hash,
                  final_state=digest_state(model), initial_file=sha(out/'initial.pt'), selected_file=sha(out/'selected.pt'),
                  ridge_residual=residual, ce_first_last=losses, import_s=IMPORT_SECONDS, parse_s=parsed-stamp,
                  initial_model_s=initial_time-parsed, initial_features_s=embedded-initial_time, bp_s=trained-embedded,
                  final_features_s=recalculated-trained, ridge_s=solved-recalculated, serialization_s=time.perf_counter()-solved)
    save(out/'fit.json', record)


def test(args, source):
    folder = args.out/f'{args.arm}-{args.seed}'
    seal = json.loads((args.out/'seal.json').read_text())
    assert all(seal[k] == sha(v) for k,v in [('program', Path(__file__)), ('protocol', ROOT/'PROTOCOL.md'),
                                             ('source', ROOT/'SOURCE.json')])
    assert seal['roster'][folder.name]['weights'] == sha(folder/'selected.pt')
    frozen = torch.load(folder/'selected.pt', map_location='cpu', weights_only=True)
    raw, y, positions, _ = rows(args.data/'Test_Arabic_Digit.txt', 'test', source)
    x = normalize(raw, frozen['input_mean'].numpy(), frozen['input_scale'].numpy())
    model = make(args.arm, args.seed)
    if model is not None:
        model.load_state_dict(frozen['model'])
    fit = frozen['ridge']
    stamp = time.perf_counter()
    z = embed(model, x).double()
    scores = ((z-fit['mean'])/fit['scale'])@fit['weight']+fit['bias']
    if not torch.isfinite(scores).all():
        raise FloatingPointError('Nonfinite test scores')
    pred = scores.argmax(1)
    np.savez_compressed(folder/'test.npz', row=positions, y=y.numpy(), pred=pred.numpy(),
                        scores=scores.numpy().astype(np.float32))
    save(folder/'test.json', dict(total=len(y), correct=int((pred==y).sum()),
         accuracy=(pred==y).double().mean().item(), forward_and_save_s=time.perf_counter()-stamp,
         prediction_sha256=sha(folder/'test.npz')))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('phase', choices=('train', 'test'))
    p.add_argument('arm', choices=ARMS); p.add_argument('seed', type=int, choices=SEEDS)
    p.add_argument('data', type=Path); p.add_argument('out', type=Path)
    args = p.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    source = json.loads((ROOT/'SOURCE.json').read_text())
    (train if args.phase=='train' else test)(args, source)
