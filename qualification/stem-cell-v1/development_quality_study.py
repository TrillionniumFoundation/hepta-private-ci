"""Five-fold controlled stopping study; independent risk testing before holdout.

The declared 2% bound is on harmful source-GROUP events, not absolute error,
wall latency or real future efficacy. All data are generated; IID group sampling
is an experimental assumption. No pretrained weight/model claim is produced.
"""

import argparse
from dataclasses import asdict
import hashlib
from pathlib import Path
import platform

import torch

from development_ablation import PhaseClock, RecurrentClassifier, fit_candidate
from development_anytime import fit_anytime_candidate
from development_quality import Census, RiskPlan, require_disjoint_history, select_guarded
from development_quality_runtime import (bind_policy, collect_observations, execute_policy,
                                         input_digests, run_selected)
from development_stopping import TrainingTrace, collect_training_trace, fit_continuation
from development_stopping_study import COST, HORIZON, execute, score, tensor_sha, write_once
from development_tensors import parameter_digest


SEEDS = (101, 202, 303)
SIZES = (('model_fit',128), ('critic_fit',96), ('calibration',64), ('risk',1024), ('heldout',512))
THRESHOLDS = (-.05, 0., .05, .1)


def make_population(seed):
    """Bernoulli difficulty per group, not a deterministic easy/hard alternation."""
    data, censuses = {}, {}
    rng = torch.Generator().manual_seed(seed)
    for time, (name,size) in enumerate(SIZES):
        x = torch.randn(size,5,8,generator=rng)
        strong = torch.rand(size,generator=rng) < .5
        signal = torch.where(strong, 1.5, .15)
        direction = torch.where(torch.rand(size,generator=rng) < .5, -1., 1.)
        x[:,:,0] += (signal*direction)[:,None]
        gold = (x[:,:,0].sum(1) > 0).long()
        data[name] = x,gold
        censuses[name] = Census('synthetic', name, tuple(f'{seed}-{name}-{i}' for i in range(size)),
                                input_digests(x), tuple(f'{seed}-{name}-group-{i}' for i in range(size)),
                                tuple('strong' if b else 'weak' for b in strong.tolist()), (time,)*size)
    previous = (censuses['model_fit'],)
    for name,_ in SIZES[1:]:
        require_disjoint_history(previous, censuses[name])
        previous += (censuses[name],)
    return data,censuses


def run_score(result, gold, census):
    predictions = torch.tensor(result['predictions'])
    depths = torch.tensor(result['depths'])
    correct = (predictions == gold).double()
    return {'accuracy': float(correct.mean()), 'cell_transitions': int(depths.sum()),
            'registered_utility': float((correct-depths*COST).mean()),
            'cpu_ns': result['cpu_ns'], 'wall_ns': result['wall_ns'],
            'strata_accuracy': {s: float(correct[torch.tensor([x == s for x in census.strata])].mean())
                                for s in sorted(set(census.strata))}}


