"""Recover all FP32 published replies and source event labels with identical-command deduplication."""
import argparse
import json
from pathlib import Path
import numpy as np

def verify(source,original,out):
    out.mkdir(parents=True,exist_ok=True);r=json.loads((original/'results.json').read_text());largest=0.;queries=0;unique=0
    for typ in '12':
        s=r['outputs'][typ]['scores'];names=list(s)
        for sid in r['cells']:
            with np.load(source/f'{sid}.npz') as raw,np.load(original/f'{sid}-{typ}_0.npz') as f0,np.load(original/f'{sid}-{typ}_1.npz') as f1:
                common=np.array_equal(raw[f'x{typ}_0'],raw[f'x{typ}_1'])
                a=f0['anchors'];h=f0['horizons'];assert np.array_equal(a,f1['anchors']) and np.array_equal(h,f1['horizons'])
                bundle={'anchors':a,'horizons':h};by={n:[] for n in names};cols=[j for j,k in enumerate(h) if k in (2,6)]
                for rep,f in enumerate((f0,f1)):
                    events=raw[f'y{typ}_{rep}'];ys=np.stack([np.logical_or.reduce([events[a+i] for i in range(k)]) for k in h],axis=1)
                    assert np.array_equal(ys,f['targets']);queries+=ys.size
                    bundle['events_'+str(rep)]=np.packbits(ys,axis=0)
                    for name in names:
                        v=f[name];assert v.dtype==np.float32
                        if rep==0 or not common:bundle[name+('_1' if rep else '')]=v
                        elif not np.array_equal(f0[name],v):raise ValueError('same commands produced different messages')
                        p=np.clip(v[:,cols].astype(float),1e-7,1-1e-7);y=ys[:,cols]
                        by[name].append([np.mean(-np.where(y,np.log(p),np.log1p(-p))),np.mean((p-y)**2)])
                for n in names:
                    wanted=s[n]['by_specimen'][str(sid)];largest=max(largest,float(np.max(abs(np.mean(by[n],0)-wanted))))
                file=out/f'{sid}_{typ}.npz';np.savez_compressed(file,**bundle)
                with np.load(file) as rec:
                    for rep,f in enumerate((f0,f1)):
                        assert np.array_equal(np.unpackbits(rec['events_'+str(rep)],axis=0)[:len(a)].astype(bool),f['targets'])
                        for n in names:assert np.array_equal(rec[n+('_1' if rep and not common else '')],f[n])
                unique+=1 if common else 2
    return {'logical_sweeps':32,'unique_prediction_matrices':unique,'forecast_targets_rebuilt_all_five_horizons':queries,
            'max_per_cell_nll_brier_abs_error':largest,'all_original_FP32_forecasts_exactly_restored':True}
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('source','original','out'):p.add_argument(n,type=Path)
    a=p.parse_args();print(json.dumps(verify(a.source,a.original,a.out),indent=1))
