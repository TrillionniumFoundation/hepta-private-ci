"""Run and cold-score a fixed split at a common fitting and selection budget."""
import argparse
import copy
import hashlib
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

PROCESS_START = time.monotonic()
ARMS = ("physical", "smooth", "lif", "attention_sdpa", "diagonal_ssm")
SEEDS = (9127, 16023, 36791)
BUDGET = 60
WEIGH_AT = (0, 12, 32, 52)
LEVELS = (.01, .02, .03)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def initialize(args):
    sys.path[:0] = [str(args.upstream), str(args.repo)]
    import numpy as np
    import torch
    import raw_train
    from controls import CausalAttention, DiagonalSelectiveSSM
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(args.seed)
    towers = []
    for i, vision in enumerate((True, False)):
        branch = args.arm if args.arm in ("physical", "smooth", "lif") else "linear"
        layer = raw_train.Encoder(branch, vision)
        if args.arm in ("attention_sdpa", "diagonal_ssm"):
            # Both controls expose a sequence of states with the established interface.
            layer.temporal.kind = "attention"
            layer.temporal.core = (CausalAttention if args.arm == "attention_sdpa" else DiagonalSelectiveSSM)(raw_train.WIDTH)
        for k, module in enumerate((layer.front, layer.scale, layer.out)):
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(args.seed + 3000 + 100 * i + k)
                module.reset_parameters()
        towers.append(layer)
    return np, torch, raw_train, torch.nn.ModuleList(towers)


def inventory(args, np, torch):
    roots = [args.repo, args.upstream, Path(__file__).parent]
    files = {}
    for m in list(sys.modules.values()):
        name = getattr(m, "__file__", None)
        if not name:
            continue
        path = Path(name).resolve()
        if Path(name).is_absolute() and path.suffix == '.py' and path.is_file() and any(path.is_relative_to(root) for root in roots):
            files[m.__name__] = digest(path)
    return dict(loaded_sources=files, python=sys.version, torch=torch.__version__, numpy=np.__version__,
                threads=torch.get_num_threads(), device='cpu', os=platform.platform(),
                manifest=digest(args.inputs / 'manifest.json'), protocol=digest(Path(__file__).with_name("PROTOCOL.md")))


def verified_data(args, raw, split):
    meta = json.loads((args.inputs/'manifest.json').read_text())
    assert meta[split]['sha256'] == digest(args.inputs / (split+'.npz'))
    return raw.load(split,args.inputs)


def fit(args):
    np, torch, raw, net = initialize(args)
    from torch.nn import functional as F
    folder = args.out / f"{args.arm}-{args.seed}"
    folder.mkdir(parents=True, exist_ok=True)
    fitfile = folder/'fit.json'
    if fitfile.exists():
        old = json.loads(fitfile.read_text())
        assert digest(folder/'selected.pt') == old['state_sha256']
        return
    train = verified_data(args, raw, 'train')
    dev = verified_data(args, raw, 'val')
    opt = torch.optim.AdamW(net.parameters(), lr=.003, weight_decay=.01)
    groups = [np.flatnonzero(train[2].numpy() == i) for i in range(len(train[0]))]
    rng = np.random.default_rng(args.seed + 31007)
    labels = torch.arange(16)
    record = dict(arm=args.arm, seed=args.seed, environment=inventory(args, np, torch),
                  params=sum(p.numel() for p in net.parameters() if p.requires_grad))
    record['common_initial'] = [
        hashlib.sha256(b''.join(t.detach().cpu().numpy().tobytes()
            for m in (layer.front, layer.scale, layer.out) for t in m.state_dict().values())).hexdigest()
        for layer in net]
    record['setup_seconds'] = time.monotonic() - PROCESS_START
    start = time.monotonic()
    cpu_start = time.process_time()
    fit_s = 0.
    step = 0
    observed = []
    best = -1.
    acceptable = None
    for checkpoint in WEIGH_AT + (BUDGET,):
        net.train()
        tr = time.monotonic()
        while time.monotonic()-start < checkpoint:
            ids = rng.choice(len(groups),16,replace=False)
            tid = [rng.choice(groups[k]) for k in ids]
            v, t = net[0](train[0][ids]), net[1](train[1][tid])
            sim = v @ t.T / .07
            loss = (F.cross_entropy(sim, labels) + F.cross_entropy(sim.T, labels)) * .5
            opt.zero_grad(set_to_none=True)
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(net.parameters(),1)
            assert torch.isfinite(norm).item()
            opt.step()
            step += 1
        fit_s += time.monotonic()-tr
        if checkpoint == BUDGET:
            break
        dev_start = time.monotonic()
        net.eval()
        with torch.no_grad():
            v, t = raw.features(net, dev)
            measure = raw.summary(raw.rank_vectors(v, t, dev[2]))
        value = float(measure['bidir_r1'])
        # Snapshot cost is charged before declaring a candidate in time.
        candidate = copy.deepcopy(net.state_dict()) if value > best else None
        ts = time.monotonic() - start
        timely = ts <= BUDGET
        observed.append(dict(step=step, scheduled_s=checkpoint, complete_s=ts, valid_s=ts-(dev_start-start),
                             value=value, within_budget=timely))
        if timely and candidate is not None:
            best, acceptable = value, candidate
            record['selected_step'] = step
    record.update(history=observed, best_dev=best, steps=step, examples=step*16,
                  fit_selection_seconds=time.monotonic()-start, gradient_update_seconds=fit_s,
                  fit_cpu_seconds=time.process_time()-cpu_start)
    assert acceptable is not None, 'no complete in-budget validation'
    tmp = folder/'selected.tmp'
    torch.save(acceptable,tmp)
    tmp.replace(folder/'selected.pt')
    record['state_sha256'] = digest(folder/'selected.pt')
    record['process_to_write_start_seconds'] = time.monotonic()-PROCESS_START
    record['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write(fitfile, record)
    print('fit', args.arm, args.seed, step, best, flush=True)


def test(args):
    np, torch, raw, model = initialize(args)
    path = args.out / f"{args.arm}-{args.seed}"
    seal = json.loads((args.out/'seal.json').read_text())
    assert len(seal)==len(ARMS)*len(SEEDS)
    assert seal[path.name]==digest(path/'selected.pt')
    fit = json.loads((path/'fit.json').read_text())
    assert inventory(args,np,torch)==fit['environment']
    testdata = verified_data(args,raw,'test')
    model.load_state_dict(torch.load(path/'selected.pt',weights_only=True))
    model.eval()
    with torch.no_grad():
        vision, language = raw.features(model, testdata)
        i,t,owners = raw.rank_vectors(vision,language,testdata[2])
    np.savez_compressed(path/'ranks.npz',image=i,caption=t,owner=owners)
    write(path/'test.json',dict(state_sha256=seal[path.name],ranks_sha256=digest(path/'ranks.npz'),
        test=raw.summary((i,t,owners)),cpu_block_seconds=time.process_time(),
        process_to_write_start_seconds=time.monotonic()-PROCESS_START))
    print('test', args.arm, args.seed, flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("fit","test"))
    parser.add_argument("arm",choices=ARMS)
    parser.add_argument("seed",type=int,choices=SEEDS)
    for key in ("upstream","repo","out","inputs"):
        parser.add_argument("--"+key,required=True,type=lambda p:Path(p).resolve())
    args=parser.parse_args()
    (fit if args.phase=="fit" else test)(args)


if __name__=="__main__":
    main()
