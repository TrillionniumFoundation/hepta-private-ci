import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
def auc(y,p):
    # Fast exact midrank AUC for ties, with stable sorting.
    k=int(y.sum());n=len(y)
    if k==0 or k==n:return None
    s=np.argsort(p,kind='stable');v=p[s];i=np.argsort(s)
    _,start,count=np.unique(v,return_index=True,return_counts=True)
    rank=np.repeat(start+.5*(count+1),count)[i]
    return float((rank[y.astype(bool)].sum()-k*(k+1)/2)/(k*(n-k)))
def main():
    out=ROOT/'out';states=json.loads((out/'seal.json').read_bytes());report={}
    for task in ('air','power'):
        with np.load(ROOT/f'{task}_test.npz') as z:
            y=z['y'];week=z['week'];site=z['site']
        scores={};allarms={}
        for name,h in states.items():
            d,arm,seed=name.split('-')
            if d!=task:continue
            loc=out/name
            assert hashlib.sha256((loc/'selected.pt').read_bytes()).hexdigest()==h
            ts=json.loads((loc/'test.json').read_bytes())
            assert hashlib.sha256((loc/'probabilities.npz').read_bytes()).hexdigest()==ts['sha256']
            with np.load(loc/'probabilities.npz') as z:p=z['p']
            fit=json.loads((loc/'fit.json').read_bytes());a=allarms.setdefault(arm,{k:[] for k in ['loss','dev','wall','selected','auc','bias','violation']})
            a['loss'].append((y-p)**2);a['dev'].append(min(v['trained_horizon_brier'] for v in fit['history']));a['wall'].append(ts['cold_seconds']+fit['cold_seconds']);a['selected'].append(fit['selected'])
            a['auc'].append([auc(y[:,j],p[:,j]) for j in range(5)]);a['bias'].append((p-y).mean(0));a['violation'].append(ts['metrics']['adjacent_monotonicity_violation'])
        best=min((a for a in allarms if not a.startswith('physical')),key=lambda a:np.mean(allarms[a]['dev']))
        def diffci(diff):
            rng=np.random.default_rng(418309);sums=[];lens=[]
            for ss in np.unique(site):
                groups=np.unique(week[site==ss]);n=len(groups)
                x=np.array([diff[week==g].sum() for g in groups]);w=np.array([(week==g).sum() for g in groups])
                k=rng.integers(n,size=(2000,n));sums.append(x[k].sum(1));lens.append(w[k].sum(1))
            return np.quantile(np.sum(sums,axis=0)/np.sum(lens,axis=0),[.025,.975]).tolist()
        ref=np.mean(allarms[best]['loss'],0)[:,[1,3]].mean(1)
        for arm,a in allarms.items():
            loss=np.mean(a['loss'],0);held=loss[:,[1,3]].mean(1);ds=held-ref
            au=np.array([[np.nan if s is None else s for s in row] for row in a['auc']])
            au=[None if np.isnan(v).all() else float(np.nanmean(v)) for v in au.T]
            scores[arm]={'dev_trained_brier':float(np.mean(a['dev'])),'brier':loss.mean(0).tolist(),'held_brier':float(held.mean()),'bias':np.mean(a['bias'],0).tolist(),'auroc':au,'max_monotonicity_violation':max(a['violation']),'cold_mean_s':float(np.mean(a['wall'])),'selected':a['selected'],'held_minus_best':float(ds.mean()),'paired95':diffci(ds),'site_deltas':{s:float(ds[site==s].mean()) for s in np.unique(site)}}
        # Same-encoder contrast prevents attributing a distributional assumption to physical representation.
        head=np.mean(allarms['gru_fht']['loss'],0)[:,[1,3]].mean(1)-np.mean(allarms['gru_weibull']['loss'],0)[:,[1,3]].mean(1)
        report[task]={'n':len(y),'weeks':len(set(week)),'best_conventional_by_dev':best,'gru_fht_minus_weibull':float(head.mean()),'head_paired95':diffci(head),'arms':scores}
    (out/'report.json').write_text(json.dumps(report,indent=1,allow_nan=False))
if __name__=='__main__':main()
