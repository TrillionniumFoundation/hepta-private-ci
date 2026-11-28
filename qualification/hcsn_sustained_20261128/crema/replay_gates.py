"""Replay every development-selected quality gate and persist its complete held-actor scores."""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from study import Data, HASHES, digest, inference, write_json
from verify_sustained import verify, scoring


def replay(source, result, dest):
    dest.mkdir(exist_ok=True,parents=True)
    for rel,h in HASHES.items():
        if digest(source/rel)!=h:
            raise ValueError(rel)
    sys.path.insert(0,str(source/"src"))
    from encoder import AVText
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    summary=verify(result)
    seal=json.loads((result/"seal.json").read_text())
    original=json.loads((result/"terminal.json").read_text())
    data=Data(source)
    y=data.y[data.test].numpy()
    idx=data.names[data.test]
    counts=0
    for key,config in seal.items():
        arm,ss=key.split("-")
        net=AVText(arm,96,int(ss),data.words,source/"src/law4.npz")
        keep={row["file"]:row for row in [config["best"],*config["gates"].values()] if row}
        keys={}
        for filename,rec in keep.items():
            start=time.perf_counter()
            weights=result/key/filename
            if digest(weights)!=rec["sha256"]:
                raise ValueError("gate weight mismatch")
            net.load_state_dict(torch.load(weights,map_location="cpu",weights_only=True))
            arr=inference(net,data,data.test).numpy()
            if filename==config["best"]["file"]:
                with np.load(result/key/"cold.npz") as a:
                    np.testing.assert_array_equal(arr,a["scores"])
            nll,acc=scoring(arr,y)
            for gate,grow in config["gates"].items():
                if grow and grow["file"]==filename:
                    expected=original["cells"][key]["gates"][gate]["cold"]
                    np.testing.assert_allclose([nll.mean(),acc],[expected["nll"],expected["top1"]],atol=1e-6,rtol=3e-7)
            target=dest/(key+"-"+weights.stem+".npz")
            np.savez_compressed(target,scores=arr,ids=idx,y=y)
            keys[filename]=dict(weight_sha256=rec["sha256"],scores_sha256=digest(target),scores_file=target.name,
                                nll=float(nll.mean()),top1=acc,independent_cold_seconds=time.perf_counter()-start)
            counts+=arr.size
        summary["cells"][key]["independent_replay"]=keys
    summary["replayed_gate_and_best_logits"]=counts
    summary["source_data_sha256"]=HASHES["data/data.npz"]
    write_json(dest/"VERIFIED.json",summary)
    print("verified all gates",digest(dest/"VERIFIED.json"),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("source",type=Path)
    p.add_argument("result",type=Path)
    p.add_argument("dest",type=Path)
    a=p.parse_args()
    replay(a.source,a.result,a.dest)
