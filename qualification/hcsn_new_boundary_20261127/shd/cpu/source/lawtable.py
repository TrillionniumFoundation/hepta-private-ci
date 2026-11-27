"""Tabulate the shared published law and audit interpolation against direct FP64."""
import argparse
from pathlib import Path
import numpy as np
import torch
from common import record,sha,usage
from literal_law import Published

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    torch.set_num_threads(1)
    law=Published()
    def raw(v):
        principal=law.p.P0*(1+.28*v.tanh())
        x=.18-(law.boundary(principal)/law.B0).log()
        e,f=law.values(x,torch.tensor(law.p.P0,dtype=torch.float64))
        return torch.stack((e/20.,f),-1)
    g=torch.linspace(-12.,12.,16385,dtype=torch.float64)
    r=raw(g)
    anchor=raw(g[8192])
    width=r.amax(0)-r.amin(0)
    normalized=(r-anchor)/width
    held=torch.linspace(-11.9743,11.9211,12051,dtype=torch.float64)
    direct=((raw(held)-anchor)/width).detach().numpy()
    v=held.numpy()
    lookup=np.stack([np.interp(v,g.numpy(),normalized[:,j].numpy()) for j in range(2)],-1)
    dx=1e-6
    test=torch.tensor([-.72,-.26,.11,.49],dtype=torch.float64)
    deriv=(raw(test+dx)-raw(test-dx))/(2*dx)/width
    positions=np.searchsorted(g.numpy(),test.numpy())
    sec=(normalized.numpy()[positions]-normalized.numpy()[positions-1])/(24./16384)
    deriv0=((raw(g[8192]+dx)-raw(g[8192]-dx))/(2*dx)/width).numpy()
    amp=np.maximum(np.abs(normalized.numpy().min(0)),np.abs(normalized.numpy().max(0)))
    out=args.out
    np.savez(out/'law.npz',lut=normalized.numpy().astype('f4'),smooth_k=(deriv0/amp).astype('f4'),smooth_amp=amp.astype('f4'))
    record(out/'law.json',dict(alpha=law.p.alpha, kappa=.28*law.bp*law.p.P0/law.B0,range_raw=width.tolist(),
         anchor=anchor.tolist(), table_count=len(g), abs_lookup_error=np.max(abs(lookup-direct),axis=0).tolist(),
         interior_slope_abs_error=np.max(abs(sec-deriv.numpy()),axis=0).tolist(),
         src=sha(Path(__file__).with_name('literal_law.py')),npz=sha(out/'law.npz'),**usage()))
if __name__=='__main__':main()
