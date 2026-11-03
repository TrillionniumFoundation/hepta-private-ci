"""Supplementary real-spike-feedback training; train/validation data only.

This program is separate from the frozen 70-run endpoint/expected matrix.
Every update samples complete Gillespie paths and scores their jump densities.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import resource
import time
import itertools
import numpy as np
import torch

from ..train import arrays
from ..policy import set_nll_per_decision
from .model import CoupledSpikePolicy,full_path_objective

ROOT=Path(__file__).resolve().parent
SEEDS=(101,211,307,401,503)


def hashes():
    paths=[ROOT/'model.py',ROOT/'train.py',ROOT.parent/'density_model.py',
           ROOT.parent/'policy.py',ROOT.parent/'data'/'manifest.json',
           ROOT.parent/'data'/'train.npz',ROOT.parent/'data'/'validation.npz']
    return {str(path.relative_to(ROOT.parent)):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def ensure_plan():
    path=ROOT/'experiment_plan.json'
    cpu_budgets={};reference_receipts={}
    for seed in SEEDS:
        receipt=ROOT.parent/'results'/'rr_density_sampled'/f'seed_{seed}'/'training.json'
        reference=json.loads(receipt.read_text())
        cpu_budgets[str(seed)]=reference['train_cpu_seconds']
        reference_receipts[str(seed)]={'path':str(receipt.relative_to(ROOT.parent)),
            'sha256':hashlib.sha256(receipt.read_bytes()).hexdigest(),
            'checkpoint_sha256':reference['checkpoint_sha256']}
    plan={'schema':'rrsnn.coupled-supplementary-plan.v1',
        'declared_at_utc':datetime.now(timezone.utc).isoformat(),
        'status':'predeclared supplemental mechanism experiment, outside the frozen primary 70-run matrix',
        'seeds':list(SEEDS),'fixed_updates_epochs':32,'fixed_updates_per_seed':256,'batch_size':128,
        'milestones':['fixed_updates','equal_cpu'],
        'equal_cpu_seconds_per_seed':cpu_budgets,'cpu_budget_reference_receipts':reference_receipts,
        'same_trajectory':'Save independent best-validation checkpoint at epoch32, then continue the same model/optimizer/RNG trajectory to the total CPU budget, not an additional budget.',
        'cpu_budget_scope':'Training, periodic validation, selection, progress/trajectory writes, including the first32epochs; initialization and initial validation excluded, matching the main receipt timer.',
        'budget_stopping':'After an epoch, with final validation; report actual CPU and any epoch/validation overshoot.',
        'optimizer':'Adam','learning_rate':.003,'gradient_clip_norm':1.,
        'validation_every_epochs':4,'validation_path_draws':4,'validation_rng_seed':777001,
        'checkpoint_selection':'Minimum validation optimal-action-set NLL including initialization',
        'fresh_splits_reused':['train','validation'],'holdout_opened_by_this_program':False,
        'architecture':'H8/input22/head81/977 parameters; actual exponential-spike trace feedback and readout',
        'training_gradient':'Direct NLL plus full real-jump path likelihood ratio; independent leave-one-sequence-out baseline',
        'likelihood':'initial law + sum_ij Nij log qij - sum_i Ti exit_i + observed-remap law',
        'feedback_timing':'refresh at true observation boundaries only; held Q between observations',
        'sampling':'All real transition times, states and counts sampled, including repeated spikes/reset/refractory',
        'scope_limits':['Finite spatial CTMC, reflecting floor, Erlang refractory and P1 remapping remain.',
                        'Oracle-imitation training on external causal observation sequences.',
                        'This supplement cannot change primary hypotheses, baseline selection or training budget.',
                        'Validation improvement is not closed-loop holdout superiority.'],
        'source_and_data_sha256':hashes()}
    if path.exists():
        existing=json.loads(path.read_text())
        if existing['source_and_data_sha256']!=plan['source_and_data_sha256']:
            raise RuntimeError('Supplementary source/data changed after plan declaration')
        return existing
    path.write_text(json.dumps(plan,indent=2)+'\n')
    return plan


@torch.no_grad()
def validation_loss(model,data,seed=777001):
    model.eval();rng=np.random.default_rng(seed);total=0.;decisions=0;spikes=0
    for _ in range(4):
        for start in range(0,len(data['x']),128):
            ids=slice(start,start+128);length=int(data['lengths'][ids].max())
            out=model(data['x'][ids,:length],data['dt'][ids,:length],
                      data['event_mask'][ids,:length],rng=rng)
            mask=data['decision'][ids,:length]
            losses=set_nll_per_decision(out['logits'],data['valid'][ids,:length],data['optimal'][ids,:length])
            total+=float(losses[mask].sum());decisions+=int(mask.sum())
            spikes+=int(out['actual_counts'].sum())
    return total/max(decisions,1),spikes


def train_one(seed,plan):
    torch.manual_seed(seed);np.random.seed(seed)
    data=arrays('train');validation=arrays('validation')
    model=CoupledSpikePolicy();optimizer=torch.optim.Adam(model.parameters(),lr=.003)
    permutation_generator=torch.Generator().manual_seed(seed+100000)
    rng=np.random.default_rng(seed+200000)
    initial,initial_spikes=validation_loss(model,validation)
    best=initial;best_state=copy.deepcopy(model.state_dict());best_epoch=0
    history=[];gradient_norms=[];named_norm_max={name:0. for name,_ in model.named_parameters()}
    train_spikes=0;begin=time.perf_counter();cpu_begin=time.process_time()
    budget=plan['equal_cpu_seconds_per_seed'][str(seed)]
    destination=ROOT/'results'/f'trajectory_seed_{seed}';destination.mkdir(parents=True,exist_ok=True)

    def save_milestone(kind):
        elapsed=time.perf_counter()-begin;cpu_elapsed=time.process_time()-cpu_begin
        target=ROOT/'results'/kind/f'seed_{seed}';target.mkdir(parents=True,exist_ok=True)
        saved={'state_dict':best_state,'variant':'rr_coupled_full_path','run_name':'rr_coupled_full_path_'+kind,
               'seed':seed,'milestone':kind,'metadata':model.metadata(),'plan':plan,
               'training_mode':'full-real-jump-path-score'}
        torch.save(saved,target/'model.pt')
        result={'schema':'rrsnn.coupled-training.v1','variant':'rr_coupled_full_path',
            'run_name':'rr_coupled_full_path_'+kind,'seed':seed,'milestone':kind,
            'plan':plan,'metadata':model.metadata(),'initial_validation_nll':initial,
            'initial_validation_actual_spikes':initial_spikes,'best_validation_nll':best,
            'best_epoch':best_epoch,'history':history,'epochs':len(history),'updates':len(gradient_norms),
            'train_seconds':elapsed,'train_cpu_seconds':cpu_elapsed,
            'equal_cpu_target_seconds':budget,'cpu_budget_overshoot_seconds':max(0.,cpu_elapsed-budget),
            'gradients_all_finite':True,'gradient_norm_max_before_clip':max(gradient_norms),
            'gradient_norm_mean_before_clip':float(np.mean(gradient_norms)),
            'per_parameter_gradient_norm_max_before_clip':named_norm_max,
            'actual_training_spikes':train_spikes,
            'process_peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
            'rss_scope':'Linux process high-water mark, including PyTorch/data/workspace; not per-component state',
            'checkpoint_sha256':hashlib.sha256((target/'model.pt').read_bytes()).hexdigest(),
            'source_and_data_sha256':hashes(),'holdout_opened_by_training':False,
            'training_objective':'Expected optimal-action-set NLL of actual real-spike-feedback trajectories; full jump-path likelihood-ratio plus direct gradient',
            'not_endpoint_likelihood':True}
        (target/'training.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'completed_milestone':kind,'seed':seed,'epochs':len(history),
            'updates':len(gradient_norms),'cpu_seconds':round(cpu_elapsed,3),
            'seconds':round(elapsed,2),'initial_validation_nll':initial,
            'best_validation_nll':best,'actual_training_spikes':train_spikes}),flush=True)
        return result

    def save_trajectory():
        torch.save({'model':model.state_dict(),'optimizer':optimizer.state_dict(),
            'numpy_rng':rng.bit_generator.state,'permutation_rng':permutation_generator.get_state(),
            'best_state':best_state,'best_epoch':best_epoch,'best_validation_nll':best,
            'history':history,'gradient_norms':gradient_norms,'named_norm_max':named_norm_max,
            'actual_training_spikes':train_spikes,'cpu_seconds_spent':time.process_time()-cpu_begin,
            'wall_seconds_spent':time.perf_counter()-begin,'seed':seed,'plan':plan},
            destination/'trajectory.pt')

    for epoch in itertools.count(1):
        model.train();order=torch.randperm(len(data['x']),generator=permutation_generator)
        weighted_loss=0.;decision_count=0;epoch_spikes=0;score_sd=[]
        for start in range(0,len(order),128):
            ids=order[start:start+128];length=int(data['lengths'][ids].max())
            optimizer.zero_grad(set_to_none=True)
            out=model(data['x'][ids,:length],data['dt'][ids,:length],
                      data['event_mask'][ids,:length],rng=rng)
            mask=data['decision'][ids,:length]
            loss=full_path_objective(out,data['valid'][ids,:length],data['optimal'][ids,:length],mask)
            if not torch.isfinite(loss):raise FloatingPointError('Nonfinite full-path training loss')
            loss.backward()
            for name,parameter in model.named_parameters():
                if parameter.grad is None:raise AssertionError(f'Unused parameter {name}')
                if not torch.isfinite(parameter.grad).all():raise FloatingPointError(f'Nonfinite gradient {name}')
                named_norm_max[name]=max(named_norm_max[name],float(parameter.grad.norm()))
            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
            gradient_norms.append(float(norm));optimizer.step()
            count=int(mask.sum());weighted_loss+=float(loss.detach())*count;decision_count+=count
            epoch_spikes+=int(out['actual_counts'].sum())
            score_sd.append(float(out['full_path_log_probability'].sum(-1).detach().std()))
        train_spikes+=epoch_spikes
        row={'epoch':epoch,'train_nll':weighted_loss/decision_count,
             'actual_training_spikes':epoch_spikes,'mean_minibatch_path_logdensity_sd':float(np.mean(score_sd))}
        budget_reached=time.process_time()-cpu_begin>=budget
        if epoch%4==0 or epoch==32 or budget_reached:
            value,validation_spikes=validation_loss(model,validation)
            row.update(validation_nll=value,actual_validation_spikes=validation_spikes)
            if value<best:best=value;best_epoch=epoch;best_state=copy.deepcopy(model.state_dict())
            print(json.dumps({'seed':seed,**row,'elapsed':round(time.perf_counter()-begin,2)}),flush=True)
        history.append(row)
        (destination/'progress.json').write_text(json.dumps({'history':history,'best_validation_nll':best,
            'best_epoch':best_epoch,'updates':len(gradient_norms),
            'cpu_seconds':time.process_time()-cpu_begin,'target_cpu_seconds':budget},indent=2)+'\n')
        if epoch==32:
            assert len(gradient_norms)==256
            save_milestone('fixed_updates')
        if epoch%4==0:save_trajectory()
        if time.process_time()-cpu_begin>=budget:
            if epoch<32:raise RuntimeError('Equal-CPU budget exhausted before the mandatory fixed32epoch milestone')
            if 'validation_nll' not in row:
                value,validation_spikes=validation_loss(model,validation)
                row.update(validation_nll=value,actual_validation_spikes=validation_spikes)
                if value<best:best=value;best_epoch=epoch;best_state=copy.deepcopy(model.state_dict())
            save_trajectory()
            return save_milestone('equal_cpu')


def summarize():
    report={'schema':'rrsnn.coupled-training-summary.v2','milestones':{},'holdout_opened':False,
        'interpretation':'Training feasibility and validation selection only; no task superiority or main-matrix claim.'}
    for kind in ('fixed_updates','equal_cpu'):
        rows=[]
        for seed in SEEDS:
            path=ROOT/'results'/kind/f'seed_{seed}'/'training.json'
            if path.exists():rows.append(json.loads(path.read_text()))
        def summary(key):
            values=np.array([row[key] for row in rows],dtype=float)
            return {'n':len(values),'raw':values.tolist(),'mean':float(values.mean()) if len(values) else None,
                    'sd':float(values.std(ddof=1)) if len(values)>1 else None}
        report['milestones'][kind]={'complete':len(rows)==len(SEEDS),'seeds':[row['seed'] for row in rows],
            **{key:summary(key) for key in ('initial_validation_nll','best_validation_nll',
                'train_seconds','train_cpu_seconds','actual_training_spikes','epochs','updates',
                'cpu_budget_overshoot_seconds')},
            'all_gradients_finite':all(row['gradients_all_finite'] for row in rows)}
    report['complete']=all(m['complete'] for m in report['milestones'].values())
    (ROOT/'results'/'training_summary.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--seed',type=int,choices=SEEDS)
    parser.add_argument('--all',action='store_true');parser.add_argument('--declare-only',action='store_true')
    args=parser.parse_args();torch.set_num_threads(1)
    try:torch.set_num_interop_threads(1)
    except RuntimeError:pass
    plan=ensure_plan()
    if not args.declare_only:
        seeds=SEEDS if args.all else ((args.seed,) if args.seed is not None else ())
        if not seeds:parser.error('Choose --seed, --all or --declare-only')
        for seed in seeds:
            if (ROOT/'results'/'equal_cpu'/f'seed_{seed}'/'training.json').exists():
                print(json.dumps({'skip_completed_seed':seed}),flush=True);continue
            train_one(seed,plan)
        print(json.dumps(summarize()),flush=True)
