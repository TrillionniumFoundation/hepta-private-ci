"""Analytic moving-wall and discriminative controls fed only pre-anchor voltage history."""
import argparse
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time
import numpy as np
from scipy.optimize import minimize
from scipy.signal import lfilter
from scipy.special import expit, log_ndtr, ndtr
from sklearn.ensemble import HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from model import boundary
H=np.array([1,2,4,6,8]);TRAIN=(1,4,8);COLD=(2,6);EPS=1e-7
LAW=('fixed','tangent','literal','cubic','logistic')
SPLINE=np.linspace(-1.,1.,1001)
LITERAL=boundary(SPLINE,'literal');LITERAL/=float((LITERAL[501]-LITERAL[499])/(SPLINE[501]-SPLINE[499]))

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def words(dest,v):dest.write_text(json.dumps(v,indent=1,allow_nan=False)+'\n')

def design(data,ids,typ,horizons):
    records=[]
    for sid in ids:
        source=data/(str(sid)+'.npz');rec=json.loads((data/f'{sid}.json').read_text())
        assert sha(source)==rec['npz_sha256']
        with np.load(source) as z:
            noise=np.r_[z['x1_0'],z['x1_1']];c=noise.mean();sd=max(noise.std(),1e-6)
            for rep in range(2):
                tag=f'{typ}_{rep}';x=(z['x'+tag]-c)/sd;y=z['y'+tag].astype(int);v=z['v'+tag].astype(float)
                current=np.clip(x,-8,8);f=[]
                for tau in (6,16,40):
                    a=np.exp(-2./tau);f.append(lfilter([1-a],[1,-a],current))
                u=np.tanh(.5*current+.35*f[0]+.15*f[1])
                count=np.r_[0,np.cumsum(y)];initial=np.arange(100,len(v)-8,5)
                i=initial[(v[initial]<-25)&(count[initial]-count[initial-2]==0)]
                hist=np.column_stack((np.ones(len(i)),np.clip((v[i]+55)/15,-5,5),np.clip((v[i]-v[i-1])/8,-5,5),np.clip((v[i]-v[i-3])/15,-5,5),
                     u[i-1],np.tanh(f[1][i-1]),np.tanh(f[2][i-1]),
                     np.minimum(3,count[i]-count[i-15]),np.minimum(5,count[i]-count[i-40])))
                for h in horizons:
                    fut=np.stack([u[i+j] for j in range(h)],1)
                    command=np.column_stack([fut.mean(1),fut.max(1),fut.min(1),fut[:,-1]-u[i-1]])
                    drift=np.column_stack([hist,command])
                    labels=count[i+h]-count[i]>0
                    records.append(dict(sid=sid,rep=rep,h=h,anchor=i,total_candidates=len(initial),u=hist,d=drift,
                             b0=u[i-1],b1=fut[:,-1],target=labels.astype(float)))
    return records

def pack(records):
    fields=('u','d','b0','b1','target')
    x={k:np.concatenate([r[k] for r in records]) for k in fields}
    x['weight']=np.concatenate([np.full(len(r['target']),1./(len(r['target'])*len(records))) for r in records])
    x['time']=np.concatenate([np.full(len(r['target']),r['h']/8.) for r in records])
    return x

def components(x,name):
    def bform(v):
        if name=='fixed':return np.empty((len(v),0))
        if name=='tangent':return v[:,None]
        if name=='literal':return np.interp(v,SPLINE,LITERAL)[:,None]
        if name=='cubic':return np.column_stack([v,v*v,v**3])
        raise ValueError(name)
    return bform(x['b0']), bform(x['b1'])

def plain(x):
    d=x['d'][:,1:];logt=np.log(x['time'])
    return np.column_stack([np.ones(len(d)),d,d*d,np.tanh(d),logt,logt*logt,d*logt[:,None],x['b0'],x['b1']])

def prep(x,name):
    if name=='logistic':
        m=plain(x);return (m,)
    b0,b1=components(x,name);t=x['time'];return x['u'],x['d'],b0,(b1-b0)/t[:,None],np.sqrt(t)

