"""Paired descriptive evaluation and exact small-sample sign-flip sensitivity."""
import itertools
import json
from pathlib import Path
import sys
import numpy as np

def sign_flip(fits):
    observed=abs(np.mean(fits))
    means=[abs(np.mean(fits*np.array(s))) for s in itertools.product((-1,1),repeat=len(fits))]
    return float(np.mean(np.array(means)>=observed-1e-14))

def summary(root):
    r=json.loads((root/'WORLD_RESULTS.json').read_bytes())
    c=json.loads((root/'CANDIDATES.json').read_bytes())
    fits=sorted({w['fit'] for w in r})
    arms=list(r[0]['metrics'])
    assert len(r)==160 and len(set(w['schedule'] for w in r))==160
    assert len({w['state_rows']<=0 for w in r})==1 and r[0]['state_rows']>0
    result={'domains':{},'method':{},'direct_vs_PGD':{},'actual_worlds':len(r),
            'actual_states':sum(w['state_rows'] for w in r)}
    for domain in ('iid','ood'):
        byfit=[[w for w in r if w['fit']==f and w['domain']==domain] for f in fits]
        assert all(len(v)==16 for v in byfit)
        result['domains'][domain]={}
        for arm in arms:
            delta=np.array([[w['metrics'][arm]['value']-w['metrics']['KEEP']['value'] for w in ws] for ws in byfit])
            values=[w['metrics'][arm] for ws in byfit for w in ws]
            result['domains'][domain][arm]={
                'mean_value':float(np.mean([v['value'] for v in values])),
                'mean_delta':float(delta.mean()),'fit_deltas':delta.mean(1).tolist(),'min_world_delta':float(delta.min()),
                'tail_violations':int((delta<-.05).sum()),'fits_passing_tail':int((delta.min(1)>=-.05).sum()),
                'fit_mean_positive':int((delta.mean(1)>1e-12).sum()),
                'paired_2s_signflip':sign_flip(delta.mean(1)),'mean_posterior_mse_common_occupancy':float(np.mean([v['belief_MSE'] for v in values])),
                'mean_continuation_gap':float(np.mean([v['continue_gap'] for v in values])),
                'mean_terminal_gap':float(np.mean([v['terminal_gap'] for v in values]))}
        d=np.array(result['domains'][domain]['DIRECT']['fit_deltas'])-result['domains'][domain]['PGD']['fit_deltas']
        result['direct_vs_PGD'][domain]={'fit_mean':d.tolist(),'mean':float(d.mean()),'paired_2s_signflip':sign_flip(d)}
    for k in ('teacher_shared_seconds','closed_form_seconds','PGD_seconds'):
        result['method'][k]=sum(v[k] for v in c.values())
    for arm in ('KEEP','DIRECT','PGD'):
        result['method'][arm+'_teacher_loss']=float(np.mean([v['arms'][arm]['teacher_loss'] for v in c.values()]))
    result['method']['original_sha256']={f:v['original_sha256'] for f,v in c.items()}
    result['maximum_PDI_residual']=max(abs(m['pdi_residual']) for w in r for m in w['metrics'].values())
    result['maximum_mass_error']=max(abs(m['terminal_mass']-1) for w in r for m in w['metrics'].values())
    return result

if __name__=='__main__':
    print(json.dumps(summary(Path(sys.argv[1])),indent=2))
