"""Assemble successful, hash-bound semantic batches in canonical query order."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(roster, split, folder, out):
    stamp=time.monotonic()
    wanted=json.loads(roster.read_text())
    wanted={r["query_id"]:r for r in wanted}
    if not wanted or any(r["split"]!=split for r in wanted.values()):
        raise ValueError("invalid split")
    data={}
    used=[]
    candidates=sorted(folder.glob(f"{split}_*.receipt.json"))
    for rp in candidates:
        r=json.loads(rp.read_text())
        if r["status"]!="ok":
            continue
        stem=rp.name.removesuffix(".receipt.json")
        ar=folder/(stem+".npz")
        rr=folder/(stem+".roster.json")
        if r["output_sha256"]!=digest(ar) or r["roster_sha256"]!=digest(rr) or r["split"]!=split:
            raise ValueError("semantic batch receipt mismatch")
        manifest={j["query_id"]:j for j in json.loads(rr.read_text())}
        with np.load(ar,allow_pickle=False) as z:
            ids=z["query_id"].tolist()
            prob=z["probability"]
            if (set(ids)!=set(manifest) or len(ids)!=len(set(ids)) or prob.shape!=(len(ids),6,2)
                    or not np.isfinite(prob).all() or prob.min()<0 or prob.max()>1
                    or not np.allclose(prob.sum(-1),1,atol=1e-12,rtol=0)
                    or [row["query_id"] for row in r["rows"]]!=ids):
                raise ValueError("invalid probability rows")
            for id,arr,measured in zip(ids,prob,r["rows"]):
                if id not in wanted:
                    continue
                w=wanted[id];m=manifest[id]
                if (Path(w["local_media"]).resolve()!=Path(m["local_media"]).resolve()
                        or str(w["start_seconds"])!=str(m["start_seconds"])
                        or float(w["start_seconds"])!=measured["start_seconds"]
                        or w["recording"]!=m["recording"]):
                    raise ValueError(f"source binding changed: {id}")
                if id in data:
                    raise ValueError(f"duplicate semantic inference: {id}")
                data[id]=arr.copy()
        used.append({"file":rp.name,"sha256":digest(rp),"process_wall_seconds":r["wall_seconds"],
                     "process_cpu_seconds":r["cpu_seconds"],"child_cpu_seconds":r["child_cpu_seconds"],
                     "queries":r["queries"],"weight_sha256":r["weight_sha256"],
                     "torchvision":r["torchvision"],"script_sha256":r["script_sha256"]})
    if set(data)!=set(wanted):
        raise ValueError(f"missing {len(set(wanted)-set(data))} required semantic queries")
    if len({(x["weight_sha256"],x["script_sha256"],x["torchvision"]) for x in used})!=1:
        raise ValueError("mixed model or decoder identities")
    with out.open("xb") as f:
        np.savez_compressed(f,query_id=np.array(list(wanted)),probability=np.stack([data[k] for k in wanted]))
    meta=dict(status="ok",split=split,queries=len(wanted),roster_sha256=digest(roster),
              output_sha256=digest(out),parts=used,assembly_wall_seconds=time.monotonic()-stamp,
              process_sum_wall_seconds=sum(p["process_wall_seconds"] for p in used),
              energy_joules=None)
    with out.with_suffix(".receipt.json").open("x") as f:
        json.dump(meta,f,allow_nan=False,indent=2)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("roster",type=Path)
    p.add_argument("split")
    p.add_argument("folder",type=Path)
    p.add_argument("out",type=Path)
    a=p.parse_args()
    assemble(a.roster,a.split,a.folder,a.out)
