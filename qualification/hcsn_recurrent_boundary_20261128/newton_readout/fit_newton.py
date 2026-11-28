"""One closed multiclass Newton write and finite full-batch refinements on frozen keys."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax,logsumexp

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/"returning_encoder"))
from fit import load_data, law, make_features, digest, local_scores, SEEDS
ARMS=("returning","raw","smooth")
METHODS=("kronecker","majorizer","diagonal","five_kronecker","five_diagonal","converged")
LAM=(.0001,.0003,.001,.003,.01,.03)
STEP=(.125,.25,.5,1.,2.)
DATA=ROOT.parent/"returning_encoder"/"evidence"/"all.xz"


def regression(X,y,V,labels,kind):
    n,d=X.shape
    k=72
    target=np.eye(k)[y]
    freq=target.mean(0)
    b0=np.log(freq)
    regularized_bias=False
    best=None
    def select(loss,w,b,choice,extra=None):
        nonlocal best
        if best is None or loss<best[0]:
            best=(loss,w.copy(),b.copy(),choice,{} if extra is None else extra)
    if kind=="converged":
        rows=[]
        for lam in (.001,.01,.1):
            def obj(wb):
                w,b=wb[:-k].reshape(d,k),wb[-k:]
                z=X@w+b
                p=softmax(z,1)-target
                return float(local_scores(z,y)[0].mean()+.5*lam*np.vdot(w,w)),np.r_[((X.T@p)/n+lam*w).ravel(),p.mean(0)]
            fit=minimize(obj,np.r_[np.zeros(d*k),b0],jac=True,method="L-BFGS-B",
                         options=dict(maxiter=350,ftol=1e-11,gtol=1e-7,maxcor=10))
            if fit.status not in (0,1):
                raise RuntimeError(fit.message)
            w,b=fit.x[:-k].reshape(d,k),fit.x[-k:]
            record=dict(lam=lam,steps=int(fit.nit),status=int(fit.status),max_abs_grad=float(abs(fit.jac).max()),
                        objective=float(fit.fun))
            rows.append(record)
            select(float(local_scores(V@w+b,labels)[0].mean()),w,b,[lam],record)
        return best,rows
    eig,U=np.linalg.eigh(X.T@X/n)
    eig=np.maximum(0.,eig)
    XU,VU=X@U,V@U
    c_at_start=np.diag(freq)-np.outer(freq,freq)
    def class_basis(prob):
        if kind=="majorizer":
            return .5*np.ones(k),np.eye(k)
        if prob is None:
            covariance=c_at_start
        else:
            covariance=np.diag(prob.mean(0))-prob.T@prob/n
        if "diagonal" in kind:
            return covariance.diagonal(),np.eye(k)
        s,v=np.linalg.eigh(covariance)
        return np.maximum(s,0.),v
    def direction(gw,gb,e,v,lam):
        dw=((-gw@v)/(eig[:,None]*e[None,:]+lam))@v.T
        db=((-gb@v)*np.divide(1.,e,out=np.zeros_like(e),where=e>1e-10))@v.T
        return dw,db-db.mean()
    def objective(w,b,lam):
        return local_scores(XU@w+b,y)[0].mean()+.5*lam*np.vdot(w,w)
    e,v=class_basis(None)
    gw=XU.T@(freq-target)/n
    for lam in LAM:
        dw,db=direction(gw,np.zeros(k),e,v,lam)
        if not kind.startswith("five_"):
            zz=VU@dw
            for eta in STEP:
                select(float(local_scores(b0+eta*zz,labels)[0].mean()),eta*(U@dw),b0,[lam,eta])
            continue
        # Initialize at a development-selected one-write step for this lambda.
        init=min(STEP,key=lambda s:local_scores(VU@(s*dw)+b0,labels)[0].mean())
        w,b=init*dw,b0.copy()
        objectives=[float(objective(w,b,lam))]
        accepted=[]
        for _ in range(4):
            p=softmax(XU@w+b,axis=1)
            g_w=XU.T@(p-target)/n+lam*w
            g_b=(p-target).mean(0)
            eig2,v2=class_basis(p)
            delta,intercept=direction(g_w,g_b,eig2,v2,lam)
            directional=np.vdot(delta,g_w)+intercept@g_b
            if directional>=0:
                break
            baseline=objectives[-1]
            for power in range(18):
                eta=2.**(-power)
                wt,bt=w+eta*delta,b+eta*intercept
                obj=float(objective(wt,bt,lam))
                if obj<=baseline+.0001*eta*directional:
                    w,b=wt,bt
                    objectives.append(obj)
                    accepted.append(eta)
                    break
            else:break
        select(float(local_scores(VU@w+b,labels)[0].mean()),U@w,b,[lam,init],dict(accepted=accepted,objective=objectives))
    return best,[]


def analytical_check():
    r=np.random.default_rng(1792)
    X=r.normal(size=(120,9))
    X-=X.mean(0)
    y=r.choice(5,120,p=(.42,.25,.19,.08,.06))
    Y=np.eye(5)[y]
    freq=Y.mean(0)
    cov=np.diag(freq)-np.outer(freq,freq)
    gram=X.T@X/len(X)
    lam=.01
    rhs=X.T@(Y-freq)/len(X)
    eig,U=np.linalg.eigh(gram)
    s,V=np.linalg.eigh(cov)
    wrote=U@((U.T@rhs@V)/(eig[:,None]*s+lam))@V.T
    delta=r.normal(size=wrote.shape)
    def gradient(w):
        p=softmax(X@w+np.log(freq),1)
        return X.T@(p-Y)/len(y)+lam*w
    eps=2e-6
    hv=(gradient(delta*eps)-gradient(-delta*eps))/(2*eps)
    independent_hessian=np.max(abs(hv-(gram@delta@cov+lam*delta)))
    local=np.max(abs(gram@wrote@cov+lam*wrote-rhs))
    global_grad=float(abs(gradient(wrote)).max())
    assert independent_hessian<1e-8 and local<1e-12 and global_grad>1e-3
    return dict(hessian_vector_error=float(independent_hessian),quadratic_solve_error=float(local),
                original_objective_grad_after_full_step=global_grad)


def run_fit(out):
    out.mkdir(exist_ok=True,parents=True)
    start=time.perf_counter()
    x,y,a,(tr,dev,held)=load_data(DATA)
    data_s=time.perf_counter()-start
    seal={}
    for arm in ARMS:
        t=time.perf_counter()
        table=law(arm)
        table_s=time.perf_counter()-t
        for seed in SEEDS:
            t=time.perf_counter()
            both=make_features(x[np.r_[tr,dev]],arm,seed,table)
            X,V=both[:len(tr)],both[len(tr):]
            mu,sd=X.mean(0),X.std(0).clip(.001)
            X,V=(X-mu)/sd,(V-mu)/sd
            common=time.perf_counter()-t+table_s+data_s
            for method in METHODS:
                t=time.perf_counter()
                (loss,w,b,choice,details),fits=regression(X,y[tr],V,y[dev],method)
                key=f"{arm}-{seed}-{method}"
                path=out/(key+".npz")
                np.savez_compressed(path,w=w,b=b,mean=mu,scale=sd)
                seal[key]=dict(sha=digest(path),dev=loss,choice=choice,fit_s=time.perf_counter()-t,
                               common_s=common,details=details,candidates=fits)
            print("fit",arm,seed,flush=True)
    (out/"seal.json").write_text(json.dumps(seal,indent=2)+"\n")
    (out/"analytic_check.json").write_text(json.dumps(analytical_check(),indent=2)+"\n")


def test(out):
    x,y,a,(_,_,held)=load_data(DATA)
    seals=json.loads((out/"seal.json").read_text())
    assert len(seals)==len(ARMS)*len(SEEDS)*len(METHODS)
    for name,row in seals.items():
        assert digest(out/(name+".npz"))==row["sha"]
    state={}
    clipped={}
    for arm in ARMS:
        table=law(arm)
        for seed in SEEDS:
            t=time.perf_counter()
            H=make_features(x[held],arm,seed,table)
            feature_cost=time.perf_counter()-t
            for method in METHODS:
                key=f"{arm}-{seed}-{method}"
                t=time.perf_counter()
                with np.load(out/(key+".npz")) as z:
                    scores=((H-z["mean"])/z["scale"])@z["w"]+z["b"]
                loss,correct=local_scores(scores,y[held])
                elapsed=time.perf_counter()-t+feature_cost
                row=seals[key]
                state[key]=dict(nll=float(loss.mean()),top1=float(correct.mean()),dev=row["dev"],
                                cost=row["common_s"]+row["fit_s"]+elapsed,held_s=elapsed,
                                score_sha=sha256(scores.tobytes()).hexdigest(),
                                gates={str(g):bool(loss.mean()<=g and row["dev"]<=g) for g in (4.1,3.75)})
                clipped[key]=np.stack((loss,correct))
    np.savez_compressed(out/"per_clip.npz",actor=a[held],label=y[held],**clipped)
    rng=np.random.default_rng(2531)
    groups=[np.where(a[held]==t)[0] for t in np.unique(a[held])]
    draws=rng.integers(0,len(groups),(4000,len(groups)))
    counts=np.array(list(map(len,groups)))[draws].sum(1)
    contrast={}
    for arm in ARMS:
        for method in METHODS[:-1]:
            dif=np.mean([clipped[f"{arm}-{s}-{method}"]-clipped[f"{arm}-{s}-converged"] for s in SEEDS],0)
            sums=np.stack([dif[:,g].sum(1) for g in groups],axis=1)
            contrast[f"{arm}-{method}-minus-lbfgs350"]=dict(mean=dif.mean(1).tolist(),
                                    interval=np.quantile(sums[:,draws].sum(2)/counts,[.025,.975],axis=1).T.tolist())
    (out/"terminal.json").write_text(json.dumps(dict(results=state,paired=contrast,
        seal_sha=digest(out/"seal.json"),loss_sha=digest(out/"per_clip.npz")),indent=2)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("stage",choices=("fit","test"))
    p.add_argument("out",type=Path)
    args=p.parse_args()
    (run_fit if args.stage=="fit" else test)(args.out)
