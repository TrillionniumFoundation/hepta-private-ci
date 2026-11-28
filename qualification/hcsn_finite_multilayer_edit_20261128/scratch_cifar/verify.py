"""Check train-time and cold implementations and every actual loss gradient using source train images."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from cifar_local import local_fit
from cifar_net import Examples,Net
from cold import evaluate,prepare_lookup


def run(root,law,dest):
    torch.set_num_threads(1)
    examples=Examples(root,'train');selection=np.random.default_rng(1058559).choice(len(examples.y),24,replace=False)
    x,y,_=examples.batch(selection);rows=[]
    for arch in ('literal','smooth','dense'):
        model=Net(law,arch,157)
        def weights():
            return dict({f'w{i}':p.detach().numpy() for i,p in enumerate(model.w)},head=model.head.detach().numpy(),
                        temperature=model.temperature.numpy())
        lut=prepare_lookup(law,arch)
        def disagreement():
            z=evaluate(examples.pix[selection],weights(),arch,lut,examples.mean.numpy())
            direct=model(x).detach().numpy()
            return dict(max_absolute=float(abs(direct-z).max()),rms=float(np.sqrt(np.mean((z-direct)**2))),
                        argmax_disagree=int((z.argmax(1)!=direct.argmax(1)).sum()))
        old=disagreement();grads={}
        model.double();xd=x[:4].double();yy=y[:4]
        value=F.cross_entropy(model(xd),yy);value.backward()
        generator=torch.Generator().manual_seed(894)
        for i,p in enumerate([*model.w,model.head]):
            v=torch.randn(p.shape,generator=generator,dtype=torch.float64);v/=v.norm()
            analytical=(p.grad*v).sum().item();vals=[]
            original=p.detach().clone()
            with torch.no_grad():
                for eps in (1e-4,1e-6,1e-8):
                    p.copy_(original+eps*v);a=F.cross_entropy(model(xd),yy).item()
                    p.copy_(original-eps*v);b=F.cross_entropy(model(xd),yy).item()
                    vals.append({'h':eps,'abs_error':abs((a-b)/(2*eps)-analytical)})
                p.copy_(original)
            grads[str(i)]=dict(exact=analytical,fnorm=p.grad.norm().item(),compared=vals)
        model.float()
        local_fit(model,examples,selection,'fp' if arch=='dense' else 'boundary',.01,1,lambda:None)
        fitted=disagreement()
        assert old['max_absolute']<1e-4 and fitted['max_absolute']<.002
        assert all(min(e['abs_error'] for e in g['compared'])<2e-5 for g in grads.values())
        rows.append(dict(arch=arch,seed=157,train_rows=selection.tolist(),cold_initial=old,cold_locally_fitted=fitted,gradients=grads))
    dest.write_text(json.dumps(rows,indent=1)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('data','law','out'):p.add_argument(k,type=Path)
    a=p.parse_args();run(a.data,a.law,a.out)
