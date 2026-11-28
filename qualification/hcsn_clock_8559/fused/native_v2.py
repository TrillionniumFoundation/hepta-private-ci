"""Fused adjoint with interpolation-cell ownership determined by the original tensor backend."""
import functools
import os
import ctypes
import hashlib
from pathlib import Path
import subprocess
import tempfile
import time
import torch
from native import HERE, NativePopulation
from model import Population
COST={}

@functools.lru_cache(None)
def library():
    src=HERE/'population.cpp';t=time.perf_counter()
    key=hashlib.sha256(src.read_bytes()+b'reference-coordinate-abi-2').hexdigest()[:20]
    cache=Path(os.environ.get('HCSN_KERNEL_CACHE',str(Path.home()/'.cache/hcsn-clock-8559')))
    cache.mkdir(parents=True,exist_ok=True);dest=cache/(key+'.so')
    COST['already_compiled']=dest.exists()
    if not dest.exists():
        with tempfile.NamedTemporaryFile(dir=cache,suffix='.so',delete=False) as f:tmp=Path(f.name)
        try:
            subprocess.run(['c++','-std=c++17','-O3','-march=native','-ffp-contract=off','-DHCSN_REFERENCE_COORDINATES','-fPIC','-shared',str(src),'-o',str(tmp)],check=True)
            os.replace(tmp,dest)
        finally:tmp.unlink(missing_ok=True)
    lib=ctypes.CDLL(str(dest))
    for func,size in [(lib.population_forward,10),(lib.population_backward,15)]:
        func.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_float,ctypes.c_int]+[ctypes.c_void_p]*size
        func.restype=None
    COST['compile_load_wall_s']=time.perf_counter()-t
    return lib

def coordinates(u,previous,beta,fixed):
    bounded=u.tanh();relative=0.*bounded if fixed else .21*bounded
    wall=torch.log1p(beta*relative);mu=-.10+.25*bounded
    i=(wall-previous+.45)/.005;j=(mu+.35)/.0125
    a=i.clamp(0,180);b=j.clamp(0,40)
    ix=a.long().clamp(max=179);jx=b.long().clamp(max=39)
    return torch.stack([bounded,relative,wall,ix,a-ix,((i>=0)&(i<=180)).to(u)/.005,jx,b-jx,((j>=0)&(j<=40)).to(u)/.0125],-1).contiguous()

class FusedStepV2(torch.autograd.Function):
    @staticmethod
    def forward(ctx,u,wall,mass,refr,table,coeff,probe,emit,beta,fixed):
        if u.dtype!=torch.float32 or u.device.type!='cpu':raise ValueError('CPU float32 is required')
        pos=coordinates(u,wall,beta,fixed)
        pack=[a.contiguous() for a in (u,wall,mass,refr,table,coeff,probe,emit)]
        out=torch.empty((*u.shape,9),dtype=u.dtype,device=u.device)
        ctx.dims=(u.numel(),u.shape[-1],beta,int(fixed))
        library().population_forward(*ctx.dims,*[a.data_ptr() for a in [pos,*pack,out]])
        ctx.save_for_backward(pos,pack[0],pack[1],pack[2],*pack[4:],out)
        return out
    @staticmethod
    def backward(ctx,grad):
        pos,u,wall,mass,table,coeff,probe,emit,out=ctx.saved_tensors
        gu=torch.empty_like(u);gw=torch.empty_like(wall);gm=torch.empty_like(mass);gr=torch.empty_like(wall);ge=torch.zeros_like(emit)
        args=[pos,u,wall,mass,table,coeff,probe,emit,out,grad.contiguous(),gu,gw,gm,gr,ge]
        library().population_backward(*ctx.dims,*[a.data_ptr() for a in args])
        return gu,gw,gm,gr,None,None,None,ge,None,None
class PopulationV2(NativePopulation):
    step=FusedStepV2
def enable(model):
    for item in model.modules():
        if type(item) is Population:item.__class__=PopulationV2
    return model
