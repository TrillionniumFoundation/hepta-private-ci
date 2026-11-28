"""NumPy-only score and paired actor-effect replay of all sealed discriminant candidates."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def verify(root):
    seal=json.loads((root/"development_seal.json").read_text())
    end=json.loads((root/"terminal.json").read_text())
    assert sha(root/"development_seal.json")==end["seal_sha256"]
    prior=np.log(np.array(seal["counts"])/sum(seal["counts"]))
    lossmap={}
    refids=refy=None
    number=0
    for k,rr in seal["candidates"].items():
        lossmap[k]={}
        for r in rr:
            path=root/r["path"]
            assert sha(path)==r["file_sha256"]
            with np.load(path.with_suffix(".npz")) as a:
                y,z,ids=a["labels"],a["scores"].astype(np.float64),a["ids"]
            assert z.shape==(1311,72)
            if refids is None:
                refids,refy=ids,y
            else:
                np.testing.assert_array_equal(ids,refids)
                np.testing.assert_array_equal(y,refy)
            for mode in ("raw","temperature_prior"):
                logits=z.copy() if mode=="raw" else r["temperature"]*z+prior
                logits-=logits.max(1,keepdims=True)
                loss=np.log(np.exp(logits).sum(1))-logits[np.arange(len(y)),y]
                vals=[loss.mean(),(logits.argmax(1)==y).mean()]
                reported=end["cold"][k][str(r["steps"])][mode]
                np.testing.assert_allclose(vals,[reported["nll"],reported["top1"]],atol=1e-11,rtol=1e-11)
                selected=min(rr,key=lambda v:(v["dev"][mode]["nll"],v["steps"]))["path"]
                assert seal["picks"][k][mode]==selected
                if selected==path.name:
                    lossmap[k][mode]=loss
            number+=1
    assert number==24
    who,act=np.unique([i.split("_")[0] for i in refids],return_inverse=True)
    assert len(who)==16
    ix=np.random.default_rng(91363).integers(16,size=(4000,16))
    for mode,entries in end["differences"].items():
        for method,rec in entries.items():
            d=np.mean([lossmap[f"full-{s}"][mode]-lossmap[f"{method}-{s}"][mode] for s in (137,311,557)],0)
            sums=np.bincount(act,weights=d)
            ci=np.quantile(sums[ix].sum(1)/np.bincount(act)[ix].sum(1),[.025,.975])
            np.testing.assert_allclose([d.mean(),*ci],[rec["nll"],*rec["ci95"]],atol=1e-11,rtol=1e-11)
    return dict(verified=True,candidates=number,cold_logits=number*1311*72,actors=len(who),paired_actor_contrasts=6,
                terminal_sha256=sha(root/"terminal.json"))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("directory",type=Path)
    print(json.dumps(verify(p.parse_args().directory),indent=2))
