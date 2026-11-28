"""Construct word embeddings and a normalized hierarchical head from conditional log odds."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import scipy.sparse as sp
from scipy.linalg import helmert
import torch


def grouped_counts(left, right, size, width, alpha):
    counts = sp.coo_matrix((np.ones(len(left), dtype=np.int32), (left, right)),
                           shape=(size, width)).tocsr()
    frequency = np.asarray(counts.sum(axis=0)).ravel() + .1
    prior = frequency / frequency.sum()
    logs = counts.astype(np.float64)
    logs.data = np.log1p(logs.data / (alpha * prior[logs.indices]))
    return logs, prior


def conditional_basis(words, vocab, seed, alpha, power):
    left, right = words[:-1], words[1:]
    rare = right >= 128
    groups = (vocab - 128 + 127) // 128
    root = np.where(rare, 128 + (right - 128) // 128, right)
    m0, p0 = grouped_counts(left, root, vocab, 128 + groups, alpha)
    m1, p1 = grouped_counts(left[rare], (right[rare] - 128) % 128, vocab, 128, alpha)
    table = sp.hstack((m0, m1), format='csr')
    centers = np.column_stack((m0 @ p0, m1 @ p1))
    group = np.repeat([0, 1], [len(p0), len(p1)])
    count = np.bincount(left, minlength=vocab)
    weight = count / count.sum()
    intercept = np.asarray(table.T @ weight).ravel() - (weight @ centers)[group]
    left_weight = np.sqrt(weight)
    # Rare-rank prediction is exercised only at positions with rare targets.
    right_weight = np.r_[p0**power, np.sqrt(rare.mean()) * p1**power]

    def centered(v):
        sums = np.stack((v[:len(p0)].sum(0), v[len(p0):].sum(0)))
        return table @ v - centers @ sums - intercept @ v

    def transpose(v):
        inverse_centers = (centers.T @ v)[group]
        return table.T @ v - inverse_centers - intercept[:, None] * v.sum(0)

    def times(v):
        return left_weight[:, None] * centered(right_weight[:, None] * v)

    def transpose_times(v):
        return right_weight[:, None] * transpose(left_weight[:, None] * v)

    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(times(rng.normal(size=(table.shape[1], 40))), mode='reduced')
    for _ in range(2):
        q, _ = np.linalg.qr(times(transpose_times(q)), mode='reduced')
    _, s, vt = np.linalg.svd(transpose_times(q).T, full_matrices=False)
    basis = vt[:30].T
    coordinates = centered(right_weight[:, None] * basis)
    slopes = basis / right_weight[:, None]
    lengths = np.linalg.norm(coordinates, axis=1)
    order = np.argsort(lengths)
    radius = lengths[order[np.searchsorted(np.cumsum(weight[order]), .995)]]
    coords = coordinates / np.maximum(radius, lengths)[:, None]
    extra = np.sqrt(np.maximum(0., 1. - np.sum(coords**2, axis=1)))
    rotation = helmert(32, full=False).T
    orient, _ = np.linalg.qr(rng.normal(size=(31, 31)))
    rotation = rotation @ orient
    target = np.column_stack((coords, extra)) @ rotation.T * np.sqrt(32.)
    output_weight = slopes @ rotation[:, :30].T * radius / np.sqrt(32.)
    tail = np.bincount(right[rare] - 128, minlength=groups * 128).reshape(groups, 128) + .1
    tail = tail / tail.sum(axis=1, keepdims=True)
    meta = dict(observed_training_targets=len(right), clipped_training_mass=float(weight[lengths>radius].sum()),
                radius=float(radius), extreme_singular_values=[float(s[0]), float(s[29])],
                maximum_target_mean=float(np.abs(target.mean(1)).max()),
                maximum_target_norm_error=float(np.abs(np.linalg.norm(target, axis=1)-np.sqrt(32.)).max()))
    return target, output_weight, intercept, p0, tail, meta


def financial_signal(block, x):
    z = torch.nn.functional.layer_norm(x, (32,))
    q, mix = torch.tanh(.06 * z), torch.sigmoid(.08 * z)
    ez0, ez1 = block.center[1] + block.slope[1]*q, block.center[2] + block.slope[2]*q
    lz0, lz1 = block.center[3] + block.slope[3]*q, block.center[4] + block.slope[4]*q
    return q + (ez0 + mix*(ez1-ez0))/block.center[2] - (lz0 + mix*(lz1-lz0))/block.center[3]


def invert_block(block, target):
    c = block.slope[0] / block.center[0]
    argument = torch.expm1(c * target) / c
    if argument.abs().max() >= 1:
        raise ValueError('inverse boundary domain')
    pre = torch.atanh(argument)
    x = pre.clone()
    zero = financial_signal(block, torch.zeros((1, 32)))
    for _ in range(24):
        x = pre - .12 * (financial_signal(block, x) - zero)
    error = (x + .12*(financial_signal(block,x)-zero) - pre).abs().max()
    if error > 2e-6:
        raise ArithmeticError(f'large fixed-point residual {float(error)}')
    return x, float(error)


@torch.no_grad()
def fit(model_type, words, vocab, seed, alpha, power):
    target, w, intercept, root_prior, tail, meta = conditional_basis(words, vocab, seed, alpha, power)
    model = model_type(vocab, 'hx')
    old = dict(model.named_parameters())
    for p in old.values():
        p.fill_(float('nan'))
    # All remaining tensors are fixed by the restricted realization below.
    for p in old.values():
        p.zero_()
    identity = torch.eye(32)
    for b in model.blocks:
        b.pre.weight.fill_(1.)
        b.qkv.weight.copy_(torch.cat((.06*identity, .08*identity, .08*identity)))
        b.out.weight.copy_(.12*identity)
        b.out.bias.copy_(-.12*financial_signal(b, torch.zeros((1,32))).ravel())
        b.ff[0].weight.fill_(1.)
    scale = .08
    desired = torch.from_numpy(scale * target).float()
    intermediate, err2 = invert_block(model.blocks[1], desired)
    start, err1 = invert_block(model.blocks[0], intermediate)
    model.emb.weight.copy_(start)
    model.norm.weight.fill_(np.sqrt(scale**2 + model.norm.eps) / scale)
    h = model.head
    n = len(root_prior)
    h.root.weight.copy_(torch.from_numpy(w[:n]))
    h.root.bias.copy_(torch.from_numpy(np.log(root_prior) + intercept[:n]))
    h.condition.weight.fill_(8.)
    h.rank.weight.copy_(torch.from_numpy(w[n:]))
    h.rank.bias.copy_(torch.from_numpy(intercept[n:] - 8*w[n:].sum(1)))
    h.prior.weight.copy_(torch.from_numpy(np.log(tail)))
    learned = ['emb.weight', 'head.root.weight', 'head.root.bias', 'head.rank.weight',
               'head.rank.bias', 'head.prior.weight']
    if any(not torch.isfinite(p).all() for p in model.parameters()):
        raise ArithmeticError('undefined deployment coefficient')
    meta.update(fitted_tensors=learned, fitted_coefficients=sum(old[k].numel() for k in learned),
                all_coefficients=sum(p.numel() for p in old.values()), all_tensors=len(old),
                inverse_residuals=[err1,err2], all_zero_tensors=[k for k,p in old.items() if not torch.any(p)],
                fixed_nonzero_tensors=[k for k,p in old.items() if k not in learned and torch.any(p)])
    return model, meta


def main(args):
    sys.path.insert(0, str(args.data / 'src'))
    from model import LanguageModel
    from train import evaluate, Windows
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    args.out.mkdir(parents=True, exist_ok=True)
    train_path = args.data / 'train.npy'
    corpus = json.loads((args.data / 'data.json').read_text())
    if hashlib.sha256(np.load(train_path).tobytes()).hexdigest() != corpus['splits']['train']['array_sha256']:
        raise ValueError('unexpected training corpus')
    dev = Windows(args.data / 'valid.npy')
    selections = {}
    for seed in (137,311,557):
        records = []
        for alpha in (16,64):
            for power in (.25,.5):
                wall, cpu = time.perf_counter(), time.process_time()
                model, info = fit(LanguageModel, np.load(train_path), corpus['vocab'], seed, alpha, power)
                fit_time = [time.perf_counter()-wall, time.process_time()-cpu]
                tag = f'spectral-{seed}-{alpha}-{int(power*100)}'
                start = time.perf_counter()
                scores = evaluate(model, dev, 32, 'cpu')
                development = time.perf_counter()-start
                weight = args.out / (tag+'.npz')
                np.savez_compressed(weight, **{k:v.numpy() for k,v in model.state_dict().items()})
                row = dict(tag=tag,seed=seed,alpha=alpha,power=power,wall_s=fit_time[0],cpu_s=fit_time[1],
                           validation_s=development,validation=scores,sha256=hashlib.sha256(weight.read_bytes()).hexdigest(),
                           **info)
                records.append(row)
                print(tag,round(fit_time[0],3),round(scores['ppl'],3),flush=True)
        selections[str(seed)] = {'records':records,'chosen':min(records,key=lambda r:r['validation']['nll'])['tag']}
    (args.out/'development.json').write_text(json.dumps(selections,indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('data', type=Path)
    parser.add_argument('out', type=Path)
    main(parser.parse_args())
