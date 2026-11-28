"""Actor-held estimates from fixed conditional regime features and two trainable heads."""
import argparse
from hashlib import sha256
import io
import json
import lzma
from pathlib import Path
import sys
import time
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logsumexp, softmax
from scipy.interpolate import RegularGridInterpolator

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"returning_regimes"))
from lattice import solve
ARMS=("returning","irreversible","stationary","disconnected","smooth","lif","raw")
SEEDS=(137,311,557)
INPUT="c74ae69666a2bf58a8147071dd9aa9fd67e00397966640d937634b0f05a16fd2"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def load_data(path):
    if digest(path)!=INPUT:
        raise ValueError("unexpected data")
    with np.load(io.BytesIO(lzma.decompress(path.read_bytes())),allow_pickle=False) as items:
        p=items["nibbles"]
        codes=np.stack((p>>4,p&15),axis=-1).reshape(len(p),4,8)
        features=items["levels"][np.arange(8)[None,None,:],codes].astype(float)
        tr,dev,held = (np.flatnonzero(items["split"]==j) for j in range(3))
        actors = np.asarray([s.split("_")[0] for s in items["ids"]])
        assert len(set(actors[tr]) & set(actors[held]))==0
        assert len(set(actors[dev]) & set(actors[held]))==0
        assert len(set(actors[tr]) & set(actors[dev]))==0
        assert list(map(len,(tr,dev,held)))==[4984,1147,1311]
        features=(features-features[tr].mean((0,1)))/features[tr].std((0,1)).clip(.001)
        return features,items["labels"].astype(int),actors,(tr,dev,held)


def law(arm):
    if arm not in ARMS[:4]:
        return None
    rate_nodes = np.linspace(.05,1.45,15)
    panels=[]
    for h in (rate_nodes[:1] if arm=="stationary" else rate_nodes):
        rates=(0.,0.) if arm=="stationary" else (float(h),0. if arm=="irreversible" else .35)
        panel=solve(steps=32,years=2.,rates=rates,log_half_width=2.,gradients=False)
        panels.append(np.stack((np.full_like(panel.assets,np.log(panel.walls[0])),
                                panel.equity[0],panel.loss[0],panel.hit[0]),-1))
    if arm=="stationary":
        panels=panels*len(rate_nodes)
    return RegularGridInterpolator((rate_nodes,np.log(panel.assets)),np.stack(panels))


def make_features(x,arm,seed,table):
    if arm=="raw":
        return x.reshape(len(x),-1)
    rng=np.random.default_rng(seed)
    width=24
    weights=(rng.normal(size=(8,width))/np.sqrt(8),rng.normal(size=(width,width))/np.sqrt(width))
    biases=rng.uniform(-.3,.3,(2,width))
    state=np.zeros((2,len(x),width))
    output=[]
    for frame in x.transpose((1,0,2)):
        wire=frame
        for layer in range(2):
            drive=wire@weights[layer]+biases[layer]+.5*state[layer]
            value=np.tanh(drive)
            if arm=="smooth":
                trace=np.tanh(drive-.25)
                positive=expit(2*drive)
                negative=expit(-2*drive)
                fourth=negative**2
                state[layer]=.5*trace+.5*value
            elif arm=="lif":
                voltage=.6*state[layer]+wire@weights[layer]+biases[layer]
                spike=(voltage>1.).astype(float)
                trace=voltage-1.
                positive=np.maximum(voltage,0.)
                negative=spike
                fourth=np.maximum(-voltage,0.)
                state[layer]=np.where(spike>0,0.,voltage)
            else:
                h=.05+1.4*expit(drive)
                log_v=np.log(90.)+.32*value
                quotes=table(np.stack((h,log_v),axis=-1))
                trace=log_v-quotes[:,:,0]
                positive=quotes[:,:,1]/20.
                negative=quotes[:,:,2]/10.
                fourth=quotes[:,:,3]
                state[layer]=value+.15*np.tanh(positive-negative)
            wire=np.zeros_like(trace) if arm=="disconnected" else trace
        output.append(np.concatenate((trace, positive, negative, fourth),axis=1))
    return np.concatenate(output,axis=1)


def local_scores(raw,y):
    return logsumexp(raw,axis=1)-raw[np.arange(len(y)),y], (raw.argmax(axis=1)==y)


def pack(a):
    return [[float(x) for x in row] for row in a]


def train_head(X, y, V, v, kind):
    features=X.shape[1]
    freq=np.bincount(y,minlength=72)/len(y)
    target=np.eye(72)[y]
    prior=np.log(freq)
    def consider(current,W,b,tag):
        val=float(np.mean(local_scores(V@W+b,v)[0]))
        return (val, W.copy(), b.copy(), tag) if current is None or val<current[0] else current
    best=None
    if kind=="direct":
        gram=X.T@X/len(y)
        rhs=X.T@(target-freq)/len(y)
        eig,U=np.linalg.eigh(gram)
        rotated=U.T@rhs
        for strength in (.0001,.001,.01,.1,1.,10.):
            W=U@(rotated/(eig[:,None]+strength))
            for scale in (4.,16.,64.,128.,256.):
                best=consider(best,W*scale,prior,(strength,scale))
    else:
        for strength in (.001,.01,.1):
            def objective(params):
                w, b = params[:-72].reshape(features,72), params[-72:]
                scores=X@w+b
                losses=logsumexp(scores,axis=1)-scores[np.arange(len(y)),y]
                diff=(softmax(scores,axis=1)-target)/len(y)
                return (float(losses.mean()+.5*strength*np.vdot(w,w)),
                        np.r_[((X.T@diff)+strength*w).ravel(),diff.sum(axis=0)])
            opt=minimize(objective,np.r_[np.zeros(features*72),prior],jac=True,method="L-BFGS-B",
                         options=dict(maxiter=70,ftol=1e-8,gtol=1e-6,maxcor=5))
            if not opt.success and opt.status!=1:
                raise RuntimeError(opt.message)
            best=consider(best,opt.x[:-72].reshape(features,72),opt.x[-72:],
                          (strength,int(opt.nit),int(opt.status)))
    return best


