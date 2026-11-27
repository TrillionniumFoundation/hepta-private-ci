"""Independent NumPy scoring check on the complete sealed archived predictions."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def main(folder):
    seal=json.loads((folder/'seal.json').read_text());official=json.loads((folder/'cold.json').read_text())
    assert hashlib.sha256((folder/'seal.json').read_bytes()).hexdigest()==official['seal_sha256']
    checked=0;maxerr=0
    for site,results in official['sites'].items():
        path=folder/f'{site}-predictions.npz'
        assert hashlib.sha256(path.read_bytes()).hexdigest()==results['predictions_sha256']
        with np.load(path) as source:
            y=source['y'].astype('float64')
            assert np.all(y[:,0,0]==y[:,1,0]) and np.all(y[:,2,0]==y[:,3,0])
            assert np.all(np.diff(y,axis=2)>=0)
            for rung,item in results['budgets'].items():
                for arm,reported in item['metrics'].items():
                    probs=[]
                    if arm=='analog':
                        probs.append(source['analog'].astype('float64'))
                    else:
                        ids=[v for label,v in seal['selected'].items() if v['arm']==arm]
                        for v in ids:
                            b=v['budget_s'] if rung=='selected' else int(rung)
                            probs.append(source[f"{arm}-{v['seed']}-{b}"].astype('float64'))
                    scores=[((p-y)**2).sum()/y.size for p in probs]
                    err=abs(np.mean(scores)-reported['brier'][0])
                    maxerr=max(maxerr,err)
                    assert err<3e-7 and np.max(np.abs(np.array(scores)-reported['per_seed_brier']))<3e-7
                    signed=np.mean([((p[:,1::2,1:]-p[:,::2,1:])-(y[:,1::2,1:]-y[:,::2,1:])).mean(axis=0) for p in probs],axis=0)
                    expected=np.array([[v[0] for v in row] for row in reported['fee_effect_error_signed_by_reserve_and_horizon']])
                    assert np.max(abs(signed-expected))<3e-7
                    checked+=1
    return {'site_rung_method_cells':checked,'max_mean_brier_recalculation_delta':float(maxerr),'cold_sha':hashlib.sha256((folder/'cold.json').read_bytes()).hexdigest()}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('out',type=Path);a=p.parse_args();result=main(a.folder);a.out.write_text(json.dumps(result,indent=2)+'\n');print(result)
