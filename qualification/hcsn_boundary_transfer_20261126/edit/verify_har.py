"""Re-score the held-out behavior from the stored action rows, independent of Torch."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


def main(folder):
    tr = json.loads((folder/'train.json').read_text())
    test = json.loads((folder/'test.json').read_text())
    if hashlib.sha256((folder/'predictions.npz').read_bytes()).hexdigest() != test['predictions_sha256']:
        raise ValueError('Predictions changed')
    if tr['sealed_sha256'] != test['sealed_sha256']:
        raise ValueError('Different train/test candidate seals')
    with np.load(folder/'predictions.npz',allow_pickle=False) as archive:
        s = archive['subjects']
        free, paid = archive['free_correct'],archive['paid_correct']
        for arm, report in test['arms'].items():
            buy,keep=archive[arm],archive['KEEP']
            if not np.isin(buy,[0,1]).all():
                raise ValueError(arm)
            def score(chosen, price):
                value=np.where(chosen.astype(bool),paid-price,free)
                return np.array([np.mean(value[s==person]) for person in test['test_groups']])
            for price,name in ((.1,'new'),(.45,'old')):
                sc=score(buy,price)
                delta=sc-score(keep,price)
                assert abs(sc.mean()-report[name+'_utility']) < 1e-12
                assert abs(delta.mean()-report[name+'_delta']) < 1e-12
                assert abs(delta.min()-report['worst_'+name]) < 1e-12
            expected = 21 if 'groups' in tr else 9
            assert len(np.unique(s)) == expected
            fitted_people = sum(tr['groups'][:3], []) if 'groups' in tr else sum(tr['group_ids'], [])
            assert set(s).isdisjoint(fitted_people)
            assert set(s) == set(test['test_groups'])
    print(f'Verified five held-out decisions, disjoint participants and both paired utilities on {expected} subjects')


if __name__=='__main__':
    main(Path(sys.argv[1]))
