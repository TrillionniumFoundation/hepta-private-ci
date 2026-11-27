"""Leave-one-person-out conditional sensor replay. Inference opens extra frames only after a gate decision."""
from pathlib import Path
import sys,json,time
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from acq_prepare import ROOT,features
from acq_gate import gate_inputs,fit_gates,scores,eligible,choose
def head(x,y):
    return make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=400)).fit(x,y)
def nll(p,y):return -np.log(np.maximum(p[np.arange(len(y)),y],1e-12))
def read_extra(store,idx,rate):
    return np.concatenate([features(store[ii],rate) for ii in np.array_split(idx,max(1,(len(idx)+127)//128))])
def run(name,person):
    started=time.monotonic();base=ROOT/name
    with np.load(base/'cheap.npz') as zz:d=dict(zz)
    a,y,sub,seg,rate=(d[k] for k in ['features','label','subject','segment','rate'])
    store=np.load(base/'expensive.npy',mmap_mode='r')
    tr=np.flatnonzero(sub!=person);te=np.flatnonzero(sub==person)
    X,Y=a[tr],y[tr];e=read_extra(store,tr,rate)
    split={p:i%3 for i,p in enumerate(np.unique(sub[tr]))};fold=np.array([split[p] for p in sub[tr]])
    p=np.zeros((len(tr),int(Y.max()+1)));q=p.copy()
    for k in range(3):
        test=fold==k;fit=~test
        small=head(X[fit],Y[fit]);full=head(np.c_[X[fit],e[fit]],Y[fit])
        p[test]=small.predict_proba(X[test]);q[test]=full.predict_proba(np.c_[X[test],e[test]])
    z,lit,tan=gate_inputs(p,seg[tr]);gates=fit_gates(z,lit,tan,nll(p,Y)-nll(q,Y));ts=scores(gates,z,lit,tan)
    small=head(X,Y);full=head(np.c_[X,e],Y)
    test_p=small.predict_proba(a[te]);z,lit,tan=gate_inputs(test_p,seg[te]);ss=scores(gates,z,lit,tan)
    ix=eligible(seg[te]);rows=te[ix];yy=y[rows]
    vectors={'source_index':rows,'target':yy,'segment':seg[rows],'row':d['row'][rows],'cheap_p':test_p[ix]}
    result={}
    for quota in [1,2]:
        for arm,risk in ss.items():
            t=time.perf_counter();threshold=np.quantile(ts[arm],1-quota/4)
            mask=choose(risk,seg[te],quota,threshold,arm=='periodic')[ix]
            checked=rows[mask];prediction=test_p[ix].copy()
            prediction[mask]=full.predict_proba(np.c_[a[checked],read_extra(store,checked,rate)])
            key=arm+str(quota);vectors[key+'_p']=prediction.astype(np.float32);vectors[key+'_mask']=mask
            result[key]={'nll':float(nll(prediction,yy).mean()),'acc':float((prediction.argmax(1)==yy).mean()),'extra_frames':len(checked),'extra_bytes':int(len(checked)*np.prod(store.shape[1:])*store.dtype.itemsize),'incremental_replay_s':time.perf_counter()-t}
    allp=full.predict_proba(np.c_[a[rows],read_extra(store,rows,rate)])
    vectors['full_p']=allp.astype(np.float32)
    for arm,prob in [('cheap',test_p[ix]),('full',allp)]:
        result[arm]={'nll':float(nll(prob,yy).mean()),'acc':float((prob.argmax(1)==yy).mean())}
    result['_meta']={'subject':person,'eligible_frames':len(ix),'frames':len(te),'wall_s':time.monotonic()-started,'frame_bytes':int(np.prod(store.shape[1:])*store.dtype.itemsize)}
    out=base/'results';out.mkdir(exist_ok=True)
    stem=out/f'p{person:02d}'
    tmp=stem.with_suffix('.tmp.npz');np.savez_compressed(tmp,**vectors);tmp.replace(stem.with_suffix('.npz'))
    tmp=stem.with_suffix('.tmp.json');tmp.write_text(json.dumps(result,indent=1));tmp.replace(stem.with_suffix('.json'))
    print(name,person,len(ix),result['_meta']['wall_s'],flush=True)
if __name__=='__main__':run(sys.argv[1],int(sys.argv[2]))
