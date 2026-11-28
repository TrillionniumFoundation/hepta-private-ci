"""Target single-step values, adjoints and directional derivatives at and between interpolation knots."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from native import FusedStep,COST
from model import Population

def ref(pop,u,wall,mass,refr,emitter,fixed):
    t=u.tanh();rel=0.*t if fixed else .21*t;w=torch.log1p(pop.beta*rel);mu=-.10+.25*t
    shift=(w-wall+.45)/.005;j=(mu+.35)/.0125
    shift=shift.clamp(0,180);j=j.clamp(0,40)
    I=shift.long().clamp(max=179);J=j.long().clamp(max=39)
    x=(shift-I)[...,None,None];y=(j-J)[...,None,None]
    i=I*41+J;tab=pop.table.to(u)
    kernel=torch.lerp(torch.lerp(tab[i],tab[i+1],y),torch.lerp(tab[i+41],tab[i+42],y),x)
    a=(mass[...,None]*kernel).sum(-2);alive=a[...,:4]+refr[...,None]*pop.reset.to(u)
    c=pop.coeff.to(u);price=(alive[...,None]*(c[0]+rel[...,None,None]*c[1])).sum(-2)
    ht=pop.probes.to(u);h=(alive[...,None]*torch.lerp(ht[J],ht[J+1],y)).sum(-2)
    sig=(torch.cat([w[...,None],a[...,4:5],price,h],-1)*emitter).sum(-1)
    return torch.cat([w[...,None],alive,a[...,4:5],price,sig[...,None]],-1)
def metric(a,b):
    a=a.detach().double();b=b.detach().double()
    return {'max_abs':float(torch.max(abs(a-b))),'relative_l2':float(torch.linalg.norm(a-b)/max(1e-12,float(torch.linalg.norm(a))))}
def run(out):
    torch.set_num_threads(1);gen=torch.Generator().manual_seed(71894)
    rows=[]
    for family in ('literal','smooth','fixed'):
        pop=Population(28,family);fixed=family=='fixed'
        for seq,case in enumerate(('random','absorbed','refractory','between_knots','knot_left','knot_right','knot_exact')):
            u=.8*torch.randn((16,48),generator=gen)
            if 'knot' in case:
                # Set fixed physical offset, including an atom that instantaneously crosses the wall.
                bases=torch.tensor([.025,.09,.18,.34])[torch.randint(4,u.shape,generator=gen)]
                additions={'between_knots':.0017,'knot_left':-2.e-6,'knot_right':2.e-6,'knot_exact':0.}
                shift=bases+additions[case]
            else:shift=.65*(torch.rand(u.shape,generator=gen)-.5)
            w=torch.log1p(pop.beta*(0. if fixed else .21)*u.tanh())-shift
            density=torch.rand((*u.shape,5),generator=gen)
            density=density/density.sum(-1,keepdim=True)
            if case=='refractory':density[:]=0.;density[...,4]=1.
            if case=='absorbed':density[:]=0.;density[...,0]=1.;w=torch.full_like(w,-.50)
            args=[a.detach().clone().requires_grad_() for a in (u,w,density[...,:4],density[...,4],pop.emitter)]
            g=torch.randn((*u.shape,9),generator=gen)
            a=ref(pop,*args,fixed)
            b=FusedStep.apply(*args[:4],pop.table,pop.coeff,pop.probes,args[4],pop.beta,fixed)
            da=torch.autograd.grad((a*g).sum(),args)
            db=torch.autograd.grad((b*g).sum(),args)
            row=dict(family=family,case=case,values=metric(a,b),backward={k:metric(l,r) for k,l,r in zip(('u','previous_wall','mass','refractory','emit'),da,db)})
            if case=='between_knots':
                args64=[v.detach().double().requires_grad_() for v in args]
                # Use the previous-wall direction, bounded to stay within the selected interpolation cell.
                d=torch.rand(u.shape,generator=gen).double()-.5;d/=d.norm()
                actual=torch.autograd.grad((ref(pop,*args64,fixed)*g).sum(),args64)[1]
                h=1.e-5
                def perturbed(amount):return (ref(pop,args64[0],args64[1]+amount*d,*args64[2:],fixed)*g).sum()
                fd=float(((perturbed(h)-perturbed(-h))/(2*h)).detach())
                row['wall_fd']=dict(central=fd,eager64=float((actual*d).sum()),native32=float((db[1].double()*d).sum()))
            rows.append(row)
    out.write_text(json.dumps(rows,indent=1)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();run(a.out)
