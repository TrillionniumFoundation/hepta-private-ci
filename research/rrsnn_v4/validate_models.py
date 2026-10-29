"""Independent numerical controls and held-path derivative checks for V4."""
import json
from pathlib import Path
import time
import numpy as np
import torch

from .models import make_policy, RRPolicy, training_objective
from .operators import DensityNeuronOperator, frozen_control_boundary, numerical_control_boundary
from .task import Oracle, make_scenario


def run():
    torch.set_num_threads(1)
    torch.manual_seed(901301)
    checks=[]
    a=torch.linspace(-1.4,1.4,31,dtype=torch.float64,requires_grad=True)
    c=torch.linspace(.21,1.31,31,dtype=torch.float64,requires_grad=True)
    analytic=frozen_control_boundary(a,c)
    numeric=numerical_control_boundary(a,c)
    ga=torch.autograd.grad(analytic.sum(),(a,c),retain_graph=True)
    gn=torch.autograd.grad(numeric.sum(),(a,c))
    value_error=float((analytic-numeric).abs().max().detach())
    gradient_error=max(float((x-y).abs().max()) for x,y in zip(ga,gn))
    assert value_error<2e-11 and gradient_error<2e-9
    checks.append({'name':'independent_bracket_root_vs_Lambert_value_and_gradient',
                   'value_error':value_error,'gradient_error':gradient_error})
    op=DensityNeuronOperator()
    drift=torch.tensor([-.8,.3,1.2],dtype=torch.float64)
    boundary=torch.tensor([.7,1.25,1.9],dtype=torch.float64)
    p=op.reset_distribution(boundary)
    left,count=op.propagate(p,1.75,drift,boundary)
    right,count2=op.propagate(p,1.75,drift,boundary,method='uniformization')
    error=max(float((left-right).abs().max()),float((count-count2).abs().max()))
    assert error<1e-10
    checks.append({'name':'matrix_exponential_vs_controlled_Poisson_series','max_error':error})
    rows=[Oracle(make_scenario(np.random.default_rng(901310+i))).demonstration() for i in range(4)]
    x,dt,valid,optimal,decision=[torch.from_numpy(np.stack([r[j] for r in rows])) for j in range(5)]
    mask=torch.from_numpy(np.arange(32)[None,:]<np.asarray([r[-1] for r in rows])[:,None])
    length=max(r[-1] for r in rows)
    x,dt,valid,optimal,decision,mask=[v[:,:length] for v in (x,dt,valid,optimal,decision,mask)]
    model=RRPolicy().double()
    output=model(x.double(),dt.double(),mask,rng=np.random.default_rng(901320),record_path=True)
    rescored=model.score_fixed_path(x.double(),output['path_records'])
    original=output['full_path_log_probability'].sum(-1)
    score_error=float((rescored-original).abs().max().detach())
    assert score_error<1e-10
    objective=rescored.sum()
    gradient=torch.autograd.grad(objective,model.input_layer.weight)[0]
    finite_differences=[]
    for index in [(0,0),(1,4),(2,7),(5,19)]:
        parameter=model.input_layer.weight
        before=float(parameter[index].detach());epsilon=1e-6
        with torch.no_grad():parameter[index]=before+epsilon
        plus=float(model.score_fixed_path(x.double(),output['path_records']).sum().detach())
        with torch.no_grad():parameter[index]=before-epsilon
        minus=float(model.score_fixed_path(x.double(),output['path_records']).sum().detach())
        with torch.no_grad():parameter[index]=before
        fd=(plus-minus)/(2*epsilon);actual=float(gradient[index])
        relative=abs(fd-actual)/(1+abs(fd))
        assert relative<2e-5,(index,fd,actual)
        finite_differences.append({'index':index,'finite_difference':fd,'analytic':actual,'scaled_error':relative})
    checks.append({'name':'censored_marked_path_rescore_and_fixed_path_gradient',
                   'path_score_error':score_error,'comparisons':finite_differences})
    prefixed_x=torch.cat((torch.zeros_like(x[:,:1]),x),1).double()
    prefixed_dt=torch.cat((torch.zeros_like(dt[:,:1]),dt),1).double()
    prefixed_mask=torch.cat((torch.zeros_like(mask[:,:1]),mask),1)
    frozen=RRPolicy(variant='rr_frozen_resource').double()
    no_op=frozen(prefixed_x,prefixed_dt,prefixed_mask,rng=np.random.default_rng(901325),record_path=True)
    score=frozen.score_fixed_path(prefixed_x,no_op['path_records'])
    prefix_error=float((score-no_op['full_path_log_probability'].sum(-1)).abs().max().detach())
    assert prefix_error<1e-10 and torch.equal(no_op['state'].initial_resource,x[:,0,4:5].double())
    checks.append({'name':'frozen_resource_latches_first_true_observation_after_noop_prefix','score_error':prefix_error})
    variants=['rr_full','fp_no_rollover','rr_mean_maturity','rr_shuffle_maturity',
              'rr_fixed_boundary','rr_frozen_resource','lif','alif','resource_lif',
              'ctrnn','ctrnn_state','ctrnn_upper_state','alif_analog','ctrnn_analog']
    cases=[]
    before=x.clone()
    for name in variants:
        torch.manual_seed(901330)
        m=make_policy(name)
        out=m(x,dt,mask,rng=np.random.default_rng(901331))
        loss=training_objective(out,valid,optimal,decision);loss.backward()
        assert sum(p.numel() for p in m.parameters())==977
        assert all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in m.parameters())
        assert torch.equal(x,before),'ablation mutated common observations'
        if name=='rr_frozen_resource':
            assert torch.equal(out['state'].initial_resource,x[:,0,4:5])
        cases.append({'variant':name,'parameters':977,'loss':float(loss.detach()),
                      'physical_latent_spikes':int(out['actual_counts'].sum()),
                      'gradient_l2':float(torch.sqrt(sum(p.grad.square().sum() for p in m.parameters())))})
    checks.append({'name':'all_variants_causal_forward_and_finite_training_gradient','cases':cases})
    # The numerical solver changes only the computation of the same boundary.
    model=RRPolicy().double();numeric_model=RRPolicy(boundary_method='root').double()
    numeric_model.load_state_dict(model.state_dict())
    a=model(x.double(),dt.double(),mask,rng=np.random.default_rng(901340))
    b=numeric_model(x.double(),dt.double(),mask,rng=np.random.default_rng(901340))
    maximum=float((a['logits']-b['logits']).abs().max().detach())
    assert torch.equal(a['actual_counts'],b['actual_counts']) and maximum<1e-9
    checks.append({'name':'same_weights_numerical_boundary_physical_network','logit_error':maximum})
    result={'schema':'rrsnn.v4-model-validation.1','all_passed':True,'checks':checks,
            'development_only':True,'training_or_holdout_data_generated':False,
            'scope':'Finite CTMC and fixed scalar threshold formula; no global network QVI claim.'}
    path=Path(__file__).with_name('model_validation.json')
    path.write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
