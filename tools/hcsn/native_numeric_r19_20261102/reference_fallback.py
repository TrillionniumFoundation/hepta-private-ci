"""Public-state-only dense reference decision when native gap guard fails.

This returns a separately identified SciPy reference action. It never repairs a
native qualification result, changes a provider state, or reads future targets.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.linalg import expm
from .provider import unseal

def decision(model_path,state_path):
    model={line.split()[0]:np.asarray([float(v)for v in line.split()[1:]])for line in model_path.read_text().splitlines()[1:]}
    q=model["Q"].reshape(40,40);emissions={2:model["READ"].reshape(40,5),3:model["REFRESH"].reshape(40,4)}
    lines=unseal(state_path.read_bytes()).splitlines();h=lines[0].split("\t")
    key,dt,scale,clock,remaining=int(h[7]),float(h[8]),float(h[11]),float(h[12]),3-int(h[13])
    anchors=np.asarray([float(v)for v in lines[1].split("\t")[1:]])
    beliefs=np.asarray([float(v)for v in lines[2].split("\t")[1:]]).reshape(4,40)
    anchored=h[3]=="anchored";p=beliefs[key]@expm((clock-anchors[key])*q)if anchored else beliefs[key]
    ps={t:expm(t*dt*q)for t in range(4)}
    def project(p):
        groups=np.r_[p[:32].reshape(8,4).sum(0),p[32:].reshape(2,4).sum(0)]
        return np.r_[np.tile(groups[:4]/8,8),np.tile(groups[4:]/2,2)]
    def values(p,left):
        result=[float((p@ps[left]).reshape(10,4).sum(0).max()),-np.inf,-np.inf,-np.inf]
        if not left:return result
        result[1]=max(values(p@ps[1],left-1))-.003*dt
        for action,slots,fee in [(2,1,.025*scale),(3,2,.07*scale)]:
            if slots>left:continue
            before=p@ps[slots];gain=0.
            for emission in emissions[action].T:
                post=before*emission;mass=float(post.sum());post=post/mass if mass>0 else model["PRIOR"]
                if anchored:post=project(post)
                gain+=mass*max(values(post,left-slots))
            result[action]=gain-fee-.003*slots*dt
        return result
    v=values(p,remaining);order=["STOP","WAIT","READ","REFRESH"]
    return dict(source="independent_scipy_dense_reference",action=order[int(np.argmax(v))],
        answer=int(np.argmax((p@ps[remaining]).reshape(10,4).sum(0))),
        values={a:(x if np.isfinite(x)else None)for a,x in zip(order,v,strict=True)},
        model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),state_sha256=hashlib.sha256(state_path.read_bytes()).hexdigest(),
        native_qualification=False,scope="Public owned belief and model only; separately metered reference fallback, not tolerance-based native retie or production activation")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("model",type=Path);p.add_argument("state",type=Path);p.add_argument("output",type=Path);a=p.parse_args()
    with a.output.open("x")as stream:json.dump(decision(a.model,a.state),stream,indent=2,sort_keys=True);stream.write("\n")
