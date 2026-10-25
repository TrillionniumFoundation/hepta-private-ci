"""Fit only historical development; calibrate/freeze before new verification."""

import argparse
import copy
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

from ...abc_recovery.training_run import file_sha, write_json
from ...v7.snapshot import Snapshot
from .forecast import HIDDEN, INPUT_DIM, Q, STATE_DIM, absent, groups, predict
from .forecast import runtime_predictions
from .boundaries import check_sources, verified_data


def load(directory):
    with np.load(directory / "data.npz", allow_pickle=False) as source:
        return {key: source[key] for key in source.files}


def freeze(protocol, model, name, files):
    write_json(model / name, {"frozen_unix_ns":time.time_ns(),
        "protocol_sha256":file_sha(protocol), "files":{key:file_sha(model/key) for key in files}})


def check_freeze(protocol, model, name):
    check_sources(protocol)
    frozen = json.loads((model / name).read_text())
    if frozen["protocol_sha256"] != file_sha(protocol):
        raise ValueError("Protocol changed")
    for key, digest in frozen["files"].items():
        if file_sha(model/key) != digest: raise ValueError("Frozen artifact changed")


def fit(protocol, data, model):
    model.mkdir(parents=True, exist_ok=False)
    spec = json.loads(protocol.read_text()); d = verified_data(data,protocol,"development")
    torch.set_num_threads(1); torch.manual_seed(spec["seed"])
    selected_mask, fit_mask = d["group"] == "selection", d["group"] == "fit"
    x = torch.tensor(d["x_q24"] / Q, dtype=torch.float32)
    past = torch.tensor(d["past_q24"] / Q, dtype=torch.float32)
    future = torch.tensor(d["future_q24"] / Q, dtype=torch.float32)
    y = torch.tensor(d["y"], dtype=torch.float32)
    network = nn.Sequential(nn.Linear(INPUT_DIM,HIDDEN),nn.Tanh(),nn.Linear(HIDDEN,STATE_DIM+1))
    nn.init.zeros_(network[2].weight); nn.init.zeros_(network[2].bias)
    optimizer = torch.optim.Adam(network.parameters(),lr=.002,weight_decay=.0001)
    train_ids = torch.tensor(np.flatnonzero(fit_mask)); dev_ids=torch.tensor(np.flatnonzero(selected_mask))

    def loss(ids):
        out = network(x[ids]); delta=out[:,:STATE_DIM].tanh()
        keep = torch.ones_like(delta); keep[:,:16] = 1-x[ids,476:477]
        forecast = (past[ids]+delta*keep).clamp(-1,1)
        mse = (forecast-future[ids]).square().mean()
        bce = nn.functional.binary_cross_entropy_with_logits(out[:,STATE_DIM],y[ids])
        return mse+.05*bce,mse,bce

    start,cpu=time.perf_counter_ns(),time.process_time_ns(); history=[];best=float("inf")
    for step in range(1,2001):
        ids=train_ids[torch.randint(len(train_ids),(128,))];optimizer.zero_grad(set_to_none=True)
        value,_,_=loss(ids);value.backward();optimizer.step()
        if step%100==0:
            with torch.inference_mode(): value,mse,bce=loss(dev_ids)
            history.append({"step":step,"selection_objective":float(value),"state_mse":float(mse),"correctness_bce":float(bce)})
            if float(value)<best:
                best=float(value);chosen=copy.deepcopy(network.state_dict());chosen_step=step
    network.load_state_dict(chosen)
    upstream=Snapshot.load(spec["paths"]["model"],expected_file_sha256=spec["input_sha256"]["model"])._model
    weights={"schema":"hepta.abc4.prospective-output-head.v1",
        "w1":network[0].weight.detach().double().tolist(),"b1":network[0].bias.detach().double().tolist(),
        "w2":network[2].weight.detach().double().tolist(),"b2":network[2].bias.detach().double().tolist(),
        "token_state":upstream.token_embedding.weight.detach()[:,:8].tanh().double().tolist()}
    write_json(model/"weights.json",weights)
    xd=d["x_q24"][selected_mask]/Q; forecast,probability=predict(weights,xd)
    cuts=np.quantile(probability[~absent(xd)],[1/3,2/3]).tolist()
    write_json(model/"cuts.json",{"cuts":cuts,"source":"historical selection ID only"})
    write_json(model/"development.json",{"selected_step":chosen_step,"history":history,
        "selection_forecast_mse":float(np.mean((forecast-d["future_q24"][selected_mask]/Q)**2)),
        "selection_persistence_mse":float(np.mean(((d["past_q24"][selected_mask]-d["future_q24"][selected_mask])/Q)**2)),
        "wall_ns":time.perf_counter_ns()-start,"cpu_ns":time.process_time_ns()-cpu,
        "historical_source_pairs":len(np.unique(d["pair"])),"data_sha256":file_sha(data/"data.npz")})
    freeze(protocol,model,"predictor-freeze.json",("weights.json","cuts.json","development.json"))


