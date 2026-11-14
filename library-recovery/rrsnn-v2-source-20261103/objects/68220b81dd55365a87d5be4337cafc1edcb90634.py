"""Exact small-path enumeration vs the frozen sampled-state training estimator.

This checks root policy.py without editing it. Endpoint state paths are fully
enumerated for a small real Policy, then independent Monte Carlo minibatches
use Policy.forward(sampled=True) and sampled_state_objective verbatim.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch

from ..density_model import DensityState
from ..policy import Policy, set_nll_per_decision, sampled_state_objective

OUT=Path(__file__).resolve().parent/"results"


def fixtures():
    x=torch.zeros(2,3,22,dtype=torch.float64)
    x[:,:,4]=.7;x[:,:,7:11]=.5;x[:,:,11:15]=1
    x[0,:,0]=torch.tensor([.8,.2,-.1]);x[1,:,0]=torch.tensor([-.8,-.2,.1])
    dt=torch.tensor([[0.,.4,.5],[0.,.4,.5]],dtype=torch.float64)
    valid=torch.zeros(2,3,81,dtype=torch.bool);valid[:,:,:2]=True
    optimal=torch.zeros_like(valid);optimal[0,:,0]=True;optimal[1,:,1]=True
    decisions=torch.tensor([[False,False,True],[False,False,True]])
    return x,dt,valid,optimal,decisions


def enumerated_objective(model,x,dt,valid,optimal,decisions):
    total=x.new_zeros(())
    path_count=0
    max_correction=0.
    for sequence in range(len(x)):
        initial=model.initial_state(1,dtype=x.dtype)
        def visit(state,index,weight,cost):
            nonlocal path_count,max_correction
            updated,out=model.encoder.step(state,x[sequence:sequence+1,index],dt[sequence,index])
            p=updated.probability
            normalized=p.clamp(min=0);normalized=normalized/normalized.sum(-1,keepdim=True)
            max_correction=max(max_correction,float((p-normalized).abs().max().detach()))
            expected=x.new_zeros(())
            for chosen in range(p.shape[-1]):
                mass=normalized[0,0,chosen]
                if float(mass.detach())==0:
                    continue
                onehot=torch.zeros_like(p);onehot[0,0,chosen]=1
                sampled=DensityState(onehot,updated.context,updated.drift,
                                     updated.boundary,updated.initial_resource)
                latent=model.encoder.operator.readout(onehot,updated.boundary)
                logits=model.head(latent)
                current=set_nll_per_decision(logits,valid[sequence:sequence+1,index],
                                             optimal[sequence:sequence+1,index]).sum()
                new_cost=cost+current*decisions[sequence,index]
                new_weight=weight*mass
                if index+1==x.shape[1]:
                    expected=expected+new_weight*new_cost;path_count+=1
                else:
                    expected=expected+visit(sampled,index+1,new_weight,new_cost)
            return expected
        total=total+visit(initial,0,x.new_ones(()),x.new_zeros(()))
    return total/decisions.sum(),path_count,max_correction


def selected_gradients(objective,model):
    parameters=(model.encoder.input_layer.bias,model.encoder.recurrent_layer.weight,
                model.head.weight,model.head.bias)
    grads=torch.autograd.grad(objective,parameters)
    return np.array([float(grads[0][0]),float(grads[1][0,0]),
                     float(grads[2][0,0]),float(grads[3][0])])


def main():
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(87001)
    began=time.perf_counter()
    source=Path(__file__).resolve().parents[1]/"policy.py"
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    model=Policy("rr_fixed",hidden=1,grid_size=3,phases=1).double()
    with torch.no_grad():
        model.encoder.input_layer.weight.zero_();model.encoder.input_layer.weight[0,0]=.3
        model.encoder.input_layer.bias.fill_(.75);model.encoder.recurrent_layer.weight.fill_(.2)
        model.head.weight.zero_();model.head.bias.zero_()
        model.head.weight[0,0]=.8;model.head.weight[1,0]=-.6
        model.head.bias[0]=.1;model.head.bias[1]=-.1
    fixture=fixtures()
    exact,paths,correction=enumerated_objective(model,*fixture)
    exact_value=float(exact.detach());truth=selected_gradients(exact,model)
    # Independent minibatches retain the actual LOO baseline implementation.
    repetitions,batch=32,512
    ids=torch.arange(batch)%2
    arrays=tuple(arr[ids] for arr in fixture)
    estimates=[];losses=[]
    for repeat in range(repetitions):
        output=model(arrays[0],arrays[1],generator=torch.Generator().manual_seed(87101+repeat),sampled=True)
        loss=sampled_state_objective(output,*arrays[2:])
        losses.append(float(loss.detach()));estimates.append(selected_gradients(loss,model))
    estimates=np.asarray(estimates);mean=estimates.mean(0);se=estimates.std(0,ddof=1)/np.sqrt(repetitions)
    z=(mean-truth)/se
    assert np.isfinite(estimates).all() and np.max(abs(z))<4.5,(mean,truth,se,z)
    # The declared forward loss should be the sampled per-decision NLL, while
    # its derivative contains the likelihood-ratio correction.
    nll=set_nll_per_decision(output["logits"],arrays[2],arrays[3])[arrays[4]].mean()
    assert abs(float(loss.detach()-nll.detach()))<1e-12
    current_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    assert current_hash==source_hash
    result={"schema":"rrsnn.independent-sampled-state-objective-audit.v1",
        "policy_source_sha256":source_hash,"source_unchanged":True,
        "model":"Actual Policy(rr_fixed,H1,N3,K1), two input sequences, three observed endpoints",
        "enumerated_nonzero_paths":paths,"exact_expected_nll":exact_value,
        "mc_average_forward_nll":float(np.mean(losses)),
        "mc_forward_nll_standard_error":float(np.std(losses,ddof=1)/np.sqrt(repetitions)),
        "selected_parameters":["input_layer.bias[0]","recurrent_layer.weight[0,0]",
                               "head.weight[0,0]","head.bias[0]"],
        "exact_enumerated_gradients":truth.tolist(),"mc_gradient_mean":mean.tolist(),
        "mc_gradient_standard_error":se.tolist(),"mc_gradient_z_scores":z.tolist(),
        "raw_minibatch_gradients":estimates.tolist(),"minibatches":repetitions,"batch_size":batch,
        "maximum_enumeration_probability_correction":correction,
        "forward_loss_equals_sampled_nll":True,"elapsed_seconds":time.perf_counter()-began,
        "mathematical_review":{
            "objective":"Expected sum of decision NLL divided by the fixed total number of supplied demonstration decisions.",
            "score":"Sum of log probabilities of sampled observed endpoint states, including observed remapping and marginalizing every unobserved within-interval jump.",
            "baseline":"Leave-one-sequence-out detached total loss is independent of each sequence's own random state path; heterogenous deterministic inputs do not invalidate this independence.",
            "direct_derivative":"Required because the readout/head and grid coordinates depend on parameters even conditional on sampled indices.",
            "numerical_law":"Clipping and renormalization make the scored normalized distribution match the distribution actually sampled; floating-point corrections are not exact uncorrected CTMC probabilities.",
            "valid_scope":"Independent sequence samples, externally supplied demonstration inputs and fixed decision masks. This is not an RL estimator for parameter-dependent environment trajectories."},
        "naming_limits":["Observed endpoint-state trajectory likelihood; not spike-time likelihood or full CTMC jump-path likelihood.",
                         "Expected counts returned alongside a sampled endpoint are conditional expectations, not realized within-interval counts.",
                         "moment_collapse sampling, if enabled, defines another observation-transition model and must not be labelled pure Q-generated CTMC.",
                         "This small exact enumeration verifies the score implementation; it does not guarantee low estimator variance in large tasks."]}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"sampled_state_objective_audit.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"passed":True,"seconds":result["elapsed_seconds"],"gradient_z":z.tolist()}),flush=True)


if __name__=="__main__":
    main()
