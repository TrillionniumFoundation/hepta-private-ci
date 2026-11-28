"""Recount saved scores and independently check the fitted first-hit probabilities."""
from pathlib import Path
import argparse
import json
import numpy as np
from scipy.special import ndtr
from recorded import Risk, current_bank, REGIONS


def summary(folder, data, law):
    all_rows = {}
    heldout = json.loads((folder/'heldout.json').read_text())
    likelihood = json.loads((folder/'likelihood_results.json').read_text())
    for site, methods in heldout.items():
        dm = {}
        with np.load(folder/(site+'-edit.npz')) as saved, np.load(data/(site+'.npz')) as z:
            y = saved['y']
            assert np.array_equal(y,z['y'][REGIONS['cold']])
            bins, repeats = y.shape
            groups = np.arange(bins)//250
            cluster_counts = np.bincount(groups)
            draws = np.random.default_rng(59207).integers(len(cluster_counts),size=(4000,len(cluster_counts)))
            def sums(p):
                p=np.clip(p,1e-10,1-1e-10)
                return -np.mean(y*np.log(p[:,None])+(1-y)*np.log1p(-p[:,None]),axis=1)
            ref = sums(saved['recursive'])
            for method, record in methods.items():
                loss = sums(saved[method])
                delta = ref-loss
                values = np.bincount(groups,weights=delta)[draws].sum(1)/cluster_counts[draws].sum(1)
                triple = np.r_[delta.mean(),np.quantile(values,[.025,.975])]
                assert np.allclose(triple,record['recursive_minus_this_nll'],atol=1e-12)
                assert abs(loss.mean()-record['nll'])<1e-12
            keys = current_bank(z['currents'])
            x = np.column_stack([np.ones(len(keys)),keys])[REGIONS['cold']]
            for method, selection in likelihood[site]['holdout'].items():
                chosen = next(row for row in likelihood[site]['all_fits'][method] if row['ridge']==selection['ridge'])
                margin = np.maximum(0,.18-np.log1p(law.k*np.tanh(x@np.asarray(chosen['weights']))))
                b = law.sigma*np.sqrt(law.t)
                p = ndtr((-margin-law.mu*law.t)/b)+np.exp(-2*law.mu*margin/(law.sigma**2))*ndtr((-margin+law.mu*law.t)/b)
                p=np.clip(p,1e-10,1-1e-10)
                dm[method]=float(sums(p).mean())
                assert abs(dm[method]-selection['nll'])<1e-12
        all_rows[site]=dict(heldout_bins=bins,repeat_trials=repeats,recomputed_likelihood=dm,
                            checked_probability_methods=len(methods),block_bootstraps=4000)
    return all_rows


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for k in ('data','core','out'):parser.add_argument('--'+k,type=Path,required=True)
    args=parser.parse_args()
    obj=summary(Path(__file__).resolve().parent,args.data,Risk(args.core))
    args.out.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
