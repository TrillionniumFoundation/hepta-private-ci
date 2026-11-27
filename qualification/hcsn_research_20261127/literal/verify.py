"""Independent quadrature and finite-difference checks for the literal financial cell."""
import json, sys
from pathlib import Path
import numpy as np
import torch
from scipy.integrate import quad
from scipy.stats import norm
from dataclasses import replace
from hx_crosscheck import Calibration, HeXiong
from cell import Law, Published, LiteralCell
ROOT=Path(__file__).resolve().parent
def main():
    stats={'E_quadrature':0.,'E_published':0.,'F_ref':0.,'mean_quadrature':0.,'B_free_boundary':0.,'gradient_x':0.,'gradient_P':0.}
    def add(name,a,b):
        stats[name]=max(stats[name],abs(float(a)-float(b)))
    for prem in [.01,.03,.06]:
        law=Published(Law(premium=prem))
        for p in [46.,61.68,77.]:
            ref=HeXiong(replace(Calibration(),principal=p),prem)
            b=ref.boundary()
            add('B_free_boundary',law.boundary(p),b)
            for v in [0.,.002,.04,.18,.5,1.1]:
                x=torch.tensor(v,dtype=torch.double,requires_grad=True)
                pp=torch.tensor(p,dtype=torch.double,requires_grad=True)
                a,f=law.values(x,pp)
                add('E_published',a.detach(),ref.equity_closed(v,b))
                add('E_quadrature',a.detach(),ref.equity_integral(v,b))
                add('F_ref',f.detach(),ref.passage(v,1.,ref.a))
                dt=.25;sig=.23*np.sqrt(dt)
                density=lambda y:norm.pdf(y,loc=v+law.mu*dt,scale=sig)-np.exp(-2*law.a*v)*norm.pdf(y,loc=-v+law.mu*dt,scale=sig)
                val=quad(lambda y:y*density(y),0,max(5.,v+2),epsabs=2e-13)[0]+.3*ref.passage(v,dt,ref.a)
                add('mean_quadrature',law.move_mean(x).detach(),val)
                if v>0:
                    dx,dp=torch.autograd.grad(a+f,(x,pp))
                    def independent(v,p):
                        r=HeXiong(replace(Calibration(),principal=p),prem)
                        return r.equity_integral(v,r.boundary())+r.passage(v,1.,r.a)
                    h=1e-5
                    add('gradient_x',dx,(independent(v+h,p)-independent(v-h,p))/(2*h))
                    h=.0001
                    add('gradient_P',dp,(independent(v,p+h)-independent(v,p-h))/(2*h))
    torch.manual_seed(425)
    net=LiteralCell();inp=torch.randn(8,3,6,dtype=torch.double,requires_grad=True)
    y,c=net(inp,diagnostics=True)
    g,=torch.autograd.grad(y[-1,:,1].sum(),inp)
    zz=net(inp,silence_boundary=True)
    gz,=torch.autograd.grad(zz[-1,:,1].sum(),inp)
    stats['link_grad_abs_max']=float(g.abs().max())
    stats['silenced_link_grad_abs_max']=float(gz.abs().max())
    stats['last_raw_frame_grad_abs_max']=float(g[-1].abs().max())
    stats['mechanism_crossing_count']=int(c.sum())
    assert max(stats[k] for k in ('E_quadrature','E_published','F_ref','mean_quadrature','B_free_boundary'))<1e-8
    assert max(stats['gradient_x'],stats['gradient_P'])<2e-5
    assert stats['link_grad_abs_max']>0 and stats['silenced_link_grad_abs_max']==0 and stats['last_raw_frame_grad_abs_max']==0
    (ROOT/'numerical.json').write_text(json.dumps(stats,indent=2))
    print(stats,flush=True)
if __name__=='__main__':main()
