"""GPU comparison on actor-disjoint two-choice RAVDESS retrieval.

Execute inside hepta-private-ci with the pinned qualification/ model sources on
PYTHONPATH. Each fit runs in a fresh process; final predictions follow the seal.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

START = time.perf_counter()
import numpy as np
import torch
from torch import nn
from dataclasses import replace
from qualification.hcsn_smallnet_20261124.model import ModelConfig, SmallHCSN

HASHES = {
    'train': 'b708c4fbc0018aa0cac928d9de10b22663fe2479904e6c7491e6c3dd90190acd',
    'dev': '099d6580639f03e16c72daca506eda6b8745fd9fd4e54deb83f103a199002d58',
    'retain': '9590a7d57fec843d18fe44ff61d0d49f8c35dffccf4320043158dd844c9a5fed',
    'test': '750526a732c93c27079a42ef9aea113e876661c4e0b3f5e6237e81c9ec268085',
}
ARMS = ('centered', 'raw', 'gru', 'attention')
SEEDS = (47, 83, 137)

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def save(obj, p):
    Path(p).write_text(json.dumps(obj, sort_keys=True, indent=2, allow_nan=False) + '\n')

def raw(root, split):
    p = Path(root) / (split + '.npz')
    if digest(p) != HASHES[split]:
        raise ValueError(f'Unexpected public cache identity: {split}')
    with np.load(p, allow_pickle=False) as a:
        # Six audio-band features, common clock, candidate-specific audio/visual scores.
        shared = a['x'][:, :, [0, 1, 2, 3, 4, 5, 7]]
        base = a['read_scores'].astype('float32')
        audio = a['scores']
        visual = 2 * a['read_scores'] - audio
        inputs = np.concatenate((np.broadcast_to(shared[:, :, None, :], (*base.shape, 7)),
                                 audio[..., None], visual[..., None]), axis=-1)
        return inputs.astype('float32'), base, a['target'].astype('int64'), a['group'].tolist()

def normalized(rawdata, moments):
    x, base, y, groups = rawdata
    mu, sd, scale = moments
    return (torch.tensor((x-mu)/sd, device='cuda'), torch.tensor(base[:, -1]/scale, device='cuda'),
            torch.tensor(y, device='cuda'), groups)

class Hybrid(nn.Module):
    def __init__(self, arm):
        super().__init__()
        self.arm = arm
        if arm in ('centered', 'raw'):
            self.body = SmallHCSN(ModelConfig(input_size=9, neurons=8, bins=6, stages=3,
                dt=.48, boundary_mode='qvi', message_mode='boundary', precision='mixed', backend='dense'))
            self.head = self.body.readout
        elif arm == 'gru':
            self.body = nn.GRU(9, 8)
            self.head = nn.Linear(8, 2)
        else:
            self.front = nn.Linear(9, 8)
            self.body = nn.TransformerEncoderLayer(8, 2, 16, dropout=0.0, batch_first=False)
            self.head = nn.Linear(8, 2)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, xs, baseline):
        batch, steps, choices, width = xs.shape
        sequence = xs.permute(1, 0, 2, 3).reshape(steps, batch*choices, width)
        if self.arm in ('centered','raw'):
            state = None
            for tick in sequence:
                if self.arm == 'centered' and state is not None:
                    msg = torch.cat(((state.message[:, 0] - self.body.fixed_boundary)[:, None],
                                     state.message[:, 1:]), dim=1)
                    state = replace(state, message=msg)
                logits, _, state = self.body(tick[None], state=state, return_features=True)
            step = logits[-1]
        elif self.arm == 'gru':
            h, _ = self.body(sequence)
            step = self.head(h[-1])
        else:
            mask = torch.ones(steps, steps, dtype=torch.bool, device=sequence.device).triu(1)
            h = self.body(self.front(sequence), src_mask=mask)
            step = self.head(h[-1])
        return baseline + (step[:, 1]-step[:, 0]).reshape(batch, choices)

def scores(logits, labels):
    probs = logits.softmax(-1)[:, 1]
    return {'accuracy': (logits.argmax(-1)==labels).float().mean().item(),
            'brier': (probs-labels).square().mean().item(),
            'ce': nn.functional.cross_entropy(logits, labels).item()}

def device():
    if not torch.cuda.is_available():
        raise RuntimeError('A physical Torch CUDA GPU is required')
    v = torch.arange(5.0, device='cuda').square().sum().item()
    if v != 30:
        raise RuntimeError('Device arithmetic failed')
    return {'name': torch.cuda.get_device_name(0), 'torch': str(torch.__version__),
            'device_witness': v, 'cuda': str(torch.version.cuda)}

def worker(args):
    hardware = device()
    torch.manual_seed(args.seed)
    torch.set_num_threads(1)
    train = raw(args.data, 'train')
    moments = (train[0].mean(axis=(0,1,2)), np.maximum(train[0].std(axis=(0,1,2)), .001),
               np.float32(max(train[1][:,-1].std(), .001)))
    tr = normalized(train, moments)
    model = Hybrid(args.arm).cuda()
    ident = f'{args.arm}_{args.seed}'
    out = Path(args.out)
    ckpt = out / (ident+'.pt')
    report = dict(arm=args.arm, seed=args.seed, gpu=hardware, parameters=sum(p.numel() for p in model.parameters()))
    if args.mode == 'fit':
        dv = normalized(raw(args.data, 'dev'), moments)
        optim = torch.optim.AdamW(model.parameters(), lr=.008, weight_decay=.001)
        generator = torch.Generator().manual_seed(args.seed+2011)
        record = []
        best = None
        for k in range(args.steps+1):
            if k in {0,4,12,args.steps}:
                model.eval()
                with torch.no_grad():
                    met = scores(model(*dv[:2]), dv[2])
                torch.cuda.synchronize()
                record.append({'updates':k,'wall':time.perf_counter()-START,**met})
                key = (met['accuracy'], -met['brier'])
                if best is None or key > best:
                    best = key
                    report['selected_updates'] = k
                    torch.save(model.state_dict(), ckpt)
            if k < args.steps:
                model.train()
                ids = torch.randperm(len(train[2]), generator=generator)[:8].to('cuda')
                optim.zero_grad(set_to_none=True)
                loss = nn.functional.cross_entropy(model(tr[0][ids],tr[1][ids]),tr[2][ids])
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optim.step()
        torch.cuda.synchronize()
        report.update(curve=record, checkpoint=digest(ckpt), peak_gpu_bytes=torch.cuda.max_memory_allocated(),
                      cold_fit_wall=time.perf_counter()-START, base_acc=record[0]['accuracy'])
        save(report, out/(ident+'.fit.json'))
    else:
        seal=json.loads((out/'seal.json').read_text())
        if digest(ckpt)!=seal[ident]: raise ValueError('model changed')
        model.load_state_dict(torch.load(ckpt, map_location='cuda', weights_only=True))
        model.eval()
        with torch.no_grad():
            for split in ('retain','test'):
                source = normalized(raw(args.data,split),moments)
                if set(source[3]) & set(train[3]): raise ValueError('actor leakage')
                pred = model(*source[:2])
                report[split] = dict(scores=scores(pred, source[2]), common=scores(source[1],source[2]),
                                     groups=source[3], labels=source[2].tolist(),
                                     margins=(pred[:,1]-pred[:,0]).tolist(),
                                     baseline_margins=(source[1][:,1]-source[1][:,0]).tolist())
        torch.cuda.synchronize()
        report['cold_eval_wall']=time.perf_counter()-START
        save(report,out/(ident+'.eval.json'))

def controller(args):
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=False)
    seeds=(193,) if args.cloud else SEEDS
    arms=('centered','attention') if args.cloud else ARMS
    runs=[(a,s) for i,s in enumerate(seeds) for a in arms[i:]+arms[:i]]
    records=[]
    for mode in ('fit','eval'):
        if mode=='eval':
            save({f'{a}_{s}':digest(out/f'{a}_{s}.pt') for a,s in runs}, out/'seal.json')
        for a,s in runs:
            launch=time.perf_counter()
            cmd=[sys.executable,__file__,mode,'--data',args.data,'--out',args.out,
                 '--arm',a,'--seed',str(s),'--steps',str(args.steps)]
            subprocess.run(cmd,check=True)
            duration=time.perf_counter()-launch
            row=json.loads((out/f'{a}_{s}.{mode}.json').read_text())
            row['process_wall']=duration
            records.append({'mode':mode,**row})
            print(mode,a,s,round(duration,3),flush=True)
    save({'benchmark':digest(__file__),'data_hashes':HASHES,'seeds':seeds,'steps':args.steps,
          'rows':records,'controller_wall':time.perf_counter()-START},out/'result.json')

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('run','fit','eval'))
    p.add_argument('--data',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--seed',type=int)
    p.add_argument('--arm',choices=ARMS)
    p.add_argument('--steps',type=int,default=24)
    p.add_argument('--cloud',action='store_true')
    args=p.parse_args()
    controller(args) if args.mode=='run' else worker(args)
