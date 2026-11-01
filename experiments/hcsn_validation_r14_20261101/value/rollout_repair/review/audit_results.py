"""Independent episode, finite-clock and cost arithmetic for the frozen repair.

No controller or run.summarize is imported. Recorded actions are replayed against
independently regenerated indexed randomness and finite transition matrices.
Saved full-clock expectations are aggregated; their policy trees are not rerun.
"""

import argparse
import gzip
import hashlib
import json
import math
import resource
import statistics
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from itertools import product
from pathlib import Path


SCRIPT = Path(__file__).resolve()
BASE = SCRIPT.parent.parent
VALUE = BASE.parent
REPO = VALUE.parents[2]
ACTIONS = ('STOP0','STOP1','WAIT','READ','RESET')
ATOL = 2e-12
WEIGHTS = {
    'B-A': {'B':1,'A':-1}, 'D-C': {'D':1,'C':-1},
    'C-A': {'C':1,'A':-1}, 'D-B': {'D':1,'B':-1},
    'interaction': {'D':1,'C':-1,'B':-1,'A':1},
    'B_prime-A': {'B_prime':1,'A':-1}, 'D_prime-C': {'D_prime':1,'C':-1},
    'D_prime-B_prime': {'D_prime':1,'B_prime':-1},
    'B_prime-B': {'B_prime':1,'B':-1}, 'D_prime-D': {'D_prime':1,'D':-1},
    'interaction_prime': {'D_prime':1,'C':-1,'B_prime':-1,'A':1},
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def serializable(value):
    if isinstance(value, dict):
        return {k:serializable(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [serializable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {'nonfinite_value':str(value)}
    return value


class Audit:
    def __init__(self):
        self.checks = {}
        self.failures = []
        self.inputs = {}

    def check(self, category, condition, where=None, **detail):
        row = self.checks.setdefault(category, dict(tested=0,failed=0))
        row['tested'] += 1
        if not bool(condition):
            row['failed'] += 1
            self.failures.append(dict(check=category, where=where, **detail))

    def close(self, category, observed, expected, where=None, tolerance=ATOL):
        error = abs(float(observed)-float(expected))
        self.check(category, math.isfinite(error) and error <= tolerance, where,
                   observed=float(observed),expected=float(expected),error=error,tolerance=tolerance)
        row = self.checks[category]
        if math.isfinite(error):
            row['max_absolute_error'] = max(row.get('max_absolute_error',0.),error)

    def file(self, path):
        digest = sha(path)
        self.inputs[str(path.relative_to(VALUE))] = digest
        return digest


def draw(np, probabilities, uniform):
    # Equivalent inverse-CDF rule expressed independently of EpisodeOwner.
    return int(np.count_nonzero(np.cumsum(probabilities[:-1]) <= uniform))


def random_tape(np, seed, n, intervals, horizon):
    rng = np.random.default_rng(seed)
    initial = rng.random(n)
    clocks = np.array(intervals)[rng.integers(len(intervals),size=(n,horizon))]
    reset, transition, emission = rng.random((3,n,horizon))
    return initial,clocks,reset,transition,emission


def select_scores(scores):
    chosen = next(action for action in ACTIONS if action in scores)
    for action in ACTIONS:
        if action in scores and scores[action] > scores[chosen]+1e-12:
            chosen = action
    return chosen


def actual_case(audit,np,folder,protocol,seed,domain,arm,kind,source_sha,world,transitions):
    result, receipt = read(folder/'RESULT.json'),read(folder/'PROCESS.json')
    name = f'{seed}/{domain}/{arm}'
    audit.file(folder/'RESULT.json');audit.file(folder/'PROCESS.json')
    evidence_sha = audit.file(folder/'episodes.jsonl.gz')
    audit.check('worker/identity', result['seed']==receipt['seed']==seed and result['domain']==receipt['domain']==domain
                and result['arm']==receipt['arm']==arm and result['source_freeze_sha256']==source_sha
                and receipt['exit_code']==0 and result['kind']==kind and result['control']==protocol['arms'][arm][1],name)
    audit.check('worker/raw_hash', evidence_sha==result['evidence']['sha256'],name)
    audit.check('worker/checkpoint', result['checkpoint_sha256']==sha(VALUE/'upstream/checkpoints'/str(seed)/(kind+'.json')),name)
    n,horizon,budget = protocol['episodes_per_seed_domain'],protocol['horizon'],protocol['read_budget']
    tape_seed = protocol['tape_seed_offsets'][domain]+seed
    audit.check('worker/tape_seed', result['tape_seed']==tape_seed,name)
    initial,clocks,reset,transition,emission = random_tape(np,tape_seed,n,protocol['domains'][domain],horizon)
    with gzip.open(folder/'episodes.jsonl.gz','rt') as stream:
        rows = [json.loads(line) for line in stream]
    audit.check('worker/episode_inventory', len(rows)==result['episodes']==n and [r['episode'] for r in rows]==list(range(n)),name)
    reconstructed,local_gaps,changed,trajectories = [],[],0,[]
    for index,row in enumerate(rows):
        where = name+f'/episode{index}'
        state = draw(np,world.prior,initial[index])
        count = dict(READ=0,WAIT=0,RESET=0)
        cost,elapsed,position,answer = 0.,0.,0,None
        sequence = []
        for k,step in enumerate(row['trace']):
            action = step['action']
            clock = clocks[index,position:]
            reads_left = budget-count['READ']
            legal = ACTIONS[:2] if not len(clock) else tuple(a for a in ACTIONS if a!='READ' or reads_left)
            audit.check('episode/legal_prefix', action in legal and step['read_budget']==reads_left and np.array_equal(step['clock'],clock),where+f'/step{k}')
            if 'base_tail_scores_under_actor_belief' in step:
                scores = step['base_tail_scores_under_actor_belief']
                audit.check('episode/repair_selection', set(scores)==set(legal) and all(math.isfinite(v) for v in scores.values()) and select_scores(scores)==action,where+f'/step{k}')
                original = step['original_value_action']
                gap = scores[action]-scores[original]
                local_gaps.append(gap);changed += action!=original
                audit.close('episode/local_gap_arithmetic',step['fitted_local_advantage'],gap,where)
                audit.check('episode/local_gap_bound',gap>=-1.0001e-12,where,gap=gap)
            sequence.append((action,tuple(step['clock']),step['read_budget'],tuple(step.get('observed_input',()))))
            if action.startswith('STOP'):
                answer = int(action[-1])
                audit.check('episode/stop_terminates',k==len(row['trace'])-1 and 'observed_input' not in step,where)
                break
            dt = clocks[index,position]
            if action=='RESET':
                state = draw(np,world.R[state],reset[index,position])
            state = draw(np,transitions[float(dt)][state],transition[index,position])
            cost += .01*dt + (.04 if action=='RESET' else 0.)
            observation = np.zeros(10)
            if action=='READ':
                token = draw(np,world.E[state],emission[index,position])
                observation[token]=1.;observation[7]=1.
                cost += world.read_cost[state]
            observation[8]=dt;observation[9]=float(action=='RESET')
            audit.check('episode/raw_observation',np.array_equal(observation,step['observed_input']),where+f'/step{k}')
            elapsed += dt;position += 1;count[action] += 1
        if answer is None:
            audit.check('episode/terminal_answer',False,where)
            continue
        reward = float(world.reward[state,answer])
        utility = reward-cost
        correct = int(answer==state%2)
        audit.check('episode/terminal_state_and_counts',row['arm']==arm and row['state']==state and row['label']==state%2
                    and row['correct']==correct and row['steps']==position and row['counts']==count,where)
        for field,value in (('cost',cost),('reward',reward),('utility',utility),('elapsed',elapsed)):
            audit.close('episode/'+field,row[field],value,where)
        reconstructed.append(dict(utility=utility,reward=reward,cost=cost,correct=correct,counts=count,initial_stop=position==0))
        trajectories.append(sequence)
    metrics = {out:float(np.mean([r[key] for r in reconstructed])) for out,key in
               (('mean_utility','utility'),('mean_reward','reward'),('mean_task_cost','cost'),('accuracy','correct'))}
    metrics['mean_episode_cpu_seconds'] = float(np.mean([r['episode_cpu_seconds'] for r in rows]))
    component = result['component_cpu_seconds']
    metrics['mean_actor_cpu_seconds'] = (component['controller']+component['estimator'])/n
    for field,value in metrics.items():
        audit.close('worker/'+field,result[field],value,name)
    counts = {action:sum(r['counts'][action] for r in reconstructed) for action in ('READ','WAIT','RESET')}
    audit.check('worker/action_counts',result['counts']==counts,name)
    audit.check('worker/initial_stop',result['initial_stop_count']==sum(r['initial_stop'] for r in reconstructed),name)
    for label,q in (('p50',.5),('p95',.95)):
        audit.close('worker/latency_'+label,result['episode_latency_ms'][label],np.quantile([r['episode_wall_seconds'] for r in rows],q)*1000,name)
    audit.close('worker/actor_cpu',result['actor_cpu_seconds'],component['controller']+component['estimator'],name)
    audit.close('worker/unattributed_execution',result['unattributed_execution_cpu_seconds'],result['execution_cpu_seconds']-sum(component[k] for k in ('controller','estimator','owner')),name)
    audit.check('worker/timing_containment',sum(r['episode_cpu_seconds'] for r in rows)<=result['execution_cpu_seconds']+1e-6 and
                sum((result['setup_cpu_seconds'],result['execution_cpu_seconds'],component['diagnostic'],component['recording']))<=receipt['child_cpu_seconds']+1e-4,name)
    repair = protocol['arms'][arm][1]=='actor_rollout_base_tail'
    audit.check('worker/diagnostic_isolation_record', (result['caches']['diagnostic'] is not None)==repair
                and (component['diagnostic']>0)==repair and 'separate planner/model after all timed episodes' in result['caches']['scope'],name)
    for category in ('actual','diagnostic'):
        cache = result['caches'][category]
        if cache is None:continue
        for key,bound in (('values',16384),('transitions',128)):
            c = cache[key]
            audit.check('worker/cache_bounds',0<=c['currsize']<=bound and c['maxsize']==bound and c['hits']>=0 and c['misses']>=c['currsize'],name+'/'+category+'/'+key)
    if local_gaps:
        audit.close('worker/min_local_gap',result['min_fitted_local_advantage'],min(local_gaps),name)
        expected_changed = result['equivalence']['hx_action_disagreements' if kind=='hx_distribution' else 'ordinary_changed_first_actions']
        audit.check('worker/changed_first_actions',expected_changed==changed,name)
    else:
        audit.check('worker/no_repair_diagnostics',result['min_fitted_local_advantage'] is None,name)
    metrics.update(counts=counts,initial_stop_count=sum(r['initial_stop'] for r in reconstructed),
                   full_process_cpu_seconds=receipt['child_cpu_seconds'],full_process_wall_seconds=receipt['wall_seconds'],
                   max_rss_kib=receipt['max_rss_kib'],component_cpu_seconds=component,
                   caches=result['caches'],equivalence=result['equivalence'])
    return metrics,trajectories


def clock_case(audit,np,folder,protocol,seed,domain,source_sha,world):
    result,receipt = read(folder/'RESULT.json'),read(folder/'PROCESS.json')
    audit.file(folder/'RESULT.json');audit.file(folder/'PROCESS.json')
    name = f'full_clock/{seed}/{domain}'
    audit.check('clock/identity',result['seed']==receipt['seed']==seed and result['domain']==receipt['domain']==domain
                and result['source_freeze_sha256']==source_sha and receipt['exit_code']==0,name)
    expected = {(arm,tuple(clock)) for arm in protocol['arms'] for clock in product(protocol['domains'][domain],repeat=protocol['horizon'])}
    records = result['records']
    observed = {(r['arm'],tuple(r['clock'])) for r in records}
    audit.check('clock/complete_unique_inventory',observed==expected and len(records)==len(expected),name)
    for r in records:
        where = name+'/'+r['arm']+'/'+str(r['clock'])
        audit.close('clock/leaf_mass',r['leaf_mass'],1.,where,tolerance=2e-10)
        count = [r[k] for k in ('expected_reads','expected_waits','expected_resets')]
        audit.check('clock/action_bounds',all(math.isfinite(v) and v>=-ATOL for v in count)
                    and count[0]<=protocol['read_budget']+ATOL and sum(count)<=protocol['horizon']+ATOL
                    and 1<=r['leaves']<=world.E.shape[1]**protocol['read_budget'] and r['decisions']>=r['leaves'],where)
        lower = float(world.reward.min())-.01*sum(r['clock'])-.04*protocol['horizon']-protocol['read_budget']*float(world.read_cost.max())
        audit.check('clock/utility_bounds',lower-ATOL<=r['utility']<=float(world.reward.max())+ATOL,where)
    means = {arm:float(np.mean([r['utility'] for r in records if r['arm']==arm])) for arm in protocol['arms']}
    for arm,value in means.items():
        audit.close('clock/mean',result['mean_utility'][arm],value,name+'/'+arm)
    error = max(abs(r['leaf_mass']-1) for r in records)
    audit.close('clock/mass_error_summary',result['max_mass_error'],error,name)
    paired = {(r['arm'],tuple(r['clock'])):r for r in records}
    hx_difference = max(abs(paired['D',clock]['utility']-paired['D_prime',clock]['utility']) for clock in product(protocol['domains'][domain],repeat=protocol['horizon']))
    return dict(means=means,max_mass_error=error,records=len(records),hx_max_D_prime_minus_D_absolute=hx_difference,
                child_cpu_seconds=receipt['child_cpu_seconds'],wall_seconds=receipt['wall_seconds'],max_rss_kib=receipt['max_rss_kib'])


def effects(audit,np,critical,values,published,where):
    results = {}
    for label,weights in WEIGHTS.items():
        paired = [sum(weights.get(arm,0)*v[arm] for arm in v) for v in values]
        mean = statistics.mean(paired)
        half = critical*statistics.stdev(paired)/math.sqrt(len(paired))
        row = dict(mean=mean,ci95_descriptive=[mean-half,mean+half],fit_values=paired)
        target = published[label]
        audit.close('contrast/mean',target['mean'],mean,where+'/'+label)
        audit.close('contrast/fit_values',np.max(np.abs(np.array(target['fit_values'])-paired)),0.,where+'/'+label)
        audit.close('contrast/descriptive_interval',np.max(np.abs(np.array(target['ci95_descriptive'])-row['ci95_descriptive'])),0.,where+'/'+label)
        results[label] = row
    audit.check('contrast/inventory',set(published)==set(WEIGHTS),where)
    return results


def run(output,audit):
    import numpy as np
    from scipy.linalg import expm
    from scipy.special import stdtrit
    sys.path.insert(0,str(REPO))
    from experiments.hcsn_validation_r14_20261101.value.upstream.cell import Cell
    protocol,freeze = read(BASE/'PROTOCOL.json'),read(BASE/'SOURCE_FREEZE.json')
    source_sha = audit.file(BASE/'SOURCE_FREEZE.json')
    for name,digest in freeze['source_files'].items():
        audit.check('source/frozen',audit.file(BASE/name)==digest,name)
    inherited = read(VALUE/'SOURCE_FREEZE.json')
    audit.check('source/inherited_freeze',audit.file(VALUE/'SOURCE_FREEZE.json')==freeze['inherited_freeze_sha256'])
    for name,digest in inherited['files'].items():
        audit.check('source/inherited_file',sha(VALUE/name)==digest,name)
    audit.check('campaign/no_failure',not (output/'FAILURE.json').exists())
    summary,campaign = read(output/'SUMMARY.json'),read(output/'PROCESS.json')
    audit.file(output/'SUMMARY.json');audit.file(output/'PROCESS.json')
    audit.check('campaign/started_identity',read(output/'STARTED.json')['source_freeze_sha256']==source_sha)
    selections = read(VALUE/'upstream/CANDIDATE_FREEZE.json')['selection']
    world = Cell()
    transitions = {float(dt):expm(float(dt)*world.Q) for intervals in protocol['domains'].values() for dt in intervals}
    actual,clocks,trajectories = {},{},{}
    for seed in protocol['seeds']:
        for domain in protocol['domains']:
            for arm,(kind,control) in protocol['arms'].items():
                kind = selections[str(seed)]['kind'] if kind=='ordinary' else kind
                case,paths = actual_case(audit,np,output/str(seed)/domain/arm,protocol,seed,domain,arm,kind,source_sha,world,transitions)
                actual[seed,domain,arm]=case;trajectories[seed,domain,arm]=paths
            clocks[seed,domain] = clock_case(audit,np,output/'full_clock'/str(seed)/domain,protocol,seed,domain,source_sha,world)
    results = {}
    critical = float(stdtrit(len(protocol['seeds'])-1,.975))
    for domain in protocol['domains']:
        published = summary['domains'][domain]
        arms = {}
        for arm in protocol['arms']:
            parts = [actual[s,domain,arm] for s in protocol['seeds']]
            row = {k:float(np.mean([p[k] for p in parts])) for k in ('mean_utility','accuracy','mean_task_cost','mean_episode_cpu_seconds','mean_actor_cpu_seconds')}
            row.update(full_process_cpu_seconds=sum(p['full_process_cpu_seconds'] for p in parts),full_process_wall_seconds=sum(p['full_process_wall_seconds'] for p in parts),
                       max_rss_kib=max(p['max_rss_kib'] for p in parts),counts={a:sum(p['counts'][a] for p in parts) for a in ('READ','WAIT','RESET')},
                       component_cpu_seconds={k:sum(p['component_cpu_seconds'][k] for p in parts) for k in parts[0]['component_cpu_seconds']})
            for metric,value in row.items():
                if isinstance(value,dict):
                    for key,number in value.items():audit.close('summary/arm_'+metric,published['arms'][arm][metric][key],number,domain+'/'+arm+'/'+key)
                else:audit.close('summary/arm_'+metric,published['arms'][arm][metric],value,domain+'/'+arm)
            arms[arm]=row
        av = [{arm:actual[s,domain,arm]['mean_utility'] for arm in protocol['arms']} for s in protocol['seeds']]
        cv = [clocks[s,domain]['means'] for s in protocol['seeds']]
        actual_effects = effects(audit,np,critical,av,published['contrasts'],domain+'/actual')
        finite = published['full_clock_secondary']
        clock_effects = effects(audit,np,critical,cv,finite['contrasts'],domain+'/full_clock')
        for arm in protocol['arms']:
            audit.close('summary/clock_mean',finite['mean_utility'][arm],np.mean([v[arm] for v in cv]),domain+'/'+arm)
            for seed in protocol['seeds']:
                audit.close('summary/clock_fit_mean',finite['per_fit_mean_utility'][str(seed)][arm],clocks[seed,domain]['means'][arm],domain+'/'+str(seed)+'/'+arm)
        audit.check('summary/clock_counts',finite['clock_count_per_fit']==27 and finite['fit_count']==len(protocol['seeds']),domain)
        audit.close('summary/clock_mass',finite['max_mass_error'],max(clocks[s,domain]['max_mass_error'] for s in protocol['seeds']),domain)
        ratios = {}
        for label,left,right in (('B_prime/B','B_prime','B'),('D_prime/D','D_prime','D')):
            ratios[label] = {k:arms[left][k]/arms[right][k] for k in ('mean_episode_cpu_seconds','mean_actor_cpu_seconds','full_process_cpu_seconds')}
            for metric,value in ratios[label].items():audit.close('summary/cost_ratio',published[label+'_ratios'][metric],value,domain+'/'+label+'/'+metric)
        identical = sum(trajectories[s,domain,'D'][i]==trajectories[s,domain,'D_prime'][i] for s in protocol['seeds'] for i in range(protocol['episodes_per_seed_domain']))
        results[domain] = dict(arms=arms,actual_effects=actual_effects,full_clock_effects=clock_effects,cost_ratios=ratios,hx_identical_actual_episode_trajectories=identical)
    actual_cpu = sum(v['full_process_cpu_seconds'] for v in actual.values())
    clock_cpu = sum(v['child_cpu_seconds'] for v in clocks.values())
    audit.close('campaign/actual_cpu',campaign['summed_full_worker_cpu_seconds'],actual_cpu)
    audit.close('campaign/clock_cpu',campaign['summed_secondary_worker_cpu_seconds'],clock_cpu)
    audit.check('campaign/worker_counts',campaign['workers']==len(actual)==96 and campaign['secondary_workers']==len(clocks)==16 and campaign['serial_workers'])
    audit.check('campaign/no_new_training_or_energy_claim',campaign['new_training_cpu_seconds']==0 and campaign['energy_joules'] is None)
    return dict(source_freeze_sha256=source_sha,domains=results,
                actual_workers={f'{s}/{d}/{a}':row for (s,d,a),row in actual.items()},
                clock_workers={f'{s}/{d}':row for (s,d),row in clocks.items()},
                counts=dict(actual_workers=len(actual),episodes=len(actual)*protocol['episodes_per_seed_domain'],clock_workers=len(clocks),clock_arm_records=sum(v['records'] for v in clocks.values())),
                cost=dict(actual_full_child_cpu_seconds=actual_cpu,full_clock_child_cpu_seconds=clock_cpu,combined_new_child_cpu_seconds=actual_cpu+clock_cpu,
                          inherited_shared_preparation_cpu_seconds=campaign['inherited_training_and_preparation_cpu_seconds'],energy_joules=None))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():raise FileExistsError('Preserve prior audit: '+str(args.report))
    start_cpu,start_wall=time.process_time(),time.perf_counter()
    audit,payload=Audit(),{}
    try:payload=run(args.output.resolve(),audit)
    except Exception as error:audit.check('fatal_exception',False,type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
    result=dict(schema='hcsn.r14.rollout_repair.independent-results-audit.v1',status='fail' if audit.failures else 'pass',
        audit_script_sha256=sha(SCRIPT),audited_at_utc=datetime.now(timezone.utc).isoformat(),input_directory=str(args.output.resolve()),
        checks=audit.checks,failed_checks=audit.failures,input_sha256=audit.inputs,result=payload,
        audit_cost=dict(body_cpu_seconds=time.process_time()-start_cpu,wall_seconds=time.perf_counter()-start_wall,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,energy_joules=None),
        scope=[
            'Independently regenerated indexed random tapes and inverse-CDF state/emission sampling, using the frozen true finite Cell parameter tables and independent scipy matrix exponentials; recorded actions are held fixed. No EpisodeOwner, choose_actor, choose_rollout or run.summarize is called.',
            'All saved clock-arm expectation records are checked and aggregated independently. The full-clock policy recursion is not re-executed here; its actual repair-selector continuation and evaluator-only true mass were separately source-reviewed.',
            'Cache isolation evidence combines frozen reviewed source, successful assertion-bearing worker exits, separately recorded actual/diagnostic cache statistics and separated timer identities. This does not reconstruct hardware cache effects or rerun performance measurements.',
            'Sampled outcomes, uniform finite-clock expectations and base-tail local scores remain different quantities. A local fitted score gain is not a true-world guarantee or repaired conditional regret.',
            'Eight inherited paired fit seeds provide descriptive intervals only. The task is a three-step finite20-state CTMC; no new training, continuum proof, natural-content result or foundation-core acceptance follows.',
            'Whole-worker costs include nested components, simulated owners, diagnostics and evidence. Component timers are not added again. Full-clock evaluator cost is separately reported; energy is unavailable.'
        ])
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x') as stream:json.dump(serializable(result),stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(dict(status=result['status'],checks=sum(v['tested'] for v in audit.checks.values()),failures=len(audit.failures),report=str(args.report),sha256=sha(args.report))))
    return int(bool(audit.failures))


if __name__=='__main__':raise SystemExit(main())
