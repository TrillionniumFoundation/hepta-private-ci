"""Device benchmark of real CREMA-D HCSN head editing on three successive script interventions."""
import argparse
import base64
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F

PACKED=None
EXPECTED=None


def basis(cov):
    eigenvectors=torch.linalg.eigh((cov+cov.T)/2)
    return eigenvectors.eigenvectors[:,eigenvectors.eigenvalues<.02]


def projected(k,t,w):
    return 12*F.normalize(k@w,dim=1)@F.normalize(t@w,dim=1).T


def metrics(z,y,stage):
    script=y//6
    target=torch.where(script<=stage,6*script+(y%6+1)%6,y)
    loss=F.cross_entropy(z,target,reduction='none')
    correct=z.argmax(1)==target
    return {n:{'count':int(m.sum()),'nll':float(loss[m].mean()),
               'top1':float(correct[m].float().mean())} for n,m in
            {'current':script==stage,'past':script<stage,'protected':script>=6}.items() if m.any()}


def gate(m,p):
    return bool(p['current']['nll']-m['current']['nll']>=.1 and
                p['past']['nll']-m['past']['nll']>=.05 and
                m['protected']['nll']-p['protected']['nll']<=.1 and
                p['protected']['top1']-m['protected']['top1']<=.02)


def sync(device):
    if device=='cuda':torch.cuda.synchronize()


def fit(data,arm,device):
    started=time.perf_counter()
    to=lambda a:torch.as_tensor(a,device=device)
    w0=to(data['W0'].astype('float32'));t=to(data['text'].astype('float32'))
    a=to(data['anchors'].astype('float32')).double()
    k=to(data['train'].astype('float32'));y=to(data['train_y'].astype('int64'))
    dev=to(data['dev'].astype('float32'));dy=to(data['dev_y'].astype('int64'))
    held=to(data['held'].astype('float32'));hy=to(data['held_y'].astype('int64'))
    w=w0.double();old=w.clone();C=a.T@a/len(a);hist=torch.zeros_like(C)
    U=basis(C);seen=last=0
    template=F.normalize(t.double()@old,dim=1)
    pre=time.perf_counter()-started
    fit_seconds=0.;ranks=[];refreshes=0
    for stage in range(3):
        mask=y//6==stage;keys=k[mask].double();labels=6*stage+(y[mask]%6+1)%6
        sync(device);tic=time.perf_counter()
        if arm=='beta':
            for pos in range(0,len(keys),32):
                z=keys[pos:pos+32]
                if seen-last>=1000:
                    U=basis((hist/seen+3000*C)/3001);last=seen;refreshes+=1
                residual=(z@old).norm(dim=1,keepdim=True)*template[labels[pos:pos+32]]-z@w
                Z=z@U
                A=10*torch.eye(U.shape[1],dtype=U.dtype,device=device)+Z.T@Z+U.T@(hist+3000*C)@U
                delta=U@torch.linalg.solve(A,Z.T@residual)
                if float(delta.norm())/(len(z)**.5)>20:raise ValueError('update guard')
                w=(w+delta).float().double();hist+=z.T@z;seen+=len(z);ranks.append(U.shape[1])
        else:
            train=y//6<=stage;allk=k[train];new_y=6*(y[train]//6)+(y[train]%6+1)%6
            w=w.float().detach().clone().requires_grad_(True)
            opt=torch.optim.Adam([w],lr=.003)
            for _ in range(128):
                opt.zero_grad(set_to_none=True);delta=w-w0
                reg=(delta.square().sum()+1024*(a.float()@delta).square().sum())/(len(allk)*w.shape[1])
                loss=F.cross_entropy(projected(allk,t,w),new_y)+reg
                loss.backward();opt.step()
            w=w.detach().double()
        sync(device);fit_seconds+=time.perf_counter()-tic
    deployed=(old+.25*(w-old)).float()
    result={}
    for name,x,labels in [('dev',dev,dy),('held',held,hy)]:
        z=projected(x,t,deployed);p=projected(x,t,w0)
        met,original=metrics(z,labels,2),metrics(p,labels,2)
        result[name]={'metrics':met,'parent':original,'quality_gate':gate(met,original)}
        if name=='held':scores=z.detach().cpu().numpy()
    sync(device)
    return dict(copy_and_setup_s=pre,fit_s=fit_seconds,all_in_memory_s=time.perf_counter()-started,
                passes=bool(result['dev']['quality_gate'] and result['held']['quality_gate']),
                metrics=result,projection_ranks=sorted(set(ranks)),refreshes=refreshes),scores


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path);parser.add_argument('--output',type=Path,default=Path('result.json'))
    parser.add_argument('--device',choices=['cuda','cpu','both'],default='both')
    parser.add_argument('--repeat',type=int,default=2)
    args=parser.parse_args();torch.set_num_threads(1)
    if args.input:datafile=args.input.read_bytes()
    else:
        datafile=lzma.decompress(base64.b85decode(PACKED))
        if hashlib.sha256(datafile).hexdigest()!=EXPECTED:raise ValueError('sealed input mismatch')
    with np.load(io.BytesIO(datafile),allow_pickle=False) as npz:data={k:npz[k] for k in npz.files}
    devices=['cpu','cuda'] if args.device=='both' else [args.device]
    result={'input_sha256':hashlib.sha256(datafile).hexdigest(),'input_dtype':str(data['W0'].dtype),
            'rows':{k:len(data[k]) for k in ('train','dev','held','anchors','text')},
            'torch':str(torch.__version__),'rocm':torch.version.hip,'cuda':torch.version.cuda,
            'cuda_available':bool(torch.cuda.is_available()),'hardware':{},'runs':[],'completed':False}
    output={}
    for device in devices:
        if device=='cuda' and not torch.cuda.is_available():
            result['hardware'][device]='unavailable';continue
        if device=='cuda':
            check=torch.arange(8,device=device,dtype=torch.float32)
            torch.backends.cuda.matmul.allow_tf32=False
            result['hardware'][device]=torch.cuda.get_device_name();result['gpu_dot']=float(check@check)
            if result['gpu_dot']!=140:raise ValueError('device arithmetic')
        else:result['hardware'][device]='cpu'
        for repeat in range(args.repeat):
            for arm in (('beta','bp') if repeat%2==0 else ('bp','beta')):
                if device=='cuda':torch.cuda.reset_peak_memory_stats()
                row,z=fit(data,arm,device);row.update(device=device,arm=arm,repeat=repeat)
                if device=='cuda':row['peak_tensor_bytes']=torch.cuda.max_memory_allocated()
                result['runs'].append(row);output[(device,arm)]=z
                args.output.write_text(json.dumps(result,allow_nan=False)+'\n')
    if all(d in result['hardware'] for d in ('cpu','cuda')) and result['hardware']['cuda']!='unavailable':
        result['device_logits_max_abs']={a:float(np.max(abs(output[('cpu',a)]-output[('cuda',a)]))) for a in ('beta','bp')}
    result['completed']=True
    args.output.write_text(json.dumps(result,allow_nan=False)+'\n')
    print(json.dumps({'hardware':result['hardware'],'runs':[(x['device'],x['arm'],x['passes'],x['all_in_memory_s']) for x in result['runs']]}),flush=True)


if __name__=='__main__':main()
