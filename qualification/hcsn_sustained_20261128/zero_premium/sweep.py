import hashlib, json, math, os, platform, sys
from dataclasses import replace
from pathlib import Path
import torch, numpy
import he_xiong as patched
import original
import test_he_xiong_zero_premium as independent

torch.set_num_threads(1)
torch.set_num_interop_threads(1)
worst={'boundary':0.,'equity':0.,'margin_gradient':0.,'principal_gradient':0.}
checks=0
for premium in (0.,1e-14,1e-10,1e-6,1.7e-5,2e-5,1e-4,.01):
    for maturity in (1., 1.5):
        for nominal in (55.,68.):
            law=patched.Law(premium=premium,m=maturity)
            obj=patched.Published(law)
            live=[.002,.04,.16,.3,.6,.8]
            b,(v,g)=independent.reference(law,nominal,live)
            _,(vp,_)=independent.reference(law,nominal+1,live)
            x=torch.tensor(live,dtype=torch.float64,requires_grad=True)
            p=torch.full_like(x,nominal,requires_grad=True)
            y=obj.equity(x,p)
            dx,dp=torch.autograd.grad(y.sum(),(x,p))
            errors=[abs(float(obj.boundary(nominal))-b),max(abs(y.detach().numpy()-v)),max(abs(dx.detach().numpy()-g)),max(abs(dp.detach().numpy()-(vp-v)))]
            for key,err in zip(worst,errors):
                worst[key]=max(worst[key],float(err))
                assert err<2e-8,(key,premium,maturity,nominal,err)
            checks+=1
torch.manual_seed(144)
c0,c1=original.LiteralCell(),patched.LiteralCell()
c1.load_state_dict(c0.state_dict())
x=torch.randn(8,4,6,dtype=torch.float64,requires_grad=True)
a,b=c0(x),c1(x)
old_grad=torch.autograd.grad(a.square().sum(),[x,*c0.parameters()])
new_grad=torch.autograd.grad(b.square().sum(),[x,*c1.parameters()])
eq=(a-b).abs().max().item()
gg=max((i-j).abs().max().item() for i,j in zip(old_grad,new_grad))
assert eq==0. and gg==0.
try: original.Published(original.Law(premium=0.))
except ZeroDivisionError: witness='ZeroDivisionError'
else: raise AssertionError('missing original failure')
print(json.dumps(dict(protocol="Additional independent 32-contract sweep",contracts=checks,margins_per_contract=6,device=str(x.device),threads=torch.get_num_threads(),torch=str(torch.__version__),numpy=numpy.__version__,python=sys.version.split()[0],max_abs_error=worst,legacy_error=witness,positive_premium_max_logit_difference=eq,positive_premium_max_input_and_parameter_gradient_difference=gg,source_sha256={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ['original.py','he_xiong.py','test_he_xiong_zero_premium.py']})))
