"""Create a model-bound table and preserve its numerical/domain identity."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"returning_regimes"))
import lattice
from lattice import Contract, solve

ARMS=("stationary","irreversible","returning")


def build(source, folder):
    if sha256(source.read_bytes()).hexdigest()!="de7378f3c170750fb16d1280bcaa376a8904a207da32d268cac82525469e2ea4":
        raise ValueError("unregistered law")
    with np.load(source) as f:
        x = f["grid"].astype(float)
    folder.mkdir(exist_ok=True,parents=True)
    u=np.linspace(-1.,1.,65)
    manifest={}
    for arm in ARMS:
        start=time.perf_counter()
        walls,prices=[],[]
        for drive in u:
            p=replace(Contract(),principal=61.68*(1+.28*drive))
            rates=(0.,0.) if arm=="stationary" else (.75+.7*drive,.35 if arm=="returning" else 0.)
            a=solve(p=p,rates=rates,steps=96,gradients=False)
            w=a.walls[0]
            margins=np.log(w)+x
            prices.append(np.stack([np.interp(margins,np.log(a.assets),v[0]) for v in (a.equity,a.loss)],axis=-1))
            walls.append(w)
        path=folder/(arm+".npz")
        wall=np.asarray(walls)
        np.savez_compressed(path,u=u,grid=x,wall=wall,mark=np.log(wall/wall[len(u)//2]),
                            prices=np.asarray(prices)/20.)
        manifest[arm]=dict(file=path.name,sha256=sha256(path.read_bytes()).hexdigest(),
                           setup_seconds=time.perf_counter()-start,wall_range=[min(walls),max(walls)])
        print(arm,manifest[arm],flush=True)
    (folder/"tables.json").write_text(json.dumps(manifest,indent=2)+"\n")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("source",type=Path)
    parser.add_argument("destination",type=Path)
    args=parser.parse_args()
    build(args.source,args.destination)
