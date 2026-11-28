"""Train one physical T4 arm to its fixed development threshold or cold-score a sealed weight."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from population import ContinuousSpikingNetwork
from validate_prices import data


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worker(args):
    torch.set_num_threads(1)
    torch.manual_seed(args.seed)
    x, y, (train, dev, test) = data()
    xt = torch.tensor(x, device='cuda', dtype=torch.float64).transpose(0,1)
    yt = torch.tensor(y, device='cuda', dtype=torch.long)
    model = ContinuousSpikingNetwork(8,3,2,args.atoms,port='priced',matrix_free=args.mode=='fft').cuda()
    assert not model.first.cache_prices and next(model.parameters()).is_cuda
    def score(rows):
        with torch.no_grad():
            batches = np.array_split(rows, int(np.ceil(len(rows)/8)))
            logits = torch.cat([model(xt[:, ix])[0][-1] for ix in batches])
            labels = yt[rows]
            accuracy = [(logits.argmax(1)[labels==i]==i).double().mean().item() for i in (0,1)]
            return {'balanced_accuracy':sum(accuracy)/2,
                    'ce':torch.nn.functional.cross_entropy(logits,labels).item()}, logits.cpu().numpy()
    name = f'{args.atoms}-{args.seed}-{args.mode}'
    state = args.output/(name+'.pt')
    if args.phase=='cold':
        seal = json.loads((args.output/'seal.json').read_text())
        assert sha(state)==seal['arms'][name]['state_sha256']
        model.load_state_dict(torch.load(state,weights_only=True,map_location='cuda'))
        cold, logits = score(test)
        np.save(args.output/(name+'-logits.npy'),logits,allow_pickle=False)
        result={'heldout':cold,'state_sha256':sha(state),'count':len(test),'device':torch.cuda.get_device_name()}
        (args.output/(name+'-cold.json')).write_text(json.dumps(result))
        return
    schedule = np.random.default_rng(args.seed).choice(train,(96,8))
    optimizer = torch.optim.AdamW(model.parameters(),lr=.016,weight_decay=.001)
    checks=[]
    gate=None
    for update in range(97):
        if update%4==0:
            devmetrics,_ = score(dev)
            torch.cuda.synchronize()
            elapsed=time.perf_counter()-args.spawn
            checks.append({'updates':update,'cold_seconds':elapsed,**devmetrics})
            if devmetrics['balanced_accuracy']>=.80:
                gate=update
                break
        if update==96:
            break
        optimizer.zero_grad(set_to_none=True)
        rows=schedule[update]
        logits=model(xt[:,rows])[0][-1]
        torch.nn.functional.cross_entropy(logits,yt[rows]).backward()
        optimizer.step()
    torch.save(model.state_dict(),state)
    result={'grid':args.atoms,'seed':args.seed,'mode':args.mode,'first_dev_gate':gate,'checks':checks,
            'state_sha256':sha(state),'schedule_sha256':hashlib.sha256(schedule.astype('<i8').tobytes()).hexdigest(),
            'device':torch.cuda.get_device_name(),'torch':str(torch.__version__),'parameters':sum(p.numel() for p in model.parameters())}
    (args.output/(name+'.json')).write_text(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--seed',type=int,required=True)
    p.add_argument('--atoms',type=int,required=True)
    p.add_argument('--phase',choices=('train','cold'),required=True)
    p.add_argument('--mode',choices=('dense','fft'),required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--spawn',type=float,required=True)
    worker(p.parse_args())
