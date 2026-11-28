"""Post-hoc calibration of previously sealed six-layer CREMA-D models."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

SEAL = "b1939366173abe2b814ad1af4fb4ad7ec56d29c55fa9e05e29ecf8b2ebf1374c"
REGIMES = ("temperature", "temperature_train_prior")
METHODS=("forward","shuffled","head","same_site_bp","keep")
SEEDS=(137,311,557)


def digest(path):
    with path.open("rb") as f: return hashlib.file_digest(f,"sha256").hexdigest()


def save(path,p):
    path.write_text(json.dumps(p,indent=2,allow_nan=False)+"\n")


def stats(scores, y, multiplier, bias):
    z=scores*multiplier+bias
    z-=z.max(1,keepdims=True)
    denominator=np.exp(z).sum(1)
    loss=np.log(denominator)-z[np.arange(len(y)),y]
    return {"nll":float(loss.mean()),"top1":float((z.argmax(1)==y).mean())},loss


def fit(scores, y, bias):
    t=time.perf_counter()
    centered=scores-scores.mean(1,keepdims=True)
    truth=centered[np.arange(len(y)),y]
    def gradient(beta):
        z=beta*centered+bias
        z-=z.max(1,keepdims=True)
        p=np.exp(z);p/=p.sum(1,keepdims=True)
        return float(((p*centered).sum(1)-truth).mean())
    lo,hi=0.,4.
    if gradient(lo)>=0: beta=lo
    elif gradient(hi)<=0: beta=hi
    else:
        for _ in range(36):
            mid=(lo+hi)/2
            if gradient(mid)>0: hi=mid
            else: lo=mid
        beta=(lo+hi)/2
    values,_=stats(scores,y,beta,bias)
    ref,_=stats(scores,y,1.,bias)
    if values["nll"]>ref["nll"]+1e-10: raise ValueError("calibration optimum")
    return {"multiplier":beta,"dev":values,"slope":gradient(beta),"fit_s":time.perf_counter()-t}


def run(base, root, out):
    started=time.perf_counter()
    if not out.is_dir() or list(out.glob("*.json")): raise ValueError("output must be fresh")
    sys.path[:0]=[str(base),str(root/"src")]
    from study import Data, inference, HASHES
    from direct import make_net, parameters
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    files=base/"edit";orig=json.loads((files/"terminal.json").read_text())
    if digest(files/"seal.json")!=SEAL or orig["seal_sha256"]!=SEAL: raise ValueError("seal mismatch")
    for path,sha in HASHES.items():
        if digest(root/path)!=sha: raise ValueError("original asset mismatch")
    if digest(base/"direct.py")!=orig["source_sha256"]: raise ValueError("direct.py mismatch")
    seal=json.loads((files/"seal.json").read_text())
    d=Data(root);dy=d.y[d.dev].numpy()
    counts=np.bincount(d.y[d.train].numpy(),minlength=72)
    if (counts<=0).any(): raise ValueError("absent training class")
    prior=np.log(counts/counts.sum());biases=dict(temperature=np.zeros(72),temperature_train_prior=prior)
    rows={};selected={r:{} for r in REGIMES}
    prep_s=time.perf_counter()-started
    for key,options in seal.items():
        rows[key]=[]
        for original in options:
            t=time.perf_counter()
            p=files/original["path"]
            if digest(p)!=original["sha256"]:raise ValueError("candidate digest")
            net=make_net(root,d,original["seed"])
            writes=torch.load(p,map_location="cpu",weights_only=True)
            mats=parameters(net)
            if set(writes)!=set(mats):raise ValueError("different write sites")
            with torch.no_grad():
                for k,m in mats.items():m.copy_(writes[k])
                raw=inference(net,d,d.dev).detach().double().numpy()
            elapsed=time.perf_counter()-t
            rawmetrics,_=stats(raw,dy,1.,biases["temperature"])
            if abs(rawmetrics['nll']-original['development_nll'])>3e-5:raise ValueError("development replay mismatch")
            row={"steps":original["steps"],"source":original["path"],"weights_sha256":original["sha256"],
                 "development_logits_sha256":hashlib.sha256(raw.astype("<f8").tobytes()).hexdigest(),
                 "development_raw":rawmetrics,"dev_reinfer_s":elapsed,"original_fit_dev_save_s":original["total_fit_dev_save_s"],
                 "regimes":{r:fit(raw,dy,b) for r,b in biases.items()}}
            rows[key].append(row)
        for r in REGIMES:
            best=min(rows[key],key=lambda z:(z["regimes"][r]["dev"]["nll"],z["steps"]))
            selected[r][key]={"steps":best["steps"],"multiplier":best["regimes"][r]["multiplier"],
                              "source":best["source"],"dev":best["regimes"][r]["dev"]}
    if sum(len(v) for v in rows.values())!=27:raise ValueError("expected 27 candidates")
    selection={"original_seal":SEAL,"seed_ids":SEEDS,"training_counts":counts.tolist(),
               "rows":rows,"selected":selected,
               "cold_opened_this_reanalysis":False,"data_sha256":HASHES["data/data.npz"]}
    save(out/"development_seal.json",selection)
    seal_hash=digest(out/"development_seal.json")
    # Only the already sealed selections open cold logits. Verify shape and record identity.
    cy=d.y[d.test].numpy();actors=d.actors[d.test];who=np.unique(actors)
    result={"development_seal_sha256":seal_hash,"script_sha256":digest(Path(__file__)),
            "study_sha256":digest(base/"study.py"),"direct_sha256":digest(base/"direct.py"),
            "original_terminal_sha256":digest(files/"terminal.json"),"data_preparation_s":prep_s,
            "clips":len(cy),"actors":len(who),"actor_ids":who.tolist(),"train":len(d.train),"dev":len(d.dev),
            "definitions":{"unscaled_score_factor":12,"multiplier_range":[0,4],"class_prior":"empirical training-only frequency, fixed additive log prior",
                            "comparison":"mean over clips after averaging matched seeds; resample whole actors with clip-count weights",
                            "cost":"original all inspected prefix fit, validation and test costs + recorded post-hoc development re-inference and calibration on every prefix + selected cold scoring; same counting rule per arm",
                            "evidence":"post-hoc, previously inspected aggregate and cohort"},
            "pure_training_prior":{"dev":stats(np.zeros((len(dy),72)),dy,0,prior)[0],
                                   "cold":stats(np.zeros((len(cy),72)),cy,0,prior)[0]},
            "uniform":{"dev":stats(np.zeros((len(dy),72)),dy,0,prior*0)[0],
                       "cold":stats(np.zeros((len(cy),72)),cy,0,prior*0)[0]},"regimes":{}}
    for regime,picks in selected.items():
        individual={};per_loss={}
        for key,pick in picks.items():
            st=time.perf_counter()
            path=(files/pick["source"]).with_name("cold.npz")
            with np.load(path,allow_pickle=False) as archive:
                if not np.array_equal(archive['ids'],d.names[d.test]) or not np.array_equal(archive['labels'],cy):
                    raise ValueError("cold identity mismatch")
                logits=archive["scores"].astype(np.float64)
            if logits.shape!=(len(cy),72) or not np.isfinite(logits).all(): raise ValueError("cold logits")
            cold,per_loss[key]=stats(logits,cy,pick['multiplier'],biases[regime])
            raw,_=stats(logits,cy,1.,biases["temperature"])
            saved=next(i for i in orig['cells'][key]['cold'] if i['steps']==pick['steps'])
            if abs(raw['nll']-saved['nll'])>3e-5:raise ValueError("cold replay mismatch")
            cold_s=time.perf_counter()-st
            add_dev=sum(row['dev_reinfer_s']+row['regimes'][regime]['fit_s'] for row in rows[key])
            original_s=orig['cells'][key]['compared_prefixes_end_to_end_s']
            individual[key]={**pick,"cold":cold,"cold_logits_sha256":digest(path),"calibration_and_replay_dev_s":add_dev,
                             "selected_cold_score_s":cold_s,"original_all_prefix_cost_s":original_s,
                             "charged_total_s":original_s+add_dev+prep_s+cold_s,
                             "dev_and_cold_nll_4_1":pick['dev']['nll']<=4.1 and cold['nll']<=4.1}
        summary={}
        for method in METHODS:
            group=[individual[f"{method}-{s}"] for s in SEEDS]
            summary[method]={"dev_nll":np.mean([r['dev']['nll'] for r in group]),"dev_top1":np.mean([r['dev']['top1'] for r in group]),
                             "cold_nll":np.mean([r['cold']['nll'] for r in group]),"cold_top1":np.mean([r['cold']['top1'] for r in group]),
                             "seeds_passing_4_1":sum(r["dev_and_cold_nll_4_1"] for r in group),
                             "mean_charged_seconds":np.mean([r["charged_total_s"] for r in group]),
                             "mean_added_seconds":np.mean([r["calibration_and_replay_dev_s"]+r["selected_cold_score_s"] for r in group])}
        diff=np.stack([per_loss[f"forward-{i}"]-per_loss[f"same_site_bp-{i}"] for i in SEEDS]).mean(0)
        mass=np.array([(actors==a).sum() for a in who]); sums=np.array([diff[actors==a].sum() for a in who])
        ix=np.random.default_rng(91363).integers(len(who),size=(4000,len(who)))
        draws=sums[ix].sum(1)/mass[ix].sum(1)
        result['regimes'][regime]={"selected":individual,"summary":summary,"forward_minus_bp":{"mean":float(diff.mean()),
                                  "ci95":np.quantile(draws,[.025,.975]).tolist(),"actor_counts":mass.tolist(),"actor_loss_sums":sums.tolist(),
                                  "bootstrap_seed":91363,"replications":4000}}
    if digest(out/"development_seal.json")!=seal_hash:raise ValueError("selection changed")
    result["total_reanalysis_wall_s"]=time.perf_counter()-started
    save(out/"result.json",result);print("complete",digest(out/"result.json"),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for arg in ('base','root','out'):p.add_argument(arg,type=Path)
    a=p.parse_args();run(a.base.resolve(),a.root.resolve(),a.out.resolve())
