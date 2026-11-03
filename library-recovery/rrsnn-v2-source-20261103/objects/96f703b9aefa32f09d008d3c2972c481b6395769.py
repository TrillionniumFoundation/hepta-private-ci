"""Generate fresh v2 data with zero-time initial cues and explicit observations.

Uses the frozen v0 resource task semantics and oracle, changes no v0 files.
Fresh split seeds prevent reusing v0 held-out outcomes after architecture changes.
The future split is still synthetic distribution shift, not a real future cohort.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import numpy as np

from rrsnn_experiments.resource_env import make_scenario, Oracle, MAX_STEPS, FEATURES

ROOT = Path(__file__).resolve().parent


def make_split(n, seed, shifted=False):
    rng = np.random.default_rng(seed)
    scenarios = [make_scenario(rng, split='future' if shifted else 'train') for _ in range(n)]
    arrays = {k:[] for k in ('x','dt','valid','optimal','decision','lengths','event_mask')}
    for scenario in scenarios:
        oracle = Oracle(scenario)
        x, _, valid, optimal, decision, _, length = oracle.demonstration()
        dt = np.zeros(MAX_STEPS, dtype=np.float32)
        dt[:length] = np.diff(np.asarray(oracle.times), prepend=0.0)
        mask = np.arange(MAX_STEPS)<length
        assert dt[0] == 0 and np.all(dt[1:length]>0)
        for name, value in zip(arrays, (x,dt,valid,optimal,decision,length,mask)):
            arrays[name].append(value)
    arrays = {k:np.asarray(v) for k,v in arrays.items()}
    return scenarios, arrays


def main():
    destination = ROOT/'data'
    destination.mkdir(exist_ok=True)
    specs = [('train',1024,120201,False),('validation',256,220201,False),
             ('test',512,320201,False),('shift',512,420201,True)]
    result = {'schema':'rrsnn.v2-data.v1','features':FEATURES,
              'event_protocol':'Advance under previously observed controls, then process the current observation; initial dt=0; no-op mask does not update controls.',
              'task_source_sha256':hashlib.sha256(Path('rrsnn_experiments/resource_env.py').read_bytes()).hexdigest(),
              'splits':[], 'real_future_window':False}
    for name,n,seed,shifted in specs:
        scenarios, arrays = make_split(n,seed,shifted)
        path = destination/f'{name}.npz'
        np.savez_compressed(path,**arrays)
        sc_path = destination/f'{name}_scenarios.json'
        sc_path.write_text(json.dumps([asdict(s) for s in scenarios],separators=(',',':'))+'\n')
        result['splits'].append({'name':name,'n':n,'seed':seed,'shifted':shifted,
                                'npz_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                'scenario_sha256':hashlib.sha256(sc_path.read_bytes()).hexdigest(),
                                'max_observations':int(arrays['lengths'].max())})
        print(name,n,flush=True)
    (destination/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__ == '__main__':
    main()
