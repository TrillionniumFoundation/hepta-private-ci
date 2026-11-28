"""Six stationary probes to identify the four monetary/recovery coefficients."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from scipy.integrate import solve_ivp

sys.path.append(str(Path(__file__).resolve().parents[1]/"contract_inverse"))
from contract_inverse import Probe, Surface

PILOT = [(0.84,.12),(1.16,.12)]
OPTIONS = [(s,x) for s in (.72,.84,1.,1.16,1.28) for x in (.02,.10,.24,.42)]
FIXED = [0,16,3,19]
TEST_SCALE = np.array([.77,.93,1.07,1.23,1.])
TEST_X = np.array([.05,.19,.35,.50])
CENTER = np.array([6.,62.5,.55,.275])
# The estimator uses wider bounds than either population.
LOW = np.array([.1,5.,.01,.001])
HIGH = np.array([25.,250.,.99,.90])
METHODS = ["fixed_spread","pooled_D","rate_preplanned_D","adaptive_D"]


def population(rng, n):
    # C,P,recovery,tax and independently sampled known physical inputs.
    bounds = np.array([[3.5,8.5],[40.,85.],[.35,.75],[.15,.4],
                       [.05,.10],[.011,.035],[.18,.32],[.75,1.6],[.001,.04]])
    return rng.uniform(bounds[:,0],bounds[:,1],(n,9))


def noise_scale(values):
    return .02+.002*np.abs(values)


class Law:
    def __init__(self, surface, points):
        self.surface = surface
        probes = [Probe.at(surface,x) for _,x in points]
        self.a,self.g,self.eta,self.d0 = (getattr(probes[0],key) for key in ("a","g","eta","d0"))
        self.scales = np.array([s for s,_ in points])
        self.h = np.array([p.h for p in probes])
        self.j = np.array([p.hit_discounted for p in probes])

    def evaluate(self, theta, indices, need_jac=False):
        # A batched matrix of indices permits each replicate its own experiment.
        c,p,alpha,tax = [theta[:,i,None] for i in range(4)]
        m = self.surface.maturity
        q = self.surface.rate+self.surface.premium
        d = self.d0+alpha*self.g/m
        a,g = self.a,self.g
        s,h,j = self.scales[indices],self.h[indices],self.j[indices]
        b = ((1-tax)*c/self.eta+(a*s*p+(g-a)*c/q)/m)/d
        loss = (h*s*p+(j-h)*c/q-j*alpha*b)/m
        out = np.stack([b,loss],axis=-1)
        if not need_jac:
            return out
        db = np.stack(np.broadcast_arrays(((1-tax)/self.eta+(g-a)/(m*q))/d,
                                         a*s/(m*d), -b*g/(m*d), -c/(self.eta*d)),-1)
        dlo = np.stack(np.broadcast_arrays((j-h)/q,h*s,-j*b,np.zeros_like(b)),-1)
        dlo = (dlo-j[...,None]*alpha[...,None]*db)/m
        return out,np.stack((db,dlo),axis=-2)

    def information(self, theta, indices):
        pred,j = self.evaluate(theta,indices,True)
        j = (j/noise_scale(pred)[...,None])*CENTER
        return j.swapaxes(-1,-2)@j

    def fit(self, ids, obs, start):
        theta = start.copy()
        repeats = len(theta)
        for _ in range(10):
            pred, jac = self.evaluate(theta,ids,True)
            weights = 1/noise_scale(pred)
            residual = ((obs-pred)*weights).reshape(repeats,-1)
            jac = ((jac*weights[...,None])*CENTER).reshape(repeats,-1,4)
            normal = jac.swapaxes(-1,-2)@jac
            rhs = (jac.swapaxes(-1,-2)@residual[...,None])
            update = np.linalg.solve(normal+1e-9*np.eye(4),rhs)[...,0]*CENTER
            if np.max(np.abs(update)/CENTER) < 2e-10:
                break
            current = np.sum(residual**2,axis=1)
            winner = theta.copy()
            for fraction in (1.,.5,.25,.125):
                proposal = np.clip(theta+fraction*update,LOW,HIGH)
                score = np.sum(((self.evaluate(proposal,ids)-obs)*weights)**2,axis=(1,2))
                accept = score < current
                current = np.where(accept,score,current)
                winner[accept] = proposal[accept]
            if np.max(np.abs(winner-theta)/CENTER)<1e-11:
                break
            theta = winner
        return theta


def all_ids(n):
    return np.tile(np.arange(len(OPTIONS)+len(PILOT)), (n,1))


def select_action(law, theta, past, *, pooled=False):
    info = law.information(theta,all_ids(len(theta)))
    return select_info(info,past,pooled=pooled)


def select_info(info,past,*,pooled=False):
    repeats = len(past)
    current = info[np.arange(repeats)[:,None],past].sum(axis=1)
    matrices = current[:,None]+info[:,len(PILOT):]
    sign,score = np.linalg.slogdet(matrices)
    if np.min(sign)<=0:
        raise ArithmeticError("singular candidate information")
    if pooled:
        return int(np.argmax(np.mean(score,axis=0)))+len(PILOT)
    return np.argmax(score,axis=1)+len(PILOT)


def freeze(output):
    t0 = time.perf_counter()
    contracts = population(np.random.default_rng(84732),32)
    info = []
    for row in contracts:
        theta = row[:4][None,:]
        law = Law(Surface(*row[4:]),PILOT+OPTIONS)
        info.append(law.information(theta,all_ids(1))[0])
    past = np.tile(np.arange(len(PILOT)),(len(info),1))
    for _ in range(4):
        selected = select_info(np.array(info),past,pooled=True)
        past = np.column_stack([past,np.full(len(info),selected)])
    item = dict(probes=(PILOT+OPTIONS),pooled_ids=past[0].tolist(),dev_contracts=32,
                seed=84732,code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                protocol_sha256=hashlib.sha256(Path(__file__).with_name("PROTOCOL.md").read_bytes()).hexdigest(),
                pooled_development_cpu_wall_seconds=time.perf_counter()-t0)
    output.write_text(json.dumps(item,indent=2)+"\n")
    print(item)


def equity_basis(surface, hit):
    # The source in (r-L)E is linear in B,H,Y/m,sP/m,alpha B/m.
    s = surface
    q = s.rate+s.premium
    discount = np.exp(-q*s.maturity)
    mu = s.rate-s.payout-s.sigma**2/2
    def rhs(x, state):
        y,dy = state.reshape(2,5)
        f = hit(x,s.maturity,mu,s.sigma)
        g = hit(x,s.maturity,mu,s.sigma,q)
        src = np.array([s.payout*np.exp(x),-1.,1-discount*(1-f)-g,discount*(1-f)-1,g])
        return np.r_[dy,2*(s.rate*y-mu*dy-src)/s.sigma**2]
    sol = solve_ivp(rhs,(0.,TEST_X[-1]),np.zeros(10),t_eval=TEST_X,
                    method="DOP853",rtol=3e-12,atol=2e-13)
    if not sol.success:
        raise RuntimeError(sol.message)
    return sol.y[:5].T


def predictions(law, theta, basis):
    n = len(theta)
    idx = np.tile(np.arange(len(TEST_SCALE)*len(TEST_X)),(n,1))
    bl = law.evaluate(theta, idx).reshape(n,len(TEST_SCALE),len(TEST_X),2)
    b = bl[:,:,0,0]
    c,p,alpha,tax = [theta[:,i,None] for i in range(4)]
    m,q = law.surface.maturity, law.surface.rate+law.surface.premium
    coeff = np.stack(np.broadcast_arrays(b,(1-tax)*c,c/(q*m),p*TEST_SCALE/m,alpha*b/m),-1)
    e = coeff@basis.T
    return np.concatenate((bl,e[...,None]),-1)


def holdout(seal, output, ref):
    if seal["code_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError("code changed since development selection")
    if seal["protocol_sha256"] != hashlib.sha256(Path(__file__).with_name("PROTOCOL.md").read_bytes()).hexdigest():
        raise ValueError("protocol changed since development selection")
    sys.path.insert(0,str(ref))
    from hx_reference import hit
    rng = np.random.default_rng(84733)
    contracts = population(rng,128)
    n = 12
    shape = (len(contracts),len(METHODS),n)
    scores = np.empty((*shape,3))
    estimates = np.empty((*shape,4))
    purchases = np.zeros((*shape,6),dtype=int)
    raw = np.empty((*shape,6,2))
    clocks = np.zeros((len(contracts),len(METHODS)))
    eye = np.arange(n)
    for i,row in enumerate(contracts):
        truth = row[:4][None,:]
        surface = Surface(*row[4:])
        law = Law(surface,PILOT+OPTIONS)
        score_law = Law(surface,[(s,x) for s in TEST_SCALE for x in TEST_X])
        basis = equity_basis(surface,hit)
        prices = predictions(score_law,truth,basis)
        possible = law.evaluate(truth,all_ids(1))[0]
        noise = rng.normal(size=(n,6,2))
        for method_id,method in enumerate(METHODS):
            t0 = time.perf_counter()
            ids = np.tile([0,1],(n,1))
            theta = np.tile(CENTER,(n,1))
            obs = possible[ids]+noise_scale(possible[ids])*noise[:,:2]
            preplan_info = None
            if method == "rate_preplanned_D":
                preplan_info = law.information(CENTER[None,:], all_ids(1))
            for slot in range(2,6):
                if method == "fixed_spread":
                    new = np.full(n,FIXED[slot-2]+2)
                elif method == "pooled_D":
                    new = np.full(n,seal["pooled_ids"][slot])
                elif method == "rate_preplanned_D":
                    new = np.full(n,select_info(preplan_info,ids[:1])[0])
                else:
                    theta = law.fit(ids,obs,theta)
                    new = select_action(law,theta,ids)
                ids = np.column_stack([ids,new])
                added = possible[new]+noise_scale(possible[new])*noise[:,slot]
                obs = np.concatenate((obs,added[:,None]),axis=1)
            # Every arm uses the same final estimator and initialization.
            z = law.fit(ids,obs,np.tile(CENTER,(n,1)))
            clocks[i,method_id] = time.perf_counter()-t0
            diff = abs(predictions(score_law,z,basis)-prices)
            scores[i,method_id,:,0] = np.max(diff[:,:-1],axis=(1,2,3))/truth[0,1]
            scores[i,method_id,:,1] = np.max(diff[:,-1],axis=(1,2))/truth[0,1]
            scores[i,method_id,:,2] = np.max(abs(z/truth-1),axis=1)
            estimates[i,method_id]=z
            purchases[i,method_id]=ids
            raw[i,method_id]=obs
    np.savez_compressed(output.with_name("held_measurements.npz"),contracts=contracts,scores=scores,
                        estimates=estimates,design_ids=purchases,raw=raw)
    names = ["off_design_max_dollar_error_over_P","nominal_max_dollar_error_over_P","parameter_max_relative"]
    boot = np.random.default_rng(84734).integers(0,128,(2000,128))
    metrics,comparisons = {},{}
    for mid,method in enumerate(METHODS):
        z = scores[:,mid]
        metrics[method] = {name:dict(mean=float(z[:,:,j].mean()),p95=float(np.quantile(z[:,:,j],.95)))
                           for j,name in enumerate(names)}
        metrics[method]["full_decision_and_fit_wall_seconds"]=float(clocks[:,mid].sum())
        metrics[method]["optional_probe_counts"]={str(i):int(v) for i,v in Counter(purchases[:,mid,:,2:].ravel()).items()}
        metrics[method]["fits_touching_bound"]=int(np.any((estimates[:,mid]<=LOW+1e-6)|(estimates[:,mid]>=HIGH-1e-6),axis=-1).sum())
        for alt in range(mid):
            delta=(z-scores[:,alt]).mean(axis=1)
            differences = delta[boot].mean(axis=1)
            comparisons[method+" minus "+METHODS[alt]] = {name:dict(
                mean=float(delta[:,j].mean()),ci95=np.quantile(differences[:,j],[.025,.975]).tolist())
                for j,name in enumerate(names)}
    result=dict(seal=seal,contracts=128,replicates=12,methods=METHODS,probe_order=PILOT+OPTIONS,
                metric_order=names,metrics=metrics,paired=comparisons,
                archive_sha256=hashlib.sha256(output.with_name("held_measurements.npz").read_bytes()).hexdigest(),
                first_passage_reference_sha256=hashlib.sha256((ref/"hx_reference.py").read_bytes()).hexdigest())
    output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"metrics":metrics,"paired":comparisons},indent=1))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["freeze","holdout"])
    parser.add_argument("seal",type=Path)
    parser.add_argument("--ref",type=Path)
    parser.add_argument("--output",type=Path)
    a=parser.parse_args()
    if a.action=="freeze":
        freeze(a.seal)
    else:
        holdout(json.loads(a.seal.read_text()),a.output,a.ref)
