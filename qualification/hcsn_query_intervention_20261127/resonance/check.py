"""Reference quadrature, gradient and real CPU times for the removable-divided-difference operator."""
import argparse
from dataclasses import replace
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
import numpy as np
import torch
from equity import curve
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hx_reference import StationaryFirm,Parameters
from model import GRID

def finite(p,o,x):
    f=StationaryFirm(p,o/p.transaction_cost);b=f.boundary_green();v=b*math.exp(x)
    F,G=f.first_passage(x);return np.array([b,f.equity_green(v,b),F,G])
def d5(fn,q,step):
    if q>=2*step:return (fn(q-2*step)-8*fn(q-step)+8*fn(q+step)-fn(q+2*step))/(12*step)
    return (-25*fn(q)+48*fn(q+step)-36*fn(q+2*step)+16*fn(q+3*step)-3*fn(q+4*step))/(12*step)
def datum(m,s,q,x):
    qv=torch.tensor(q,dtype=torch.float64,requires_grad=True);xs=torch.tensor(x,dtype=torch.float64,requires_grad=True)
    vec=curve(qv,xs,s,m);base=np.array([v.item() for v in vec]);p=replace(Parameters(),maturity=m,volatility=s)
    ref=finite(p,q,x)
    grads=np.array([torch.autograd.grad(t,qv,retain_graph=True)[0].item() for t in vec])
    # Numerical reference independently solves the Green condition, including the changing boundary.
    dq=d5(lambda a:finite(p,a,x),q,1e-5)
    return dict(m=m,sigma=s,premium=q,margin=x,value=base.tolist(),quad=ref.tolist(),abs_error=np.abs(base-ref).tolist(),
         dq=grads.tolist(),dq_reference=dq.tolist(),dq_abs_error=abs(grads-dq).tolist())
def native(path):
    spec=importlib.util.spec_from_file_location('published_native_for_test',path);mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod;spec.loader.exec_module(mod);obs=[]
    for q in (0.,1e-14,1e-10,1e-6,.01):
        try:
            f=mod.Published(mod.Law(premium=q));x=torch.tensor(.1,dtype=torch.float64);p=torch.tensor(f.p.P0,dtype=torch.float64)
            b=f.boundary(p);e=f.equity(x,p);obs.append(dict(q=q,b=float(b),e=float(e)))
        except (ArithmeticError,ValueError,RuntimeError) as err:obs.append(dict(q=q,error=type(err).__name__+': '+str(err)))
    return {'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'records':obs}
def timings():
    us=np.linspace(-1.,1.,81);qs=.01*np.exp(1.5*us)
    prem=torch.tensor(qs[:,None],dtype=torch.float64);x=torch.tensor(GRID[None,:],dtype=torch.float64)
    curve(prem,x);fast=[];baseline=[]
    for rep in range(9):
        t=time.perf_counter();data=curve(prem,x);fast.append(time.perf_counter()-t)
    for rep in range(3):
        table=[];then=time.perf_counter()
        for q in qs:
            f=StationaryFirm(Parameters(),q/.01);b=f.boundary_closed()
            table.append([f.equity_green(b*np.exp(y),b) for y in GRID])
        baseline.append(time.perf_counter()-then)
    single=[]
    for k in range(25):
        at=time.perf_counter();curve(torch.tensor(.01,dtype=torch.float64),.1);single.append(time.perf_counter()-at)
    return dict(grid=[81,12],threads=torch.get_num_threads(),dtype='float64',torch=torch.__version__,batched_s=fast,sequential_green_s=baseline,scalar_direct_s=single,
                median_batch_speedup=float(np.median(baseline)/np.median(fast)),table_max_abs_difference=float(np.max(abs(np.array(table)-data[1].numpy()))))
def main(out,native_path):
    out.mkdir(parents=True,exist_ok=True);torch.set_num_threads(1);torch.set_num_interop_threads(1)
    tests=[(1,.23,q,x) for q in (0.,1e-14,1e-10,1e-6,.001,.01,.04,.5) for x in (1e-5,.02,.1,.4)]
    tests += [(m,s,q,x) for m in (.1,1.,5.) for s in (.15,.23,.4) if (m,s)!=(1.,.23) for q in (0.,.04,.5) for x in (.02,.4)]
    rows=[]
    for args in tests:rows.append(datum(*args))
    prices=np.array([rr['abs_error'] for rr in rows]);derivs=np.array([rr['dq_abs_error'] for rr in rows]);drelative=np.array([np.array(rr['dq_abs_error'])/np.maximum(1,np.abs(rr['dq_reference'])) for rr in rows]);times=timings()
    obj=dict(cases=rows,absolute_error_max_by_B_E_F_G=prices.max(0).tolist(),derivative_abs_max_by_B_E_F_G=derivs.max(0).tolist(),
       derivative_scaled_max_by_B_E_F_G=drelative.max(0).tolist(),native=native(native_path),timing=times)
    (out/'result.json').write_text(json.dumps(obj,indent=1,allow_nan=False)+'\n')
    print(len(rows),obj['absolute_error_max_by_B_E_F_G'],obj['derivative_scaled_max_by_B_E_F_G'],times['median_batch_speedup'])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('native',type=Path);a=p.parse_args();main(a.out,a.native)
