"""Physical wall precision, noise-limited binary readability, and finite-state recall."""
from pathlib import Path
import json
import math
import sys
import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr
import torch
src=Path(__file__).resolve().parents[2]/"hcsn_sustained_20261128"/"boundary_port"
sys.path.insert(0,str(src))
from port import port_gain,Stationary,drive,root,rate


def entropy(p):
    if p in (0,1):return 0.
    return -(p*math.log2(p)+(1-p)*math.log2(1-p))


def info_per_token(error,q):
    return math.log2(q)-entropy(error)-error*math.log2(q-1)


def converse(bits,n,q=256):
    rho=bits/n
    if rho>=math.log2(q):return 0.
    return brentq(lambda e:info_per_token(e,q)-rho,0.,1.-1/q)


def run():
    base=Stationary().B;precision=[]
    for eps in (.001,.005,.025):
        pair=[port_gain(eps,1.,b) for b in ("low","high")]
        walls=np.array([z["physical_sender_boundary"] for z in pair])
        bound=np.log(walls/base)
        original=np.array([z["receiver_rate"] for z in pair])
        def read(message):
            state=Stationary(drive=drive(float(message)))
            return rate(root(lambda u:state.stationary(u)[0],"high"))
        checks=[]
        for tp in (torch.float32,torch.float16,torch.bfloat16):
            for codec in ("absolute","centered_log"):
                stored=torch.as_tensor(walls if codec=="absolute" else bound).to(tp)
                restored=stored.to(torch.float64).numpy()
                read_wire=np.log(restored/base) if codec=="absolute" else restored
                received=[read(y) for y in read_wire]
                checks.append(dict(dtype=str(tp),codec=codec,stored=restored.tolist(),
                                   distinguishable=bool(stored[0]!=stored[1]),
                                   receiver_rates=received,rate_contrast=received[1]-received[0]))
        noise=[]
        for sd in (.00001,.00005,.0001,.0005,.001):
            probability=float(ndtr(-(bound[1]-bound[0])/(2*sd)))
            noise.append(dict(sd=sd,best_equal_prior_error=probability))
        precision.append(dict(epsilon=eps,base=base,walls=walls.tolist(),log_wire=bound.tolist(),
                              exact_rate_contrast=float(np.diff(original)[0]),checks=checks,noise=noise))
    assert abs(precision[-1]["exact_rate_contrast"]-0.0007769986)<5e-8
    capacity={}
    for name,b in (("reported_hcsn_stream",5376),("reported_lif_stream",3072)):
        bits=b*8
        capacity[name]=dict(bytes=b,q=256,max_n_99pct=math.floor(bits/info_per_token(.01,256)),
            min_error={str(n):converse(bits,n) for n in (4096,8192,16384,32768,131072)})
    return dict(precision=precision,uniform_iid_random_address=capacity)
if __name__=="__main__":
    r=run()
    Path(__file__).with_name("verified.json").write_text(json.dumps(r,indent=2)+"\n")
    for v in r["precision"]:
        print(v["epsilon"],v["walls"],[(a["dtype"],a["codec"],a["distinguishable"],a["rate_contrast"]) for a in v["checks"]])
    print(r["uniform_iid_random_address"])