def fit(data,out):
    start=time.perf_counter()
    x,y,actors,(tr,dev,_)=load_data(data)
    load_seconds=time.perf_counter()-start
    out.mkdir(parents=True,exist_ok=True)
    state={}
    for arm in ARMS:
        before=time.perf_counter()
        table=law(arm)
        table_s=time.perf_counter()-before
        for seed in SEEDS:
            name=f"{arm}-{seed}"
            tick=time.perf_counter()
            both=make_features(x[np.r_[tr,dev]],arm,seed,table)
            X,V=both[:len(tr)],both[len(tr):]
            mean,scale=X.mean(0),X.std(0).clip(.001)
            X,V=(X-mean)/scale,(V-mean)/scale
            common_s=time.perf_counter()-tick+table_s+load_seconds
            for kind in ("direct","cross_entropy"):
                key=f"{name}-{kind}"
                path=out/(key+".npz")
                before=time.perf_counter()
                score,w,b,tag=train_head(X,y[tr],V,y[dev],kind)
                np.savez_compressed(path,w=w,b=b,mean=mean,scale=scale)
                state[key]=dict(model_sha=digest(path),development=score,choice=tag,
                                fit_s=time.perf_counter()-before,common_feature_s=common_s,
                                table_s=table_s)
            print("fit",name,flush=True)
    (out/"seal.json").write_text(json.dumps(state,indent=2)+"\n")


def evaluate(data,out):
    x,y,actors,(tr,_,held)=load_data(data)
    seal=out/"seal.json"
    state=json.loads(seal.read_text())
    assert len(state)==len(ARMS)*len(SEEDS)*2
    for key,details in state.items():
        if digest(out/(key+".npz"))!=details["model_sha"]:
            raise ValueError("weights differ from seal")
    metrics, clips={},{}
    rows=np.arange(len(held))
    prior=np.log(np.bincount(y[tr],minlength=72)/len(tr))
    prior_nll,prior_acc=local_scores(np.tile(prior,(len(held),1)),y[held])
    for arm in ARMS:
        table=law(arm)
        for seed in SEEDS:
            start=time.perf_counter()
            H=make_features(x[held],arm,seed,table)
            features_s=time.perf_counter()-start
            for kind in ("direct","cross_entropy"):
                key=f"{arm}-{seed}-{kind}"
                start=time.perf_counter()
                with np.load(out/(key+".npz")) as model:
                    raw=((H-model["mean"])/model["scale"])@model["w"]+model["b"]
                nll,acc=local_scores(raw,y[held])
                seconds=features_s+time.perf_counter()-start
                per_clip=np.stack((nll,acc.astype(float)))
                clips[key]=per_clip
                z=state[key]
                metrics[key]=dict(nll=float(nll.mean()),top1=float(acc.mean()),dev=z["development"],
                                  charged=z["common_feature_s"]+z["fit_s"]+seconds,
                                  score_s=seconds,gate=bool(z["development"]<=4.1 and nll.mean()<=4.1),
                                  sha256_logits=sha256(raw.tobytes()).hexdigest())
    pool=np.unique(actors[held])
    rng=np.random.default_rng(8127)
    draws=rng.integers(0,len(pool),(4000,len(pool)))
    cluster=(actors[held,None]==pool[None,:]).astype(float)
    counts=cluster.sum(0)[draws].sum(1)
    paired={}
    for rival in ("irreversible","stationary","disconnected","smooth","lif","raw"):
        for kind in ("direct","cross_entropy"):
            d=np.mean([clips[f"returning-{s}-{kind}"]-clips[f"{rival}-{s}-{kind}"] for s in SEEDS],axis=0)
            sums=d@cluster
            paired[f"returning-minus-{rival}-{kind}"]=dict(
                mean=d.mean(1).tolist(),interval=np.quantile(sums[:,draws].sum(2)/counts,[.025,.975],axis=1).T.tolist())
    np.savez_compressed(out/"per_clip.npz",actor=actors[held],label=y[held],**clips)
    results=dict(seal=digest(seal),input_sha256=digest(data),per_clip_sha256=digest(out/"per_clip.npz"),
                 actor_count=len(pool),prior=[float(prior_nll.mean()),float(prior_acc.mean())],
                 results=metrics,paired=paired)
    (out/"terminal.json").write_text(json.dumps(results,indent=2)+"\n")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("stage",choices=("fit","evaluate"))
    parser.add_argument("data",type=Path)
    parser.add_argument("out",type=Path)
    a=parser.parse_args()
    (fit if a.stage=="fit" else evaluate)(a.data,a.out)
