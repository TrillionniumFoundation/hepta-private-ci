"""Report a sealed TRAIN-only edit on four already disclosed panels, including the training split."""
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from time import perf_counter

import numpy as np
from qualification.hcsn_blocker_followup import metrics
from intercept_capacity import load_first_prefix
from train_return_edit import historical_inputs

HERE = Path(__file__).resolve().parent


def evaluate():
    began = perf_counter()
    blob = (HERE/'train-return-seal.json').read_bytes()
    weight_hash = hashlib.sha256(blob).hexdigest()
    if weight_hash != '6ae738217ea463d48a5aac72b0b46c52dd9fdfabec4a3aed9e947cd20c340dae':
        raise ValueError('Unbound training weights')
    seal = json.loads(blob)
    delta = [Fraction(n, 1_000_000_000) for n in seal['edit_numerators']]
    results = {}
    for split in ('train','dev','test','third_cohort'):
        tick = perf_counter()
        if split == 'third_cohort':
            x, w, data, _, _, ids = load_first_prefix()
        else:
            x, w, data, _, _, _ = historical_inputs(split)
            ids = list(data['query_id'])
        edited = [Fraction(float(v)) + d for v,d in zip(w,delta,strict=True)]
        margins = [sum(Fraction(float(y))*z for y,z in zip(row,edited,strict=True)) - Fraction(3,10) for row in x]
        buys = np.array([s>0 for s in margins])
        assert np.array_equal(buys, x @ (w + np.asarray(seal['edit_numerators'])/1e9) > .30)
        score = metrics.evaluate(data,buys)
        if split == 'train':
            assert score == seal['training']
        results[split] = {
            'rows':len(ids), 'sources':len(set(data['group'])), 'elapsed_seconds':perf_counter()-tick,
            'score':score, 'min_absolute_margin':str(min(map(abs,margins))),
            'actions':{i:int(a) for i,a in zip(ids,buys,strict=True)}
        }
    return {'study':'Retrospective evaluation of a single TRAIN-only edit on previously released outcomes',
            'weight_sha256':weight_hash, 'fit_commit':'dc447bb86369e12c804b394ec64b9ccc3a882aae',
            'panels':results, 'elapsed_seconds':perf_counter()-began}


if __name__ == '__main__':
    print(json.dumps(evaluate(),indent=2,sort_keys=True))
