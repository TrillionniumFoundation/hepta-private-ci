"""Independent replay of a saved primal decoder and its two extremal populations.

Load the uncompressed JSON list of CPU LP witnesses (or the cloud's result.json).
Only NumPy and PyTorch are required. No optimizer is loaded or called.
"""
import argparse
import hashlib
import json
import math
import lzma
import time
from pathlib import Path

import numpy as np
import torch


def phi(x):
    return math.erfc(-x / math.sqrt(2.0)) / 2


def gaussian_hit(grid, shift, horizon):
    sigma = 0.23
    drift = 0.08 - 0.02 - sigma**2 / 2
    scale = sigma * math.sqrt(horizon)
    return [1.0 if x + shift <= 0 else
            phi((-(x+shift)-drift*horizon)/scale) +
            math.exp(-2*drift*(x+shift)/sigma**2) * phi((-(x+shift)+drift*horizon)/scale)
            for x in grid]


def replay(path, device):
    torch.set_num_threads(1)
    start = time.perf_counter()
    payload = path.read_bytes()
    if path.suffix == '.xz':
        payload = lzma.decompress(payload)
    rows = json.loads(payload)
    if isinstance(rows, dict):
        rows = rows['rows']
    four = [(0.08, 0), (0.125, 0), (0.5, 0), (3, 0)]
    queries = {'fixed_boundary': [], 'one_hit': [(0.25, 0)], 'stock_four_horizons':four,
               'eight_horizons':[(t,0) for t in np.geomspace(0.04,6,8)],
               'four_horizons_plus_four_shocks':four+[(0.25,s) for s in [-0.2,-0.1,0.1,0.2]]}
    maxgap = feasibility = replay_excess = 0
    groups = {}
    rows_seen = set()
    for r in rows:
        k, name, noise, shock = r['atoms'], r['port'], r['noise'], r['shift']
        key=(k, name, noise, shock)
        if key in rows_seen:
            raise ValueError('repeated cell')
        rows_seen.add(key)
        if k not in groups:
            w = np.random.default_rng(916243+k).gamma(0.3,1,size=(8192,k))
            groups[k] = torch.tensor(w/w.sum(1,keepdims=True),device=device,dtype=torch.float64)
        convert=lambda x: torch.as_tensor(x,dtype=torch.float64,device=device)
        x = np.linspace(.015,1.30,k)
        M = convert([gaussian_hit(x,s,t) for t,s in queries[name]]).reshape(-1,k)
        g = convert(gaussian_hit(x,shock,.25))
        hi, lo, a = map(convert,(r['p_plus'],r['p_minus'],r['a']))
        v1=(M@(hi-lo)).abs().max().item() if M.shape[0] else 0
        feasibility=max(feasibility,v1-2*noise,float(-hi.min()),float(-lo.min()),
                        abs(float(hi.sum())-1),abs(float(lo.sum())-1))
        estimate = r['c'] + a@M
        upper = (g-estimate).abs().max().item()+noise*a.abs().sum().item()
        lower = float(g@(hi-lo))/2
        maxgap=max(maxgap,abs(upper-lower),abs(upper-r['upper']),abs(lower-r['lower']))
        err=(groups[k]@(g-estimate)).abs().max().item()+noise*a.abs().sum().item()
        replay_excess=max(replay_excess,err-upper)
    expected={(k,n,e,s) for k in (12,32,64) for n in queries for e in (0,1e-4,.001)
              for s in (-.175,-.075,.075,.175)}
    if rows_seen != expected or maxgap>5e-7 or feasibility>5e-8 or replay_excess>5e-7:
        raise ValueError((len(rows_seen),maxgap,feasibility,replay_excess))
    return dict(cells=len(rows_seen),device=torch.cuda.get_device_name() if device=='cuda' else 'CPU',
                torch=str(torch.__version__),numpy=str(np.__version__),reference='Python math.erfc',
                elapsed_s=time.perf_counter()-start,max_gap_or_crosscheck=maxgap,
                max_feasibility_excess=feasibility,max_replay_excess=replay_excess,
                random_populations_per_cell=8192,sha256=hashlib.sha256(payload).hexdigest())


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('witness',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    a=p.parse_args()
    a.output.write_text(json.dumps(replay(a.witness,a.device),indent=2)+'\n')
