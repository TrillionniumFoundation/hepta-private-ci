"""Independent numerical checks of the supplementary full-path CTMC policy.

The exact reference integrates a supplied generator with a matrix exponential;
it does not reuse the sampler's holding-time/jump implementation.  Monte Carlo
gradient error bars are sampling diagnostics, not hypothesis tests of efficacy.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch

from ..density_model import DensityNeuronOperator
from ..train import arrays
from .model import (CoupledSpikePolicy, categorical_rows, chosen_log_probability,
                    full_path_objective, interval_log_likelihood,
                    normalized_probabilities, sample_interval)

ROOT=Path(__file__).resolve().parent


def exact_count_and_trace(operator,theta,horizon,tau=2.5,detach_reset=False):
    drift,boundary=theta[0].reshape(1,1),theta[1].reshape(1,1)
    q,reward=operator.generator(drift,boundary)
    probability=operator.reset_distribution(boundary)
    if detach_reset:
        probability=probability.detach()
        # Include the repeated refractory-release reset law, not just p(0).
        q=q.clone();q[...,-1,:]=q[...,-1,:].detach()
    size=operator.state_size
    augmented=theta.new_zeros(size+2,size+2)
    augmented[:size,:size]=q[0,0]
    augmented[:size,size]=reward[0,0]
    augmented[:size,size+1]=reward[0,0]
    augmented[-1,-1]=-1/tau
    initial=torch.cat((probability[0,0],theta.new_zeros(2)))
    final=initial@torch.matrix_exp(augmented*horizon)
    return final[-2],final[-1]


def interval_gradient_audit(paths=32768):
    torch.set_default_dtype(torch.float64)
    op=DensityNeuronOperator(grid_size=12,refractory_phases=3,
                             sigma=.45,refractory=.17)
    theta=torch.tensor([1.7,.83],requires_grad=True)
    horizon=1.6;tau=2.5
    exact_count,exact_trace=exact_count_and_trace(op,theta,horizon,tau)
    exact_value=exact_count+.3*exact_trace
    exact_gradient=torch.autograd.grad(exact_value,theta)[0].detach().numpy()
    wrong_count,wrong_trace=exact_count_and_trace(op,theta,horizon,tau,True)
    wrong_gradient=torch.autograd.grad(wrong_count+.3*wrong_trace,theta)[0].detach().numpy()
    q,_=op.generator(theta[0].reshape(1,1),theta[1].reshape(1,1))
    p=normalized_probabilities(op.reset_distribution(theta[1].reshape(1,1)))
    rng=np.random.default_rng(710301)
    p_many=p.expand(paths,1,-1)
    initial=categorical_rows(p_many.detach().numpy(),rng)
    sampled=sample_interval(q.detach().numpy().repeat(paths,axis=0),initial,
        np.full(paths,horizon),np.zeros((paths,1)),rng,trace_tau=tau,
        spike_edge=(op.grid_size-1,op.grid_size))
    counts=sampled['counts'][:,0];traces=sampled['trace'][:,0]
    payoff=counts+.3*traces
    # The exact expectation is a deterministic, sample-independent baseline.
    weights=payoff-float(exact_value.detach())
    logscore=chosen_log_probability(p_many,initial).sum(-1)
    logscore+=interval_log_likelihood(q.expand(paths,-1,-1,-1),
        sampled['jump_counts'],sampled['dwell_times']).sum(-1)
    estimator=(torch.from_numpy(weights)*logscore).mean()
    mc_gradient=torch.autograd.grad(estimator,theta)[0].detach().numpy()
    epsilon=1e-5;per_path_scores=[]
    for parameter in range(2):
        scores=[]
        for sign in (1,-1):
            changed=theta.detach().clone();changed[parameter]+=sign*epsilon
            changed_q,_=op.generator(changed[0].reshape(1,1),changed[1].reshape(1,1))
            changed_p=normalized_probabilities(op.reset_distribution(changed[1].reshape(1,1)))
            score=chosen_log_probability(changed_p.expand(paths,-1,-1),initial).sum(-1)
            score+=interval_log_likelihood(changed_q.expand(paths,-1,-1,-1),
                sampled['jump_counts'],sampled['dwell_times']).sum(-1)
            scores.append(score.detach().numpy())
        per_path_scores.append((scores[0]-scores[1])/(2*epsilon))
    per_path_scores=np.stack(per_path_scores,axis=-1)
    contributions=weights[:,None]*per_path_scores
    se=contributions.std(axis=0,ddof=1)/np.sqrt(paths)
    z=(mc_gradient-exact_gradient)/se
    fd_error=np.max(np.abs(contributions.mean(axis=0)-mc_gradient))
    score_mean=per_path_scores.mean(axis=0)
    score_se=per_path_scores.std(axis=0,ddof=1)/np.sqrt(paths)
    value_se=float(payoff.std(ddof=1)/np.sqrt(paths))
    assert np.max(np.abs(z))<4.5,(mc_gradient,exact_gradient,se,z)
    assert fd_error<2e-7,fd_error
    assert abs(payoff.mean()-float(exact_value.detach()))<4.5*value_se
    assert np.mean(counts>=2)>.25
    assert np.max(np.abs(score_mean/score_se))<4.5
    result={'paths':paths,'seed':710301,'parameters':{'drift':1.7,'boundary':.83,
            'sigma':.45,'refractory_mean':.17,'grid_size':12,'refractory_phases':3,
            'horizon':horizon,'trace_tau':tau},
        'payoff':'realized total count + 0.3 * terminal exponential spike trace',
        'exact_count':float(exact_count.detach()),'mc_count':float(counts.mean()),
        'exact_trace':float(exact_trace.detach()),'mc_trace':float(traces.mean()),
        'exact_payoff':float(exact_value.detach()),'mc_payoff':float(payoff.mean()),
        'payoff_standard_error':value_se,'repeat_spike_probability_mc':float(np.mean(counts>=2)),
        'parameters_gradient_order':['drift','boundary'],
        'exact_gradient':exact_gradient.tolist(),'mc_full_path_gradient':mc_gradient.tolist(),
        'gradient_standard_error':se.tolist(),'gradient_standardized_error':z.tolist(),
        'fixed_path_score_finite_difference_vs_autograd_max_error':float(fd_error),
        'mean_score':score_mean.tolist(),'score_mean_standard_error':score_se.tolist(),
        'incorrect_gradient_if_initial_and_repeated_reset_probabilities_detached':wrong_gradient.tolist(),
        'boundary_reset_gradient_contribution':float(exact_gradient[1]-wrong_gradient[1]),
        'dwell_time_sum_max_error':float(np.max(np.abs(sampled['dwell_times'].sum(-1)-horizon))),
        'scope':'Finite CTMC exact matrix-exponential expectation versus complete real-jump path likelihood; not a continuous diffusion claim.'}
    torch.set_default_dtype(torch.float32)
    return result


def path_and_causality_audit():
    torch.manual_seed(710302)
    model=CoupledSpikePolicy().double()
    data=arrays('train');b=4;length=int(data['lengths'][:b].max())
    x=data['x'][:b,:length].double();dt=data['dt'][:b,:length].double()
    mask=data['event_mask'][:b,:length]
    output=model(x,dt,mask,rng=np.random.default_rng(710303),record_spikes=True,record_path=True)
    recorded=output['path_records']
    original_score=output['full_path_log_probability'].sum(-1)
    rescored=model.score_fixed_path(x,recorded)
    score_error=float((original_score-rescored).abs().max().detach())
    assert score_error<1e-10
    weights=torch.tensor([.7,-.4,.2,1.1],dtype=torch.float64)
    score=(rescored*weights).sum()
    parameters=dict(model.named_parameters())
    named_indices=[('input_layer.weight',(0,4)),('input_layer.bias',(3,)),
                   ('recurrent_layer.weight',(0,1)),('recurrent_layer.weight',(4,3))]
    gradients=torch.autograd.grad(score,[parameters[name] for name in dict(named_indices)],allow_unused=False)
    gradient_map=dict(zip(dict(named_indices),gradients))
    fd_rows=[];epsilon=1e-6
    for name,index in named_indices:
        parameter=parameters[name];old=float(parameter[index].detach());values=[]
        for sign in (1,-1):
            with torch.no_grad():parameter[index]=old+sign*epsilon
            values.append(float((model.score_fixed_path(x,recorded)*weights).sum().detach()))
        with torch.no_grad():parameter[index]=old
        fd=(values[0]-values[1])/(2*epsilon);ad=float(gradient_map[name][index])
        fd_rows.append({'name':name,'index':list(index),'autograd':ad,'finite_difference':fd,
                        'absolute_error':abs(fd-ad)})
    assert max(row['absolute_error'] for row in fd_rows)<2e-6
    # All jumps, including multiple events in one observation interval and
    # observation-remap firings, must be visible to the trace and total counts.
    event_counts=np.zeros((b,model.hidden_size),dtype=int)
    reconstructed_trace=np.zeros_like(event_counts,dtype=float)
    for event in output['spike_times']:
        row,component=event['batch'],event['component']
        event_counts[row,component]+=1
        reconstructed_trace[row,component]+=np.exp(-(output['state'].time[row]-event['time'])/model.trace_tau)
    np.testing.assert_array_equal(event_counts,output['state'].total_counts)
    trace_error=float(np.max(np.abs(reconstructed_trace-output['state'].trace)))
    assert trace_error<1e-12
    assert torch.equal(output['actual_counts'].sum(1),torch.from_numpy(event_counts))
    assert np.max(np.abs(recorded[0]['dwell_times']))==0
    assert torch.equal(output['actual_counts'][:,0],output['immediate_counts'][:,0])
    try:
        bad_dt=dt.clone();bad_dt[:,0]=.1
        model(x,bad_dt,mask,rng=np.random.default_rng(710303))
        raise AssertionError('Nonzero initial elapsed time accepted')
    except ValueError:pass
    for invalid_tau in (0.,float('inf')):
        try:
            CoupledSpikePolicy(trace_tau=invalid_tau)
            raise AssertionError('Invalid trace time constant accepted')
        except ValueError:pass
    for invalid_elapsed in (float('nan'),float('inf')):
        try:
            model.step(output['state'],x[:,0],np.full(b,invalid_elapsed),
                       np.random.default_rng(19),False)
            raise AssertionError('Nonfinite elapsed time accepted')
        except ValueError:pass
    try:
        chosen_log_probability(torch.tensor([[1.,0.]]),np.array([1]))
        raise AssertionError('Zero-probability recorded transition accepted')
    except ValueError:pass
    try:
        interval_log_likelihood(torch.zeros(1,1,2,2),np.array([[[[0,1],[0,0]]]]),
                                np.zeros((1,1,2)),check_support=True)
        raise AssertionError('Zero-rate recorded jump accepted')
    except ValueError:pass
    # Altering a future observation cannot change any earlier path segment.
    cutoff=length-2;changed=x.clone();changed[:,cutoff:,:]+=3.
    future=model(changed,dt,mask,rng=np.random.default_rng(710303),record_path=True)
    for k in range(cutoff):
        for field in ('initial_indices','indices_after_interval','indices_after_observation',
                      'jump_counts','dwell_times','trace_after_observation'):
            np.testing.assert_array_equal(recorded[k][field],future['path_records'][k][field])
    # A no-op advances the CTMC under held controls but cannot refresh R or W.
    rng=np.random.default_rng(710304);state=model.initial_state(b,rng)
    state,_=model.step(state,x[:,0],np.zeros(b),rng,True)
    previous=(state.context.clone(),state.drift.clone(),state.boundary.clone())
    state,no_op=model.step(state,torch.full_like(x[:,0],99.),np.full(b,.4),rng,False,
                          record_spikes=True,record_path=True)
    for before,after in zip(previous,(state.context,state.drift,state.boundary)):
        assert torch.equal(before,after)
    # The recurrent input is the actual stochastic trace, not a stored analog
    # context. Intervene on one trace component and inspect other neurons.
    alternative=state.trace.copy();alternative[:,0]+=2.
    original_controls=model.controls(x[:,1],state.trace,state.context)
    altered_controls=model.controls(x[:,1],alternative,state.context)
    cross_effect=float((original_controls['drift'][:,1:]-altered_controls['drift'][:,1:]).abs().max().detach())
    assert cross_effect>1e-5
    output=model(x,dt,mask,rng=np.random.default_rng(710305))
    loss=full_path_objective(output,data['valid'][:b,:length],data['optimal'][:b,:length],
                             data['decision'][:b,:length])
    loss.backward()
    norms={name:float(parameter.grad.norm()) for name,parameter in model.named_parameters()}
    assert all(np.isfinite(v) for v in norms.values())
    assert norms['recurrent_layer.weight']>0 and norms['input_layer.weight']>0
    assert float((output['latent'][:,-1]-torch.from_numpy(np.tanh(output['state'].trace))).abs().max())==0
    return {'parameters':model.metadata()['parameters_including_head'],
        'fixed_path_log_likelihood_recompute_max_error':score_error,
        'fixed_path_parameter_gradient_checks':fd_rows,
        'actual_event_count':int(event_counts.sum()),'count_and_complete_event_trace_match':True,
        'final_exponential_trace_reconstruction_max_error':trace_error,
        'nonzero_initial_dt_rejected':True,'initial_interval_has_zero_dwell_and_zero_elapsed_spikes':True,
        'nonfinite_elapsed_and_nonpositive_or_nonfinite_trace_tau_rejected':True,
        'fixed_path_scoring_rejects_changed_support':True,
        'future_observation_cannot_change_past_path':True,'no_op_holds_context_and_controls_bitwise':True,
        'actual_trace_intervention_cross_neuron_drift_max_change':cross_effect,
        'head_reads_only_actual_trace':True,'full_path_nll':float(loss.detach()),
        'all_gradients_finite':True,'gradient_norms':norms,
        'limits':['No-op interval partition has the same law but need not give the same RNG-coupled path.',
                  'Feedback refreshes at true observation boundaries, not at every asynchronous spike.',
                  'The training inputs and optimal action sets are external oracle-imitation sequences.']}


def training_step_benchmark(repeats=3):
    torch.manual_seed(710306);model=CoupledSpikePolicy();optimizer=torch.optim.Adam(model.parameters(),lr=.003)
    data=arrays('train');b=128;length=int(data['lengths'][:b].max())
    x=data['x'][:b,:length];dt=data['dt'][:b,:length];mask=data['event_mask'][:b,:length]
    rng=np.random.default_rng(710307);rows=[]
    for repeat in range(repeats):
        begin=time.perf_counter();cpu_begin=time.process_time();optimizer.zero_grad(set_to_none=True)
        output=model(x,dt,mask,rng=rng)
        loss=full_path_objective(output,data['valid'][:b,:length],data['optimal'][:b,:length],
                                 data['decision'][:b,:length]);loss.backward()
        norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
        assert all(p.grad is None or torch.isfinite(p.grad).all() for p in model.parameters())
        rows.append({'repeat':repeat,'wall_seconds':time.perf_counter()-begin,
            'cpu_seconds':time.process_time()-cpu_begin,'nll':float(loss.detach()),
            'gradient_norm_before_clip':float(norm),'actual_spike_count':int(output['actual_counts'].sum())})
    return {'batch_size':b,'observations':length,'repeats':repeats,'raw':rows,
            'median_wall_seconds':float(np.median([row['wall_seconds'] for row in rows])),
            'scope':'One real full-path sampled forward/backward/Adam step; CPU 1 thread; no holdout data.'}


def main():
    torch.set_num_threads(1)
    try:torch.set_num_interop_threads(1)
    except RuntimeError:pass
    begin=time.perf_counter()
    interval=interval_gradient_audit();print(json.dumps({'interval_gradient':interval}),flush=True)
    path=path_and_causality_audit();print(json.dumps({'path_and_causality':path}),flush=True)
    timing=training_step_benchmark();print(json.dumps({'training_step':timing}),flush=True)
    report={'schema':'rrsnn.coupled-path-audit.v1','passed':True,
        'single_interval_exact_gradient':interval,'path_and_causality':path,'training_step':timing,
        'wall_seconds':time.perf_counter()-begin,
        'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                         for name in ('model.py','validate.py')},
        'frozen_operator_sha256':hashlib.sha256((ROOT.parent/'density_model.py').read_bytes()).hexdigest()}
    destination=ROOT/'results';destination.mkdir(exist_ok=True)
    (destination/'validation.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
