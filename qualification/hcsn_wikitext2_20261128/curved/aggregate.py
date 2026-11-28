import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;DIR=HERE/'results';seeds=(137,311,557)
def run():
    kinds=('hxcurve','bilinear','smoothwall')
    records={(k,s):json.loads((DIR/f'{k}-{s}.json').read_text()) for k in kinds for s in seeds}
    common=max(set.intersection(*(set(r['clock'] for r in j['timed']) for j in records.values())))
    summary={}
    for k in kinds:
        r=[records[k,s] for s in seeds]
        c=[next(v for v in j['timed'] if v['clock']==common) for j in r]
        summary[k]=dict(test_ppl=[j['test']['ppl'] for j in r],mean_test_ppl=np.mean([j['test']['ppl'] for j in r]),
             mean_test_nll=np.mean([j['test']['nll'] for j in r]),mean_cut_test_ppl=np.mean([j['cut_test']['ppl'] for j in r]),
             clock_test_ppl=[j['test']['ppl'] for j in c],mean_clock_test_ppl=np.mean([j['test']['ppl'] for j in c]),
             clock_targets=[j['tokens'] for j in c],clock_actual=[j['actual_seconds'] for j in c],
             parameters=[j['metadata']['parameter_count'] for j in r],train_tokens=[j['epochs'][-1]['cumulative_targets'] for j in r])
    diag=[json.loads((DIR/f'diagnostic-{s}.json').read_text()) for s in seeds]
    pairs=[np.load(DIR/f'paired-{s}.npz') for s in seeds]
    comparisons={}
    rng=np.random.default_rng(8721)
    for k in ('bilinear','smoothwall','replaced'):
        dif=np.stack([p['hxcurve'][:,0]-p[k][:,0] for p in pairs]);cnt=pairs[0]['hxcurve'][:,1]
        start=np.arange(0,len(cnt),16);num=np.add.reduceat(dif.mean(0),start);den=np.add.reduceat(cnt,start)
        draws=rng.integers(len(den),size=(5000,len(den)));b=num[draws].sum(1)/den[draws].sum(1)
        comparisons[k]=dict(difference_hx_minus_alternative_per_seed=(dif.sum(1)/cnt.sum()).tolist(),
           average=float(num.sum()/den.sum()),test_macroblock_95=np.quantile(b,[.025,.975]).tolist(),macroblocks=len(den))
    activ={}
    for layer in range(2):
        a=[q['replaced']['layers'][layer] for q in diag]
        activ[str(layer+1)]={k:[u[k] for u in a] for k in ('empirical_test_rmse','uniform_test_rmse','train_scalar_samples','test_scalar_samples')}
    return dict(common_clock_seconds=common,seed_order=seeds,models=summary,matched_test_comparisons=comparisons,
         measured_state_projection=activ,test_ppl_after_fitted_curve_replacement=[q['replaced']['ppl'] for q in diag])
if __name__=='__main__':
    (HERE/'summary.json').write_text(json.dumps(run(),indent=2)+'\n')
