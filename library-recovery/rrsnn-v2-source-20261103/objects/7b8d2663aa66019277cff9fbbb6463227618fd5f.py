"""Same-weight numerical boundary + uniformization implementation control.

Only this process's density module function is temporarily replaced, inside a
finally-restored context. Frozen source files and checkpoint weights are not
edited. The root is solved by bisection; its first derivative is implicit.
The finite-state propagation uses the existing uniformization implementation.

This is a numerical implementation control of the SAME finite CTMC model, not
a continuous PDE solution, not a new model, and not end-to-end retraining.
Only the first 64 frozen validation examples are opened. No test/shift data or
speed comparison is used.
"""
from __future__ import annotations

from contextlib import contextmanager
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

for _name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']:
    os.environ[_name]='1'

import numpy as np
from scipy.optimize import brentq
import torch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import rrsnn_v2.density_model as density_module
from rrsnn_v2.policy import Policy,expected_loss

ANALYTIC_BOUNDARY=density_module.frozen_control_boundary
TOLERANCES={
    'scalar_root_vs_scipy_abs':2e-12,
    'scalar_residual_abs':2e-13,
    'scalar_gradient_fd_abs':5e-7,
    'effective_boundary_abs_float32':2e-5,
    'state_distribution_abs_float32':2e-4,
    'expected_count_abs_float32':2e-4,
    'logit_abs_float32':2e-4,
    'nll_abs_float32':1e-4,
    'gradient_global_relative_l2_float32':5e-4,
    'gradient_global_max_abs_float32':1e-4,
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NumericalBoundary(torch.autograd.Function):
    """Unique root in [c,c+1/gamma], with exact implicit first derivative."""
    @staticmethod
    def forward(ctx,drift,cost,sigma,discount,refractory):
        ctx.drift_shape=drift.shape;ctx.cost_shape=cost.shape
        ctx.drift_dtype=drift.dtype;ctx.cost_dtype=cost.dtype
        mu,c=torch.broadcast_tensors(drift.to(torch.float64),cost.to(torch.float64))
        sigma=float(sigma);discount=float(discount);refractory=float(refractory)
        if sigma<=0 or discount<=0 or refractory<0 or bool((c<=0).any()):
            raise ValueError('Require sigma>0, rho>0, refractory>=0, cost>0')
        root=torch.sqrt(mu.square()+2*discount*sigma*sigma)
        # Algebraically equivalent gamma; the rationalized positive-drift
        # expression avoids subtracting two nearly equal positive numbers.
        gamma=torch.where(mu>=0,2*discount/(root+mu),(root-mu)/(sigma*sigma))
        low=c.clone();high=c+1/gamma
        for _ in range(64):
            middle=(low+high)/2
            residual=gamma*(middle-c)-1+torch.exp(-discount*refractory-gamma*middle)
            low=torch.where(residual<=0,middle,low)
            high=torch.where(residual>0,middle,high)
        h=(low+high)/2
        q=torch.exp(-discount*refractory-gamma*h)
        ctx.save_for_backward(h,c,root,q)
        return h.to(drift.dtype)

    @staticmethod
    def backward(ctx,gradient):
        h,c,root,q=ctx.saved_tensors
        # F_h=gamma*(1-q), gamma_mu=-gamma/root.
        # dh/dc=1/(1-q); dh/dmu=((h-c)-h*q)/((1-q)*root).
        denominator=1-q
        grad=gradient.to(torch.float64)
        drift_gradient=grad*((h-c)-h*q)/(denominator*root)
        cost_gradient=grad/denominator
        return (drift_gradient.sum_to_size(ctx.drift_shape).to(ctx.drift_dtype),
                cost_gradient.sum_to_size(ctx.cost_shape).to(ctx.cost_dtype),
                None,None,None)


def numerical_frozen_control_boundary(drift,cost,sigma=.4,discount=.4,refractory=.1):
    if not torch.is_tensor(cost):
        cost=torch.as_tensor(cost,dtype=drift.dtype,device=drift.device)
    return NumericalBoundary.apply(drift,cost,sigma,discount,refractory)


@contextmanager
def boundary_context(replacement):
    previous=density_module.frozen_control_boundary
    density_module.frozen_control_boundary=replacement
    try:
        yield
    finally:
        density_module.frozen_control_boundary=previous


def boundary_recorder(function,tape):
    def recorded(drift,cost,sigma=.4,discount=.4,refractory=.1):
        h=function(drift,cost,sigma,discount,refractory)
        tape.append({'drift':drift.detach().clone(),'cost':cost.detach().clone(),
                     'raw_boundary':h.detach().clone()})
        return h
    return recorded


def scalar_validation():
    mus=np.linspace(-1.1,1.1,9)
    costs=np.array([.20,.45,.80,1.10])
    pairs=[(m,c) for m in mus for c in costs]
    mu=torch.tensor([p[0] for p in pairs],dtype=torch.float64,requires_grad=True)
    c=torch.tensor([p[1] for p in pairs],dtype=torch.float64,requires_grad=True)
    h=numerical_frozen_control_boundary(mu,c)
    gradients=torch.autograd.grad(h.sum(),(mu,c))
    scipy_reference=[];residuals=[];fd_errors=[];rows=[]
    epsilon=1e-5
    for index,(m,price) in enumerate(pairs):
        radical=np.sqrt(m*m+2*.4*.4*.4)
        gamma=2*.4/(radical+m) if m>=0 else (radical-m)/(.4*.4)
        function=lambda value:gamma*(value-price)-1+np.exp(-.4*.1-gamma*value)
        reference=brentq(function,price,price+1/gamma,xtol=5e-15,rtol=1e-14)
        actual=float(h[index].detach())
        scipy_reference.append(reference);residuals.append(abs(function(actual)))
        finite_difference=[]
        for parameter in range(2):
            plus=[m,price];minus=[m,price]
            plus[parameter]+=epsilon;minus[parameter]-=epsilon
            hp=numerical_frozen_control_boundary(torch.tensor(plus[0],dtype=torch.float64),torch.tensor(plus[1],dtype=torch.float64))
            hm=numerical_frozen_control_boundary(torch.tensor(minus[0],dtype=torch.float64),torch.tensor(minus[1],dtype=torch.float64))
            finite_difference.append(float((hp-hm)/(2*epsilon)))
        error=[abs(float(gradients[k][index])-finite_difference[k]) for k in range(2)]
        fd_errors.append(error)
        rows.append({'drift':float(m),'cost':float(price),'numerical_boundary':actual,
                     'scipy_brentq':reference,'equation_residual':residuals[-1],
                     'implicit_drift_gradient':float(gradients[0][index]),
                     'implicit_cost_gradient':float(gradients[1][index]),
                     'fd_drift_gradient':finite_difference[0],'fd_cost_gradient':finite_difference[1],
                     'gradient_abs_errors':error})
    reference_error=float(np.max(np.abs(h.detach().numpy()-np.asarray(scipy_reference))))
    analytic_error=float((h.detach()-ANALYTIC_BOUNDARY(mu.detach(),c.detach())).abs().max())
    gradient_error=float(np.max(fd_errors))
    checked_mu=torch.tensor([-.8,-.2,.4,1.0],dtype=torch.float64,requires_grad=True)
    checked_cost=torch.tensor(.45,dtype=torch.float64,requires_grad=True)
    gradcheck=torch.autograd.gradcheck(numerical_frozen_control_boundary,(checked_mu,checked_cost),
                                      eps=1e-6,atol=2e-6,rtol=2e-5)
    try:
        with boundary_context(numerical_frozen_control_boundary):
            assert density_module.frozen_control_boundary is numerical_frozen_control_boundary
            raise RuntimeError('intentional-context-restoration-probe')
    except RuntimeError as error:
        assert str(error)=='intentional-context-restoration-probe'
    restored=density_module.frozen_control_boundary is ANALYTIC_BOUNDARY
    assert restored and gradcheck
    assert reference_error<TOLERANCES['scalar_root_vs_scipy_abs']
    assert max(residuals)<TOLERANCES['scalar_residual_abs']
    assert gradient_error<TOLERANCES['scalar_gradient_fd_abs']
    return {'cases':len(rows),'method':'64-step float64 bisection, implicit first derivative',
            'equation':'gamma*(h-c)-1+exp(-rho*tau-gamma*h)=0',
            'bracket':'[c,c+1/gamma]','reset':0.,'sigma':.4,'rho':.4,'refractory':.1,
            'maximum_abs_difference_vs_scipy_brentq':reference_error,
            'maximum_abs_difference_vs_lambert_w_float64':analytic_error,
            'maximum_equation_residual':max(residuals),
            'maximum_implicit_gradient_fd_error':gradient_error,
            'torch_gradcheck_with_broadcast_cost':bool(gradcheck),
            'context_restored_after_exception':restored,'rows':rows,
            'derivative_scope':'implicit first derivative only; no claim of implemented second-order derivatives'}


def load_validation(limit):
    path=ROOT/'data'/'validation.npz'
    with np.load(path) as source:
        n=min(limit,len(source['x']));length=int(source['lengths'][:n].max())
        result={name:torch.from_numpy(source[name][:n,:length].copy())
                for name in ['x','dt','event_mask','valid','optimal','decision']}
    return result,{'file_sha256':sha(path),'case_selection':f'first {n} validation cases',
                   'episodes':n,'maximum_steps':length,'decision_count':int(result['decision'].sum())}


def one_forward_backward(model,data,boundary_function):
    tape=[]
    model.eval();model.zero_grad(set_to_none=True)
    with boundary_context(boundary_recorder(boundary_function,tape)):
        output=model(data['x'],data['dt'],event_mask=data['event_mask'],sampled=False)
        loss=expected_loss(output['logits'],data['valid'],data['optimal'],data['decision'])
        loss.backward()
    gradients={name:parameter.grad.detach().clone() for name,parameter in model.named_parameters()
               if parameter.grad is not None}
    assert len(gradients)==sum(1 for _ in model.parameters())
    assert all(bool(torch.isfinite(value).all()) for value in gradients.values())
    tensors={key:output[key].detach().clone() for key in
             ['boundary','probabilities','spikes','latent','logits']}
    return tensors,float(loss.detach()),gradients,tape


def compare_gradients(analytic,numeric):
    rows=[];a_all=[];b_all=[]
    for name,a in analytic.items():
        b=numeric[name];av=a.to(torch.float64).reshape(-1);bv=b.to(torch.float64).reshape(-1)
        delta=bv-av;an=float(torch.linalg.vector_norm(av));bn=float(torch.linalg.vector_norm(bv))
        rows.append({'parameter':name,'shape':list(a.shape),'analytic_l2':an,'numeric_l2':bn,
                     'maximum_abs_difference':float(delta.abs().max()),
                     'relative_l2_difference':float(torch.linalg.vector_norm(delta))/max(an,1e-12)})
        a_all.append(av);b_all.append(bv)
    a=torch.cat(a_all);b=torch.cat(b_all);difference=b-a
    an=float(torch.linalg.vector_norm(a));bn=float(torch.linalg.vector_norm(b))
    return {'per_parameter':rows,'global_analytic_l2':an,'global_numeric_l2':bn,
            'global_maximum_abs_difference':float(difference.abs().max()),
            'global_relative_l2_difference':float(torch.linalg.vector_norm(difference))/max(an,1e-12),
            'global_cosine_similarity':float(torch.dot(a,b))/max(an*bn,1e-24)}


def compare_seed(seed,data,data_metadata,destination):
    checkpoint=ROOT/'results'/'rr_density_sampled'/f'seed_{seed}'/'model.pt'
    receipt=checkpoint.with_name('training.json')
    if not checkpoint.exists() or not receipt.exists():
        raise FileNotFoundError(f'Completed formal checkpoint missing: {checkpoint}')
    blob=torch.load(checkpoint,map_location='cpu',weights_only=True)
    assert blob.get('sampled_training') is True and blob['variant']=='rr_density'
    analytic=Policy(blob['variant']);analytic.load_state_dict(blob['state_dict'])
    numeric=copy.deepcopy(analytic)
    numeric.encoder.ablations=numeric.encoder.ablations|frozenset({'numerical_kernel'})
    before={key:value.detach().clone() for key,value in analytic.state_dict().items()}
    assert all(torch.equal(value,numeric.state_dict()[key]) for key,value in before.items())
    a,aloss,agrad,atape=one_forward_backward(analytic,data,ANALYTIC_BOUNDARY)
    b,bloss,bgrad,btape=one_forward_backward(numeric,data,numerical_frozen_control_boundary)
    assert density_module.frozen_control_boundary is ANALYTIC_BOUNDARY
    unchanged=all(torch.equal(value,analytic.state_dict()[key]) and torch.equal(value,numeric.state_dict()[key])
                  for key,value in before.items())
    assert unchanged
    assert len(atape)==len(btape)
    controls_identical=all(torch.equal(left[key],right[key]) for left,right in zip(atape,btape)
                           for key in ['drift','cost'])
    assert controls_identical
    raw_a=torch.stack([row['raw_boundary'] for row in atape]);raw_b=torch.stack([row['raw_boundary'] for row in btape])
    branch_a=torch.where(raw_a<.55,-torch.ones_like(raw_a),torch.where(raw_a>2.25,torch.ones_like(raw_a),torch.zeros_like(raw_a)))
    branch_b=torch.where(raw_b<.55,-torch.ones_like(raw_b),torch.where(raw_b>2.25,torch.ones_like(raw_b),torch.zeros_like(raw_b)))
    errors={key:float((a[key]-b[key]).abs().max()) for key in a}
    am=a['logits'].masked_fill(~data['valid'],-1e9).argmax(-1)
    bm=b['logits'].masked_fill(~data['valid'],-1e9).argmax(-1)
    disagreements=int(((am!=bm)&data['decision']).sum())
    gradient_comparison=compare_gradients(agrad,bgrad)
    checks={
        'boundary':errors['boundary']<TOLERANCES['effective_boundary_abs_float32'],
        'state_distribution':errors['probabilities']<TOLERANCES['state_distribution_abs_float32'],
        'expected_counts':errors['spikes']<TOLERANCES['expected_count_abs_float32'],
        'logits':errors['logits']<TOLERANCES['logit_abs_float32'],
        'nll':abs(aloss-bloss)<TOLERANCES['nll_abs_float32'],
        'gradient_relative_l2':gradient_comparison['global_relative_l2_difference']<TOLERANCES['gradient_global_relative_l2_float32'],
        'gradient_max_abs':gradient_comparison['global_maximum_abs_difference']<TOLERANCES['gradient_global_max_abs_float32'],
        'legal_argmax_equal':disagreements==0,
        'boundary_clip_branch_equal':bool(torch.equal(branch_a,branch_b)),
    }
    raw={f'analytic_{key}':value.numpy() for key,value in a.items()}
    raw.update({f'numeric_{key}':value.numpy() for key,value in b.items()})
    raw.update({'analytic_unclipped_boundary':raw_a.numpy(),'numeric_unclipped_boundary':raw_b.numpy()})
    for name in agrad:
        raw['analytic_gradient__'+name]=agrad[name].numpy()
        raw['numeric_gradient__'+name]=bgrad[name].numpy()
    arrays_path=destination/f'seed_{seed}_arrays.npz'
    np.savez_compressed(arrays_path,**raw)
    return {'seed':seed,'checkpoint_sha256':sha(checkpoint),'training_receipt_sha256':sha(receipt),
            'training_plan':blob['plan'],'weights_identical_and_unchanged':unchanged,
            'deterministic_drift_and_cost_tapes_bitwise_equal':controls_identical,
            'validation':data_metadata,'unclipped_boundary_maximum_abs_error':float((raw_a-raw_b).abs().max()),
            'effective_boundary_maximum_abs_error':errors['boundary'],
            'state_distribution_maximum_abs_error':errors['probabilities'],
            'expected_count_maximum_abs_error':errors['spikes'],
            'latent_maximum_abs_error':errors['latent'],'logit_maximum_abs_error':errors['logits'],
            'legal_argmax_disagreements':disagreements,
            'boundary_clip_branch_mismatches':int((branch_a!=branch_b).sum()),
            'deterministic_expected_set_nll':{'analytic':aloss,'full_numeric':bloss,'absolute_difference':abs(aloss-bloss)},
            'one_backward_gradient_comparison':gradient_comparison,
            'checks':checks,'all_checks_passed':all(checks.values()),
            'raw_arrays':str(arrays_path),'raw_arrays_sha256':sha(arrays_path)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds',nargs='+',type=int,default=[101,211,307,401,503])
    parser.add_argument('--limit',type=int,default=64)
    parser.add_argument('--cpu',type=int,default=7)
    args=parser.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    allowed=sorted(os.sched_getaffinity(0));os.sched_setaffinity(0,{args.cpu if args.cpu in allowed else allowed[-1]})
    destination=ROOT/'full_numeric_control_results';destination.mkdir(exist_ok=True)
    frozen_files=['density_model.py','policy.py','train.py','experiment_plan.json']
    frozen_before={name:sha(ROOT/name) for name in frozen_files}
    scalar=scalar_validation()
    data,metadata=load_validation(args.limit)
    rows=[]
    for seed in args.seeds:
        print(json.dumps({'starting_full_numeric_control_seed':seed}),flush=True)
        record=compare_seed(seed,data,metadata,destination);rows.append(record)
        (destination/f'seed_{seed}.json').write_text(json.dumps(record,indent=2)+'\n')
        print(json.dumps({'finished_seed':seed,'all_checks_passed':record['all_checks_passed'],
            'max_logit_error':record['logit_maximum_abs_error'],
            'gradient_relative_l2':record['one_backward_gradient_comparison']['global_relative_l2_difference'],
            'argmax_disagreements':record['legal_argmax_disagreements']}),flush=True)
    frozen_after={name:sha(ROOT/name) for name in frozen_files}
    assert frozen_before==frozen_after
    assert density_module.frozen_control_boundary is ANALYTIC_BOUNDARY
    result={'schema':'rrsnn.v2.full-numeric-implementation-control.v1',
            'complete':True,'seeds':args.seeds,'validation':metadata,
            'scalar_root_and_implicit_gradient_validation':scalar,
            'tolerances_defined_in_source':TOLERANCES,'results':rows,
            'all_model_checks_passed':all(row['all_checks_passed'] for row in rows),
            'frozen_sources_unchanged':True,'frozen_source_sha256':frozen_before,
            'implementation_sha256':sha(Path(__file__).resolve()),
            'boundary_patch_restored':True,'training_runs_added':0,'optimizer_steps_added':0,
            'test_or_shift_opened':False,
            'scope':'Same finite CTMC, same weights/input/grid/Erlang phases/reset/observation map: Lambert-W replaced by numerical root with implicit gradient, matrix exponential replaced by uniformization. Expected-distribution forward and expected-set NLL backward only; not continuous-PDE equivalence, not sampled-path retraining, not full training rerun.',
            'speed_claim':'None; current shared-resource conditions are not used for performance conclusions.',
            'runtime':{'torch':str(torch.__version__),'threads':torch.get_num_threads(),'affinity':list(os.sched_getaffinity(0))}}
    path=destination/'summary.json';path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':str(path),'all_model_checks_passed':result['all_model_checks_passed'],
                      'scalar_fd_error':scalar['maximum_implicit_gradient_fd_error']}),flush=True)


if __name__=='__main__':
    main()
