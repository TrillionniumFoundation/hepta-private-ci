"""Focused operator/gradient/accounting checks, not a task-performance benchmark."""
from pathlib import Path
import hashlib
import itertools
import json
import math
import sys

import numpy as np
from scipy.integrate import quad
from scipy.special import lambertw, ndtr
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from rrsnn_experiments.models import (
    CANONICAL_VARIANTS, SurrogateSequenceModel, BudgetMatchedCTRNN,
    first_hit_cdf, discounted_hit, numerical_hit_integral,
    surviving_distance_mean, optimal_reset_threshold,
)


def close_gradient(function,values,eps=1e-5):
    args=[torch.tensor([v],dtype=torch.float64,requires_grad=True) for v in values]
    value=function(*args)
    gradients=torch.autograd.grad(value.sum(),args)
    checks=[]
    for i,gradient in enumerate(gradients):
        plus=[a.detach().clone() for a in args]
        minus=[a.detach().clone() for a in args]
        plus[i]+=eps;minus[i]-=eps
        numeric=float(((function(*plus)-function(*minus))/(2*eps)).item())
        auto=float(gradient.item())
        checks.append({'autograd':auto,'finite_difference':numeric,'abs_error':abs(auto-numeric)})
    return checks


def sample_sequence():
    torch.manual_seed(37)
    x=torch.zeros(8,7,22)
    x[:,0,:4]=torch.rand(8,4)
    x[:,:,4]=torch.tensor([1.,1.,.4,.4,.8,.8,.8])
    x[:,:,5]=1.
    actual_time=torch.tensor([0.,1.,1.5,2.,2.5,3.,4.])
    deadlines=torch.tensor([1.,3.,1.,3.])
    remaining=(deadlines[None,:]-actual_time[:,None]).clamp(min=0)/4
    x[:,:,7:11]=remaining
    x[:,:,6]=remaining.mean(dim=-1)
    x[:,:,11:15]=1
    x[:,0,15]=.6;x[:,0,16]=.375
    x[:,0,17]=.7;x[:,0,18]=.625
    x[:,:,19]=actual_time/4
    x[:,0,20]=1;x[:,:,21]=1/6
    dt=torch.tensor([0.,1.,.5,.5,.5,.5,1.])
    return x,dt


