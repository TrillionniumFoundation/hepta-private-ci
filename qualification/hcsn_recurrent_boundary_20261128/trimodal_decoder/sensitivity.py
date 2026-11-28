"""How actor clustering, seed variation and multiple comparisons affect conclusions."""
import argparse
import json
from pathlib import Path
import numpy as np
from data import streams
from train import ARMS,SEEDS


def run(folder):
    j=json.loads((folder/"terminal.json").read_text())
    _,y,(_,_,ix),actor,mod,V,_=streams();y=y[ix].numpy();actor=actor[ix];mod=mod[ix]
    groups=np.unique(actor);results={}
    endpoints=["best"]+sorted({tag for r in j["rows"].values() for tag in r["labels"]})
    for endpoint in endpoints:
        diff=np.zeros((len(SEEDS),len(groups),12));size=np.zeros((len(groups),12));labs=[]
        for k,arm in enumerate(ARMS[1:]):
            for m in range(3):labs.append(f"financial minus {arm}/{j['mode_order'][m]}")
            for si,seed in enumerate(SEEDS):
                def score(arm):
                    if endpoint=="best":key=j["primary"][arm][str(seed)]
                    else:key=next(k for k,v in j["rows"].items() if k.startswith(f"{arm}-{seed}-") and endpoint in v["labels"])
                    with np.load(folder/(key+"-original-test.npz")) as a:return -a["logp"].sum(1,dtype="float64")
                d=score("financial")-score(arm)
                for ai,a in enumerate(groups):
                    for m in range(3):
                        where=(actor==a)&(mod==m)
                        diff[si,ai,3*k+m]=d[where].sum();size[ai,3*k+m]=(y[where]!=-100).sum()
        theta=diff.mean(0).sum(0)/size.sum(0)
        rng=np.random.default_rng(987342)
        actor_weights=rng.multinomial(len(groups),np.ones(len(groups))/len(groups),size=12000)
        seeds=rng.multinomial(len(SEEDS),np.ones(len(SEEDS))/len(SEEDS),size=12000)/len(SEEDS)
        den=actor_weights@size
        ress={}
        for label,sw in (("fixed_three_seeds",np.full_like(seeds,1/len(SEEDS))),("resampled_paired_seeds",seeds)):
            draws=np.einsum("rs,ra,saj->rj",sw,actor_weights,diff,optimize=True)/den
            sd=draws.std(0,ddof=1)
            q=np.quantile(np.max(abs(draws-theta)/np.maximum(sd,1e-15),axis=1),.95)
            ci=np.quantile(draws,[.025,.975],axis=0).T
            adj=np.stack((theta-q*sd,theta+q*sd),1)
            ress[label]=dict(family_size=len(theta),bootstrap_replicates=len(draws),
                             max_standardized_quantile=float(q),comparisons={
                name:dict(norm=float(t),marginal=c.tolist(),simultaneous=ac.tolist(),
                          all_three_seed_means=(diff.sum(1)/size.sum(0))[:,i].tolist())
                for i,(name,t,c,ac) in enumerate(zip(labs,theta,ci,adj))})
        results[endpoint]=ress
    return results
if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("dir",type=Path);s=a.parse_args();r=run(s.dir)
    (s.dir/"sensitivity.json").write_text(json.dumps(r,indent=2)+"\n")
    for key in ("best",):
        for k,v in r[key]["resampled_paired_seeds"]["comparisons"].items():print(k,round(v["norm"],4),[round(x,4) for x in v["simultaneous"]])
