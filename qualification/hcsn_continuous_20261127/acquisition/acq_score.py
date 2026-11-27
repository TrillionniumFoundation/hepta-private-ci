"""Cold-verify every retained prediction and meter, aggregate equal-person primary contrasts."""
from acq_prepare import ROOT
import json,hashlib,time,sys
import numpy as np
def summarize(name):
    files=sorted((ROOT/name/'results').glob('p*.npz'));assert len(files)==10
    B=np.random.default_rng(71641).integers(10,size=(20000,10))
    per={};man={};diffdec={};total=0;cost={}
    for file in files:
        rows=json.loads(file.with_suffix('.json').read_bytes())
        with np.load(file) as z:d=dict(z)
        y=d['target'];total+=len(y);man[file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
        for arm in [k[:-2] for k in d if k.endswith('_p')]:
            p=d[arm+'_p'];assert np.isfinite(p).all() and abs(p.sum(1)-1).max()<2e-6
            loss=-np.log(np.maximum(1e-12,p[np.arange(len(y)),y].astype(float))).mean()
            acc=(p.argmax(1)==y).mean()
            assert abs(loss-rows[arm]['nll'])<1e-6 and abs(acc-rows[arm]['acc'])<1e-10
            if arm not in ['cheap','full']:
                mask=d[arm+'_mask'];q=int(arm[-1]);assert np.all(mask.reshape(-1,4).sum(1)==q)
                assert int(mask.sum())==rows[arm]['extra_frames'] and rows[arm]['extra_bytes']==rows['_meta']['frame_bytes']*mask.sum()
                assert np.array_equal(p[~mask].astype(np.float32),d['cheap_p'][~mask].astype(np.float32))
                assert np.max(abs(p[mask]-d['full_p'][mask]))<3e-6
                cost[arm]=cost.get(arm,0)+int(rows[arm]['extra_bytes'])
            per.setdefault(arm,[]).append([float(loss),float(acc)])
        for a in ['tangent','learned','entropy','periodic']:
            diffdec[a]=diffdec.get(a,0)+int(np.sum(d['literal1_mask']!=d[a+'1_mask']))
    metrics={arm:np.mean(v,axis=0).tolist() for arm,v in per.items()}
    contr={}
    for q in ['1','2']:
        for a in ['tangent','learned','entropy','periodic']:
            dif=np.array(per['literal'+q])[:,0]-np.array(per[a+q])[:,0]
            contr[q+'-'+a]={'nll_delta':float(dif.mean()),'paired_subject_95':np.quantile(dif[B].mean(1),[.025,.975]).tolist(),'per_subject':dif.tolist()}
    return {'windows':total,'subjects':10,'metrics_nll_accuracy':metrics,'paired':contr,'extra_bytes':cost,'different_25pct_binary_decisions':diffdec,'prediction_sha256':man,'primary_pass':all(contr['1-'+a]['paired_subject_95'][1]<0 for a in ['tangent','learned'])}
if __name__=='__main__':
    d={n:summarize(n) for n in ['daphnet','mhealth']};(ROOT/'SUMMARY.json').write_text(json.dumps(d,indent=1))
    for n,v in d.items():print(n,v['windows'],v['metrics_nll_accuracy'],v['paired']['1-tangent'],v['paired']['1-learned'],v['primary_pass'])
