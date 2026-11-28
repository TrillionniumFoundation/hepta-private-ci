"""Independent per-repeat log/Brier reconstruction from the transmitted FP32 scores."""
from pathlib import Path
import json
import numpy as np

def run(root):
    study=json.loads((root/'measured/results.json').read_text());out={}
    for site,cell in study['cells'].items():
        with np.load(root/'measured'/(site+'.npz')) as z:
            ix=np.where(np.isin(z['horizons'],[2,6]))[0]
            counts=z['y_count'][:,ix].astype(float);n=int(z['trial_count']);err=0
            for name,row in cell['score'].items():
                p=z[name][:,ix].astype(float).clip(1e-7,1-1e-7)
                terms=-counts*np.log(p)-(n-counts)*np.log1p(-p)
                b=counts*(1-p)**2+(n-counts)*p**2
                err=max(err,abs(terms.mean()/n-row['new_log_loss']),abs(b.mean()/n-row['new_brier']))
            out[site]={'rows':len(counts),'repeats':n,'heads':len(cell['score']),'max_error':err}
            assert err<1e-13
    return out
if __name__=='__main__':
    print(json.dumps(run(Path(__file__).resolve().parent),indent=2))
