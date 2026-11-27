"""Research-only HCSN P1: honest risk-state counterfactual and strict CPU budget.

A genuinely EXOGENOUS, evolving Markov volatility regime controls a physical
Brownian-bridge first-passage label. Both learned arms receive the SAME
(log-distance, log-absolute-scale, log-time, initial regime) observations.
The proposed Call/Put/Margin/first-hit feature map is entirely deterministic
in those observations, so it supplies NO new Shannon information. Baseline
features are similarly calibrated ordinary smooth functions. At anchor each
first four channels has exactly matched value and signed local slope.

This is a controlled simplified GBM simulation, NOT coupled original HX,
real-world neural task utility, energy evidence, or production authority.
DENY_ALL / NO_GO.
"""
from __future__ import annotations
import hashlib
import json
import math
import time

import numpy as np
from scipy.special import ndtr
import torch

ANCHOR = .35
SIGMAS=(.22,.46)
RATE=.05
PAYOUT=.03
STEPS=12

class Refuse(ValueError):
    pass


def _ensure_rows(x: np.ndarray):
    if not isinstance(x,np.ndarray) or x.ndim!=2 or x.shape[1]!=4:
        raise Refuse('expected [N,4] exogenous initial observations')
    if not np.isfinite(x).all() or not np.all((x[:,0]>.04)&(x[:,0]<1.1)):
        raise Refuse('nonfinite or invalid log-distance')
    if not np.all(np.abs(x[:,1])<=1.) or not np.all((x[:,2]>math.log(.5))&(x[:,2]<math.log(4.1))):
        raise Refuse('invalid log-scale / log-horizon')
    if not np.all((x[:,3]==0)|(x[:,3]==1)):
        raise Refuse('invalid initial exogenous risk state')


def first_hit(m: np.ndarray, t: np.ndarray, sigma: np.ndarray):
    """Constant-regime first hit (feature, not switching-regime oracle)."""
    nu = RATE-PAYOUT-.5*sigma*sigma
    root=sigma*np.sqrt(t)
    a=(-m-nu*t)/root
    b=(-m+nu*t)/root
    e=np.exp(-2*nu*m/(sigma*sigma))
    p=ndtr(a)+e*ndtr(b)
    phi=lambda y:np.exp(-y*y/2)/math.sqrt(2*math.pi)
    d=-phi(a)/root-e*phi(b)/root-2*nu/(sigma*sigma)*e*ndtr(b)
    if not np.isfinite(p).all() or not np.isfinite(d).all() or (p<0).any() or (p>1+1e-12).any():
        raise Refuse('unstable first-hit feature')
    return p,d


def _perpetual(m: np.ndarray,sigma: np.ndarray):
    """Simplified normalized one-shot Call and Put, NOT coupled financial HX."""
    drift=RATE-PAYOUT-.5*sigma*sigma
    disc=np.hypot(drift,np.sqrt(2*RATE*sigma*sigma))
    beta=np.where(drift<0,2*RATE/(disc-drift),(disc+drift)/(sigma*sigma))
    ratio=beta/(1+beta)
    call=ratio*(np.expm1(m)+np.expm1(-beta*m)/beta)
    put=call-np.expm1(m)*ratio - (ratio-1)  # C-P=V/K-1
    dc=ratio*(np.exp(m)-np.exp(-beta*m))
    dp=-ratio*np.exp(-beta*m)
    return call,put,dc,dp


def features(obs: np.ndarray, arm: str):
    """7 nontrainable inputs. Value and d/dm of first 4 at .35 are .35 and +1.

    Baseline gets full exogenous z, time, scale, as does mechanism; transform
    differences cannot establish an independent-information advantage.
    """
    _ensure_rows(obs)
    m,lk,lt,z=obs.T
    if arm not in ('ordinary','call_put_margin_risk'):
        raise Refuse('unknown feature arm')
    t=np.exp(lt)
    sig=np.where(z==0,SIGMAS[0],SIGMAS[1])
    if arm=='ordinary':
        # Same four channels, calibrated in value and signed slope at ANCHOR.
        a=ANCHOR
        h1=m
        h2=a+(np.tanh(m)-math.tanh(a))/(1-math.tanh(a)**2)
        h3=a+(np.arctan(m)-math.atan(a))*(1+a*a)
        h4=a+(m/(1+m)-a/(1+a))*(1+a)**2
        pre=np.stack((h1,h2,h3,h4),axis=1)
    else:
        c,p,dc,dp=_perpetual(m,sig)
        aa=np.full_like(m,ANCHOR)
        ca,pa,dca,dpa=_perpetual(aa,sig)
        q,dq=first_hit(m,t,sig)
        qa,dqa=first_hit(aa,t,sig)
        if (np.abs(dca)<1e-12).any() or (np.abs(dpa)<1e-12).any() or (np.abs(dqa)<1e-8).any():
            raise Refuse('calibration derivative not resolvable')
        pre=np.stack((ANCHOR+(c-ca)/dca,ANCHOR+(p-pa)/dpa,m,
                      ANCHOR+(q-qa)/dqa),axis=1)
    out=np.column_stack((pre,lk,lt,z)).astype(np.float32)
    if out.shape!=(len(obs),7) or not np.isfinite(out).all():
        raise Refuse('invalid calibrated feature map')
    return out


