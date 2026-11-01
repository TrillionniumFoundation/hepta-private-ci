"""Actual serial CPU cost and a diagnostic full-output optimization trajectory."""

import json
from pathlib import Path
import platform
import time

import numpy as np
import torch

import ds_kernel
from fresh import stable32,reference_tools,check_freeze,write


def call(mode,theta,state,jacobian=True):
    if mode=='double_single':
        return ds_kernel.evaluate(theta,state,jacobian=jacobian)
    return stable32.evaluate(theta,state,mode='float32' if mode=='single32' else 'mixed32',
                             candidate=mode=='single32',jacobian=jacobian)


def main():
    receipt=check_freeze()
    timings=[]
    for mode in ('single32','double_single','mixed64'):
        for jacobian in (False,True):
            call(mode,stable32.k.BASE,.1,jacobian)
            start=time.perf_counter()
            checksum=0.
            for state in np.resize([.001,.1,1.,2.],64):
                v,j=call(mode,stable32.k.BASE,state,jacobian)
                checksum += float(v.sum())+(float(j.sum()) if jacobian else 0.)
            elapsed=time.perf_counter()-start
            row=dict(mode=mode,batch=64,jacobian=jacobian,seconds=elapsed,
                     microseconds_per_cell=1e6*elapsed/64,checksum=checksum)
            timings.append(row)
            print(json.dumps(row),flush=True)
    states=[.001,.05,.1]
    teacher=stable32.k.BASE.copy()
    teacher[[2,5,6]]=[.3,.02,1.4]
    target=np.asarray([reference_tools.fields(teacher,x,'log_distance') for x in states],np.float32)
    scale=np.asarray([100,100,1,1,100],np.float32)
    lo=stable32.k.LOWER[[2,5,6]].astype(np.float32)
    hi=stable32.k.UPPER[[2,5,6]].astype(np.float32)
    fits=[]
    for mode in ('double_single','mixed64'):
        theta=stable32.k.BASE.astype(np.float32)
        ratio=(theta[[2,5,6]]-lo)/(hi-lo)
        raw=np.log(ratio/(1-ratio))
        first,second=np.zeros(3,np.float32),np.zeros(3,np.float32)
        trajectory=[]
        start=time.perf_counter()
        for step in range(13):
            sigmoid=1/(1+np.exp(-raw))
            theta[[2,5,6]]=lo+(hi-lo)*sigmoid
            values,tangents=zip(*(call(mode,theta,x) for x in states))
            values,tangents=np.asarray(values),np.asarray(tangents)
            residual=(values-target)/scale
            loss=np.mean(residual**2)
            grad=np.sum(2*residual[:,:,None]*tangents[:,:,[2,5,6]]/scale[None,:,None],axis=(0,1))/residual.size
            grad *= (hi-lo)*sigmoid*(1-sigmoid)
            trajectory.append(dict(step=step,loss=float(loss),theta=theta.tolist(),gradient=grad.tolist()))
            if step<12:
                first,second=.9*first+.1*grad,.999*second+.001*grad**2
                raw -= .04*(first/(1-.9**(step+1)))/(np.sqrt(second/(1-.999**(step+1)))+1e-8)
        row=dict(mode=mode,seconds=time.perf_counter()-start,trajectory=trajectory,
                 loss_reduction=1-trajectory[-1]['loss']/trajectory[0]['loss'])
        fits.append(row)
        print(mode,'fit_seconds',row['seconds'],'loss_reduction',row['loss_reduction'],flush=True)
    assert check_freeze()==receipt
    write('COST_AND_FIT.json',dict(freeze_sha256=receipt,timings=timings,fits=fits,
        environment=dict(python=platform.python_version(),numpy=np.__version__,torch=torch.__version__,
                         platform=platform.platform(),cuda_available=torch.cuda.is_available()),
        scope='Actual scalar-loop CPU batch64; no cache or vectorized throughput claim; 12 FP32 Adam updates fit full HX outputs, not content-task quality',
        memory='DS holds two FP32 parts (64 bits of payload per real scalar, excluding Python/AD overhead); no 32-bit storage advantage'))


if __name__=='__main__':
    main()
