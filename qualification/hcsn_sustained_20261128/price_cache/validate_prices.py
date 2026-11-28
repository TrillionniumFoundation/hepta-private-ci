"""Test full two-layer gradients and cold training on the UCI optical digits data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
DATA_SHA = '64e0d2d6eefdf5690076708a08bc4ef38a2a8d996158f0c455386fdaf6ae255f'


def tensor_tree(t):
    import torch
    if isinstance(t,torch.Tensor):
        yield t
    else:
        for part in t:
            yield from tensor_tree(part)


def max_error(xs, ys):
    return max((a.detach()-b.detach()).abs().max().item() for a,b in zip(xs,ys,strict=True))


def equivalence(device='cpu'):
    from population import ContinuousSpikingNetwork
    import torch
    report=[]
    torch.manual_seed(962)
    for dtype in (torch.float64,torch.float32):
        for k in (12,64):
            for fft, changed in ((False,False),(False,True),(True,False)):
                direct=ContinuousSpikingNetwork(3,2,3,k,matrix_free=fft).to(device=device,dtype=dtype)
                cached=ContinuousSpikingNetwork(3,2,3,k,matrix_free=fft,cache_prices=True).to(device=device,dtype=dtype)
                assert direct.state_dict().keys()==cached.state_dict().keys()
                x=torch.randn(5,3,3,device=device,dtype=dtype)
                # Warm a distinct initial state, then alter its parameters
                # and replace the mesh before a strict old-format checkpoint load.
                with torch.no_grad():
                    cached(x)
                    if changed:
                        for layer in (direct.first,direct.second):
                            layer.grid.copy_(layer.grid + .025*layer.grid.square())
                            layer.cuts.copy_((layer.grid[1:]+layer.grid[:-1])/2)
                cached.load_state_dict(direct.state_dict(),strict=True)
                if changed:
                    for net in (direct,cached):
                        for layer in (net.first,net.second):
                            layer.grid.requires_grad_()
                def run(net):
                    xx=x.detach().clone().requires_grad_()
                    out,state=net(xx)
                    w=torch.linspace(-.4,1.,out.numel(),device=device,dtype=dtype).reshape_as(out)
                    loss=(out*w).sum()+sum(v.square().mean() for v in tensor_tree(state))
                    trainable=[*net.parameters(),xx]
                    if changed:
                        trainable.extend([net.first.grid,net.second.grid])
                    grad=torch.autograd.grad(loss,trainable)
                    return list(tensor_tree((out,state))),grad
                a,g=run(direct);b,h=run(cached)
                diff=max_error(a,b);gdiff=max_error(g,h)
                tol=3e-10 if dtype==torch.float64 else 3e-4
                assert diff < tol and gdiff < tol,(dtype,k,fft,changed,diff,gdiff)
                # A direct single-step caller must still obtain fresh values after
                # an in-place edit even if a cached full forward was already run.
                if changed:
                    with torch.no_grad():
                        for net in (direct,cached):
                            net.first.grid[1]+=.002
                        assert max_error(tensor_tree(direct(x)),tensor_tree(cached(x))) < tol
                report.append(dict(dtype=str(dtype),atoms=k,fft=fft,modified_mesh=changed,
                                   max_output_and_state_error=diff,max_gradient_error=gdiff))
    return report


def data():
    import numpy as np
    path=HERE/'digits01.npz'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==DATA_SHA
    with np.load(path,allow_pickle=False) as z:
        x=z['images'].astype(np.float64)/16
        y=z['labels'].astype(np.int64)
    rng=np.random.default_rng(20261128)
    train,dev,test=[],[],[]
    for cls in (0,1):
        rows=rng.permutation(np.flatnonzero(y==cls))
        n,m=int(.64*len(rows)),int(.80*len(rows))
        train.extend(rows[:n]);dev.extend(rows[n:m]);test.extend(rows[m:])
    return x,y,(np.array(train),np.array(dev),np.array(test))


def fit(mode,k,seed,device):
    import numpy as np
    import torch
    from population import ContinuousSpikingNetwork
    torch.set_num_threads(1)
    if device=='cuda':
        assert torch.cuda.is_available()
        sync=torch.cuda.synchronize
    else:
        sync=lambda:None
    sync();start=time.perf_counter()
    torch.manual_seed(seed)
    x,y,(tr,dev,test)=data()
    xt=torch.tensor(x,device=device,dtype=torch.float64).transpose(0,1)
    yt=torch.tensor(y,device=device,dtype=torch.long)
    model=ContinuousSpikingNetwork(8,3,2,k,port='priced',cache_prices=mode=='cached').to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=.016,weight_decay=.001)
    plan=np.random.default_rng(seed).choice(tr,(16,8))
    def score(ids):
        outputs=[]
        with torch.no_grad():
            for i in range(0,len(ids),8):
                outputs.append(model(xt[:,ids[i:i+8]])[0][-1])
            logits=torch.cat(outputs)
            labels=yt[ids]
            accuracy=[(logits.argmax(1)[labels==c]==c).double().mean().item() for c in (0,1)]
            return dict(ce=torch.nn.functional.cross_entropy(logits,labels).item(),
                        balanced_accuracy=sum(accuracy)/2)
    curves=[]
    for step in range(17):
        if step in (0,4,8,12,16):
            row=score(dev);sync();curves.append(dict(step=step,**row,seconds=time.perf_counter()-start))
        if step==16: break
        optimizer.zero_grad(set_to_none=True)
        ids=plan[step]
        z=model(xt[:,ids])[0][-1]
        torch.nn.functional.cross_entropy(z,yt[ids]).backward()
        optimizer.step()
    test_values=score(test)
    sync();elapsed=time.perf_counter()-start
    return dict(mode=mode,atoms=k,seed=seed,device=device,torch=str(torch.__version__),
                device_name=torch.cuda.get_device_name() if device=='cuda' else 'CPU',
                data_sha256=DATA_SHA,split=[len(tr),len(dev),len(test)],updates=16,batch=8,
                dev=curves,heldout=test_values,setup_train_eval_s=elapsed)


def supervise(device, output, seeds=(314,159)):
    import torch
    torch.set_num_threads(1)
    checks=equivalence(device)
    report=dict(equivalence=checks,runs=[],pairs=[])
    for j,k in enumerate((12,64)):
        for i,seed in enumerate(seeds):
            order=('original','cached') if (i+j)%2==0 else ('cached','original')
            paired={}
            for mode in order:
                with tempfile.TemporaryDirectory() as temp:
                    result=Path(temp)/'fit.json'
                    start=time.perf_counter()
                    subprocess.run([sys.executable,str(Path(__file__).resolve()),'--mode',mode,
                                    '--atoms',str(k),'--seed',str(seed),'--device',device,
                                    '--output',str(result)],check=True,
                                   env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1',
                                        'MKL_NUM_THREADS':'1'})
                    elapsed=time.perf_counter()-start
                    row=json.loads(result.read_text());row['cold_process_s']=elapsed
                    report['runs'].append(row);paired[mode]=row
            a,b=paired['original'],paired['cached']
            max_ce=max(abs(i['ce']-j['ce']) for i,j in zip(a['dev'],b['dev']))
            diff=abs(a['heldout']['ce']-b['heldout']['ce'])
            assert max_ce<1e-8 and diff<1e-8
            assert a['heldout']['balanced_accuracy']==b['heldout']['balanced_accuracy']
            report['pairs'].append(dict(atoms=k,seed=seed,max_dev_ce_difference=max_ce,
                    heldout_ce_difference=diff,heldout_balanced_accuracy=b['heldout']['balanced_accuracy'],
                    cold_ratio=a['cold_process_s']/b['cold_process_s'],
                    setup_train_eval_ratio=a['setup_train_eval_s']/b['setup_train_eval_s']))
            output.write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['original','cached'])
    parser.add_argument('--atoms',type=int,default=12)
    parser.add_argument('--seed',type=int,default=314)
    parser.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=fit(args.mode,args.atoms,args.seed,args.device) if args.mode else supervise(args.device,args.output)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
