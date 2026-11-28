"""Run locked stochastic neurons autonomously and evaluate their generated counts and onsets."""
import ctypes
import json
import math
from pathlib import Path

import numpy as np

from forecast import DT, ROOT, Model, put, sha
from independent_held import filtered

NAMES = ("dual", "no_price", "lif", "glm")
M = 256


def distribution_score(draws, outcome):
    """Unbiased Monte Carlo CRPS from an ensemble of independent draws."""
    n = len(draws)
    pair = np.dot(2*np.arange(n)-n+1, np.sort(draws.reshape(-1)))/(n*(n-1))
    return float(np.mean(np.abs(draws-outcome)) - pair)


def run():
    cohort = json.loads((ROOT/"source/cohort.json").read_text())
    models = json.loads((ROOT/"results/seal.json").read_text())["models"]
    out = ROOT/"generative"
    out.mkdir(exist_ok=True)
    data = Model(ROOT/"source", ROOT/"law4.npz")
    f = ctypes.CDLL(str(ROOT/"generative.so")).sample
    F=np.ctypeslib.ndpointer(dtype=np.float64,flags="C_CONTIGUOUS")
    I=np.ctypeslib.ndpointer(dtype=np.int32,flags="C_CONTIGUOUS")
    f.argtypes=[ctypes.c_int]*3+[F]*10+[ctypes.c_double,F,I,I,F]
    f.restype=ctypes.c_int
    proof = {}
    score = {}
    records = []
    err = 0.
    for sid, sw, x, y in data.traces(cohort["held"]):
        rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([950185,sid,sw])))
        n=len(y)
        u=rng.random((M,n))
        target_count=int(y.sum())
        first=np.flatnonzero(y)
        target_time=DT*(first[0]+1) if len(first) else DT*n
        arrays={}
        row=dict(specimen=sid,sweep=sw,observed_count=target_count,observed_first_or_end_s=target_time,observed_silent=not len(first))
        for k,arm in enumerate(NAMES):
            reg=models[arm]["selected"]
            slope=np.asarray(reg["weights"][1:])/np.asarray(reg["sd"])
            base=np.full(n,reg["weights"][0]-np.dot(slope,reg["mean"]))
            if arm=="glm":
                cur=x/100.
                base+=np.column_stack([cur,*[filtered(cur,tau) for tau in (5,20,80)]])@slope[:4]
                coeff=slope[4:]
            else:
                coeff=slope
            v=np.tanh(x/(reg["opt"] or 100))
            wall=np.log1p(data.s["kappa"].item()*v)
            d=.03355-.70*v+(np.r_[0.,wall[:-1]]-wall)/.25
            def predict(uniforms):
                repeats=uniforms.shape[0]
                count=np.zeros(repeats,dtype=np.int32);tfirst=np.zeros(repeats,dtype=np.int32);trace=np.empty(n)
                ret=f(n,repeats,k,x,v,d,data.table,data.s["grid"],data.s["reset"],data.s["pmid"],data.s["pd"],base,np.ascontiguousarray(coeff),float(reg["opt"] or 5),uniforms,count,tfirst,trace)
                assert ret==0
                return count,tfirst,trace
            # Independent consistency check with the archived conditional probabilities.
            # This check's uniforms and results never enter the following autonomous draws.
            forced=np.where(y>0,0.,1.)[None,:]
            cf,tf,trace=predict(forced)
            with np.load(ROOT/f"results/{arm}-{sid}-{sw}.npz") as src:
                error=float(np.max(np.abs(src["probability"]-trace)))
            assert error<1.e-9 and cf[0]==np.sum(y>0)
            err=max(err,error)
            count,tfirst,_=predict(u)
            event_time=np.minimum(n,tfirst+1)*DT;silent=float(np.mean(count==0))
            arrays[arm+"_count"]=count;arrays[arm+"_first_bin"]=tfirst
            row[arm]=dict(predicted_count_mean=float(count.mean()),predicted_first_or_end_mean_s=float(event_time.mean()),predicted_silence=silent)
            metrics=[distribution_score(count,target_count),distribution_score(event_time,target_time),(silent-(not len(first)))**2,abs(count.mean()-target_count)]
            score.setdefault(arm,{}).setdefault(sid,[]).append(metrics)
        p=out/f"{sid}-{sw}.npz"
        if not p.exists():np.savez_compressed(p,**arrays)
        with np.load(p) as orig:
            assert set(orig.files)==set(arrays) and all(np.array_equal(orig[k],v) for k,v in arrays.items())
        proof[p.name]=sha(p);records.append(row)
    per={a:np.array([np.mean(score[a][sid],axis=0) for sid in cohort["held"]]) for a in NAMES}
    sample=np.random.default_rng(950186).integers(0,len(cohort["held"]),(10000,len(cohort["held"])))
    contrasts={}
    for a in NAMES[1:]:
        delta=per["dual"]-per[a]
        contrasts[a]=dict(mean=delta.mean(0).tolist(),specimen95=np.quantile(delta[sample].mean(1),[.025,.975],axis=0).T.tolist())
    put(out/"terminal.json",dict(source_sha256=sha(Path(__file__)),c_source_sha256=sha(ROOT/"generative.c"),library_sha256=sha(ROOT/"generative.so"),model_seal_sha256=sha(ROOT/"results/seal.json"),
            protocol_sha256=sha(ROOT/"GENERATIVE.md"),draws_per_trial=M,streams=M*len(records)*len(NAMES),max_conditional_probability_alignment_error=err,
            metrics_order=["spike_count_CRPS","first_spike_or_end_CRPS_s","silence_Brier","absolute_count_error"],metrics={a:x.mean(0).tolist() for a,x in per.items()},paired_dual_minus=contrasts,
            mean_observed_count=float(np.mean([r["observed_count"] for r in records])),observed_silent=sum(r["observed_silent"] for r in records),records=records,draw_archives=proof))
    print("streams",M*len(records)*len(NAMES),"archive",sha(out/"terminal.json"),flush=True)


if __name__=="__main__":
    run()
