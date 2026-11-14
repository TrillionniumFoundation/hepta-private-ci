"""Synthetic scalar first-passage MLE with correct right-censoring.

This trains only drift and diffusion scale, with the distance scale observed
and fixed. It is not training/calibrating the complete RR-SNN or its resource
policy. Test labels never select checkpoints. Data come from independently
sampled inverse-Gaussian hitting times, including their observed censoring.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import time

import numpy as np
import torch


SEEDS=[101,211,307,401,503]
TRUE_MU=-.7
TRUE_SIGMA=.8
INITIAL_MU=-.15
INITIAL_SIGMA=1.3
SIGMA_FLOOR=1e-4


def make_data(size,seed):
    rng=np.random.default_rng(seed)
    x=rng.uniform(.25,2.,size)
    horizon=rng.uniform(.25,1.5,size)
    latent_hit=rng.wald(x/(-TRUE_MU),x*x/(TRUE_SIGMA**2))
    hit=latent_hit<=horizon
    observed_time=np.minimum(latent_hit,horizon)
    # Latent uncensored times are intentionally not exposed to fitting.
    return {'x':x,'horizon':horizon,'observed_time':observed_time,'hit':hit}


def tensors(data):
    return {key:torch.as_tensor(value,dtype=torch.bool if key=='hit' else torch.float64)
            for key,value in data.items()}


def log_survival(x,t,mu,sigma):
    scale=sigma*torch.sqrt(t)
    a=torch.special.log_ndtr((x+mu*t)/scale)
    b=-2*mu*x/(sigma*sigma)+torch.special.log_ndtr((-x+mu*t)/scale)
    difference=b-a
    if torch.any(difference>=0):
        raise FloatingPointError('Unresolved survival tail subtraction; refusing silent clipping')
    return a+torch.log(-torch.expm1(difference))


def censored_nll(data,mu,sigma):
    x,t=data['x'],data['observed_time']
    log_density=(torch.log(x)-torch.log(sigma)-.5*math.log(2*math.pi)
                 -1.5*torch.log(t)-(x+mu*t)**2/(2*sigma*sigma*t))
    log_s=log_survival(x,data['horizon'],mu,sigma)
    return -torch.where(data['hit'],log_density,log_s).mean()


def sigma_from(raw_sigma):
    return torch.nn.functional.softplus(raw_sigma)+SIGMA_FLOOR


def raw_from(sigma):
    return math.log(math.expm1(sigma-SIGMA_FLOOR))


def gradient_check(data,mu_value,sigma_value):
    mu=torch.tensor(mu_value,dtype=torch.float64,requires_grad=True)
    raw=torch.tensor(raw_from(sigma_value),dtype=torch.float64,requires_grad=True)
    value=censored_nll(data,mu,sigma_from(raw))
    gradients=torch.autograd.grad(value,(mu,raw))
    results=[]
    step=1e-6
    for index,name in enumerate(['mu','raw_sigma']):
        theta=np.array([mu_value,raw_from(sigma_value)])
        def loss_at(values):
            with torch.no_grad():
                return float(censored_nll(data,torch.tensor(values[0],dtype=torch.float64),
                                         sigma_from(torch.tensor(values[1],dtype=torch.float64))))
        plus=theta.copy();plus[index]+=step
        minus=theta.copy();minus[index]-=step
        finite_difference=(loss_at(plus)-loss_at(minus))/(2*step)
        analytic=float(gradients[index])
        error=abs(analytic-finite_difference)
        if not math.isfinite(analytic) or error>1e-6*(1+abs(finite_difference)):
            raise AssertionError(f'Gradient mismatch for {name}: {analytic} vs {finite_difference}')
        results.append({'parameter':name,'autodiff':analytic,
                        'central_difference':finite_difference,'absolute_error':error})
    return results


def reliability(probabilities,labels,bins=10):
    bucket=np.minimum((probabilities*bins).astype(int),bins-1)
    rows=[];ece=0.
    for b in range(bins):
        chosen=bucket==b
        count=int(chosen.sum())
        if count:
            pred=float(probabilities[chosen].mean())
            frequency=float(labels[chosen].mean())
            ece+=count/len(labels)*abs(pred-frequency)
            # Wilson interval measures observed bin-frequency uncertainty;
            # adaptive model fit uncertainty is not included.
            z=1.96;den=1+z*z/count
            center=(frequency+z*z/(2*count))/den
            radius=z*math.sqrt(frequency*(1-frequency)/count+z*z/(4*count*count))/den
            lo,hi=center-radius,center+radius
        else:
            pred=frequency=lo=hi=None
        rows.append({'bin':b,'left':b/bins,'right':(b+1)/bins,'count':count,
                     'mean_predicted_probability':pred,'observed_frequency':frequency,
                     'observed_frequency_wilson_95':[lo,hi]})
    return ece,rows


def evaluate(data,mu,sigma):
    ts=tensors(data)
    with torch.no_grad():
        drift=torch.tensor(mu,dtype=torch.float64)
        diffusion=torch.tensor(sigma,dtype=torch.float64)
        nll=float(censored_nll(ts,drift,diffusion))
        probability=(-torch.expm1(log_survival(ts['x'],ts['horizon'],drift,diffusion))).numpy()
    if not (np.isfinite(probability).all() and ((probability>=0)&(probability<=1)).all()):
        raise AssertionError('Invalid probability')
    labels=data['hit'].astype(float)
    ece,table=reliability(probability,labels)
    return {'mu':mu,'sigma':sigma,'censored_nll':nll,
            'brier':float(np.mean((probability-labels)**2)),'ece_10_equal_width':ece,
            'observed_event_fraction':float(labels.mean()),
            'mean_predicted_event_fraction':float(probability.mean()),
            'reliability':table},probability


def fit_one(seed,train_size,val_size,test_size,steps,output):
    data={split:make_data(size,seed*1000+offset) for split,size,offset in
          [('train',train_size,1),('validation',val_size,2),('test',test_size,3)]}
    for split,values in data.items():
        np.savez_compressed(output/f'censored_{seed}_{split}.npz',**values)
    train,val=tensors(data['train']),tensors(data['validation'])
    mu=torch.tensor(INITIAL_MU,dtype=torch.float64,requires_grad=True)
    raw_sigma=torch.tensor(raw_from(INITIAL_SIGMA),dtype=torch.float64,requires_grad=True)
    optimizer=torch.optim.Adam([mu,raw_sigma],lr=.04)
    checks_initial=gradient_check(train,INITIAL_MU,INITIAL_SIGMA)
    with torch.no_grad():
        best_val=float(censored_nll(val,mu,sigma_from(raw_sigma)))
    best={'step':0,'mu':INITIAL_MU,'sigma':INITIAL_SIGMA,'validation_nll':best_val}
    trace=[];norms=[]
    started=time.perf_counter()
    for step in range(1,steps+1):
        optimizer.zero_grad(set_to_none=True)
        loss=censored_nll(train,mu,sigma_from(raw_sigma))
        if not torch.isfinite(loss):
            raise FloatingPointError('Nonfinite training objective')
        loss.backward()
        gradient=torch.stack([mu.grad,raw_sigma.grad])
        if not torch.isfinite(gradient).all():
            raise FloatingPointError('Nonfinite MLE gradient')
        norms.append(float(torch.linalg.vector_norm(gradient)))
        optimizer.step()
        if step%10==0 or step==steps:
            with torch.no_grad():
                validation=float(censored_nll(val,mu,sigma_from(raw_sigma)))
                snapshot={'step':step,'mu':float(mu),'sigma':float(sigma_from(raw_sigma)),
                          'train_nll':float(censored_nll(train,mu,sigma_from(raw_sigma))),
                          'validation_nll':validation}
            trace.append(snapshot)
            if validation<best_val:
                best_val=validation
                best={key:snapshot[key] for key in ['step','mu','sigma','validation_nll']}
    elapsed=time.perf_counter()-started
    checks_selected=gradient_check(train,best['mu'],best['sigma'])
    metrics={};probabilities={}
    for name,drift,diffusion in [('untrained',INITIAL_MU,INITIAL_SIGMA),
           ('trained',best['mu'],best['sigma']),('true_parameters',TRUE_MU,TRUE_SIGMA)]:
        metrics[name],probabilities[name]=evaluate(data['test'],drift,diffusion)
    hashes={split:hashlib.sha256((output/f'censored_{seed}_{split}.npz').read_bytes()).hexdigest()
            for split in data}
    result={'seed':seed,'data_sizes':{split:len(values['x']) for split,values in data.items()},
        'data_sha256':hashes,'selected_checkpoint':best,'test':metrics,'optimization_trace':trace,
        'gradient_checks':{'initial':checks_initial,'selected':checks_selected},
        'all_optimization_gradients_finite':True,'gradient_steps_checked':steps,
        'gradient_norm_min':min(norms),'gradient_norm_max':max(norms),
        'fit_wall_seconds':elapsed,
        'parameter_error':{'mu':best['mu']-TRUE_MU,'sigma':best['sigma']-TRUE_SIGMA}}
    print(json.dumps({'seed':seed,'mu':best['mu'],'sigma':best['sigma'],
                     'selected_step':best['step'],'fit_seconds':elapsed,
                     'trained_test_nll':metrics['trained']['censored_nll'],
                     'trained_test_brier':metrics['trained']['brier'],
                     'trained_test_ece':metrics['trained']['ece_10_equal_width']}),flush=True)
    return result,probabilities,data['test']['hit']


def run(output,steps=400):
    output.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    began=time.perf_counter()
    rows=[];pooled={name:[] for name in ['untrained','trained','true_parameters']};labels=[]
    for seed in SEEDS:
        row,probabilities,truth=fit_one(seed,4096,2048,4096,steps,output)
        rows.append(row);labels.append(truth)
        for name in pooled:
            pooled[name].append(probabilities[name])
    y=np.concatenate(labels).astype(float)
    pooled_metrics={}
    for name,parts in pooled.items():
        probability=np.concatenate(parts)
        ece,table=reliability(probability,y)
        pooled_metrics[name]={'n':len(y),'censored_nll':float(np.mean([r['test'][name]['censored_nll'] for r in rows])),
            'brier':float(np.mean((probability-y)**2)),'ece_10_equal_width':ece,
            'reliability':table,
            'nll_std_across_seeds':float(np.std([r['test'][name]['censored_nll'] for r in rows],ddof=1)),
            'brier_std_across_seeds':float(np.std([r['test'][name]['brier'] for r in rows],ddof=1)),
            'ece_mean_across_seeds':float(np.mean([r['test'][name]['ece_10_equal_width'] for r in rows])),
            'ece_std_across_seeds':float(np.std([r['test'][name]['ece_10_equal_width'] for r in rows],ddof=1))}
    mu_values=[r['selected_checkpoint']['mu'] for r in rows]
    sigma_values=[r['selected_checkpoint']['sigma'] for r in rows]
    result={'schema':'rrsnn.scalar-censored-mle.v1',
        'scope':'Synthetic scalar distribution calibration only; not complete-network or Hepta calibration.',
        'data_generation':{'true_mu':TRUE_MU,'true_sigma':TRUE_SIGMA,
            'x_uniform':[.25,2.],'horizon_uniform':[.25,1.5],
            'hitting_time':'Inverse Gaussian mean=x/0.7, shape=x^2/0.8^2',
            'observed_time':'min(latent hitting time, horizon)',
            'latent_hitting_times_hidden_from_fitter':True,
            'split_rng_seeds':'base_seed*1000 + {train:1, validation:2, test:3}'},
        'protocol':{'seeds':SEEDS,'train_size_per_seed':4096,'validation_size_per_seed':2048,
            'test_size_per_seed':4096,'learned_parameters':['mu','sigma'],
            'distance_scale':'x observed and fixed','initial_mu':INITIAL_MU,'initial_sigma':INITIAL_SIGMA,
            'sigma_parameterization':'softplus(raw_sigma)+1e-4','optimizer':'Adam',
            'learning_rate':.04,'full_batch_steps':steps,'dtype':'float64','cpu_threads':1,
            'selection':'minimum validation censored NLL, evaluated every 10 steps; test never selects'},
        'parameter_recovery':{'mu_mean':float(np.mean(mu_values)),'mu_std':float(np.std(mu_values,ddof=1)),
            'sigma_mean':float(np.mean(sigma_values)),'sigma_std':float(np.std(sigma_values,ddof=1))},
        'seeds':rows,'pooled_test':pooled_metrics,
        'all_gradients_finite':all(r['all_optimization_gradients_finite'] for r in rows),
        'max_gradient_check_absolute_error':max(x['absolute_error'] for r in rows
            for checks in r['gradient_checks'].values() for x in checks),
        'environment':{'python':platform.python_version(),'numpy':np.__version__,
            'torch':torch.__version__,'intraop_threads':torch.get_num_threads(),
            'interop_threads':torch.get_num_interop_threads()},
        'wall_seconds_total':time.perf_counter()-began,
        'timing_scope':'Data writes, fitting, selection and metric evaluation; figure rendering excluded.',
        'limitations':['Ground truth is inside the fitted scalar model family; this does not test model misspecification.',
            'No resource state, maturity policy, hard-spike network gradient, recurrent coupling, or biological data.',
            'True-parameter scores are distributional references; a finite-sample MLE may occasionally score better by chance.',
            'ECE uses ten equal-width bins and depends on that binning; Wilson intervals only address observed bin frequencies.',
            'Five seeds quantify limited data/fit variation, not a production reliability guarantee.']}
    (output/'censored_training_results.json').write_text(json.dumps(result,indent=2)+'\n')
    os.environ.setdefault('MPLCONFIGDIR',str(output/'.matplotlib-cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4.3),layout='constrained')
    colors={'untrained':'#b45309','trained':'#155e75','true_parameters':'#7c3aed'}
    for name,summary in pooled_metrics.items():
        nonempty=[x for x in summary['reliability'] if x['count']]
        axes[0].plot([x['mean_predicted_probability'] for x in nonempty],
                     [x['observed_frequency'] for x in nonempty],marker='o',ms=4,
                     label=name.replace('_',' '),color=colors[name])
    axes[0].plot([0,1],[0,1],'k--',lw=1)
    axes[0].set(xlabel='Predicted hit probability',ylabel='Observed hit frequency',
                title='Held-out right-censored calibration',xlim=(0,1),ylim=(0,1))
    axes[0].legend(fontsize=9)
    ids=np.arange(len(SEEDS))
    axes[1].scatter(ids,mu_values,label='learned mu',color='#155e75')
    axes[1].scatter(ids,sigma_values,label='learned sigma',color='#7c3aed')
    axes[1].axhline(TRUE_MU,color='#155e75',ls='--',alpha=.6)
    axes[1].axhline(TRUE_SIGMA,color='#7c3aed',ls='--',alpha=.6)
    axes[1].set(xticks=ids,xticklabels=SEEDS,xlabel='Independent data seed',
                ylabel='Parameter value',title='Two-parameter recovery (fixed distance scale)')
    axes[1].legend(fontsize=9)
    fig.savefig(output/'censored_reliability.png',dpi=170)
    plt.close(fig)
    print(json.dumps({'saved':str(output/'censored_training_results.json'),
        'parameter_recovery':result['parameter_recovery'],
        'pooled_test':{name:{key:value for key,value in metrics.items() if key!='reliability'}
                        for name,metrics in pooled_metrics.items()},
        'all_gradients_finite':result['all_gradients_finite'],
        'max_gradient_error':result['max_gradient_check_absolute_error'],
        'wall_seconds_total':result['wall_seconds_total']},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'results'/'censored')
    parser.add_argument('--steps',type=int,default=400)
    args=parser.parse_args()
    run(args.output,args.steps)
