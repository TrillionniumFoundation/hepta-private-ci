"""Input-dependent continuous safety margin, best bilinear projection or generic control."""
import ctypes,hashlib,json,os,subprocess,sys,tempfile
from functools import lru_cache
from pathlib import Path
import torch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'src'))
from model import LanguageModel,Block


@lru_cache(maxsize=1)
def kernel():
    c=HERE/'polynomial.c'
    path=Path(tempfile.gettempdir())/('hxwiki-poly-'+hashlib.sha256(c.read_bytes()).hexdigest()[:16]+'.so')
    if not path.exists():
        tmp=path.with_suffix('.'+str(os.getpid())+'.so')
        subprocess.run(['cc','-O3','-std=c11','-shared','-fPIC',str(c),'-o',str(tmp)],check=True)
        tmp.replace(path)
    lib=ctypes.CDLL(str(path));lib.polyeval.argtypes=[ctypes.c_int64,ctypes.c_int]+[ctypes.c_void_p]*6
    lib.polyeval.restype=None
    return lib


class CPUCurve(torch.autograd.Function):
    @staticmethod
    def forward(ctx,u,t,c):
        ua=u.contiguous();ta=t.contiguous()
        y=torch.empty_like(ta);du=torch.empty_like(ta);dt=torch.empty_like(ta)
        kernel().polyeval(ta.numel(),len(c)-1,*[q.data_ptr() for q in (c,ua,ta,y,du,dt)])
        ctx.save_for_backward(du,dt)
        return y
    @staticmethod
    def backward(ctx,adj):
        du,dt=ctx.saved_tensors
        return adj*du,adj*dt,None


def evaluate(u,t,c):
    if u.device.type=='cpu' and u.dtype==torch.float32:
        return CPUCurve.apply(u,t,c)
    uc=u.double();tc=t.double()
    out=c[-1,0]+uc*c[-1,1]
    for j in range(len(c)-2,-1,-1):
        out=out*tc+c[j,0]+uc*c[j,1]
    return out.to(u.dtype)


class PriceBlock(Block):
    def forward(self,x):
        q,k,v=self.qkv(self.pre(x)).chunk(3,dim=-1)
        p=self.histpow[:x.size(1)]
        history=torch.cumsum(k*(1-self.decay)/p,dim=1)*p
        u=torch.tanh(q+history);w=torch.sigmoid(v)
        if self.kind=='smoothwall':
            signal=u+torch.tanh(w+u)-torch.sigmoid(u-w)
        else:
            signal=evaluate(u,2*w-1,self.pricing)
        z=x+self.out(signal)
        z=z+self.ff(z)
        c=self.slope[0]/self.center[0]
        return torch.log1p(c*torch.tanh(z))/c


class CurveLM(LanguageModel):
    def __init__(self,vocab,kind):
        super().__init__(vocab,kind)
        data=json.loads((HERE/'tables.json').read_text())
        tag='scalar_coefficients' if kind=='hxcurve' else 'uniform_projection_coefficients'
        for b in self.blocks:
            b.__class__=PriceBlock
            b.register_buffer('pricing',torch.tensor(data[tag],dtype=torch.float64))
