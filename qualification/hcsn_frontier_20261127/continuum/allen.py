"""Compare the exact stationary renewal response with archived real within-cell held-out sweeps."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from scipy.optimize import least_squares


def curve(x,p):
    theta,a,refractory=p
    drive=np.maximum(x-theta,0)
    return drive/(a+refractory*drive)


def fit(x,y):
    best=None
    for threshold in (-1.25,-.65,-.1,.35):
        for d in (0.001, .015,.06):
            a=max(.001,1/max(1,np.ptp(y)))
            r=least_squares(lambda p:curve(x,p)-y,[threshold,a,d],
                            bounds=([-4,1e-5,0],[2.,8.,.5]),max_nfev=500,
                            xtol=1e-9,ftol=1e-9,gtol=1e-9)
            obj=float(r.fun@r.fun)
            if best is None or obj<best[0]:
                best=(obj,r.x,int(r.status))
    return best


def group_run(source,which):
    direct=which=='nwb_curve_records'
    archive=source/(which+'.zip');t0=time.monotonic()
    fits={}
    with ZipFile(archive) as z:
        for name in sorted(k for k in z.namelist() if k.startswith('fits/')):
            row=json.loads(z.read(name));sid=str(row['specimen' if direct else 'specimen_id'])
            x=np.array(row['train_amplitudes']);y=np.array(row['train_actual_counts' if direct else 'train_y'])
            lo,hi=float(x.min()),float(x.max())
            score,p,code=fit(2*(x-lo)/(hi-lo)-1,y)
            fits[sid]={'lo':lo,'hi':hi,'parameters':p.tolist(),'train_ss':score,'status':code}
        # Checkpoint all cell-local fits before opening a held-out count or existing prediction.
        seal=json.dumps(fits,sort_keys=True).encode()
        cells=json.loads(z.read('nwb_predictions.json' if direct else 'predictions.json'))
    records={};comparisons={}
    for sid,data in cells.items():
        spec=fits[sid];p=spec['parameters'];amps=np.array(data['heldout_amplitudes'])
        target=np.asarray(data['mean_counts'])
        if direct:
            # Original measurements are grouped at integer-pA levels.
            dur=np.array([np.mean([v['duration'] for v in data['sweeps'] if int(round(v['I_pA']))==int(a)]) for a in amps])
        else:dur=np.array(data['duration_s'])
        assert np.isfinite(dur).all() and np.all((.99<=dur)&(dur<=1.01))
        pred=curve(2*(amps-spec['lo'])/(spec['hi']-spec['lo'])-1,p)*dur
        other=data['mean_count_predictions' if direct else 'predictions']
        records[sid]={'test_current':amps.tolist(),'counts':target.tolist(),'durations':dur.tolist(),'renewal':pred.tolist(),'other':other}
        for k,v in {'renewal':pred,**other}.items():
            y=np.abs(np.array(v)-target)
            comparisons.setdefault(k,{})[sid]=[float(y.mean()),float(y[target==0].mean()) if (target==0).any() else None,float(y[target>0].mean()) if (target>0).any() else None]
    refs=sorted(cells);ids=np.random.default_rng(77591).integers(len(refs),size=(10000,len(refs)))
    stats={}
    base=np.array([comparisons['renewal'][s][0] for s in refs])
    for k,entries in comparisons.items():
        ar=np.array([entries[s][0] for s in refs]);b=base-ar
        stats[k]={'mean_cell_mae':float(ar.mean()),'paired_renewal_minus':float(b.mean()),'interval':np.quantile(b[ids].mean(1),[.025,.975]).tolist(),'zero_level_cell_mae':None,'positive_level_cell_mae':None}
        for j,lbl in [(1,'zero_level_cell_mae'),(2,'positive_level_cell_mae')]:
            eligible=[entries[s][j] for s in refs if entries[s][j] is not None]
            if eligible:stats[k][lbl]=float(np.mean(eligible))
    return dict(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),cells=len(refs),levels=sum(len(r['counts']) for r in records.values()),zeros=sum(np.sum(np.array(r['counts'])==0).item() for r in records.values()),train_fit_seal_sha256=hashlib.sha256(seal).hexdigest(),fit_and_compare_wall_s=time.monotonic()-t0,metrics=stats,records=records,fits=fits)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
    res={k:group_run(a.source,k) for k in ('ephys_records','nwb_curve_records')}
    res['overlapping_specimens']=sorted(set(res['ephys_records']['records'])&set(res['nwb_curve_records']['records']))
    a.out.write_text(json.dumps(res,indent=1)+'\n')
    print([(k,v['cells'],v['metrics']['renewal']) for k,v in res.items() if isinstance(v,dict)])
