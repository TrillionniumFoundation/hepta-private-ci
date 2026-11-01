"""Optional DS backend in an unchanged finite-cell Torch/Bayes computation.

This is DS financial arithmetic followed by FP64 Torch propagation, explicitly
not a wholly low-precision recurrent model or a new content experiment.
"""

import hashlib
import importlib.util
from pathlib import Path
import time

import numpy as np
import torch

import ds_kernel
from fresh import write,check_freeze

SOURCE=Path(__file__).resolve().parents[2]/'unified_cell_r12_20261031'/'contract.py'
SPEC=importlib.util.spec_from_file_location('r13_ds_chain_contract',SOURCE)
c=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
ORIGINAL=c.FinancialOutputs


class DSOutputs(torch.autograd.Function):
    @staticmethod
    def forward(ctx,theta,z):
        v,j=ds_kernel.evaluate(theta.detach().numpy(),z.detach().item())
        ctx.save_for_backward(torch.as_tensor(j,dtype=theta.dtype))
        return torch.as_tensor(v,dtype=theta.dtype)

    @staticmethod
    def backward(ctx,gradient):
        result=gradient@ctx.saved_tensors[0]
        return result[:9],result[9]


def loss(theta,steps,backend):
    c.FinancialOutputs=DSOutputs if backend=='double_single' else ORIGINAL
    terms=c.model_terms(theta=theta,n_active=8,prices=True)
    p=terms['prior']
    emission=c.emission_matrix(n_active=8)
    transitions={dt:torch.matrix_exp(terms['Q']*dt) for dt in (.05,.15,.45)}
    for i in range(steps):
        p=p@transitions[(.05,.15,.45)[i%3]]
        p=p*emission[:,(6,0,2,4,1,3)[i%6]]
        p=p/p.sum()
    objective=-torch.log(p[:10].sum())
    objective += .03*(p*terms['read_cost']).sum()
    objective -= .02*(p*terms['answer_rewards'][:,0]).sum()
    return objective


def main():
    torch.set_num_threads(1)
    receipt=check_freeze()
    rows=[]
    for steps in (12,64):
        theta=ds_kernel.k.BASE.astype(np.float32).astype(np.float64)
        gradients={}
        values={}
        timings={}
        for backend in ('double_single','float64'):
            arg=torch.tensor(theta,dtype=torch.float64,requires_grad=True)
            start=time.perf_counter()
            value=loss(arg,steps,backend)
            value.backward()
            values[backend]=value.item()
            gradients[backend]=arg.grad.detach().numpy()
            timings[backend]=time.perf_counter()-start
        comparisons=[]
        for i in (2,5,6):
            for relative in (1e-3,5e-4):
                h=relative*max(.01,abs(theta[i]))
                plus,minus=theta.copy(),theta.copy()
                plus[i]+=h
                minus[i]-=h
                with torch.no_grad():
                    a=loss(torch.tensor(plus),steps,'double_single').item()
                    b=loss(torch.tensor(minus),steps,'double_single').item()
                secant=(a-b)/(2*h)
                ad=gradients['double_single'][i]
                scaled=float(abs(secant-ad)/max(1,abs(ad)))
                comparisons.append(dict(parameter=i,relative_step=relative,secant=secant,ad=float(ad),scaled_error=scaled))
        chain_error=float(np.max(np.abs(gradients['double_single']-gradients['float64'])/
                                 np.maximum(1,np.abs(gradients['float64']))))
        row=dict(steps=steps,theta=theta.tolist(),loss=values,
                 gradients={k:v.tolist() for k,v in gradients.items()},timings=timings,
                 ds_to_float64_ad_error=chain_error,cast_secants=comparisons,
                 passed=bool(chain_error<=2e-5 and max(r['scaled_error'] for r in comparisons)<=.01))
        rows.append(row)
        print(steps,'DS/FP64 AD error',chain_error,'cast secant max',max(r['scaled_error'] for r in comparisons),flush=True)
    assert check_freeze()==receipt
    write('CHAIN_GRADIENT.json',dict(freeze_sha256=receipt,contract_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),rows=rows,
        precision='DS full-HX -> FP64 reset/Q/matrix_exp -> repeated Bayes -> content/read-cost/answer-reward loss',
        cast_secant_rule='Original R11 cast secant relative steps 1e-3/5e-4 and tolerance .01; not the derivative of a discontinuous quantizer. Full-HX reference Jacobian gate remains 2e-5.',
        scope='Optional-backend integration diagnostic on the unchanged R12 finite cell; no R13 task-quality or all-FP32 recurrence claim'))


if __name__=='__main__':
    main()
