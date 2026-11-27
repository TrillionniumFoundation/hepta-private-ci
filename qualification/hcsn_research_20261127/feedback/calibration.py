"""Fit thresholds and two-parameter calibration on development sets of all sealed primary models."""
import json,hashlib,zipfile,time
from pathlib import Path
import numpy as np
from scipy.special import expit,logit
from scipy.optimize import minimize
import torch
from campaign import make,predict,file_sha,write_once
from datasets import load
HERE=Path(__file__).resolve().parent
PLAN=json.loads((HERE/'protocol.json').read_text());PRO=json.loads((HERE/'calibration_protocol.json').read_text())
def optimize(x,y):
    x=np.array(x);y=np.array(y);v=np.unique(x)
    choices=np.r_[np.nextafter(v[0],-np.inf),.5*(v[1:]+v[:-1]),np.nextafter(v[-1],np.inf)]
    def balanced(t):return .5*(np.mean(x[y==1]>=t)+np.mean(x[y==0]<t))
    ranked=sorted(choices,key=lambda t:(-balanced(t),abs(t-.5),t))
    l=logit(np.clip(x,1e-8,1-1e-8));center=l.mean();scale=max(l.std(),1e-8);z=(l-center)/scale
    def objective(arg):
        a,b=arg;h=a*z+b
        return np.mean(np.logaddexp(0,h)-y*h)+PRO['ridge']*a*a/2
    res=minimize(objective,[1.,0.],method='L-BFGS-B',bounds=[(0,30),(-30,30)],options={'ftol':1e-14,'maxiter':500})
    if not res.success:raise ValueError(str(res.message))
    return dict(threshold=float(ranked[0]),dev_ba=balanced(ranked[0]),slope=float(res.x[0]),bias=float(res.x[1]),center=center,scale=scale)
def metrics(y,p,t):
    y=np.array(y);p=np.array(p);b=p>=t
    return dict(ba=float(.5*((b[y==1]).mean()+(~b[y==0]).mean())),brier=float(((p-y)**2).mean()),accuracy=float((b==y).mean()),positive=int(b.sum()))
def main():
    import sys
    out=HERE/'calibration_results';out.mkdir(exist_ok=True)
    params={};raw={}
    for ds,folder in zip(PLAN['tasks'],[Path(sys.argv[1]),Path(sys.argv[2])]):
        dv=load(ds,folder,'dev')
        for seed in PLAN['seeds']:
            for arm in PLAN['arms']:
                key=f"{ds}/{arm}-{seed}";base=HERE/'results'/key;fit=json.loads((base/'fit.json').read_text())
                assert fit['weights']==file_sha(base/'weights.pt');m=make(arm);m.load_state_dict(torch.load(base/'weights.pt',weights_only=True))
                score,p=predict(m,dv);p=np.array(p);y=dv[1].numpy();c=optimize(p,y)
                params[key]=dict(weights=fit['weights'],calibration=c,ids=dv[2],y=y.tolist(),p=p.tolist())
    pfile=out/'dev-seal.json';write_once(pfile,params)
    rows={}
    for key,info in params.items():
        orig=json.loads((HERE/'results'/key/'predictions.json').read_text());p=np.asarray(orig['p']);y=orig['y'];c=info['calibration']
        scaled=expit(c['slope']*(logit(p.clip(1e-8,1-1e-8))-c['center'])/c['scale']+c['bias'])
        rows[key]=dict(ids=orig['ids'],groups=orig['sources'],y=y,raw_p=p.tolist(),calibrated_p=scaled.tolist(),
            original=metrics(y,p,.5),threshold=metrics(y,p,c['threshold']),platt=metrics(y,scaled,.5))
    write_once(out/'predictions.json',rows)
    summary={}
    for ds in PLAN['tasks']:
        summary[ds]={}
        for arm in PLAN['arms']:
            cohort=[rows[f'{ds}/{arm}-{s}'] for s in PLAN['seeds']]
            summary[ds][arm]={method:{k:float(np.mean([r[method][k] for r in cohort])) for k in ['ba','brier','accuracy']} for method in ['original','threshold','platt']}
    write_once(HERE/'calibration_summary.json',summary)
    with zipfile.ZipFile(HERE/'calibration_records.zip','w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(out.iterdir()):z.write(p,p.name)
if __name__=="__main__":
    torch.set_num_threads(1);main()
