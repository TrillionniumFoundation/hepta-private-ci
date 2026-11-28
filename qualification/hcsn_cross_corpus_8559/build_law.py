"""Tabulate exact per-source-bin killed transition and solve the two prices independently."""
import argparse,hashlib,json,os,sys
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0,os.environ['HCSN_CORE'])
from population import BoundaryPopulation

def build(out,k):
    torch.set_num_threads(1);base=BoundaryPopulation(1,1,atoms=k)
    grid=torch.linspace(.015,.87,k,dtype=torch.float64);base.grid=grid;base.cuts=.5*(grid[1:]+grid[:-1]);reset=torch.zeros_like(grid)
    j=int(torch.searchsorted(grid,torch.tensor(.30)));reset[j]=(.30-grid[j-1])/(grid[j]-grid[j-1]);reset[j-1]=1-reset[j]
    p=base.prices;shift=torch.linspace(-.8,.8,4097,dtype=torch.float64);surv,hit=base.kernels(shift[:,None]+grid[None]);kernel=torch.cat((surv,hit[...,None]),-1)
    def prices(u):
        e,l=base.priced_channels(torch.tensor(p.p.P0*(1+.28*u),dtype=torch.float64));return torch.stack([e,l],-1)/20.
    mid=prices(0);dp=(prices(1)-prices(-1))/2;assert (prices(.37)-(mid+.37*dp)).abs().max()<1e-11
    base.grid=torch.tensor([.18-1e-5,.18,.18+1e-5],dtype=torch.float64);vals=prices(0);center=vals[1];slope=(vals[2]-vals[0])/.00002;du=(prices(1)[1]-prices(-1)[1])/2
    rng=np.random.default_rng(1461);z=rng.uniform(-.65,.65,1500);rr,hh=base.kernels(torch.tensor(z)[:,None]+grid);exact=torch.cat((rr,hh[...,None]),-1).numpy();u=(z+.8)*(4096/1.6);i=np.floor(u).astype(int);frac=(u-i)[:,None,None];kk=kernel.numpy();approx=kk[i]*(1-frac)+kk[i+1]*frac
    def arr(t):return np.asarray(t,dtype=np.float32)
    path=out/f'law{k}.npz';np.savez(path,grid=arr(grid),reset=arr(reset),kernel=arr(kernel),pmid=arr(mid),pd=arr(dp),center=arr(center),slope=arr(slope),du=arr(du),kappa=arr(.28*p.bp*p.p.P0/p.B0))
    au={'grid':grid.tolist(),'max_halfstep_transition_error':float(abs(approx-exact).max()),'max_probability_row_sum_error':float((kernel.sum(-1)-1).abs().max()),'sha':hashlib.sha256(path.read_bytes()).hexdigest()};assert au['max_probability_row_sum_error']<1e-12 and au['max_halfstep_transition_error']<.002;return au
if __name__=='__main__':
    out=Path(sys.argv[1]);(out/'law_audit.json').write_text(json.dumps({k:build(out,k) for k in [4,12]},indent=1))
