"""Independent exhaustive service mixtures and scalar/batch count comparisons."""
import argparse
import hashlib
import json
from pathlib import Path
from itertools import combinations
import sys

import numpy as np
import torch
from experiments.hcsn_v10_followup_20261101.control import mpc
from experiments.hcsn_v9_followup_20261101.mechanisms.campaign import FittedAnalytic
from experiments.hcsn_mechanism_content_v2.renewal import Physics
from experiments.hcsn_v8_execution_20261101.mechanisms.recurrent_counts import load_core
from .enumeration_reference import score as enumerate_score


def run(output):
    torch.set_num_threads(1)
    rng = np.random.default_rng(101731)
    checks = 0
    errors = []
    max_mixture_error = 0.
    for case in range(120):
        tick = case % 7
        deadlines = [d for d in (2, 4, 6, 8) if d > tick]
        if not deadlines:
            continue
        arrivals = list(range(tick+1, max(deadlines)+1))
        base = {d: float(rng.random()) for d in deadlines}
        read = {(a,d): float(rng.random()) for a in arrivals for d in deadlines if a <= d}
        if case % 3 == 0:
            q = rng.integers(0, 2, 9).astype(float).tolist()
        else:
            q = rng.random(9).tolist()
        for size in range(min(3,len(arrivals))+1):
            for schedule in combinations(arrivals,size):
                target = mpc.score_schedule(schedule, deadlines, base, read, q)
                ref = enumerate_score(schedule, deadlines, base, read, q)
                error = abs(target-ref)
                checks += 1
                max_mixture_error = max(max_mixture_error, error)
                if error > 1e-12:
                    errors.append({'case':case,'schedule':schedule,'error':error})
    root = Path(__file__).resolve().parents[4]
    checkpoint_path = root/'experiments/hcsn_v8_execution_20261101/mechanisms/results/development001/fit_81101/models.pt'
    checkpoint = torch.load(checkpoint_path,weights_only=False,map_location='cpu')
    cores = {'analytic':FittedAnalytic('original',1.),
             **{f:load_core(checkpoint,f) for f in ('gru','ssm')}}
    maximum_batch_error = {}
    for name,core in cores.items():
        worst = 0.
        for case in range(12):
            physics = Physics(-rng.uniform(.3,1),rng.uniform(.2,.65),rng.uniform(.4,1),rng.uniform(.16,.28))
            packets = []
            for row in range(32):
                horizon = 0. if row == 0 else float(rng.uniform(.01,3))
                remaining = physics.refractory if row % 3 == 0 else 0.
                if row == 1:
                    remaining=horizon
                x = physics.reset if remaining > 0 else float(rng.uniform(.2,1.4))
                packets.append([x,horizon,physics.nu,physics.sigma,physics.reset,physics.refractory,remaining])
            packets = np.asarray(packets)
            actual = mpc.batch_counts(core,packets,physics)
            ref = np.stack([core.counts(float(v[0]),float(v[1]),physics,float(v[6])) for v in packets])
            error = float(np.abs(actual-ref).max())
            worst=max(worst,error)
            checks += len(packets)
            if error>2e-12:
                errors.append({'family':name,'case':case,'batch_error':error})
        maximum_batch_error[name] = worst
    result = {'status':'passed' if not errors else 'failed','checks':checks,
              'mixture_max_error':max_mixture_error,'batch_max_error_by_family':maximum_batch_error,
              'errors':errors,'scope':'all 2^R service patterns; historical first fit scalar/batch parity at valid sampled physics',
              'mpc_sha256':hashlib.sha256(Path(mpc.__file__).read_bytes()).hexdigest(),
              'reference_sha256':hashlib.sha256(Path(__file__).with_name('enumeration_reference.py').read_bytes()).hexdigest(),
              'torch':torch.__version__}
    with output.open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps(result))
    if errors:
        sys.exit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