def ece(confidence, labels):
    bins=np.minimum((confidence*10).astype(int),9)
    return sum(abs(float(labels[bins==i].sum())-float(confidence[bins==i].sum())) for i in range(10))/len(labels)


def stats(weights, calibration, d):
    x=d["x_q24"]/Q; observed=d["future_q24"]/Q; y=d["y"]; mask=d["ood"]
    forecast,raw,p,_,_,cp,op,group=runtime_predictions(weights,calibration,x,observed)
    accepted=(cp>=750000)&(op<=500000)
    ids=np.unique(d["pair"]); ood_ids=np.unique(d["pair"][mask])
    false_pairs=sum(bool(accepted[(d["pair"]==i)&mask].any()) for i in ood_ids)
    point={"rows":len(y),"source_pairs":len(ids),"id_source_pairs":len(ids)-len(ood_ids),"ood_source_pairs":len(ood_ids),
        "prospective_ece_id":ece(p[~mask],y[~mask]),"prospective_ece_full":ece(p,y),
        "native_ece_id":ece(cp[~mask]/1e6,y[~mask]),"native_ece_full":ece(cp/1e6,y),
        "prospective_brier":float(np.mean((p-y)**2)),"joint_correct_id":float(y[~mask].mean()),
        "native_id_accepted_rows":int(accepted[~mask].sum()),"native_id_acceptance_fraction":float(accepted[~mask].mean()),
        "native_ood_false_accepted_rows":int(accepted[mask].sum()),"native_ood_false_accepted_source_pairs":false_pairs,
        "native_ood_false_acceptance_pair_rate":false_pairs/len(ood_ids),
        "native_ood_false_acceptance_pair_upper95":1-.05**(1/len(ood_ids)) if false_pairs==0 else None,
        "calibration_group_counts":np.bincount(group,minlength=8).tolist(),
        "mean_forecast_mse":float(np.mean((forecast-observed)**2)),
        "mean_persistence_mse":float(np.mean((d["past_q24"]/Q-observed)**2))}
    point["native_point_gates"]={"ece":max(point["native_ece_id"],point["native_ece_full"])<=.03,
        "ood_far":point["native_ood_false_acceptance_pair_rate"]<=.004999,
        "id_nonvacuity":point["native_id_acceptance_fraction"]>=.25}
    return point


def calibrate(protocol, data, model):
    check_freeze(protocol,model,"predictor-freeze.json")
    weights=json.loads((model/"weights.json").read_text()); d=verified_data(data,protocol,"calibration");x=d["x_q24"]/Q
    cuts=json.loads((model/"cuts.json").read_text())["cuts"]
    forecast,raw=predict(weights,x); group=groups(x,raw,cuts)
    counts=np.bincount(group,minlength=8);wins=np.bincount(group,weights=d["y"],minlength=8)
    if (counts==0).any():raise ValueError("Empty frozen calibration bin")
    radius={}
    for ood in (False,True):
        pairs=np.unique(d["pair"][d["ood"]==ood])
        errors=[np.abs(forecast[d["pair"]==i]-d["future_q24"][d["pair"]==i]/Q).max() for i in pairs]
        rank=min(len(errors),int(np.ceil(.9*(len(errors)+1))))
        radius[str(ood)]=float(np.sort(errors)[rank-1])
    cal={"cuts":cuts,"probabilities":((wins+.5)/(counts+1)).tolist(),"counts":counts.tolist(),
        "successes":wins.astype(int).tolist(),"source_max_error_radius90":radius,
        "data_sha256":file_sha(data/"data.npz"),"source_role":"fresh calibration only"}
    write_json(model/"calibration.json",cal)
    result=stats(weights,cal,d);write_json(model/"calibration-result.json",result)
    freeze(protocol,model,"calibrator-freeze.json",("weights.json","cuts.json","development.json",
        "predictor-freeze.json","calibration.json","calibration-result.json"))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("phase",choices=("fit","calibrate"))
    for name in ("protocol","data","model"):p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps({"fit":fit,"calibrate":calibrate}[a.phase](a.protocol,a.data,a.model)))