def make_data(seed: int,n: int,ood: bool=False):
    """Initial regime independent of m,K,T, then evolves as 2-state Markov.

    Conditional within-step Brownian-bridge crossing probability accounts for
    hits between sampling endpoints; volatility constant within each segment.
    The simulation is not a reference solution of the *switching* PDE.
    """
    if type(seed) is not int or type(n) is not int or n<1:
        raise Refuse('invalid panel spec')
    rng=np.random.default_rng(seed)
    m=rng.uniform(.06,.95,n)
    lk=rng.uniform(-.6,.6,n)
    T=rng.uniform(2.4,3.7,n) if ood else rng.uniform(.7,1.7,n)
    z0=rng.integers(0,2,n)
    obs=np.column_stack((m,lk,np.log(T),z0.astype(float)))
    alive=np.ones(n,dtype=bool)
    y=np.zeros(n,dtype=np.int8)
    curr=m.copy()
    z=z0.copy()
    dt=T/STEPS
    p01,p10=(.42,.25) if ood else (.28,.13)
    for _ in range(STEPS):
        sigma=np.where(z==0,SIGMAS[0],SIGMAS[1])
        nu=RATE-PAYOUT-.5*sigma*sigma
        nxt=curr+nu*dt+sigma*np.sqrt(dt)*rng.normal(size=n)
        bridge=np.exp(-2*np.maximum(curr,0)*np.maximum(nxt,0)/(sigma*sigma*dt))
        crossed=alive & ((nxt<=0)|((curr>0)&(rng.random(n)<bridge)))
        y[crossed]=1
        alive[crossed]=False
        curr=nxt
        flip=rng.random(n)<np.where(z==0,p01,p10)
        z=np.where(flip,1-z,z)
    _ensure_rows(obs)
    return obs,y


def parameter_count():
    return sum(t.numel() for t in make_model().parameters())


def make_model():
    return torch.nn.Sequential(torch.nn.Linear(7,24),torch.nn.Tanh(),
            torch.nn.Linear(24,16),torch.nn.Tanh(),torch.nn.Linear(16,1))


def warmup_runtime():
    """One shared process-bootstrap warmup, not credited as a trial arm."""
    before=time.process_time()
    torch.set_num_threads(1)
    net=make_model(); opt=torch.optim.Adam(net.parameters(),lr=.012)
    pred=net(torch.zeros((2,7),dtype=torch.float32)).flatten()
    loss=torch.nn.functional.binary_cross_entropy_with_logits(pred,torch.zeros(2))
    opt.zero_grad(set_to_none=True);loss.backward();opt.step()
    return time.process_time()-before


def score(model,obs,y,arm):
    before=time.process_time()
    xx=torch.from_numpy(features(obs,arm))
    with torch.no_grad():
        p=torch.sigmoid(model(xx).flatten()).numpy().astype(np.float64)
    cpu=time.process_time()-before
    brier=float(np.mean((p-y)**2))
    accuracy=float(np.mean((p>=.5)==y))
    nll=float(np.mean(-y*np.log(np.clip(p,1e-7,1))-(1-y)*np.log(np.clip(1-p,1e-7,1))))
    return dict(brier=brier,accuracy=accuracy,nll=nll,inference_cpu_seconds=cpu,prediction=[float(x) for x in p])


def train(seed,arm,train_obs,train_labels,*,budget_seconds):
    if not isinstance(budget_seconds,(float,int)) or not math.isfinite(budget_seconds) or budget_seconds<=0:
        raise Refuse('positive process-CPU budget required')
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    start=time.process_time()
    x=torch.from_numpy(features(train_obs,arm))
    y=torch.from_numpy(train_labels.astype(np.float32))
    model=make_model()
    opt=torch.optim.Adam(model.parameters(),lr=.012)
    gen=torch.Generator().manual_seed(seed+777777)
    updates=0
    last_loss=float('nan')
    # A single CPU thread; no wall-time loophole for training/preprocessing.
    while time.process_time()-start<budget_seconds:
        ix=torch.randint(0,len(x),(128,),generator=gen)
        pred=model(x[ix]).flatten()
        loss=torch.nn.functional.binary_cross_entropy_with_logits(pred,y[ix])
        opt.zero_grad(set_to_none=True)
        loss.backward();opt.step()
        updates+=1
        last_loss=float(loss.detach())
    cpu=time.process_time()-start
    if not updates:
        raise Refuse('process CPU budget consumed before a single optimization step')
    sd={k:v.detach().cpu().numpy().tolist() for k,v in model.state_dict().items()}
    digest=hashlib.sha256(json.dumps(sd,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return model,dict(training_and_feature_cpu_seconds=cpu,updates=updates,final_train_loss=last_loss,
                      model_state_sha256=digest,parameters=parameter_count())


def exact_signflip_p(deltas: list[float]):
    """Exact two-sided paired sign-flip test, finite 2^n enumerated signs."""
    n=len(deltas)
    if n<2 or n>16 or not all(math.isfinite(x) for x in deltas):
        raise Refuse('not enough finite pairs for exact test')
    observed=abs(sum(deltas))
    extremes=0
    for bits in range(1<<n):
        s=sum((1 if bits&(1<<i) else -1)*v for i,v in enumerate(deltas))
        if abs(s)+1e-15>=observed: extremes+=1
    return extremes/(1<<n)
