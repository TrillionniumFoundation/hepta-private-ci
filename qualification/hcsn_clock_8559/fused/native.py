"""Drop-in CPU float32 physical operator with first-order autograd for the original SHD models."""
import ctypes
import functools
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import torch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from model import Population,Classifier
COST={}

@functools.lru_cache(maxsize=1)
def library():
    start=time.perf_counter()
    cpp=HERE/'population.cpp'
    key=hashlib.sha256(cpp.read_bytes()).hexdigest()[:20]
    cache=Path(os.environ.get('HCSN_KERNEL_CACHE',str(Path.home()/'.cache/hcsn-clock-8559')))
    cache.mkdir(parents=True,exist_ok=True)
    dest=cache/(key+'.so')
    COST['already_compiled']=dest.exists()
    if not dest.exists():
        with tempfile.NamedTemporaryFile(dir=cache,suffix='.so',delete=False) as f:tmp=Path(f.name)
        try:
            subprocess.run(['c++','-std=c++17','-O3','-march=native','-ffp-contract=off','-fPIC','-shared',str(cpp),'-o',str(tmp)],check=True)
            os.replace(tmp,dest)
        finally:tmp.unlink(missing_ok=True)
    lib=ctypes.CDLL(str(dest))
    prefix=[ctypes.c_int,ctypes.c_int,ctypes.c_float,ctypes.c_int]
    for method,count in [(lib.population_forward,9),(lib.population_backward,14)]:
        method.argtypes=prefix+[ctypes.c_void_p]*count;method.restype=None
    COST['compile_load_wall_s']=time.perf_counter()-start
    return lib

class FusedStep(torch.autograd.Function):
    @staticmethod
    def forward(ctx,u,wall,mass,refr,table,coeff,probe,emit,beta,fixed):
        if u.dtype!=torch.float32 or u.device.type!='cpu':raise ValueError('CPU float32 is required')
        pack=[a.contiguous() for a in (u,wall,mass,refr,table,coeff,probe,emit)]
        out=torch.empty((*u.shape,9),dtype=u.dtype,device=u.device)
        ctx.dims=(u.numel(),u.shape[-1],beta,int(fixed))
        library().population_forward(*ctx.dims,*[a.data_ptr() for a in [*pack,out]])
        ctx.save_for_backward(pack[0],pack[1],pack[2],*pack[4:],out)
        return out

    @staticmethod
    def backward(ctx,grad):
        u,wall,mass,table,coeff,probe,emit,out=ctx.saved_tensors
        gu=torch.empty_like(u);gw=torch.empty_like(wall);gm=torch.empty_like(mass);gr=torch.empty_like(wall);ge=torch.zeros_like(emit)
        pack=[u,wall,mass,table,coeff,probe,emit,out,grad.contiguous(),gu,gw,gm,gr,ge]
        library().population_backward(*ctx.dims,*[a.data_ptr() for a in pack])
        return gu,gw,gm,gr,None,None,None,ge,None,None

class NativePopulation(Population):
    def forward(self,x):
        if x.device.type!='cpu' or x.dtype!=torch.float32:return super().forward(x)
        d=self.inp(x);z=torch.zeros_like(d[:,0])
        wall=z;signal=z;refr=z;price=z[...,None].expand(-1,-1,2)
        mass=self.reset.expand(*z.shape,4);history=[]
        for frame in d.unbind(1):
            fb=(price.tanh()*self.feedback).sum(-1)
            u=frame+self.recurrent(signal)+(0.*fb if self.arm=='no_feedback' else fb)
            out=FusedStep.apply(u,wall,mass,refr,self.table,self.coeff,self.probes,self.emitter,self.beta,self.arm=='fixed')
            wall=out[...,0];mass=out[...,1:5];refr=out[...,5];price=out[...,6:8];signal=out[...,8]
            history.append(signal)
        return torch.stack(history,1)

def enable(model):
    for item in model.modules():
        if type(item) is Population:item.__class__=NativePopulation
    return model