def pred_grad(params,arr,name):
    if name=='logistic':
        eta=arr[0]@params;f=expit(eta)
        return f,lambda coeff: arr[0].T@(coeff*f*(1-f))
    u,d,b0,slope,rt=arr;nu=u.shape[1];nd=d.shape[1]
    gain=params[nu+nd:]
    eta=u@params[:nu]-b0@gain
    start=np.logaddexp(0,eta)+.005
    drift=d@params[nu:nu+nd]-slope@gain
    a=-start/rt-drift*rt;c=-start/rt+drift*rt
    log_image=-2*start*drift+log_ndtr(c);image=np.exp(np.minimum(0,log_image))
    raw=ndtr(a)+image
    f=np.minimum(1,np.maximum(0,raw));p=EPS+(1-2*EPS)*f
    du=(-2*np.exp(-.5*a*a)/(np.sqrt(2*np.pi)*rt)-2*drift*image)*expit(eta)
    dv=-2*start*image
    def gradient(coeff):
        scaled=(1-2*EPS)*coeff
        aa=scaled*du;dd=scaled*dv
        return np.r_[u.T@aa,d.T@dd,-b0.T@aa-slope.T@dd]
    return p,gradient

def fit_one(x,name,penalty):
    arr=prep(x,name)
    if name=='logistic':
        init=np.zeros(arr[0].shape[1]);init[0]=np.log(.1/.9)
        reg=np.ones(len(init));reg[0]=0
    else:
        nu=x['u'].shape[1];nd=x['d'].shape[1];ng=arr[2].shape[1]
        init=np.zeros(nu+nd+ng);init[0]=1.
        reg=np.ones(len(init));reg[0]=reg[nu]=0
    y=x['target'];weights=x['weight']
    def objective(v):
        p,g=pred_grad(v,arr,name);p=np.clip(p,1e-12,1-1e-12)
        value=weights@(-y*np.log(p)-(1-y)*np.log1p(-p))+.5*penalty*(reg*v)@v
        return value,g(weights*(p-y)/(p*(1-p)))+penalty*reg*v
    c=init.copy();c+=np.random.default_rng(855943).normal(0,.05,len(c));step=1e-5
    delta=np.random.default_rng(855944).normal(size=len(c));delta/=np.linalg.norm(delta)
    j=objective(c)[1]@delta;fd=(objective(c+step*delta)[0]-objective(c-step*delta)[0])/(2*step)
    if abs(j-fd)>1e-5:raise ArithmeticError(('gradient',name,j,fd))
    bounds=[(-8.,8.)]*len(init)
    if name!='logistic' and ng:bounds[-ng:]=[(-2.,2.)]*ng
    then=time.monotonic()
    result=minimize(objective,init,jac=True,method='L-BFGS-B',bounds=bounds,options={'maxiter':400,'ftol':1e-11,'gtol':1e-6,'maxls':35})
    if not np.isfinite(result.x).all():raise ArithmeticError('nonfinite')
    return dict(params=result.x.tolist(),finite_difference_directional_error=float(abs(j-fd)),success=bool(result.success),status=str(result.message),
        iterations=int(result.nit),train_obj=float(result.fun),sec=time.monotonic()-then,penalty=penalty)

def fp_pred(x,name,model):
    return pred_grad(np.asarray(model['params']),prep(x,name),name)[0].astype(np.float32)
def score(p,y):
    p=np.clip(p.astype(float),EPS,1-EPS);return np.column_stack([-y*np.log(p)-(1-y)*np.log1p(-p),(y-p)**2])