def run_seed(seed, output, *, training_mode='terminal', alpha=.05/len(SEEDS)):
    if training_mode not in ('terminal', 'anytime'):
        raise ValueError('unregistered training experiment')
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        total = PhaseClock()
        data,censuses = make_population(seed)
        priors = tuple(censuses[n] for n,_ in SIZES[:3])
        configs = ([{'mode':'fixed','depth':d} for d in (1,2,3,4)] +
                   [{'mode':'confidence','depth':4,'threshold':t} for t in (.5,.6,.7,.8,.9,1.)] +
                   [{'mode':'learned','depth':4,'threshold':t} for t in THRESHOLDS])
        write_once(output/f'design-{seed}.json', {'seed':seed,'population_sizes':SIZES,'configs':configs,
                    'training_mode':training_mode, 'per_portfolio_alpha':alpha,
                    'exit_loss_weights':[.25]*4 if training_mode == 'anytime' else [0,0,0,1],
                    'maximum_group_harm':.02,'family_alpha_across_seeds':.05,'minimum_groups_per_slice':64,
                    'minimum_median_wall_saving':.05,'timing_repetitions':3,'strata':['strong','weak'],
                    'sample_group_scope':'generated IID mixture, not authenticated production episodes',
                    'input_digests':{n:tensor_sha(x) for n,(x,y) in data.items()},
                    'censuses':{n:asdict(c) for n,c in censuses.items()}})
        initial = RecurrentClassifier(8,2,depth=HORIZON)
        initial_identity = parameter_digest(initial)
        fitter = fit_anytime_candidate if training_mode == 'anytime' else fit_candidate
        model,model_fit = fitter(initial, *data['model_fit'], steps=180,seed=seed)
        model_fit['initial_model_digest'] = initial_identity
        model_fit['readout_rows'] = model_fit.get('readout_rows', model_fit['examples_processed'])
        model_fit['equal_actual_training_compute_claimed'] = False
        x,y = data['critic_fit']
        traces = [collect_training_trace(model,x[i:i+32],horizon=HORIZON) for i in range(0,len(x),32)]
        trace = TrainingTrace(torch.cat([t.states for t in traces]),torch.cat([t.logits for t in traces]),
                              parameter_digest(model),{k:sum(t.cost[k] for t in traces)
                              for k in ('cpu_ns','wall_ns','cell_transitions')})
        critic,critic_fit = fit_continuation(trace,y,unit_cost=COST)
        calibration_clock = PhaseClock()
        x,y = data['calibration']
        calibration = [{'config':c,'index':i,**score(execute(model,x,c,critic),y)} for i,c in enumerate(configs)]
        def best(items):
            return max(items,key=lambda c:(c['registered_utility'],-c['mean_depth'],-c['index']))['config']
        baseline_config = best([c for c in calibration if c['config']['mode'] != 'learned'])
        naive_config = best([c for c in calibration if c['config']['mode'] == 'learned'])
        calibration_cost = calibration_clock.finish()
        baseline = bind_policy(model,baseline_config)
        candidates = tuple(bind_policy(model,{'mode':'learned','depth':4,'threshold':t},critic) for t in THRESHOLDS)
        plan = RiskPlan(baseline,candidates,('strong','weak'),alpha=alpha)
        plan.validate()
        # Freeze both the baseline and the entire portfolio BEFORE risk outcomes.
        write_once(output/f'portfolio-{seed}.json', {'plan':asdict(plan),'identity':plan.identity(),
                    'calibration':calibration,'calibration_cost':calibration_cost,
                    'all_calibration_transitions':sum(c['cell_transitions'] for c in calibration),
                    'naive_learned':naive_config})
        x,risk_gold = data['risk']
        observed,measurement = collect_observations(model,x,censuses['risk'],(baseline,)+candidates,critic)
        # Preserve complete risk predictions and actual work before label comparison.
        write_once(output/f'risk-predictions-{seed}.json',measurement)
        testing_clock = PhaseClock()
        chosen,decision = select_guarded(plan,priors,censuses['risk'],tuple(risk_gold.tolist()),observed)
        decision['testing_cost'] = testing_clock.finish()
        decision['selection'] = asdict(chosen)
        write_once(output/f'risk-decision-{seed}.json',decision)
        x,heldout_gold = data['heldout']
        naive = bind_policy(model,naive_config,critic)
        raw = {'baseline':execute_policy(model,x,censuses['heldout'],baseline),
               'naive_learned':execute_policy(model,x,censuses['heldout'],naive,critic),
               'guarded':run_selected(model,x,censuses['heldout'],plan=plan,selection=chosen,
                            priors=priors,risk_census=censuses['risk'],critic=critic),
               'maximum_fixed':execute_policy(model,x,censuses['heldout'],
                                bind_policy(model,{'mode':'fixed','depth':4}))}
        exact_clock = PhaseClock()
        exact_predictions = (x[:,:,0].sum(1) > 0).long().tolist()
        exact_cost = exact_clock.finish()
        write_once(output/f'heldout-predictions-{seed}.json',{'arms':raw,'cheap_exact':exact_predictions,
                    'cheap_exact_cost':exact_cost,'census_digest':censuses['heldout'].identity()})
        metrics = {name:run_score(r,heldout_gold,censuses['heldout']) for name,r in raw.items()}
        # Selectors never see this evaluation census or its gold labels.
        paired_harm = sum(a == y and b != y for a,b,y in zip(raw['baseline']['predictions'],
                          raw['guarded']['predictions'],heldout_gold.tolist()))
        metrics['cheap_exact'] = {'accuracy':float((torch.tensor(exact_predictions)==heldout_gold).double().mean()),
                                   **exact_cost,'transition_cost_equivalence_claimed':False}
        all_transition_work = (model_fit['examples_processed']*HORIZON + trace.cost['cell_transitions'] +
                              sum(c['cell_transitions'] for c in calibration) +
                              measurement['actual_cell_transitions'] + sum(r['cell_transitions'] for r in raw.values()))
        report = {'seed':seed,'training_mode':training_mode,'baseline':baseline_config,'naive_learned':naive_config,'decision':decision,
                  'model_fit':model_fit,'critic_fit':critic_fit,'calibration_cost':calibration_cost,
                  'risk_measurement_cost':{k:v for k,v in measurement.items() if k not in ('ledger','observations')},
                  'heldout':metrics,'heldout_harmful_rows':paired_harm,
                  'guarded_selection_and_execution':raw['guarded']['selection_check_and_execution'],
                  'forward_transition_work_excluding_backward_and_preview':all_transition_work,
                  'nested_phase_times_must_not_be_added':True,'total':total.finish(),
                  'pretrained_encoder_executed':False,'real_future_window':False,'production_authorized':False}
        write_once(output/f'report-{seed}.json',report)
        return report


