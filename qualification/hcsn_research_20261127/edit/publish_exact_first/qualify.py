"""Equivalence tests and alternating, paired single-thread CPU measurements."""
import argparse
import json
import platform
import resource
import sys
import time
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import experiment as core
import exact


def compare(a, b):
    error = float((a-b).abs().max())
    ref = float(a.abs().max())
    return {'abs_error': error, 'max_reference': ref, 'pass': error <= 1e-5 + 2e-5*ref}


def gradients(fn, model, c, x, y, synthetic):
    model.zero_grad(set_to_none=True)
    z = fn(model, x)
    if synthetic:
        weights = torch.linspace(-1., 1., z.numel(), dtype=z.dtype).reshape_as(z)
        obj = (z*weights).sum() / len(x)
    else:
        read = c['ridge']
        scores = ((z.double()-read['mean'])/read['scale']) @ read['weight']+read['bias']
        obj = (scores-F.one_hot(y, 10)).square().mean()
    obj.backward()
    return torch.cat((model.input_drive.weight.grad.flatten(), model.input_drive.bias.grad))


def comparison(model, c, train):
    refs = {}
    ln = (1, 2, 3, 6)
    with torch.no_grad():
        for count in (1, 7, 24):
            merged = torch.cat((train['eng'][0][:12], train['ar'][0][:12]))
            for n in ln:
                primary = merged[:count, :n].contiguous()
                variants = dict(real=primary, zero=torch.zeros_like(primary))
                alternating = torch.arange(primary.numel()).reshape_as(primary) % 2
                variants['plusminus'] = (alternating*10-5).to(primary)
                for name, x in variants.items():
                    label = f'{count}/{n}/{name}'
                    a, b = core.trace(model, x), exact.trace(model, x)
                    out = {k: compare(a[k], b[k]) for k in a}
                    out['features'] = compare(core.study.features(model, x), exact.features(model, x))
                    if n == 6:
                        ref = core.score(model, c['ridge'], x)
                        opt = exact.score(model, c['ridge'], x)
                        out['logits'] = compare(ref, opt)
                        out['disagreements'] = int((ref.argmax(1) != opt.argmax(1)).sum())
                    refs[label] = out
    grads = {}
    x, y, _ = train['eng']
    for n, synthetic in [(3, True), (6, True), (6, False)]:
        a, b = [gradients(fn, model, c, x[:4, :n], y[:4], synthetic) for fn in (core.study.features, exact.features)]
        grads[f'{n}/{synthetic}'] = compare(a, b)
    # Structural guard must reject actively reading a transport-generated channel.
    with torch.no_grad():
        idx = (0,model.config.neurons)
        before = model.synaptic_mask[idx].clone()
        model.synaptic_mask[idx] = 1.
        rejected = False
        try:
            exact.trace(model,x[:1])
        except ValueError:
            rejected=True
        finally:
            model.synaptic_mask[idx] = before
    assert rejected
    return refs, grads


def solve_equiv(model, train):
    results = []
    for trace in (core.trace, exact.trace):
        blocks = {k: trace(model, v[0]) for k, v in train.items()}
        d, _ = core.solve(model, blocks, train, 'direct')
        results.append(d)
    return {str(s): float(((results[0]-results[1])*s).norm()) for s in (.125,.25,.5,1.)}


def timings(model, c, train):
    x = torch.cat((train['eng'][0][:24],train['ar'][0][:24]))
    y = train['eng'][1][:4]
    ops = {
        'trace48': (lambda: core.trace(model,x),lambda: exact.trace(model,x)),
        'score48': (lambda: core.scores(model,c,x),lambda: exact.scores(model,c,x)),
        'backward4': (lambda: gradients(core.study.features,model,c,x[:4],y,False),
                      lambda: gradients(exact.features,model,c,x[:4],y,False)),
    }
    result = {}
    for op, pair in ops.items():
        for f in pair: f()
        records = []
        for i in range(5):
            duration = {}
            order = [0,1] if i%2==0 else [1,0]
            for j in order:
                t = time.perf_counter()
                value = pair[j]()
                del value
                duration[['original','reduced'][j]] = time.perf_counter()-t
            records.append({'first': ['original','reduced'][order[0]], **duration})
        result[op] = dict(reps=records,
                          median_paired_ratio=float(np.median([r['original']/r['reduced'] for r in records])))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed',type=int,required=True)
    for k in ('parents','input','output'): ap.add_argument('--'+k,type=Path,required=True)
    args = ap.parse_args()
    torch.set_num_threads(1)
    model,c,parent=core.read_parent(args)
    train=core.loads(args,'train',c)
    out_dir=args.output/str(args.seed)
    out_dir.mkdir(exist_ok=True,parents=True)
    ref, grads=comparison(model,c,train)
    solve=solve_equiv(model,train)
    bench=timings(model,c,train)
    condition=(all(r['pass'] if isinstance(r,dict) else r==0 for row in ref.values() for r in row.values())
               and all(r['pass'] for r in grads.values()) and max(solve.values())<=2e-5)
    result=dict(seed=args.seed, parent=parent, version=str(torch.__version__),
                protocol=core.sha((Path(__file__).parent/'PROTOCOL.md').read_bytes()),
                implementation=core.sha((Path(__file__).parent/'exact.py').read_bytes()),
                threads=torch.get_num_threads(), processor=platform.processor(),
                platform=platform.platform(), measurements=bench, maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                comparisons=ref, gradients=grads, solve_norm_difference=solve,
                qualified=condition)
    core.write(out_dir/'qualification.json',result)
    print(args.seed,condition,grads,solve,{k:v['median_paired_ratio'] for k,v in bench.items()},flush=True)
if __name__=='__main__':main()
