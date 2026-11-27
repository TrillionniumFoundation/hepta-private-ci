"""Validate the public binary pieces, the selection lock, and all row-level retrieval metrics."""
import argparse, hashlib, io, json, lzma, zipfile
from pathlib import Path
import numpy as np

def verify(directory):
    manifest=json.loads((directory/"manifest.json").read_text())
    chunks=[]
    for part in manifest["chunks"]:
        data=(directory/part["file"]).read_bytes()
        assert len(data)==part["size"] and hashlib.sha256(data).hexdigest()==part["sha256"]
        chunks.append(data)
    delivery=b"".join(chunks)
    if "delivery_sha256" in manifest:assert hashlib.sha256(delivery).hexdigest()==manifest["delivery_sha256"]
    data=lzma.decompress(delivery) if manifest.get("delivery_encoding")=="xz" else delivery
    assert hashlib.sha256(data).hexdigest()==manifest["zip_sha256"]
    p=manifest["panel"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert len(z.namelist())==manifest["files"]
        for name,digest in manifest["inputs"].items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
        results=json.loads(z.read(p+"/results.json"));sealed=json.loads(z.read(p+"/seal.json"))
        state_map=json.loads(z.read("state_map.json"));checked=0;maxdiff=0
        with np.load(io.BytesIO(z.read(p+"/cold_ranks.npz"))) as ranks:
            for name,state in sealed.items():
                if state is None:assert name not in results["scores"];continue
                fp=state["sha256"];assert hashlib.sha256(z.read(state_map[name])).hexdigest()==fp
                a=ranks[name];assert a.shape[0]==2 and a.shape[2]==3 and np.all((a>=1)&(a<=a.shape[1]))
                for k in [1,5,10]:
                    val=(a[:,:,0]<=k).mean()
                    maxdiff=max(maxdiff,abs(val-results["scores"][name]["strict_R"+str(k)]));checked+=1
                if p!="warm":
                    kind,seed,budget=name.split("/")
                    source_panel="short" if p=="long" and kind!="conventional" else p
                    h=json.loads(z.read(source_panel+"/"+kind+"-"+seed+"/history.json"))
                    options=[r for r in h if r.get("state") and r["time"]<=int(budget)]
                    best=max(options,key=lambda x:(x["dev_r1"],x["dev_r5"],-x["time"]));assert best["hash"]==fp
    if maxdiff>1e-14:raise AssertionError(maxdiff)
    return {"panel":p,"archive_files":manifest["files"],"independent_r1_r5_r10_metrics":checked,"max_abs_error":maxdiff,"sha256":manifest["zip_sha256"]}
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("dir",type=Path);print(json.dumps(verify(parser.parse_args().dir),indent=1))