def macro(x,p):return (score(p,x['target'])*x['weight'][:,None]).sum(0)
def train(data,out):
    out.mkdir(parents=True,exist_ok=True);roster=json.loads((data/'roster.json').read_text());ids=roster['cells'];assert len(ids)==24
    training=pack(design(data,ids[:12],'1',TRAIN));development=pack(design(data,ids[12:16],'1',TRAIN));fitted={};trials={}
    for name in LAW:
        starts=time.monotonic(); choices=[]
        for pen in (.001,.01):
            model=fit_one(training,name,pen);p=fp_pred(development,name,model)
            model['validation']=macro(development,p).tolist();choices.append(model)
        selected=min(choices,key=lambda m:m['validation'][0]);fitted[name]=selected;trials[name]=choices
        print(name,selected['validation'],selected['success'],round(time.monotonic()-starts,2),flush=True)
    then=time.monotonic()
    boosted=HistGradientBoostingClassifier(max_leaf_nodes=15,min_samples_leaf=60,max_iter=160,learning_rate=.08,random_state=855942,early_stopping=False)
    boosted.fit(plain(training),training['target'],sample_weight=training['weight']*len(training['weight']))
    pred=boosted.predict_proba(plain(development))[:,1].astype(np.float32)
    with (out/'boost.pkl').open('wb') as dst:pickle.dump(boosted,dst,protocol=5)
    model=dict(ids=ids,roster_sha=sha(data/'roster.json'),source_sha256={str(i):sha(data/f'{i}.npz') for i in ids},fitted=fitted,trials=trials,
               boost=dict(sha256=sha(out/'boost.pkl'),validation=macro(development,pred).tolist(),train_and_validate_sec=time.monotonic()-then))
    words(out/'SEAL.json',model)
    print('boost',model['boost'],flush=True)

def cold(data,fit,out):
    out.mkdir(parents=True,exist_ok=True);m=json.loads((fit/'SEAL.json').read_text());ids=m['ids'][16:]
    assert sha(data/'roster.json')==m['roster_sha'] and sha(fit/'boost.pkl')==m['boost']['sha256']
    for i in ids:assert sha(data/f'{i}.npz')==m['source_sha256'][str(i)]
    with (fit/'boost.pkl').open('rb') as src:boost=pickle.load(src)
    rng=np.random.default_rng(855941);sample=rng.integers(0,8,(10000,8))
    results={};names=list(LAW)+['boost']
    for typ in ('1','2'):
        rows=design(data,ids,typ,COLD);scores={n:{} for n in names};audit=[]
        for row in rows:
            begin=time.monotonic();x=pack([row]);sid=row['sid'];rep=row['rep'];h=row['h']
            probs={n:fp_pred(x,n,m['fitted'][n]) for n in LAW};probs['boost']=boost.predict_proba(plain(x))[:,1].astype(np.float32)
            for n,p in probs.items():scores[n].setdefault(sid,[]).append(macro(x,p))
            audit.append({'sid':sid,'rep':rep,'h':h,'n':len(row['target']),'events':int(row['target'].sum()),'candidate_count':row['total_candidates'],'all_inference_s':time.monotonic()-begin})
            np.savez_compressed(out/f'{sid}_{typ}_{rep}_{h}.npz',anchors=row['anchor'].astype(np.int32),y=row['target'].astype(np.uint8),**probs)
        arrays={n:np.stack([np.mean(scores[n][sid],axis=0) for sid in ids]) for n in names}
        delta={n:arrays['literal']-arr for n,arr in arrays.items() if n!='literal'}
        contrasts={n:{'mean':v.mean(0).tolist(),'ci95':np.quantile(v[sample].mean(1),[.025,.975],axis=0).tolist(),'wins':int((v[:,0]<0).sum())} for n,v in delta.items()}
        results[typ]=dict(averages={n:v.mean(0).tolist() for n,v in arrays.items()},individual={n:dict(zip(map(str,ids),v.tolist())) for n,v in arrays.items()},
                          contrast=contrasts,audit=audit,gate=all(s['ci95'][1][0]<0 and s['mean'][1]<0 for s in contrasts.values()))
    words(out/'results.json',dict(seal_sha=sha(fit/'SEAL.json'),by_waveform=results));print({n:v['averages'] for n,v in results.items()},flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=('fit','cold'));p.add_argument('--data',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path);p.add_argument('--fit',type=Path)
    a=p.parse_args()
    with threadpool_limits(limits=1):
        if a.phase=='fit':train(a.data,a.out)
        else:cold(a.data,a.fit,a.out)
