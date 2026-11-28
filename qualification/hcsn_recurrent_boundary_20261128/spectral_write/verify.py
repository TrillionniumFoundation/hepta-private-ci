"""Independent sequential NumPy inference and per-word replay of the sealed financial deployments."""
from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from scipy.special import expit,logsumexp,ndtr


def layer_norm(x, w, b):
    centered=x-x.mean(-1,keepdims=True)
    return centered/np.sqrt(np.mean(centered*centered,-1,keepdims=True)+1e-5)*w+b


def forward(weights, x, y):
    W=weights;h=W['emb.weight'][x]+W['pos'][:x.shape[1]]
    for j in (0,1):
        p=f'blocks.{j}.'
        z=layer_norm(h,W[p+'pre.weight'],W[p+'pre.bias'])
        q,k,v=np.split(z@W[p+'qkv.weight'].T+W[p+'qkv.bias'],3,axis=-1)
        decay=W[p+'decay'];previous=np.zeros_like(k[:,0]);hist=np.empty_like(k)
        for i in range(k.shape[1]):
            previous=decay*previous+(1-decay)*k[:,i];hist[:,i]=previous
        u=np.tanh(q+hist);mix=expit(v)
        c=W[p+'center'];s=W[p+'slope']
        def price(a,b):return (1-mix)*(c[a]+s[a]*u)+mix*(c[b]+s[b]*u)
        signal=u+price(1,2)/c[2]-price(3,4)/c[3]
        z=h+signal@W[p+'out.weight'].T+W[p+'out.bias']
        if np.any(W[p+'ff.3.weight']) or np.any(W[p+'ff.3.bias']):
            raise ArithmeticError('unexpected nonzero feed-forward head')
        ratio=s[0]/c[0];h=np.log1p(ratio*np.tanh(z))/ratio
    ok=y>=0
    z=layer_norm(h,W['norm.weight'],W['norm.bias'])[ok]
    t=y[ok];rare=t>=128
    root=np.where(rare,128+(t-128)//128,t)
    logits=z@W['head.root.weight'].T + W['head.root.bias']
    rows=np.arange(len(t));scores=logsumexp(logits,axis=1)-logits[rows,root]
    g=(t[rare]-128)//128;rank=(t[rare]-128)%128
    a=z[rare]+W['head.condition.weight'][g]
    logits=(a*ndtr(a))@W['head.rank.weight'].T+W['head.rank.bias']+W['head.prior.weight'][g]
    logits[128+g[:,None]*128+np.arange(128)[None,:]>=len(W['emb.weight'])]=-np.inf
    scores[rare]+=logsumexp(logits,axis=1)-logits[np.arange(len(g)),rank]
    return scores


def verify(data,run):
    dev=json.loads((run/'development.json').read_bytes())
    report=json.loads((run/'terminal.json').read_bytes())
    if report['development_sha256']!=sha256((run/'development.json').read_bytes()).hexdigest():
        raise ArithmeticError('changed chosen endpoints')
    tokens=np.load(data/'test.npy');n=len(tokens)-1;pad=(-n)%128
    xx=np.pad(tokens[:-1],(0,pad)).reshape(-1,128);yy=np.pad(tokens[1:],(0,pad),constant_values=-1).reshape(-1,128)
    rows={}
    for seed,ss in report['results'].items():
        choices={v['tag']:v for v in dev[seed]['records']}
        for name,r in ss['fits'].items():
            f=run/(name+'.npz');scorefile=run/r['file']
            if sha256(f.read_bytes()).hexdigest()!=choices[name]['sha256'] or sha256(scorefile.read_bytes()).hexdigest()!=r['sha256']:
                raise ValueError(name)
            with np.load(f) as file:weights={k:v.astype(float) for k,v in file.items()}
            with np.load(scorefile) as file:orig=file['normal']
            got=np.concatenate([forward(weights,xx[i:i+8],yy[i:i+8]) for i in range(0,len(xx),8)])
            a=np.max(abs(got-orig));b=abs(np.mean(got)-r['scores']['normal']['nll'])
            if len(got)!=n or a>1e-4 or b>2e-6:raise ArithmeticError((name,len(got),a,b))
            rows[name]={'words':n,'max_nll_error':float(a),'mean_nll_error':float(b)}
            print(name,rows[name],flush=True)
    return rows


if __name__=='__main__':
    p=ArgumentParser();p.add_argument('data',type=Path);p.add_argument('result',type=Path);a=p.parse_args()
    v=verify(a.data,a.result)
    (a.result/'verified.json').write_text(json.dumps(v,indent=2)+'\n')
