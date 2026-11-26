"""Train or confirm one actor-disjoint audiovisual boundary-transfer candidate."""
import time
START = time.perf_counter()

import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from qualification.hcsn_closure_20261124.boundary_fix import BoundaryControlHCSN
from qualification.hcsn_smallnet_20261124.model import ModelConfig
from qualification.hcsn_closure_av_20261125.models import LIF

PHYSICAL = {
    "centered": ("qvi", "boundary_only", "centered"),
    "raw": ("qvi", "boundary_only", "raw"),
    "joint": ("qvi", "boundary_signed", "centered"),
    "signed": ("qvi", "signed_only", "raw"),
    "learned": ("learned", "boundary_only", "centered"),
    "fixed": ("fixed", "boundary_only", "centered"),
}
CONTROLS = ("attention", "gru", "lif", "diagonal", "linear")
ARMS = (*PHYSICAL, *CONTROLS)
SEEDS = (6101, 6102, 6103)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def record(path, value):
    with path.open("x") as out:
        json.dump(value, out, sort_keys=True, allow_nan=False)
        out.write("\n")

class Encoder(nn.Module):
    def __init__(self, arm, seed):
        super().__init__()
        self.arm = arm
        torch.manual_seed(seed + 10)
        self.projection = nn.Linear(256, 8)
        torch.manual_seed(seed + 20)
        width = 8
        if arm in PHYSICAL:
            policy, channel, mode = PHYSICAL[arm]
            self.core = BoundaryControlHCSN(
                ModelConfig(input_size=8, neurons=32, precision="mixed",
                            backend="uniformized", boundary_mode=policy, message_mode="full"),
                channel=channel, control_mode="accumulate", boundary_mode=mode)
            width = self.core.feature_dim
            self.core.readout = nn.Identity()
        elif arm == "gru":
            self.core = nn.GRU(8, 8, batch_first=True)
        elif arm == "attention":
            self.core = nn.TransformerEncoderLayer(8, 2, dim_feedforward=32, dropout=0.,
                                                   batch_first=True, norm_first=True)
        elif arm == "lif":
            self.core = LIF()
        elif arm == "diagonal":
            self.core = nn.Linear(8, 8)
            self.decay = nn.Parameter(torch.zeros(8))
        elif arm != "linear":
            raise ValueError(arm)
        torch.manual_seed(seed + 30)
        self.head = nn.Linear(width, 6)

    def forward(self, x):
        z = torch.tanh(self.projection(x))
        if self.arm in PHYSICAL:
            _, z, _ = self.core(z.transpose(0,1), return_features=True)
            z = z.transpose(0,1)
        elif self.arm == "gru":
            z, _ = self.core(z)
        elif self.arm == "attention":
            mask = torch.ones(z.shape[1], z.shape[1], dtype=torch.bool, device=z.device).triu(1)
            positions = torch.arange(z.shape[1], device=z.device, dtype=z.dtype)[:,None]
            freq = torch.exp(-torch.arange(0,8,2,device=z.device,dtype=z.dtype) * (np.log(10000.) / 8))
            encoded = torch.stack(((positions * freq).sin(), (positions * freq).cos()), -1).flatten(1)
            z = self.core(z + encoded, src_mask=mask)
        elif self.arm == "lif":
            z = self.core(z)
        elif self.arm == "diagonal":
            a = self.decay.sigmoid()
            state = z.new_zeros(z.shape[0],8)
            out = []
            for frame in self.core(z).unbind(1):
                state = a*state + (1-a)*frame
                out.append(state)
            z = torch.stack(out, 1)
        return self.head(z.mean(1))

def data(folder, part):
    path = folder / (part + ".npz")
    expected = json.loads((folder/"data_receipt.json").read_text())["arrays"][part]
    if sha(path) != expected:
        raise ValueError("changed data " + part)
    with np.load(path) as z:
        x = z["x"].transpose(0,2,1,3).reshape(-1,8,256)
        return torch.from_numpy(x), torch.from_numpy(z["y"]), z["actors"], z["clips"]

