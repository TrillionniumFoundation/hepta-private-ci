"""Preserve the matched three-seed cold rankings and weights at one fixed horizon."""
import argparse, hashlib, io, json, lzma, zipfile
from pathlib import Path
import numpy as np

def digest(b):return hashlib.sha256(b).hexdigest()
def write(data,budget,dest):
    root=data/"hybrid_long";dest.mkdir(parents=True,exist_ok=True);files={}
    for name in [f'seal-{budget}.json',f'cold-{budget}.npz',f'outcome-{budget}.json']:
        files[name]=(root/name).read_bytes()
    seals=json.loads(files[f'seal-{budget}.json']);outcomes=json.loads(files[f'outcome-{budget}.json'])
    paired=[]
    with np.load(io.BytesIO(files[f'cold-{budget}.npz'])) as arr,np.load(data/'short'/'cold_ranks.npz') as base:
        for seed,selected in sorted(seals.items()):
            state=(root/seed/selected["state"]).read_bytes();assert digest(state)==selected["hash"]
            files[f'{seed}/'+selected["state"]]=state
            history=[json.loads(l) for l in (root/seed/'history.jsonl').read_text().splitlines()]
            eligible=[row for row in history if row["time"]<=budget]
            expected=max([r for r in eligible if r["state"]],key=lambda r:(r["dev_r1"],r["dev_r5"],-r["time"]));assert expected==selected
            files[f'{seed}/eligible.json']=json.dumps(eligible,separators=(',',':')).encode()
            files[f'{seed}/cost.json']=(root/seed/f'budget-{budget}.json').read_bytes()
            r=arr[seed];assert r.shape==(2,964,3)
            for rank in (1,5,10):
                metric=float((r[:,:,0]<=rank).mean())
                assert abs(metric-outcomes["scores"][seed][f"strict_R{rank}"])<1e-14
            paired.append(((r[:,:,0]==1).astype(float)-(base[f'literal/{seed}/60'][:,:,0]==1)).mean(0))
    delta=float(np.mean(paired));assert abs(delta-outcomes['delta_vs_frozen'])<1e-14
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w',zipfile.ZIP_STORED) as z:
        for name,b in sorted(files.items()):z.writestr(zipfile.ZipInfo(name,(2026,11,27,0,0,0)),b)
    raw=mem.getvalue();transport=lzma.compress(raw,preset=4);chunks=[]
    for i in range(0,len(transport),360000):
        b=transport[i:i+360000];name=f'part{i//360000:03d}.bin';(dest/name).write_bytes(b);chunks.append(dict(file=name,size=len(b),sha256=digest(b)))
    manifest=dict(delivery_encoding='xz',zip_sha256=digest(raw),delivery_sha256=digest(transport),delivery_bytes=len(transport),zip_bytes=len(raw),chunks=chunks,files={n:digest(v) for n,v in files.items()});(dest/'manifest.json').write_text(json.dumps(manifest,indent=1))
    (dest/'outcome.json').write_text(json.dumps(outcomes,indent=1));(dest/'seal.json').write_text(json.dumps(seals,indent=1))
    print(budget,delta,len(chunks),len(transport))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('budget',type=int);p.add_argument('dest',type=Path);args=p.parse_args();write(args.data,args.budget,args.dest)
