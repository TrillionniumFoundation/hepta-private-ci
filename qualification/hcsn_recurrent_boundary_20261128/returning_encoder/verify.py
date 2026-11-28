"""Recover all score arrays from released weights; independently recompute paired effects."""
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
from fit import ARMS,SEEDS,digest,load_data,law,make_features

root=Path(__file__).resolve().parent
evidence=root/"evidence"
terminal=json.loads((root/"terminal.json").read_text())
seal=json.loads((root/"seal.json").read_text())
if digest(root/"seal.json")!=terminal["seal"] or digest(evidence/"per_clip.npz")!=terminal["per_clip_sha256"]:
    raise ValueError("seal or per-clip array changed")
x,y,actor,(_,_,held)=load_data(evidence/"all.xz")
worst=0.
verified=0
with np.load(evidence/"per_clip.npz") as raw:
    assert np.array_equal(raw["actor"],actor[held]) and np.array_equal(raw["label"],y[held])
    for arm in ARMS:
        grid=law(arm)
        for seed in SEEDS:
            features=make_features(x[held],arm,seed,grid)
            for kind in ("direct","cross_entropy"):
                key=f"{arm}-{seed}-{kind}"
                path=evidence/(key+".npz")
                assert digest(path)==seal[key]["model_sha"]
                with np.load(path) as w:
                    standardized=(features-w["mean"])/w["scale"]
                    direct=standardized@w["w"]+w["b"]
                    assert sha256(direct.tobytes()).hexdigest()==terminal["results"][key]["sha256_logits"]
                    independent=np.einsum("ij,jk->ik",standardized,w["w"],optimize=False)+w["b"]
                individual=np.logaddexp.reduce(independent,axis=1)-independent[np.arange(len(held)),y[held]]
                worst=max(worst,float(np.max(abs(individual-raw[key][0]))))
                assert np.array_equal(independent.argmax(1)==y[held],raw[key][1].astype(bool))
                verified+=direct.size
    assert worst<1e-9
    rng=np.random.default_rng(8127)
    actors=np.unique(actor[held])
    boot=rng.integers(0,len(actors),(4000,len(actors)))
    weights=np.stack([np.bincount(draw,minlength=len(actors)) for draw in boot])
    groups=[np.flatnonzero(actor[held]==s) for s in actors]
    totals=weights@np.array(list(map(len,groups)))
    max_pair_error=0.
    for key,row in terminal["paired"].items():
        rival,kind=key.removeprefix("returning-minus-").split("-",1)
        d=sum(raw[f"returning-{s}-{kind}"]-raw[f"{rival}-{s}-{kind}"] for s in SEEDS)/len(SEEDS)
        sums=np.array([d[:,g].sum(1) for g in groups])
        interval=np.quantile((weights@sums)/totals[:,None],[.025,.975],axis=0).T
        max_pair_error=max(max_pair_error,float(abs(interval-np.array(row["interval"])).max()))
    assert max_pair_error<1e-11
result=dict(models=len(seal),score_values=verified,max_per_clip_nll_error=worst,
            max_paired_interval_error=max_pair_error,terminal_sha256=digest(root/"terminal.json"))
(root/"verified.json").write_text(json.dumps(result,indent=2)+"\n")
print(result)