def metrics(prob, y, actors):
    idx = torch.arange(len(y))
    truth = F.one_hot(y, 6)
    corr = (prob.argmax(1)==y).float()
    brier = (prob-truth).square().sum(1)
    accs = {str(a):corr[actors==a].mean().item() for a in sorted(set(actors))}
    return {"accuracy": sum(accs.values())/len(accs), "brier": brier.mean().item(),
            "ce": -prob[idx,y].clamp_min(1e-12).log().mean().item(), "actor_accuracy":accs}

@torch.no_grad()
def evaluate(model, batch):
    x,y,actors,clips = batch
    model.eval()
    prob = torch.cat([model(v).softmax(1) for v in x.split(8)])
    return metrics(prob,y,actors), prob

def fit(data_dir, out, arm, seed):
    train = data(data_dir,"train")
    dev = data(data_dir,"dev")
    model = Encoder(arm,seed)
    opt = torch.optim.Adam(model.parameters(),lr=.003)
    generator = torch.Generator().manual_seed(seed + 40)
    ids = torch.randint(len(train[1]), (32,8), generator=generator)
    history = []
    best_ce = float("inf")
    first_quality = None
    mpath = out/"weights.pt"
    for step in range(33):
        if step%8 == 0:
            scores,_ = evaluate(model,dev)
            if scores["ce"] < best_ce:
                best_ce, best_step = scores["ce"],step
                torch.save(model.state_dict(),mpath)
            elapsed=time.perf_counter()-START
            if first_quality is None and scores["accuracy"] >= .35 and scores["brier"] <= .82:
                first_quality=elapsed
            history.append({"step":step,"seconds":elapsed,**scores})
        if step == 32:
            break
        model.train()
        opt.zero_grad(set_to_none=True)
        ii = ids[step]
        loss = F.cross_entropy(model(train[0][ii]),train[1][ii])
        if not torch.isfinite(loss):
            raise FloatingPointError("loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(),2.,error_if_nonfinite=True)
        opt.step()
    nparams = sum(p.numel() for p in model.parameters() if p.requires_grad)
    active = nparams
    if arm in PHYSICAL:
        active -= model.core.recurrent.weight.numel()-int(model.core.synaptic_mask.count_nonzero())
    record(out/"fit.json", {"arm":arm,"seed":seed,"updates":32,"best_step":best_step,
           "weights":sha(mpath),"quality_dev_seconds":first_quality,"trace":history,
           "trainable":nparams,"active_minus_synaptic_mask":active,"torch":torch.__version__,
           "cpu":platform.machine(),"peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
           "wall_to_receipt_seconds":time.perf_counter()-START})

def confirm(data_dir, work, out, arm, seed):
    seal=json.loads((work/"seal.json").read_text())
    stem=f"{arm}-{seed}"
    if set(seal) != {f"{a}-{s}" for a in ARMS for s in SEEDS}:
        raise ValueError("incomplete campaign")
    if seal[stem] != {"weights":sha(out/"weights.pt"),"fit":sha(out/"fit.json")}:
        raise ValueError("candidate drift")
    batch=data(data_dir,"test")
    model=Encoder(arm,seed)
    model.load_state_dict(torch.load(out/"weights.pt",map_location="cpu",weights_only=True))
    scores,prob=evaluate(model,batch)
    np.savez_compressed(out/"predictions.npz",p=prob.numpy(),y=batch[1].numpy(),actor=batch[2],clip=batch[3])
    record(out/"test.json",dict(arm=arm,seed=seed,scores=scores,
           predictions=sha(out/"predictions.npz"),wall_to_receipt_seconds=time.perf_counter()-START))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("stage",choices=("fit","confirm"))
    p.add_argument("work",type=Path)
    p.add_argument("data",type=Path)
    p.add_argument("arm",choices=ARMS)
    p.add_argument("seed",type=int,choices=SEEDS)
    a=p.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    dest=a.work/f"{a.arm}-{a.seed}"
    if a.stage=="fit":
        dest.mkdir(parents=True)
        fit(a.data,dest,a.arm,a.seed)
    else:
        confirm(a.data,a.work,dest,a.arm,a.seed)
