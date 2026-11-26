"""Edit the actual trained audiovisual physical costs and confirm on disjoint actors."""
import argparse
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.func import functional_call
from torch.nn.functional import cross_entropy
from study import Encoder, SEEDS, data, evaluate, record, sha

ARMS = ("keep", "inverse", "matched", "wide")

def snapshot(model):
    return {k: v.detach().clone() for k, v in model.state_dict().items()}

class Inverse:
    def __init__(self, core):
        c = core.config
        self.c = c
        self.base = core.raw_cost.detach().clone()
        self.a = core.reset_absolute.detach().double()
        self.mu = torch.full_like(self.a, c.base_drift)
        self.b = core.qvi_boundary(self.mu, c.cost+c.cost_span*self.base.double().tanh()).detach()
        self.eta = math.exp(-c.stages*math.log1p(c.discount*c.refractory/c.stages))
        self.k = 2*c.discount/((self.mu.square()+2*c.discount*c.sigma**2).sqrt()-self.mu)
        self.u = c.gain/c.discount
        self.intercept = c.gain*self.mu/c.discount**2-c.maintenance/c.discount
        self.amp = self.u/self.k
        self.nominal = self.inverse(self.b)

    def inverse(self, b):
        future = self.u*self.a+self.intercept+self.amp*torch.exp(-self.k*(self.a-b))
        amount = self.eta*future-(self.u*b+self.intercept+self.amp)
        z = (amount-self.c.cost)/self.c.cost_span
        if bool((z.abs() >= 1).any()):
            raise ValueError("infeasible inverse")
        return z.atanh()

    def raw(self, shift):
        d = shift.double().repeat_interleave(self.b.numel()//2)
        return self.base + (self.inverse(self.b+d)-self.nominal).to(self.base)

def scores(prob, batch):
    _, y, actors, _ = batch
    target = y < 4
    hits = (prob.argmax(1)==y).float()
    per = {}
    for actor in np.unique(actors):
        sel = torch.as_tensor(actors == actor)
        per[str(actor)] = [float(hits[sel & target].mean()), float(hits[sel & ~target].mean())]
    return {"ce":float(-prob[target,y[target]].clamp_min(1e-12).log().mean()),
            "brier":float((prob[target]-nn.functional.one_hot(y[target],6)).square().sum(1).mean()),
            "actor":per}

def fit(folder, parents, out):
    train, dev = data(folder,"train"), data(folder,"dev")
    source = json.loads((parents/"seal.json").read_text())
    out.mkdir(exist_ok=False)
    receipt = {}
    for seed in SEEDS:
        parent = parents/f"centered-{seed}"/"weights.pt"
        if sha(parent) != source[f"centered-{seed}"]["weights"]:
            raise ValueError("parent drift")
        model = Encoder("centered",seed)
        model.load_state_dict(torch.load(parent,weights_only=True))
        baseline = snapshot(model)
        law = Inverse(model.core)
        base_metrics = scores(evaluate(model,dev)[1],dev)
        idx = torch.where(train[1] < 4)[0]
        schedule = idx[torch.randint(len(idx),(32,8),generator=torch.Generator().manual_seed(seed+289))]
        for arm in ARMS:
            tick = time.perf_counter()
            model.load_state_dict(baseline)
            # Preserve the original physical policy's inactive learned-boundary parameter.
            for name,param in model.named_parameters():
                param.requires_grad_(arm=="wide" and name!="core.raw_boundary")
            history = []
            best_ce = base_metrics["ce"]
            selected = "keep"
            best_state = baseline
            def consider(label, raw=None):
                nonlocal best_ce, selected, best_state
                if raw is not None:
                    with torch.no_grad():
                        model.core.raw_cost.copy_(raw)
                row = scores(evaluate(model,dev)[1],dev)
                damage = max(base_metrics["actor"][a][1]-v[1] for a,v in row["actor"].items())
                history.append(dict(label=label,protected_damage=damage,**row))
                if damage <= .05 and row["ce"] < best_ce:
                    best_ce, selected, best_state = row["ce"], label, snapshot(model)
            if arm=="inverse":
                for x,y in itertools.product((-.006,0.,.006),repeat=2):
                    d = torch.tensor([x,y],dtype=torch.double)
                    try:
                        raw = law.raw(d)
                    except ValueError:
                        history.append(dict(label=[x,y],status="infeasible"))
                        continue
                    expected = law.b+d.repeat_interleave(law.b.numel()//2)
                    observed = model.core.qvi_boundary(law.mu,law.c.cost+law.c.cost_span*raw.double().tanh())
                    if float((observed-expected).abs().max()) > 1e-6:
                        raise ValueError("incorrect inverse")
                    consider([x,y],raw)
            elif arm in ("wide","matched"):
                latent = nn.Parameter(torch.zeros(2,dtype=torch.double))
                params = [p for p in model.parameters() if p.requires_grad] if arm=="wide" else [latent]
                optimizer = torch.optim.Adam(params,lr=.003 if arm=="wide" else .1)
                consider(0)
                for step, ii in enumerate(schedule,1):
                    model.train()
                    optimizer.zero_grad(set_to_none=True)
                    if arm=="wide":
                        logits = model(train[0][ii])
                    else:
                        raw = law.raw(.006*latent.tanh())
                        logits = functional_call(model,{"core.raw_cost":raw},(train[0][ii],))
                    loss = cross_entropy(logits,train[1][ii])
                    loss.backward()
                    nn.utils.clip_grad_norm_(params,2.,error_if_nonfinite=True)
                    optimizer.step()
                    if step % 8 == 0:
                        consider(step,law.raw(.006*latent.detach().tanh()) if arm=="matched" else None)
            stem = f"{arm}-{seed}"
            torch.save(best_state,out/(stem+".pt"))
            receipt[stem] = {"weights":sha(out/(stem+".pt")), "parent":sha(parent),
                "selected":selected,"history":history,"keep_dev":base_metrics,
                "selection_seconds":time.perf_counter()-tick,
                "max_raw_cost_change":float((best_state["core.raw_cost"]-baseline["core.raw_cost"]).abs().max())}
        print("sealed candidates",seed,flush=True)
    record(out/"fit.json",receipt)
    record(out/"seal.json",{"fit":sha(out/"fit.json"),"parents_seal":sha(parents/"seal.json")})

def confirm(folder,parents,out):
    seal = json.loads((out/"seal.json").read_text())
    if seal != {"fit":sha(out/"fit.json"),"parents_seal":sha(parents/"seal.json")}:
        raise ValueError("seal")
    receipt = json.loads((out/"fit.json").read_text())
    batch = data(folder,"test")
    result, arrays = {}, {}
    for seed,arm in itertools.product(SEEDS,ARMS):
        stem = f"{arm}-{seed}"
        path = out/(stem+".pt")
        if sha(path)!=receipt[stem]["weights"]:
            raise ValueError(stem)
        model = Encoder("centered",seed)
        model.load_state_dict(torch.load(path,weights_only=True))
        prob = evaluate(model,batch)[1]
        result[stem] = scores(prob,batch)
        arrays[stem] = prob.numpy()
    np.savez_compressed(out/"predictions.npz",y=batch[1].numpy(),actors=batch[2],clips=batch[3],**arrays)
    summary={}
    for arm in ARMS:
        diffs=np.asarray([[
          np.asarray(result[f"{arm}-{s}"]["actor"][a])-np.asarray(result[f"keep-{s}"]["actor"][a])
          for a in sorted(result[f"keep-{s}"]["actor"])] for s in SEEDS])
        paired=diffs.mean(0)
        groups=list(itertools.product(range(len(paired)),repeat=len(paired)))
        ci=np.percentile(paired[np.asarray(groups),0].mean(1),[2.5,97.5])
        summary[arm]=dict(gain=float(paired[:,0].mean()),ci95=ci.tolist(),
          worst_protected_delta=float(paired[:,1].min()),worst_seed_actor_protected=float(diffs[:,:,1].min()),
          passed=bool(ci[0]>0 and paired[:,1].min()>=-.05),
          seed_gains=diffs[:,:,0].mean(1).tolist())
    record(out/"test.json",{"selection":sha(out/"seal.json"),"predictions":sha(out/"predictions.npz"),
          "scores":result,"summary":summary})
    print(json.dumps(summary),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("stage",choices=("fit","confirm"));p.add_argument("folder",type=Path)
    p.add_argument("parents",type=Path);p.add_argument("out",type=Path)
    a=p.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    (fit if a.stage=="fit" else confirm)(a.folder,a.parents,a.out)
