"""A two-source marked continuum Chapman--Kolmogorov check with live pending ages.

At a split time an initial source has an active density over all release orders
and an exact residual waiting-time law for each possible prior hit. Both measures are integrated
over their actual continuum supports. No projected bins are propagated as
point masses. A linear moving physical boundary is a change of coordinates
with effective drift equal to physical drift minus velocity.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from numpy.polynomial.legendre import leggauss as roots_legendre
import torch

from qualification.hcsn_halfline_transport import finite_marked as product


SOURCES = [(0.35,0.23,[0.7,-0.45]),(0.65,0.46,[-0.3,0.8])]
EDGES = np.array([0,.08,.18,.32,.57,1])
POINTS = np.array([.11,.21,.43,.82])
PHASE = [0,.2,.55,1]
MATRIX = np.array([[.68,.24],[-.21,.81]])
DRIFT, SIGMA, RESET, DELAY, END = -.35,.58,.21,.14,.39


def gauss(a,b,n):
    nodes,w = roots_legendre(n)
    return a+(b-a)*(nodes+1)/2, (b-a)*w/2


def tensor(x):
    return torch.tensor(x,dtype=torch.float64)


def run(module,x,mark,t,drift=DRIFT,reset=RESET,edges=EDGES,points=POINTS):
    return module.finite_marked_state(*map(tensor,(x,drift,SIGMA,reset,DELAY,t,mark,MATRIX,edges,PHASE,points)))


def row(z):
    return np.concatenate([z.state.probability.numpy().ravel(),z.state.content_mass.numpy().ravel(),
                           z.density_by_release.sum(0).numpy(),z.density_content.numpy().ravel(),
                           [z.event_probability_by_hit.sum().item(),z.event_rate_by_hit.sum().item()],
                           z.marked_cumulative_hits.numpy(),z.marked_event_rate.numpy()])


def components(a):
    return {name:a[lo:hi] for name,lo,hi in (("P",0,9),("C",9,27),("density",27,31),("density_content",31,39),
            ("cumulative_hits",39,40),("rate",40,41),("marked_cumulative_hits",41,43),("marked_rate",43,45))}


def first_density(z,u):
    return z*np.exp(-(z+DRIFT*u)**2/(2*SIGMA**2*u))/(SIGMA*np.sqrt(2*np.pi)*u**1.5)


def time_measure(left,right,order):
    angle,weights=gauss(0,np.pi/2,order)
    sine,cosine=np.sin(angle),np.cos(angle)
    return left+(right-left)*sine**2,(right-left)*cosine**2,2*(right-left)*sine*cosine*weights


def killed(start,h,y):
    variance=SIGMA**2*h
    return (np.exp(-(y-start-DRIFT*h)**2/(2*variance))/np.sqrt(2*np.pi*variance)
            * -np.expm1(-2*start*y/variance))


def compose(module,order,split):
    value=np.zeros(45)
    incoming=[]
    # All currently pending sources will release before the final observation.
    assert END-split>DELAY
    for weight,x,mark_list in SOURCES:
        mark=np.array(mark_list)
        active_mass=0.0
        phase_mass=0.0
        # An independent positive time convolution, at every spatial node,
        # gives the intermediate density after any completed releases.
        # Split at the reset cusp before performing the outer spatial rule.
        upper=max(x,RESET)+abs(DRIFT)*split+11*SIGMA*math.sqrt(split)
        cut=sorted({0.,RESET,upper})
        for left,right in zip(cut,cut[1:]):
            y,w=gauss(left,right,order)
            for j in range(int(split/DELAY)+1):
                if j==0:
                    pdf=killed(x,split,y)
                else:
                    z=x+(j-1)*RESET
                    h=split-j*DELAY
                    theta,wtheta=gauss(0,np.pi/2,4*order)
                    sn,cs=np.sin(theta),np.cos(theta)
                    denominator=sn**4+cs**4
                    u=h*sn**4/denominator
                    remaining=h*cs**4/denominator
                    wu=4*h*wtheta*(sn*cs)**3/denominator**2
                    pdf=(wu*first_density(z,u)) @ killed(RESET,remaining[:,None],y[None,:])
                source_mark=np.linalg.matrix_power(MATRIX,j)@mark
                for probability,position in zip(w*pdf,y):
                    value+=weight*probability*row(run(module,position,source_mark,END-split))
                active_mass+=float(w@pdf)
        for n in range(1,int(split/DELAY)+2):
            z=x+(n-1)*RESET
            stop=split-(n-1)*DELAY
            start=max(0.,split-n*DELAY)
            if stop<=0:
                continue
            u,_,w=time_measure(0,stop,2*order)
            previous_hit=float(w@first_density(z,u))
            value[39]+=weight*previous_hit
            value[41:43]+=weight*previous_hit*(np.linalg.matrix_power(MATRIX,n-1)@mark)
            # Retain every residual time, including crossings of later phase edges.
            points={start,stop}
            for j in range(int(END/DELAY)+2):
                for f in PHASE:
                    point=END-n*DELAY-j*DELAY+f*DELAY
                    if start<point<stop:
                        points.add(point)
            cut=sorted(points)
            next_mark=np.linalg.matrix_power(MATRIX,n)@mark
            for low,high in zip(cut,cut[1:]):
                u,_,w=time_measure(low,high,order)
                crossing=w*first_density(z,u)
                phase_mass+=float(np.sum(crossing))
                for probability,first_hit in zip(crossing,u):
                    value+=weight*probability*row(run(module,RESET,next_mark,END-first_hit-n*DELAY))
        incoming.append({"weight":weight,"active_mass":active_mass,"waiting_mass":phase_mass})
    return value,incoming


def flux(module):
    probability=0.0; signed=np.zeros(2); emitted=0.0; emitted_signed=np.zeros(2)
    for w,x,mark in SOURCES:
        y=tensor([0.0]).requires_grad_()
        z=module.finite_marked_state(*map(tensor,(x,DRIFT,SIGMA,RESET,DELAY,END,mark,MATRIX,EDGES,PHASE)),y)
        derivative=lambda out:torch.autograd.grad(out,y,retain_graph=True)[0].item()
        probability+=w*SIGMA**2/2*derivative(z.density_by_release.sum())
        signed+=w*SIGMA**2/2*np.array([derivative(z.density_content[0,i]) for i in range(2)])
        emitted+=w*z.event_rate_by_hit.sum().item()
        emitted_signed+=w*z.marked_event_rate.detach().numpy()
    return {"probability_wall_flux":probability,"rate":emitted,"signed_wall_flux":signed.tolist(),"signed_rate":emitted_signed.tolist(),
            "max_absolute":float(max(abs(probability-emitted),np.max(np.abs(signed-emitted_signed))))}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    mod=product
    with torch.no_grad():
        exact=sum(w*row(run(mod,x,m,END)) for w,x,m in SOURCES)
        out={}
        for split in (.06,.18):
            out[str(split)]={}
            for n in (32,64):
                calc,incoming=compose(mod,n,split)
                errs=components(abs(calc-exact))
                out[str(split)][str(n)]={"max_abs":float(np.max(abs(calc-exact))),"errors":{k:float(np.max(x))for k,x in errs.items()},"split_source_masses":incoming}
        # Each individual source is specified in absolute coordinates in this
        # second calculation. It checks a constant boundary velocity only.
        k0,velocity=3.25,.22
        wall_at_t=k0+velocity*END
        transformed=np.zeros_like(exact)
        for w,x,m in SOURCES:
            physical_mu=DRIFT+velocity
            transformed+=w*row(run(mod,(k0+x)-k0,m,END,drift=physical_mu-velocity,reset=(wall_at_t+RESET)-wall_at_t,
                                    edges=(wall_at_t+EDGES)-wall_at_t,points=(wall_at_t+POINTS)-wall_at_t))
        shift_error=float(np.max(np.abs(exact-transformed)))
    mass_flux=flux(mod)
    summary={"source_sha256":hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest(),"torch":str(torch.__version__),"T":END,"split_times":[.06,.18],"sources":SOURCES,
             "orders":out,"effective_drift":DRIFT,"constant_boundary_velocity":velocity,"physical_origin_at_0":k0,
             "coordinate_translation_max_abs":shift_error,"wall_flux":mass_flux,"direct":{k:v.tolist()for k,v in components(exact).items()}}
    summary["verification_source_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n")
    assert all(v["64"]["max_abs"]<2e-11 for v in out.values()) and shift_error<1e-13 and mass_flux["max_absolute"]<1e-13


if __name__=="__main__":
    main()