def main(output, *, paired_anytime=False):
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    files = [Path(__file__).with_name(n) for n in ('development_quality_study.py','development_quality.py',
             'development_quality_runtime.py','development_stopping.py','development_stopping_study.py',
             'development_ablation.py','development_composition.py','development_tensors.py','development_anytime.py')]
    sources = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    experiments = (tuple((s,m) for s in (404,505,606) for m in ('terminal','anytime'))
                   if paired_anytime else tuple((s,'terminal') for s in SEEDS))
    write_once(output/'source.json',{'sources':sources,'torch':torch.__version__,'python':platform.python_version(),
                                    'experiments':experiments,'threads':1,'synthetic':True,
                                    'same_data_initialization_steps':True,'same_actual_compute_claimed':False})
    try:
        reports = []
        for seed,mode in experiments:
            destination = output/f'{seed}-{mode}' if paired_anytime else output
            if paired_anytime:
                destination.mkdir(exist_ok=False)
            reports.append(run_seed(seed,destination,training_mode=mode,alpha=.05/len(experiments)))
        if paired_anytime:
            for i in range(0,len(reports),2):
                a,b = reports[i:i+2]
                if a['model_fit']['initial_model_digest'] != b['model_fit']['initial_model_digest']:
                    raise RuntimeError('paired model initialization mismatch')
        if sources != {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}:
            raise RuntimeError('consumed source changed during experiment')
        write_once(output/'summary.json',{'results':[{'seed':r['seed'],'training_mode':r['training_mode'],'baseline':r['baseline'],
                    'model_fit':r['model_fit'],
                    'fallback':r['decision']['fallback'],'heldout':r['heldout'],
                    'heldout_harmful_rows':r['heldout_harmful_rows']} for r in reports],
                    'quality_event':'any harmful answer in a future IID source group',
                    'pretrained_encoder_executed':False,'statistical_speedup_established':False,
                    'independent_outcome_attestation':False,'production_authorized':False})
    except Exception as error:
        write_once(output/'FAILED.json',{'type':type(error).__name__,'message':str(error),'sources':sources})
        raise
    finally:
        torch.set_num_threads(threads)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic',action='store_true',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--paired-anytime',action='store_true')
    args = parser.parse_args()
    main(args.output,paired_anytime=args.paired_anytime)
