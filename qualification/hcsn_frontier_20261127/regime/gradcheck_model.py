import json
from pathlib import Path
import numpy as np
import torch
from implicit import outputs,RegimeCell
from stopping import Model,Continuation,FirstHit

torch.set_num_threads(1)
x=torch.tensor([.30,.50,.62,1.,1.5],dtype=torch.float64,requires_grad=True)
p=torch.tensor([.04,.08,.12,.16],dtype=torch.float64,requires_grad=True)
def vector(z,p):
    E,H,B=outputs(z,p)
    return torch.cat([E.flatten(),H.flatten(),B])
def independent(z,par):
    cheap,dear,up,down=par;e=Continuation(Model(cheap=cheap,dear=dear,up=up,down=down))
    return np.r_[e.values(z).ravel(),FirstHit(e).values(z).ravel(),e.b0,e.b1]
val=vector(x,p)
ad_x,ad_p=torch.autograd.functional.jacobian(vector,(x,p))
xx=x.detach().numpy();pp=p.detach().numpy()
def diff(source,f,step):
    eye=np.eye(len(source))
    return np.stack([(f(source+q*step)-f(source-q*step))/(2*step) for q in eye],axis=1)
dp=diff(pp,lambda p:independent(xx,p),2e-7);dx=diff(xx,lambda x:independent(x,pp),2e-6)
torch.manual_seed(219)
net=RegimeCell(.048,.093,.09,.20)
assets=torch.linspace(.34,1.5,41,dtype=torch.float64)
with torch.no_grad():
    E,H,B=outputs(assets,p)
def loss():
    e,h,b=net(assets)
    return (e-E).square().mean()+(h-H).square().mean()+(b-B).square().mean()
start=loss().item();opt=torch.optim.Adam(net.parameters(),lr=.03)
for i in range(90):
    opt.zero_grad();l=loss();l.backward();opt.step()
result={'value_agreement':float(np.max(abs(val.detach().numpy()-independent(xx,pp)))),
        'asset_derivatives':int(dx.size),'parameter_derivatives':int(dp.size),'asset_jacobian_max_abs':float(np.max(abs(dx-ad_x.numpy()))),
        'parameter_jacobian_max_abs':float(np.max(abs(dp-ad_p.numpy()))),'boundary_jacobian':ad_p.numpy()[-2:].tolist(),
        'fit_initial':start,'fit_after_90':loss().item(),'asset_grid':assets.detach().tolist()}
assert result['asset_jacobian_max_abs']<1e-6 and result['parameter_jacobian_max_abs']<2e-6 and result['fit_after_90']<start*.02
Path(__file__).with_name('implicit_check.json').write_text(json.dumps(result,indent=2)+'\n')
print({k:v for k,v in result.items() if k!='asset_grid'})
