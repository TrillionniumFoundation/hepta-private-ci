"""Supplementary closed-loop adapter; reuses the frozen task evaluator.

No holdout is read until all10 supplementary milestones and the main70-run
validation-only selection lock exist. Only the adapter uses the evaluator's
legacy 'density' dispatch; the returned physical mode is explicitly replaced.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import numpy as np
import torch
from torch import nn

from ..evaluate import evaluate as frozen_evaluate,load_scenarios,load_oracles
from ..aggregate_results import (PairedBootstrap,compare,describe,load_evaluations,
    paired_indices,retention,stats,CONTRACT,BOOTSTRAP_DRAWS,BOOTSTRAP_SEED)
from .model import CoupledSpikePolicy
from .train import SEEDS

ROOT=Path(__file__).resolve().parent
MAIN=ROOT.parent
MILESTONES=('fixed_updates','equal_cpu')
COMPARATORS={'fixed_updates':'ctrnn_matched','equal_cpu':'ctrnn_matched_cpu'}
MODE='coupled_real_ctmc_path'
FREE_CPUS=[];CPU_LOCK=threading.Lock()


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path=Path(path)
    if path.suffix=='.gz':
        with gzip.open(path,'rt',encoding='utf-8') as handle:return json.load(handle)
    return json.loads(path.read_text())


def write_gzip(path,payload):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    with gzip.open(temporary,'wt',encoding='utf-8') as handle:json.dump(payload,handle)
    temporary.replace(path)


class CoupledEvaluationAdapter(nn.Module):
    """Only dispatch compatibility; actual transitions use CoupledSpikePolicy."""
    is_density=False
    def __init__(self,policy,seed,record_spikes=False,record_observations=False):
        super().__init__();self.policy=policy;self.seed=int(seed)
        self.record_spikes=bool(record_spikes);self.record_observations=bool(record_observations)
        self.spike_times=[];self.observations=[];self.outputs=[];self.final_state=None

    @property
    def head(self):return self.policy.head

    def initial_state(self,batch_size):
        self.rng=np.random.default_rng(self.seed)
        self.spike_times=[];self.observations=[];self.outputs=[]
        self.final_state=self.policy.initial_state(batch_size,self.rng)
        return self.final_state

    def step(self,state,observation,dt,event_mask,generator=None,sampled=False):
        if sampled:raise ValueError('This adapter always samples full real jump paths')
        state,out=self.policy.step(state,observation,dt,self.rng,event_mask,
                                  record_spikes=self.record_spikes)
        self.spike_times.extend(out['spike_times']);self.final_state=state
        if self.record_observations:
            self.observations.append({'x':observation.clone(),'dt':dt.clone(),'event_mask':event_mask.clone()})
            self.outputs.append(out['logits'].detach().clone())
        return state,out

    def state_storage(self):
        state=self.final_state;arrays={}
        for name,value in vars(state).items():
            if isinstance(value,np.ndarray):arrays[name]=value.nbytes
            elif torch.is_tensor(value):arrays[name]=value.numel()*value.element_size()
        n=len(state.indices)
        return {'resident_numeric_arrays_bytes':arrays,'total_numeric_bytes':sum(arrays.values()),
            'sequences':n,'numeric_bytes_per_sequence':sum(arrays.values())/n,
            'excluded':'Python containers, RNG object, learned parameters, shared grid buffer, temporary Q/remap/path statistics and framework/RSS overhead',
            'inference_only':'No autograd graph is retained under the frozen evaluator no_grad context.'}


@torch.no_grad()
def evaluate_coupled(model,scenarios,oracles=None,seed=900001,keep_trace=False,
                     return_adapter=False,record_observations=False):
    adapter=CoupledEvaluationAdapter(model,seed,keep_trace,record_observations)
    result=frozen_evaluate(adapter,scenarios,oracles,mode='density',seed=seed,keep_trace=keep_trace)
    result.update(mode=MODE,internal_count_semantics='real spikes',
        physical_model=model.metadata()['physical_model'],
        feedback=model.metadata()['feedback'],head_input=model.metadata()['head_input'],
        state_storage=adapter.state_storage(),
        evaluator_dispatch_note='The frozen legacy density dispatch invokes the adapter.step method; all internal jumps and spikes here are sampled real CTMC events.')
    if keep_trace:
        result['real_spike_times']=adapter.spike_times
        actual=np.bincount([event['batch'] for event in adapter.spike_times],minlength=len(scenarios))
        if not np.array_equal(actual,np.asarray(result['episode_internal_count'],dtype=np.int64)):
            raise AssertionError('Complete recorded spike stream does not match per-episode counts')
    return (result,adapter) if return_adapter else result


def declare_analysis():
    path=ROOT/'analysis_protocol.json'
    protocol={'schema':'rrsnn.coupled-analysis-protocol.v1',
        'declared_at_utc':datetime.now(timezone.utc).isoformat(),
        'declared_without_opening_holdout_metrics':True,
        'milestones':list(MILESTONES),'comparators':COMPARATORS,'seeds':list(SEEDS),
        'comparison_status':'Predeclared supplementary contrasts; frozen primary70-run hypotheses remain unchanged.',
        'evaluation_gate':'All10 supplementary receipts/checkpoints exist, and main selection.json has locked all70 runs using validation only.',
        'datasets':{'test':512,'shift':512,'paired':{'value_groups':128,'conditions':['A0','A2','B0','B2'],'episodes':512}},
        'modes':{milestone:MODE for milestone in MILESTONES},
        'replay_counts':{'test':1,'shift':1,'paired':4},
        'random_seed_rules':{'test_shift':'900000+training_seed','paired':'940000+training_seed+10007*repeat'},
        'pairing_scope':'Four conditions share task values and initial-state distributions, not identical realized CTMC indices or common-noise spike paths. The fixed rowwise RNG law is unchanged from the predeclared comparison.',
        'action_policy':'argmax over the exact causal legal-action mask, same frozen ledger and oracle scoring as the main matrix',
        'output_files':['results/<milestone>/seed_<seed>/closed_test.json.gz',
                        'results/<milestone>/seed_<seed>/closed_shift.json.gz',
                        'results/<milestone>/seed_<seed>/paired_rep<0..3>.json.gz',
                        'results/selection.json','results/aggregate.json'],
        'episode_schema':'Header identifies checkpoint/source/selection. evaluation contains per-episode utility, oracle, normalized utility, budget spent, actual spike count, retained value and terminal live mask. Paired files additionally contain all action traces and actual spike times.',
        'aggregate_schema':'Two independent budget rows with5seed mean/SD training/utility metrics; each has paired contrasts versus its prelocked comparator for test/shift/paired, CI and raw-replay negative/positive/tie fractions, paired four-condition results, maturity-shock interaction and high-value terminal retention.',
        'statistics_shared_with_main':CONTRACT,'bootstrap_draws':BOOTSTRAP_DRAWS,'bootstrap_seed':BOOTSTRAP_SEED,
        'inference_limits':['Intervals condition on the four fixed paired replays.',
                            'No new test-based comparator selection or training adjustment.',
                            'Synthetic shift is not an independent real future window.',
                            'Full-path oracle-imitation training is not a terminal-utility policy gradient.'],
        'training_plan_sha256':sha(ROOT/'experiment_plan.json'),
        'source_sha256':{str(p.relative_to(MAIN)):sha(p) for p in
            [ROOT/'evaluate.py',ROOT/'model.py',ROOT/'train.py',MAIN/'evaluate.py',MAIN/'aggregate_results.py']}}
    if path.exists():
        existing=read(path)
        if existing['source_sha256']!=protocol['source_sha256']:
            raise RuntimeError('Supplementary evaluation sources changed after declaration')
        return existing
    path.write_text(json.dumps(protocol,indent=2)+'\n');return protocol


def readiness(require_results=False):
    missing=[]
    if not (MAIN/'results/selection.json').exists():missing.append(str(MAIN/'results/selection.json'))
    for milestone in MILESTONES:
        for seed in SEEDS:
            folder=ROOT/'results'/milestone/f'seed_{seed}'
            filenames=['training.json','model.pt']
            if require_results:filenames+=['closed_test.json.gz','closed_shift.json.gz']+[f'paired_rep{r}.json.gz' for r in range(4)]
            missing.extend(str(folder/name) for name in filenames if not (folder/name).exists())
    return {'ready':not missing,'missing_count':len(missing),'missing':missing}


def freeze_selection():
    ready=readiness()
    if not ready['ready']:raise RuntimeError(f"Supplementary holdout gate not ready: {ready['missing_count']} files missing")
    protocol=declare_analysis();main_selection=read(MAIN/'results/selection.json')
    if main_selection['holdout_metrics_used_for_selection']:raise ValueError('Main selection used holdout')
    if main_selection['evaluation_source_sha256']!=sha(MAIN/'evaluate.py'):raise ValueError('Frozen ledger evaluator changed')
    checkpoints={};paths=[]
    for milestone in MILESTONES:
        checkpoints[milestone]={}
        for seed in SEEDS:
            folder=ROOT/'results'/milestone/f'seed_{seed}';receipt=read(folder/'training.json')
            if receipt['milestone']!=milestone or receipt['seed']!=seed:raise ValueError('Supplementary identity mismatch')
            if receipt['holdout_opened_by_training'] or not receipt['not_endpoint_likelihood']:
                raise ValueError('Supplementary training semantic mismatch')
            if milestone=='fixed_updates' and (receipt['epochs']!=32 or receipt['updates']!=256):
                raise ValueError('Fixed update budget changed')
            if milestone=='equal_cpu' and receipt['train_cpu_seconds']<receipt['equal_cpu_target_seconds']:
                raise ValueError('Equal CPU budget underspent')
            for name,expected in receipt['source_and_data_sha256'].items():
                if sha(MAIN/name)!=expected:raise ValueError('Supplementary source/data drift')
            path=folder/'model.pt'
            if sha(path)!=receipt['checkpoint_sha256']:raise ValueError('Supplementary checkpoint changed')
            checkpoints[milestone][str(seed)]=receipt['checkpoint_sha256'];paths.append(path)
            reference=MAIN/'results'/COMPARATORS[milestone]/f'seed_{seed}'/'model.pt'
            if sha(reference)!=main_selection['checkpoints'][COMPARATORS[milestone]][str(seed)]:
                raise ValueError('Prelocked comparator checkpoint changed')
    selection={'schema':'rrsnn.coupled-selection.v1','checkpoints':checkpoints,'comparators':COMPARATORS,
        'main_selection_sha256':sha(MAIN/'results/selection.json'),
        'analysis_protocol_sha256':sha(ROOT/'analysis_protocol.json'),
        'training_plan_sha256':sha(ROOT/'experiment_plan.json'),
        'holdout_metrics_used_for_selection':False,'source_sha256':protocol['source_sha256']}
    target=ROOT/'results/selection.json'
    if target.exists() and read(target)!=selection:raise RuntimeError('Supplementary selection changed')
    target.write_text(json.dumps(selection,indent=2)+'\n')
    return paths


def validate_identity(payload,milestone,seed,dataset,repeat,checkpoint_sha256,selection_sha256):
    expected={'schema':'rrsnn.coupled-evaluation.v1','milestone':milestone,'seed':seed,
        'run_name':'rr_coupled_full_path_'+milestone,'variant':'rr_coupled_full_path',
        'dataset':dataset,'repeat':repeat,'random_seed':940000+seed+10007*repeat if dataset=='paired' else 900000+seed,
        'checkpoint_sha256':checkpoint_sha256,'selection_sha256':selection_sha256,
        'mode':MODE,'evaluator_sha256':sha(Path(__file__)),
        'frozen_ledger_evaluator_sha256':sha(MAIN/'evaluate.py')}
    for name,value in expected.items():
        if payload.get(name)!=value:raise ValueError(f'Evaluation identity mismatch: {name}')


def one(checkpoint):
    torch.set_num_threads(1)
    selection=read(ROOT/'results/selection.json')
    if selection['main_selection_sha256']!=sha(MAIN/'results/selection.json'):
        raise ValueError('Main selection lock changed')
    for name,expected in selection['source_sha256'].items():
        if sha(MAIN/name)!=expected:raise ValueError('Evaluation source drift')
    checkpoint=Path(checkpoint);blob=torch.load(checkpoint,map_location='cpu',weights_only=False)
    milestone,seed=blob['milestone'],blob['seed']
    if sha(checkpoint)!=selection['checkpoints'][milestone][str(seed)]:raise ValueError('Unselected weights')
    model=CoupledSpikePolicy();model.load_state_dict(blob['state_dict']);model.eval()
    header={'schema':'rrsnn.coupled-evaluation.v1','run_name':blob['run_name'],'variant':blob['variant'],
        'milestone':milestone,'seed':seed,'checkpoint_sha256':sha(checkpoint),
        'selection_sha256':sha(ROOT/'results/selection.json'),'real_future_window':False,
        'evaluated_after_frozen_model_selection':True,'mode':MODE,
        'evaluator_sha256':sha(Path(__file__)),'frozen_ledger_evaluator_sha256':sha(MAIN/'evaluate.py')}
    for name in ('test','shift','paired'):
        scenarios=load_scenarios(name);oracles=load_oracles(name,scenarios)
        for repeat in range(4 if name=='paired' else 1):
            filename=f'paired_rep{repeat}.json.gz' if name=='paired' else f'closed_{name}.json.gz'
            target=checkpoint.parent/filename
            if target.exists():
                old=read(target)
                validate_identity(old,milestone,seed,name,repeat,header['checkpoint_sha256'],header['selection_sha256'])
                continue
            rng_seed=940000+seed+10007*repeat if name=='paired' else 900000+seed
            result=evaluate_coupled(model,scenarios,oracles,rng_seed,keep_trace=name=='paired')
            write_gzip(target,{**header,'dataset':name,'repeat':repeat,'random_seed':rng_seed,'evaluation':result})
            print(json.dumps({'milestone':milestone,'seed':seed,'dataset':name,'repeat':repeat,
                'normalized_utility':result['normalized_utility_mean']}),flush=True)


def candidate_arrays(milestone,dataset,selection,scenarios):
    repeats=4 if dataset=='paired' else 1;rows=[];files=[]
    for seed in SEEDS:
        seed_rows=[]
        for repeat in range(repeats):
            filename=f'paired_rep{repeat}.json.gz' if dataset=='paired' else f'closed_{dataset}.json.gz'
            path=ROOT/'results'/milestone/f'seed_{seed}'/filename;payload=read(path)
            validate_identity(payload,milestone,seed,dataset,repeat,
                selection['checkpoints'][milestone][str(seed)],sha(ROOT/'results/selection.json'))
            e=payload['evaluation']
            if e['mode']!=MODE or e['internal_count_semantics']!='real spikes':raise ValueError('Wrong physical rollout mode')
            if e['episodes']!=len(scenarios) or not e['ledger_conservation'] or e['budget_violations']:
                raise ValueError('Episode/ledger invariant failed')
            seed_rows.append(e);files.append({'path':str(path.relative_to(MAIN)),'sha256':sha(path)})
        rows.append(seed_rows)
    fields={'utility':'episode_utility','oracle':'episode_oracle','normalized_utility':'episode_normalized_utility',
            'budget_spent':'episode_budget_spent','internal_count':'episode_internal_count'}
    arrays={key:np.asarray([[row[field] for row in seed_rows] for seed_rows in rows],dtype=float)
            for key,field in fields.items()}
    if any(a.shape!=(len(SEEDS),repeats,len(scenarios)) or not np.isfinite(a).all() for a in arrays.values()):
        raise ValueError('Malformed episode arrays')
    oracle,utility=arrays['oracle'],arrays['utility']
    if not np.allclose(oracle,oracle[0,0],rtol=0,atol=1e-12):raise ValueError('Task oracle differs across seeds/replays')
    if np.max(utility-oracle)>1e-8:raise ValueError('Utility exceeds oracle')
    normalized=np.divide(utility,oracle,out=np.ones_like(utility),where=oracle>1e-12)
    if not np.allclose(normalized,arrays['normalized_utility'],rtol=0,atol=1e-12):raise ValueError('Ratio mismatch')
    masks=np.asarray([[row['episode_live_final'] for row in seed_rows] for seed_rows in rows])
    keep=retention(np.array([s['values'] for s in scenarios]),masks)
    reported=np.asarray([[row['episode_retained_value'] for row in seed_rows] for seed_rows in rows])
    if not np.allclose(keep['retained_value'],reported,rtol=0,atol=1e-10):raise ValueError('Retention mismatch')
    arrays.update(keep);arrays['regret']=oracle-utility
    return {'arrays':arrays,'replays':repeats,'modes':[MODE],'files':files,
        'unique_zero_oracle_episodes':int(np.sum(oracle[0,0]<=1e-12))}


def aggregate():
    ready=readiness(require_results=True)
    if not ready['ready']:raise RuntimeError(f"Refusing partial supplementary aggregate: {ready['missing_count']} files missing")
    selection=read(ROOT/'results/selection.json');main_selection=read(MAIN/'results/selection.json')
    if selection['main_selection_sha256']!=sha(MAIN/'results/selection.json'):raise ValueError('Selection drift')
    protocol=declare_analysis()
    scenarios={name:read(MAIN/'data'/f'{name}_scenarios.json') for name in ('test','shift','paired')}
    index=paired_indices(scenarios['paired'])
    bootstrap={name:PairedBootstrap(len(SEEDS),len(index) if name=='paired' else len(items))
               for name,items in scenarios.items()}
    report={'schema':'rrsnn.coupled-aggregate.v1','milestones':{},'protocol':protocol,
        'main_selection_sha256':sha(MAIN/'results/selection.json'),
        'supplementary_selection_sha256':sha(ROOT/'results/selection.json'),
        'status':'Supplementary predeclared contrasts; primary70-run conclusions are separate.',
        'real_future_window':False,'training_target':'External teacher-tape expected NLL, not terminal utility policy gradient',
        'input_files':[]}
    for milestone in MILESTONES:
        training=[read(ROOT/'results'/milestone/f'seed_{seed}'/'training.json') for seed in SEEDS]
        row={'comparator':COMPARATORS[milestone],
            'training':{key:stats([r[key] for r in training]) for key in
                ('initial_validation_nll','best_validation_nll','epochs','updates','train_cpu_seconds',
                 'train_seconds','process_peak_rss_mib','actual_training_spikes','cpu_budget_overshoot_seconds')},
            'all_gradients_finite':all(r['gradients_all_finite'] for r in training),
            'datasets':{},'paired_comparisons':{}}
        for name in scenarios:
            ca=candidate_arrays(milestone,name,selection,scenarios[name])
            ra=load_evaluations(COMPARATORS[milestone],list(SEEDS),name,main_selection,scenarios[name])
            if not np.allclose(ca['arrays']['oracle'][:,0],ra['arrays']['oracle'][:,0],rtol=0,atol=1e-12):
                raise ValueError('Candidate/reference task oracle differs')
            indices=index if name=='paired' else None
            row['datasets'][name]={'candidate':describe(ca,indices),'reference':describe(ra,indices)}
            row['paired_comparisons'][name]=compare(ca,ra,bootstrap[name],indices)
            report['input_files']+=ca['files']+ra['files']
        report['milestones'][milestone]=row
    path=ROOT/'results/aggregate.json';temporary=path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report,indent=2)+'\n');temporary.replace(path)
    print(json.dumps({'aggregate':str(path),'comparators':COMPARATORS}),flush=True)
    return report


def run_child(checkpoint):
    with CPU_LOCK:cpu=FREE_CPUS.pop()
    try:
        with (checkpoint.parent/'evaluation.log').open('w') as log:
            env=os.environ.copy();env.update(OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
            completed=subprocess.run(['taskset','-c',str(cpu),sys.executable,'-m','rrsnn_v2.coupled.evaluate',
                '--one',str(checkpoint)],cwd=str(MAIN.parent),env=env,stdout=log,stderr=subprocess.STDOUT)
        if completed.returncode:raise RuntimeError(f'Supplementary evaluation failed: {checkpoint}')
        print(json.dumps({'completed_evaluation':str(checkpoint)}),flush=True)
    finally:
        with CPU_LOCK:FREE_CPUS.append(cpu)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--declare-only',action='store_true')
    parser.add_argument('--check',action='store_true');parser.add_argument('--one')
    parser.add_argument('--all',action='store_true');parser.add_argument('--aggregate',action='store_true')
    parser.add_argument('--workers',type=int,default=4);args=parser.parse_args()
    if args.declare_only:print(json.dumps(declare_analysis(),indent=2))
    elif args.check:print(json.dumps(readiness(),indent=2))
    elif args.one:one(Path(args.one))
    elif args.aggregate:aggregate()
    elif args.all:
        if not 1<=args.workers<=6:parser.error('Use1..6 workers on free CPUs0..5 only')
        paths=freeze_selection();FREE_CPUS.extend(range(args.workers))
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(run_child,path) for path in paths]):future.result()
        aggregate()
    else:parser.error('Choose --declare-only, --check, --one, --all or --aggregate')
