"""Fixed-budget causal training; no holdout evaluation in this program."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import resource
import time
import numpy as np
import torch
from torch import nn
from .policy import Policy, expected_loss, sampled_state_objective, set_nll_per_decision

ROOT=Path(__file__).resolve().parent

def arrays(name):
    with np.load(ROOT/'data'/f'{name}.npz') as z:
        return {k:torch.from_numpy(z[k].copy()) for k in z.files}

@torch.no_grad()
def validation_loss(model,data,sampled=False,seed=777001):
    model.eval()
    gen=torch.Generator().manual_seed(seed)
    total=0.;decisions=0
    # The sampled objective is evaluated with four fixed independent draws.
    repetitions=4 if sampled else 1
    for _ in range(repetitions):
        for start in range(0,len(data['x']),128):
            ids=slice(start,start+128)
            length=int(data['lengths'][ids].max())
            out=model(data['x'][ids,:length],data['dt'][ids,:length],
                      event_mask=data['event_mask'][ids,:length],generator=gen,sampled=sampled)
            mask=data['decision'][ids,:length]
            losses=set_nll_per_decision(out['logits'],data['valid'][ids,:length],data['optimal'][ids,:length])
            total+=float(losses[mask].sum());decisions+=int(mask.sum())
    return total/max(decisions,1)

def source_hashes():
    paths=['train.py','policy.py','density_model.py','causal_baselines.py','spiking_baselines.py','prepare_data.py']
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths if (ROOT/p).exists()}

def train_one(variant,seed,epochs,output_group='results',sampled=False,learning_rate=.003,batch_size=128,
              cpu_budget_seconds=None,run_suffix=''):
    torch.set_num_threads(1)
    try: torch.set_num_interop_threads(1)
    except RuntimeError: pass
    torch.manual_seed(seed);np.random.seed(seed)
    training=arrays('train');validation=arrays('validation')
    model=Policy(variant)
    optimizer=torch.optim.Adam(model.parameters(),lr=learning_rate)
    initial=validation_loss(model,validation,sampled)
    best=initial;best_state=copy.deepcopy(model.state_dict());best_epoch=0
    permutation_generator=torch.Generator().manual_seed(seed+100000)
    state_generator=torch.Generator().manual_seed(seed+200000)
    history=[];gradient_norms=[];maximum_probability_correction=0.;begin=time.perf_counter();cpu_begin=time.process_time()
    run_name=variant+('_sampled' if sampled else '')+run_suffix
    destination=ROOT/output_group/run_name/f'seed_{seed}'
    destination.mkdir(parents=True,exist_ok=True)
    for epoch in range(1,epochs+1):
        model.train();order=torch.randperm(len(training['x']),generator=permutation_generator)
        weighted_loss=0.;decision_count=0
        for start in range(0,len(order),batch_size):
            ids=order[start:start+batch_size];length=int(training['lengths'][ids].max())
            optimizer.zero_grad(set_to_none=True)
            out=model(training['x'][ids,:length],training['dt'][ids,:length],
                event_mask=training['event_mask'][ids,:length],generator=state_generator,sampled=sampled)
            if sampled: maximum_probability_correction=max(maximum_probability_correction,float(out['maximum_probability_correction'].detach()))
            valid=training['valid'][ids,:length];optimal=training['optimal'][ids,:length]
            decision=training['decision'][ids,:length]
            loss=(sampled_state_objective(out,valid,optimal,decision) if sampled else
                  expected_loss(out['logits'],valid,optimal,decision))
            if not torch.isfinite(loss): raise FloatingPointError('Nonfinite training loss')
            loss.backward()
            for name,p in model.named_parameters():
                if p.grad is not None and not torch.isfinite(p.grad).all():
                    raise FloatingPointError(f'Nonfinite gradient {name}')
            norm=nn.utils.clip_grad_norm_(model.parameters(),1.)
            gradient_norms.append(float(norm));optimizer.step()
            count=int(decision.sum());weighted_loss+=float(loss.detach())*count;decision_count+=count
        row={'epoch':epoch,'train_nll':weighted_loss/decision_count}
        budget_reached=cpu_budget_seconds is not None and time.process_time()-cpu_begin>=cpu_budget_seconds
        if epoch%4==0 or epoch==epochs or budget_reached:
            vl=validation_loss(model,validation,sampled);row['validation_nll']=vl
            if vl<best:
                best=vl;best_epoch=epoch;best_state=copy.deepcopy(model.state_dict())
            print(json.dumps({'run':run_name,'seed':seed,**row,'elapsed':round(time.perf_counter()-begin,2)}),flush=True)
        history.append(row)
        (destination/'progress.json').write_text(json.dumps({'history':history,'best_validation_nll':best,'best_epoch':best_epoch},indent=2))
        if budget_reached: break
    elapsed=time.perf_counter()-begin
    cpu_elapsed=time.process_time()-cpu_begin
    plan={'epochs':len(history),'epochs_cap':epochs,'updates':len(gradient_norms),'batch_size':batch_size,'learning_rate':learning_rate,
          'optimizer':'Adam','gradient_clip_norm':1.,'validation_interval_epochs':4,
          'cpu_budget_seconds':cpu_budget_seconds,'cpu_budget_scope':'train forward/backward, validation, checkpoint selection and progress writes; initialization excluded',
          'checkpoint_selection':'minimum validation optimal-action-set NLL, including initialization',
          'sampled_validation_draws':4 if sampled else 0,'data_manifest_sha256':hashlib.sha256((ROOT/'data/manifest.json').read_bytes()).hexdigest()}
    torch.save({'state_dict':best_state,'variant':variant,'run_name':run_name,'sampled_training':sampled,
                'seed':seed,'plan':plan,'metadata':model.metadata()},destination/'model.pt')
    result={'variant':variant,'run_name':run_name,'seed':seed,'sampled_training':sampled,'plan':plan,
            'metadata':model.metadata(),'initial_validation_nll':initial,'best_validation_nll':best,
            'best_epoch':best_epoch,'history':history,'train_seconds':elapsed,'train_cpu_seconds':cpu_elapsed,
            'gradients_all_finite':True,'gradient_norm_max_before_clip':max(gradient_norms),
            'maximum_sample_probability_correction':maximum_probability_correction,
            'process_peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
            'checkpoint_sha256':hashlib.sha256((destination/'model.pt').read_bytes()).hexdigest(),
            'source_hashes':source_hashes(),'holdout_opened_by_training':False,
            'training_objective':('sampled CTMC observation-state sequence expected NLL, likelihood-ratio plus direct gradient'
                                  if sampled else 'deterministic encoder optimal-action-set NLL')}
    (destination/'training.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'completed':run_name,'seed':seed,'seconds':round(elapsed,2),'best_validation_nll':best}),flush=True)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--variant',required=True);parser.add_argument('--seed',type=int,required=True)
    parser.add_argument('--epochs',type=int,default=32);parser.add_argument('--group',default='results')
    parser.add_argument('--sampled',action='store_true');parser.add_argument('--lr',type=float,default=.003)
    parser.add_argument('--cpu-budget',type=float);parser.add_argument('--suffix',default='')
    args=parser.parse_args()
    train_one(args.variant,args.seed,args.epochs,args.group,args.sampled,args.lr,
              cpu_budget_seconds=args.cpu_budget,run_suffix=args.suffix)
