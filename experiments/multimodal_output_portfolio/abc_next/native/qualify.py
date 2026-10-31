"""Fit once, freeze, calibrate, freeze, then open independent verification once."""

import argparse
import copy
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

from ...abc_recovery.training_run import file_sha, write_json


Q = 2**24


def load_data(directory):
    with np.load(directory / "features.npz", allow_pickle=False) as data:
        return data["x_q24"].astype(np.float64) / Q, data["y"], data["group"]


def absent(x):
    return ((x[:, 480:482] == 0).all(1) & (x[:, 492] == 1) & (x[:, 503] == 1))


def raw_prediction(weights, x):
    z = np.tanh(x @ np.asarray(weights["w1"]).T + np.asarray(weights["b1"]))
    logits = z @ np.asarray(weights["w2"]) + weights["b2"]
    return 1 / (1 + np.exp(-logits))


def confidence(weights, calibration, x):
    raw = raw_prediction(weights, x)
    group = np.searchsorted(calibration["cuts"], raw, side="right")
    group[absent(x)] = 3
    probability = np.asarray(calibration["probabilities"])[group]
    pq = np.floor(probability * Q + .5).astype(np.int64)
    error = Q - pq
    return 1000000 - error * 1000000 // Q, error * 1000000 // Q, group


def ece(confidence_ppm, labels):
    bins = np.minimum(confidence_ppm // 100000, 9)
    return sum(abs(float(labels[bins == i].sum()) - float(confidence_ppm[bins == i].sum()) / 1e6)
               for i in range(10)) / len(labels)


def metrics(weights, calibration, x, y):
    cp, op, group = confidence(weights, calibration, x)
    ood = absent(x)
    accepted = (cp >= 750000) & (op <= 500000)
    fp = int(accepted[ood].sum())
    ood_n = int(ood.sum())
    # The zero-count formula is exact; any nonzero count fails this frozen design.
    upper = 1 - .05 ** (1 / ood_n) if fp == 0 else None
    result = {"n":len(y),"id_n":int((~ood).sum()),"ood_n":ood_n,
        "ece_full":ece(cp,y),"ece_id":ece(cp[~ood],y[~ood]),
        "joint_correct_full":float(y.mean()),"joint_correct_id":float(y[~ood].mean()),
        "brier":float(np.mean((cp / 1e6-y)**2)),
        "accepted_id":int(accepted[~ood].sum()),"accepted_id_fraction":float(accepted[~ood].mean()),
        "accepted_id_correctness":float(y[accepted & ~ood].mean()) if (accepted & ~ood).any() else None,
        "false_acceptances":fp,"false_acceptance_rate":fp/ood_n,
        "false_acceptance_one_sided_95_upper":upper,
        "calibration_group_counts":np.bincount(group,minlength=4).tolist(),
        "probabilities":calibration["probabilities"]}
    result["gates"]={"ece":max(result["ece_full"],result["ece_id"])<=.03,
        "ood_far":result["false_acceptance_rate"]<=.004999,
        "ood_upper":upper is not None and upper<=.004999,
        "id_nonvacuity":result["accepted_id_fraction"]>=.25}
    return result


def fit(protocol, data, output):
    output.mkdir(parents=True,exist_ok=False)
    spec=json.loads(protocol.read_text())
    x,y,group=load_data(data)
    train=group=="fit"; dev=group=="development"
    torch.set_num_threads(1);torch.manual_seed(spec["seed"])
    model=nn.Sequential(nn.Linear(508,32),nn.Tanh(),nn.Linear(32,1))
    optimizer=torch.optim.Adam(model.parameters(),lr=.002,weight_decay=.0001)
    xt,yt=torch.tensor(x[train],dtype=torch.float32),torch.tensor(y[train],dtype=torch.float32)
    xd,yd=torch.tensor(x[dev],dtype=torch.float32),torch.tensor(y[dev],dtype=torch.float32)
    best=float("inf"); selected=None; history=[]; begin=time.perf_counter_ns()
    for step in range(1,2001):
        ids=torch.randint(len(xt),(128,));optimizer.zero_grad(set_to_none=True)
        loss=nn.functional.binary_cross_entropy_with_logits(model(xt[ids]).flatten(),yt[ids])
        loss.backward();optimizer.step()
        if step%100==0:
            with torch.inference_mode():value=nn.functional.binary_cross_entropy_with_logits(model(xd).flatten(),yd).item()
            history.append({"step":step,"development_bce":value})
            if value<best:best=value;selected=copy.deepcopy(model.state_dict());selected_step=step
    model.load_state_dict(selected)
    weights={"schema":"hepta.abc3.resident-correctness-mlp.v1",
             "w1":model[0].weight.detach().double().tolist(),"b1":model[0].bias.detach().double().tolist(),
             "w2":model[2].weight.detach().double()[0].tolist(),"b2":model[2].bias.item()}
    write_json(output/"weights.json",weights)
    raw=raw_prediction(weights,x[dev]); dev_id=~absent(x[dev])
    cuts=np.quantile(raw[dev_id],[1/3,2/3]).tolist()
    write_json(output/"cuts.json",{"cuts":cuts,"source":"development ID only"})
    write_json(output/"development.json",{"selected_step":selected_step,"selected_bce":best,
        "history":history,"fit_wall_ns":time.perf_counter_ns()-begin,
        "n_fit":int(train.sum()),"n_development":int(dev.sum()),
        "development_id_success":float(y[dev][dev_id].mean()),
        "raw_predicted_id_mean":float(raw[dev_id].mean()),
        "raw_predicted_ood_mean":float(raw[~dev_id].mean()),
        "raw_id_acceptance":float((raw[dev_id]>=.75).mean()),
        "training_data_sha256":file_sha(data/"features.npz")})
    write_json(output/"predictor-freeze.json",{"phase":"predictor-frozen","frozen_unix_ns":time.time_ns(),
        "protocol_sha256":file_sha(protocol),"files":{name:file_sha(output/name) for name in
            ("weights.json","cuts.json","development.json")},
        "implementation_sha256":file_sha(Path(__file__)),"reserved_outcomes_opened":False})


def calibrate(protocol, data, model):
    barrier=json.loads((model/"predictor-freeze.json").read_text())
    if barrier["protocol_sha256"]!=file_sha(protocol):raise ValueError("Wrong protocol")
    for name,pin in barrier["files"].items():
        if file_sha(model/name)!=pin:raise ValueError("Frozen predictor changed")
    weights=json.loads((model/"weights.json").read_text());cuts=json.loads((model/"cuts.json").read_text())["cuts"]
    x,y,_=load_data(data);raw=raw_prediction(weights,x)
    groups=np.searchsorted(cuts,raw,side="right");groups[absent(x)]=3
    counts=np.bincount(groups,minlength=4);wins=np.bincount(groups,weights=y,minlength=4)
    if (counts==0).any():raise ValueError("Empty frozen calibration bin")
    calibration={"cuts":cuts,"probabilities":((wins+.5)/(counts+1)).tolist(),
                 "counts":counts.tolist(),"successes":wins.astype(int).tolist(),
                 "data_sha256":file_sha(data/"features.npz"),"fitted_only_on":"neuron_calibration"}
    write_json(model/"calibration.json",calibration)
    report=metrics(weights,calibration,x,y);write_json(model/"calibration-result.json",report)
    write_json(model/"calibrator-freeze.json",{"phase":"calibrator-frozen","frozen_unix_ns":time.time_ns(),
        "protocol_sha256":file_sha(protocol),"files":{name:file_sha(model/name) for name in
            ("weights.json","cuts.json","calibration.json","calibration-result.json","predictor-freeze.json")},
        "implementation_sha256":file_sha(Path(__file__)),"verification_opened":False})
    return report


def verify(protocol,data,model):
    barrier=json.loads((model/"calibrator-freeze.json").read_text())
    if barrier["protocol_sha256"]!=file_sha(protocol):raise ValueError("Wrong protocol")
    for name,pin in barrier["files"].items():
        if file_sha(model/name)!=pin:raise ValueError("Frozen calibration changed")
    weights=json.loads((model/"weights.json").read_text());cal=json.loads((model/"calibration.json").read_text())
    x,y,_=load_data(data);report=metrics(weights,cal,x,y)
    report["data_sha256"]=file_sha(data/"features.npz")
    report["protocol_sha256"]=file_sha(protocol)
    report["calibrator_freeze_sha256"]=file_sha(model/"calibrator-freeze.json")
    before=json.loads((model/"calibration-result.json").read_text())
    report["native_measured_ece_ppm"]=int(np.ceil(max(before["ece_full"],before["ece_id"],report["ece_full"],report["ece_id"])*1e6))
    report["native_measured_false_acceptance_ppm"]=int(np.ceil(max(before["false_acceptance_rate"],report["false_acceptance_rate"])*1e6))
    report["all_gates_passed"]=all(report["gates"].values()) and all(before["gates"].values())
    write_json(model/"verification-result.json",report)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("fit","calibrate","verify"))
    for name in ("protocol","data","model"):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    result={"fit":fit,"calibrate":calibrate,"verify":verify}[args.phase](args.protocol,args.data,args.model)
    print(json.dumps(result,sort_keys=True))
