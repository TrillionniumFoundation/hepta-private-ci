"""Load the unchanged literal model and original split/score interface."""
import hashlib
import json
import os
from pathlib import Path
import sys
import numpy as np
import torch
from torch.nn import functional as F

BASE=Path(os.environ.get('RSICD_BASE_SOURCE',Path(__file__).resolve().parent)).resolve()
os.environ.setdefault('FULLSTACK_DATA','/workspace/scratch/e0bf6e4e8dc1/fullstack-run')
sys.path.insert(0,str(BASE))
from study import Data,net,eval_rows,ROOT
ARMS=('forward','shuffle','feature_only','tied_only','frozen_probe')
SEEDS=(109,271,463);PREFIXES=(4,16,48,128);TIMES=(60,180,300)
WIDTH=416;RANK=32;RIDGE=.03;BLEND=.45;CAP=512;VCAP=4096


def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def tensor_sha(x):
    return hashlib.sha256(x.detach().contiguous().cpu().numpy().tobytes()).hexdigest()


def write(p,data):
    p=Path(p);tmp=p.with_suffix('.json.partial');tmp.write_text(json.dumps(data,indent=1,sort_keys=True,allow_nan=False)+'\n');tmp.replace(p)


def normal(shape,seed):
    return torch.randn(shape,generator=torch.Generator().manual_seed(int(seed)))


def projection(width,rank,seed):
    return normal((width,min(width,rank)),seed)/(width**.5)


def sampled_data(d,seed,steps):
    rng=np.random.default_rng(seed)
    parts=[rng.choice(d.index['train'],size=8,replace=False) for _ in range(steps)]
    rows=np.concatenate(parts);p,x,y=d.batch(rows)
    digests=[hashlib.sha256(s.astype('<i8').tobytes()).hexdigest() for s in parts]
    return p,x,y,rows,digests


def choose(total,cap,seed):
    if total<=cap:return torch.arange(total,dtype=torch.long)
    return torch.randperm(total,generator=torch.Generator().manual_seed(seed))[:cap].sort().values


def save_recipe(path,recipe):
    temp=Path(str(path)+'.partial');torch.save(recipe,temp);temp.replace(path)
    return sha(path)


class Probe(torch.nn.Module):
    def __init__(self,base,w):
        super().__init__();self.base=base;self.register_buffer('probe_weight',w)
    def forward(self,pix,t):
        last=[]
        handle=self.base.final.register_forward_hook(lambda m,inp,out:last.append(out))
        try:self.base(pix,t)
        finally:handle.remove()
        return F.linear(last[0],self.probe_weight)


def original(seed,data):
    m=net('literal',seed,data);m.eval()
    for p in m.parameters():p.requires_grad_(False)
    return m


def rebuild(seed,data,recipe):
    m=original(seed,data);params=dict(m.named_parameters())
    for name,spec in recipe['writes'].items():
        p=params[name]
        if 'value' in spec:p.copy_(spec['value'])
        else:
            flat=p.reshape(p.shape[0],-1);r=projection(flat.shape[1],spec['rank'],spec['seed'])
            flat.add_(spec['coefficient']@r.T)
        assert tensor_sha(p)==spec['result_sha256'],name
    return Probe(m,recipe['probe']) if 'probe' in recipe else m


def ranks(s):
    """Actual singular spectrum of the normalized local design, before positive ridge."""
    e=torch.linalg.eigvalsh(s.T.double()@s.double()).clamp_min(0)
    mx=float(e[-1]);mask=e>max(mx*1e-8,1e-12)
    return {'columns':len(e),'nondegenerate_columns':int(mask.sum()),
            'largest_eigenvalue':mx,'smallest_eigenvalue':float(e[0]),
            'ridge_effective_df_per_response':float((e/(e+RIDGE*e.mean().clamp_min(1e-9))).sum()),
            'regularized_spectral_condition':float((e[-1]+RIDGE*e.mean().clamp_min(1e-9))/(e[0]+RIDGE*e.mean().clamp_min(1e-9)))}


def ridge(x,dest):
    a=x.double();b=dest.double();g=a.T@a;pen=RIDGE*g.diag().mean().clamp(min=1e-9)
    g.diagonal().add_(pen);return torch.linalg.solve(g,a.T@b).float()


class Writer:
    def __init__(self,model):
        self.model=model;self.rows={};self.log={};self.p=dict(model.named_parameters())
    def finish(self,name,old,spec):
        value=self.p[name];newsha=tensor_sha(value)
        spec['result_sha256']=newsha;self.rows[name]=spec
        self.log[name]={'shape':list(value.shape),'tensor_scalars':value.numel(),
            'changed_coordinates':int(torch.count_nonzero(value-old)),
            'free_coefficients':spec['coefficient'].numel() if 'coefficient' in spec else value.numel(),
            'rank_cap':spec.get('rank'), 'frobenius_change':float((value-old).norm()),
            'before_sha256':tensor_sha(old),'after_sha256':newsha}
    def low(self,name,coef,seed):
        p=self.p[name];old=p.clone();flat=p.reshape(p.shape[0],-1);r=projection(flat.shape[1],RANK,seed);flat.add_(coef@r.T)
        self.finish(name,old,{'coefficient':coef.contiguous(),'rank':RANK,'seed':int(seed)})
    def value(self,name,v):
        p=self.p[name];old=p.clone();p.copy_(v);self.finish(name,old,{'value':v.contiguous().clone()})

class FitData(Data):
    def __init__(self,work):
        self.meta=json.loads((ROOT/'data.json').read_bytes())
        self.p=np.load(self.meta['pixels'],mmap_mode='r')
        prep=json.loads((work/'prepared.json').read_bytes())
        assert sha(work/'fit_only.npz')==prep['fit_only_sha256']
        with np.load(work/'fit_only.npz') as z:
            self.x=z['inputs'];self.y=z['targets'];self.index={k:z[k] for k in ('train','development')}
        assert len(self.index['train'])==6311 and len(self.index['development'])==128
