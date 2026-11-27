"""Check every continuous port and independent directional derivatives without any MOSI test labels."""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
import torch
from models import Physical,ThreeStage,initialize_norms
from source import sha


def main():
    q=argparse.ArgumentParser();q.add_argument('law',type=Path);q.add_argument('reference',type=Path);q.add_argument('out',type=Path);a=q.parse_args()
    torch.set_num_threads(1);torch.manual_seed(39119);sys.path.insert(0,str(a.reference));from receiver import Cell
    ref=Cell(a.law);law=Physical(a.law).double();rng=np.random.default_rng(89417)
    maxes=[]
    for amp in (.15,.7,2.):
        x=rng.normal(0,amp,size=(23,6,19));target,_=ref.run(x);actual=law(torch.tensor(x)).reshape(target.shape).detach().numpy()
        diff=np.max(abs(target-actual),axis=(0,1,2));maxes.append(diff.tolist());assert diff.max()<1e-12
    md=ThreeStage(7,'bp_h',a.law).double();x=torch.randn(16,6,793,dtype=torch.float64)*.4
    initialize_norms(md,x);target=torch.randn(len(x),dtype=torch.float64);loss=(md(x)-target).square().mean();loss.backward()
    gradient={}
    for key,p in md.named_parameters():
        rows=[]
        for _ in range(4):
            dv=torch.randn_like(p);dv/=dv.norm();old=p.detach().clone();eps=1.e-7
            with torch.no_grad():
                p.copy_(old+eps*dv);up=(md(x)-target).square().mean().item()
                p.copy_(old-eps*dv);down=(md(x)-target).square().mean().item();p.copy_(old)
            obs=(up-down)/(2*eps);expect=float((p.grad*dv).sum());rows.append([expect,obs,abs(expect-obs)])
        gradient[key]=rows;assert max(r[2] for r in rows)<2e-5
    a.out.write_text(json.dumps({'reference_sha256':sha(a.reference/'receiver.py'),'law_sha256':sha(a.law),'tested_scalar_port_values':3*23*6*19*4,'max_port_discrepancy_per_amplitude':maxes,'directions':gradient},indent=1)+'\n');print(max(max(a) for a in maxes),max(max(x[2] for x in v) for v in gradient.values()))


if __name__=='__main__':main()
