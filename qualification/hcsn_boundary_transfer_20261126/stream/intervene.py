"""Frozen-parent mechanism diagnostic on the already scored test dates."""
import argparse
import hashlib
import json
from pathlib import Path

import torch
import run


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",type=Path,required=True)
    parser.add_argument("--campaign",type=Path,required=True)
    args=parser.parse_args()
    torch.set_num_threads(1)
    root=args.campaign
    seal=json.loads((root/"seal.json").read_text())
    prior=json.loads((root/"predictions.json").read_text())
    x,y,ids,dates=run.load_data(args.data,["train","test"])["test"]
    order=sorted(range(len(ids)),key=lambda i:hashlib.sha256(("sender-probe-20261126/"+ids[i]).encode()).digest())
    if len(order)%16:raise ValueError("expected complete 16-member source batches")
    outputs={}
    with torch.no_grad():
        for seed in run.SEEDS:
            key=f"qvi_centered-{seed}"
            path=root/key/"selected.pt"
            if run.sha(path)!=seal["roster"][key][1]:
                raise ValueError("changed candidate")
            model=run.model_for("qvi_centered")
            model.load_state_dict(torch.load(path,weights_only=True))
            model.eval()
            for mode in ("intact","zero_senders","roll_senders"):
                def intervention(instance,frame,control,raw,delivered,step):
                    # Apply only to the previously emitted boundary of the sender
                    # half; preserve receiver recurrence and the entire input stream.
                    if step and mode!="intact":
                        boundary=delivered[:,0,:16]
                        if mode=="zero_senders":boundary.zero_()
                        else:boundary.copy_(torch.roll(boundary,1,0))
                model.observer=intervention
                p=torch.empty(len(order))
                for start in range(0,len(order),16):
                    idx=order[start:start+16]
                    p[idx]=model(x[:,idx])[-1].softmax(-1)[:,1]
                original=prior[key+"/fixed_updates"]["p"]
                if mode=="intact" and max(abs(a-b) for a,b in zip(original,p.tolist()))>2e-5:
                    raise ValueError("regrouped intact prediction mismatch")
                outputs[f"{key}/{mode}"]={"score":run.metrics(p.tolist(),y.tolist(),dates),"p":p.tolist(),
                                          "max_change_vs_original":max(abs(a-b) for a,b in zip(original,p.tolist()))}
    run.write_new(root/"sender_intervention.json",{"candidate_sha":{k:v[1] for k,v in seal["roster"].items()
               if k.startswith("qvi_centered")},"purpose":"post-confirmation frozen-model mechanism diagnostic on the same dates",
               "test_ids":ids,"batch_order":order,"rows":outputs})


if __name__=="__main__":main()