def main():
    torch.set_num_threads(1)
    out=Path(__file__).resolve().parent
    checks={}
    parameters=np.array(list(itertools.product([1e-4,.02,.1,.5,1.,3.],[-1.,0.,.8],[.05,.5,2.])))
    x=torch.tensor(parameters[:,0],dtype=torch.float64)
    mu=torch.tensor(parameters[:,1],dtype=torch.float64)
    t=torch.tensor(parameters[:,2],dtype=torch.float64)
    a=first_hit_cdf(x,t,mu,.4)
    reference=ndtr((-parameters[:,0]-parameters[:,1]*parameters[:,2])/(.4*np.sqrt(parameters[:,2])))
    reference+=np.exp(-2*parameters[:,1]*parameters[:,0]/.4**2)*ndtr(
        (-parameters[:,0]+parameters[:,1]*parameters[:,2])/(.4*np.sqrt(parameters[:,2])))
    checks['cdf_scipy_max_abs_error']=float(np.max(np.abs(a.numpy()-reference)))
    checks['quadrature']={}
    for rho in [0,.4]:
        analytic=a if not rho else discounted_hit(x,t,mu,.4,rho)
        numeric=numerical_hit_integral(x,t,mu,.4,rho=rho)
        error=(analytic-numeric).abs()
        i=int(error.argmax())
        checks['quadrature'][str(rho)]={'max_abs_error':float(error.max()),
              'worst_x_mu_t':parameters[i].tolist(),'n_cases':len(parameters),
              'method':'two-interval transformed-density Gauss-Legendre, 48 nodes each'}
        assert error.max()<2e-6
    checks['cdf_gradients']=close_gradient(lambda xx,mm:first_hit_cdf(xx,torch.ones_like(xx)*.8,mm,.4),[.7,-.3])
    checks['discount_gradients']=close_gradient(lambda xx,mm:discounted_hit(xx,torch.ones_like(xx)*.8,mm,.4,.4),[.7,-.3])
    checks['threshold_gradients']=close_gradient(lambda aa,cc:optimal_reset_threshold(aa,.4,.4,cc,refractory=.1),[.7,.2])
    for label in ['cdf_gradients','discount_gradients','threshold_gradients']:
        assert max(c['abs_error'] for c in checks[label])<1e-6
    threshold,kroot=optimal_reset_threshold(torch.tensor([.7],dtype=torch.float64),.4,.4,torch.tensor([.2],dtype=torch.float64)),None
    gamma=(math.sqrt(.7**2+2*.4*.4**2)-.7)/.4**2
    scipy_threshold=.2+(1+float(lambertw(-math.exp(-.4*.1-1-gamma*.2)).real))/gamma
    checks['threshold_scipy_abs_error']=abs(float(threshold)-scipy_threshold)
    assert checks['threshold_scipy_abs_error']<1e-10

    checks['surviving_mean']=[]
    for xx,mm,tt in [(0.2,-.7,.5),(.8,.2,1.),(.6,0.,.8)]:
        def kernel(z):
            return math.exp(-(z-xx-mm*tt)**2/(2*.4**2*tt))/(.4*math.sqrt(2*math.pi*tt))*(-math.expm1(-2*xx*z/(.4**2*tt)))
        mass=quad(kernel,0,np.inf,epsabs=1e-12)[0]
        numerical=quad(lambda z:z*kernel(z),0,np.inf,epsabs=1e-12)[0]/mass
        analytic=float(surviving_distance_mean(torch.tensor([xx],dtype=torch.float64),
                  torch.tensor([tt],dtype=torch.float64),torch.tensor([mm],dtype=torch.float64),.4))
        checks['surviving_mean'].append({'x':xx,'mu':mm,'t':tt,'analytic':analytic,
                 'quadrature':numerical,'abs_error':abs(analytic-numerical)})
        assert abs(analytic-numerical)<1e-9

    sequence,dt=sample_sequence()
    checks['models']={}
    for variant in CANONICAL_VARIANTS:
        torch.manual_seed(101)
        model=SurrogateSequenceModel(variant,22,16,mode='expected')
        result=model(sequence,dt)
        loss=result['latent'].square().mean()
        loss.backward()
        finite=all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters())
        assert result['latent'].shape==(8,7,16) and finite
        assert bool(torch.isfinite(result['latent']).all())
        assert model.state_accounting()['trainable_parameters']==624
        model.mode='hard'
        hard=model(sequence,dt,generator=torch.Generator().manual_seed(421))
        binary=bool(((hard['spikes']==0)|(hard['spikes']==1)).all())
        assert binary
        checks['models'][variant]={'finite_gradients':finite,'hard_events_binary':binary,
             'finite_outputs':True,'accounting':model.state_accounting(),
             'expected_loss_probe':float(loss.detach())}
    torch.manual_seed(101)
    rr=SurrogateSequenceModel('rr_full',22,16,mode='expected')
    rr_output=rr(sequence,dt)['latent'].detach()
    checks['ablations']={}
    for ablation in ['no_rollover','collapse_maturity','shuffle_maturity','fixed_boundary','frozen_resource','numerical_kernel']:
        model=SurrogateSequenceModel('rr_full',22,16,mode='expected',ablations=[ablation])
        model.load_state_dict(rr.state_dict())
        value=model(sequence,dt)['latent']
        value.square().mean().backward()
        finite=all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters())
        assert finite
        delta=float((value.detach()-rr_output).abs().max())
        checks['ablations'][ablation]={'finite_gradients':finite,'same_weight_max_latent_difference':delta,
                                      'scope':'mechanism branch only, full input projection unchanged'}
    fixed=SurrogateSequenceModel('fp_multi_fixed',22,16,mode='expected')
    rr_fixed=SurrogateSequenceModel('rr_full',22,16,mode='expected',ablations=['fixed_boundary'])
    fixed.load_state_dict(rr.state_dict());rr_fixed.load_state_dict(rr.state_dict())
    difference=float((fixed(sequence,dt)['latent']-rr_fixed(sequence,dt)['latent']).abs().max())
    checks['fixed_boundary_equivalence_max_difference']=difference
    assert difference==0.0
    xa=sequence[:,0].clone();xb=xa.clone()
    xa[:,7:11]=torch.tensor([.25,.75,.25,.75]);xb[:,7:11]=.5
    pa=rr._maturity(xa)[2];pb=rr._maturity(xb)[2]
    checks['same_mean_different_profile_pressure']={'A':float(pa[0]),'B':float(pb[0]),'same_mean':True}
    assert abs(float(pa[0]-pb[0]))>.01
    collapsed=SurrogateSequenceModel('rr_full',22,16,ablations=['collapse_maturity'])
    collapsed_delta=float((collapsed._maturity(xa)[2]-collapsed._maturity(xb)[2]).abs().max())
    checks['collapse_equal_mean_pressure_difference']=collapsed_delta
    assert collapsed_delta==0
    permuted=xa.clone();perm=[2,0,3,1]
    permuted[:,7:11]=xa[:,7:11][:,perm];permuted[:,11:15]=xa[:,11:15][:,perm]
    checks['paired_item_permutation_pressure_difference']=float((rr._maturity(xa)[2]-rr._maturity(permuted)[2]).abs().max())

    low_resource=sequence.clone()
    low_resource[:,:,4]=0.0
    checks['zero_resource_freeze']={}
    for name in ['resource_lif','fp_no_maturity','fp_multi_fixed','rr_full']:
        model=SurrogateSequenceModel(name,22,16,mode='hard')
        blocked=model(low_resource,dt,generator=torch.Generator().manual_seed(11))
        checks['zero_resource_freeze'][name]={
            'emitted_events':float(blocked['spikes'].sum()),
            'effective_probability_sum':float(blocked['probabilities'].sum()),
            'max_abs_latent':float(blocked['latent'].abs().max())}
        assert float(blocked['spikes'].sum())==0
        assert float(blocked['probabilities'].sum())==0
        assert float(blocked['latent'].abs().max())==0

    stronger=BudgetMatchedCTRNN()
    result=stronger(sequence,dt)
    result['logits'].square().mean().backward()
    checks['budget_matched_ctrnn']={'accounting':stronger.state_accounting(),
       'finite_gradients':all(bool(torch.isfinite(p.grad).all()) for p in stronger.parameters()),
       'logit_shape':list(result['logits'].shape)}
    assert stronger.state_accounting()['trainable_parameters']==1984
    assert stronger.state_accounting()['active_state_bytes_per_sequence']==384
    assert result['logits'].shape==(8,7,81)
    checks['scope']='Operator, surrogate-gradient, binary-event, and accounting checks only; no trained task outcome.'
    checks['torch_version']=torch.__version__
    checks['source_sha256']={name:hashlib.sha256((out/name).read_bytes()).hexdigest()
                             for name in ['sequence_models.py','budget_ctrnn.py']}
    (out/'validation_results.json').write_text(json.dumps(checks,indent=2)+'\n')
    print(json.dumps(checks,indent=2))


if __name__=='__main__':
    main()
