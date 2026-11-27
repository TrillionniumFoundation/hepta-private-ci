"""Independent float64 automatic and finite-difference check of the online BP baseline."""
from pathlib import Path
import sys
from online import *
import torch
torch.set_num_threads(1);torch.set_num_interop_threads(1)
def loss(key,W,b,head,bias,L,label):
    d=key@W+b;out=[];fb=0.
    for t in range(T):
        q=((d[t]+fb+12)*(16384/24)).clamp(0,16384);k=q.long();aa=L[k]+(q-k)[:,None]*(L[(k+1).clamp(max=16384)]-L[k]);out.append(aa);fb=.4*aa[:,0].tanh()+.4*aa[:,1].tanh()
    z=torch.stack(out).reshape(1,-1)@head+bias
    return torch.nn.functional.cross_entropy(z,torch.tensor([label]))
def main():
    L=table();lt=torch.tensor(L,dtype=torch.float64);tab=splits('dev');res={}
    for seed in (409,571,647):
        p=dict(np.load(CROSS/'fits'/str(seed)/'parent.npz'));K=lower(tab['gsc'][0][:8],p,L);W=p['w2'].astype('f8')
        ww=torch.tensor(W,dtype=torch.float64,requires_grad=True);rest=[torch.tensor(p[k],dtype=torch.float64) for k in ('b2','head','bias')];rows=[]
        for x,label in zip(K,tab['gsc'][1][:8]):
            xx=torch.tensor(x,dtype=torch.float64);z=loss(xx,ww,*rest,lt,int(label));zz,=torch.autograd.grad(z,ww)
            g=gradient(x.astype('f8'),W,p,L,y=int(label));err=abs(g-zz.detach().numpy());r={'max_abs':float(err.max()),'max_rel_norm':float(err.max()/max(1e-12,abs(g).max()))}
            rg=np.random.default_rng(seed);check=[]
            for j in range(7):
                v=rg.normal(size=W.shape);v/=np.linalg.norm(v);vv=torch.tensor(v,dtype=torch.float64)
                plus=loss(xx,ww+1e-5*vv,*rest,lt,int(label)).item();minus=loss(xx,ww-1e-5*vv,*rest,lt,int(label)).item()
                check.append(abs((plus-minus)/2e-5-np.sum(g*v)))
            r['directional_max']=max(check);rows.append(r)
        res[seed]=rows
    dump(HERE/'gradient_check.json',{'examples_checked':24,'num_coordinates':24*512,'directions':24*7,'rows':res,'max_full_tensor_diff':max(r['max_abs'] for q in res.values() for r in q),'max_directional_diff':max(r['directional_max'] for q in res.values() for r in q)})
    print('full/directional',max(r['max_abs'] for q in res.values() for r in q),max(r['directional_max'] for q in res.values() for r in q))
if __name__=='__main__':main()
