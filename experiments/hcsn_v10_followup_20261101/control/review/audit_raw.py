"""Streaming independent raw audit and exact-reward world-block statistics."""
import argparse
from fractions import Fraction
import gzip
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import random
from .enumeration_reference import score as enumerate_score


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def estimate(values):
    """Exact rewards and integer resampling; quantiles use exact interpolation."""
    n = len(values)
    denominator = math.lcm(*(v.denominator for v in values))
    ints = [int(v*denominator) for v in values]
    rng = random.Random(101603)
    draws = sorted(sum(ints[rng.randrange(n)] for _ in range(n)) for _ in range(10000))
    def quantile(frac):
        x = frac*(len(draws)-1)
        lo = x.numerator//x.denominator
        hi = min(lo+1,len(draws)-1)
        return (Fraction(draws[lo])+(x-lo)*(draws[hi]-draws[lo]))/(n*denominator)
    low, high = quantile(Fraction(1,40)), quantile(Fraction(39,40))
    mean = sum(values)/n
    return {'mean':float(mean),'mean_fraction':str(mean),'interval95':[float(low),float(high)],
            'interval95_fractions':[str(low),str(high)],'per_world_fractions':list(map(str,values)),
            'independent_worlds':n,'strict_positive_lower_bound':low>0,
            'method':'exact world rewards; fits averaged within world; 10000 world-block bootstrap draws seed101603'}


def audit(run, output):
    p = json.loads((run/'PLAN.json').read_text())
    complete = json.loads((run/'COMPLETE.json').read_text())
    repo=Path(__file__).resolve().parents[4]
    service=json.loads((repo/'experiments/hcsn_v9_followup_20261101/mechanisms/results/development001/SERVICE_FIT.json').read_text())['forecast']
    freeze = json.loads((run/'EVALUATION_FREEZE.json').read_text())
    checks = 0
    counters = {'main_runs':0,'fixed_replays':0,'outputs':0,'read_requests':0,
                'failed_reads':0,'MPC_decisions':0,'candidate_scores':0}
    max_error = 0.
    def require(ok, label):
        nonlocal checks
        checks += 1
        if not ok:
            raise AssertionError(label)
    for section in ('source_sha256','assets_sha256'):
        for path,expected in p[section].items():require(digest(repo/path)==expected,'frozen source/asset identity')
    require(digest(run/'runs.jsonl.gz')==complete['raw_sha256'],'runs hash')
    require(digest(run/'worlds.jsonl.gz')==complete['worlds_sha256'],'worlds hash')
    require(digest(run/'PLAN.json')==freeze['plan_sha256'],'plan hash')
    with gzip.open(run/'worlds.jsonl.gz','rt') as stream:
        worlds = {(v['condition'],v['index']):v for v in map(json.loads,stream)}
    require(len(worlds)==12,'world inventory')
    records = {}
    cfg=p['config']
    def validate(record, world, fixed=False):
        nonlocal max_error
        episode=world['episode']
        obs={'time':0.,'x':episode['initial_x'],'refractory_remaining':0.,
             'content_probs':[1/cfg['classes']]*cfg['classes'],'has_read':False}
        traces={r['tick']:r for r in record['trace']}
        outputs={r['tick']:r for r in record['outputs']}
        accesses={r['arrival_tick']:r for r in record['access']}
        require(len(traces)==len(record['trace']),'duplicate trace tick')
        require(set(outputs)==set(cfg['deadlines']),'mandatory output inventory')
        require(len(accesses)==len(record['access']),'duplicate access tick')
        pending=None
        stopped=False
        budget=cfg['budget']
        reads=0
        for tick in range(cfg['ticks']+1):
            if pending==tick:
                success=episode['service_uniform'][tick]<.9-.7*tick/20
                if success:
                    probs=[0.]*cfg['classes'];probs[episode['path']['content'][tick]]=1.
                    obs={'time':tick*cfg['dt'],'x':episode['path']['x'][tick],
                         'refractory_remaining':episode['path']['refractory_remaining'][tick],
                         'content_probs':probs,'has_read':True}
                access=accesses[tick]
                require(access=={'arrival_tick':tick,'success':success,'fee':cfg['read_cost'],'observation':obs},'service successor')
                if not fixed:
                    counters['failed_reads']+=not success
                pending=None
            else:
                require(tick not in accesses,'unsolicited access')
            if tick in outputs:
                row=outputs[tick]
                require(row['observation']==obs,'output observation')
                require(row['truth_for_scoring_only']==episode['path']['content'][tick],'output truth')
                probs=row['probabilities']
                require(all(math.isfinite(v) and v>=-1e-12 for v in probs) and abs(sum(probs)-1)<1e-9,'output law')
                require(row['correct']==int(max(range(len(probs)),key=probs.__getitem__)==row['truth_for_scoring_only']),'output class')
                z=obs['content_probs'][:]; expected=[0.]*cfg['classes']
                for weight in row['count_probabilities']:
                    for i in range(cfg['classes']):expected[i]+=weight*z[i]
                    z=[.15*z[i]+.55*z[(i-1)%len(z)]+.30*z[(i+1)%len(z)] for i in range(len(z))]
                require(max(abs(a-b) for a,b in zip(expected,probs))<2e-12,'count-to-content mixture')
                if not fixed:counters['outputs']+=1
            if tick==cfg['ticks'] or stopped:
                require(tick not in traces,'trace after STOP/end')
                continue
            row=traces[tick]
            require(row['observation']==obs,'decision observation')
            action=row['action'];detail=row['detail']
            require(action in ('STOP','WAIT','READ'),'unknown action')
            if not fixed and record['controller']=='multi_read_mpc' and 'candidates' in detail:
                counters['MPC_decisions']+=1
                future=[d for d in cfg['deadlines'] if d>tick]
                require(detail['samples']==p['MPC_samples'],'MPC budget')
                require(detail['service_forecast']==service,'frozen service forecast')
                require(detail['actual_hidden_world_accepted'] is False,'MPC interface scope')
                base={int(k):v for k,v in detail['base_correct'].items()}
                read={(v['arrival'],v['deadline']):v['correct'] for v in detail['read_correct']}
                require(set(base)==set(future),'baseline output inventory')
                expected_pairs={(a,d) for a in range(tick+1,max(future)+1) for d in future if a<=d}
                require(set(read)==expected_pairs,'READ successor inventory')
                require(all(0<=v<=1 and abs(v*p['MPC_samples']-round(v*p['MPC_samples']))<1e-10 for v in list(base.values())+list(read.values())),'MC frequencies')
                expected_schedules={s for size in range(min(budget,cfg['ticks']-tick)+1)
                    for s in combinations(range(tick+1,max(future)+1),size)}
                candidates=detail['candidates']
                actual_schedules={tuple(v['arrivals']) for v in candidates}
                require(len(candidates)==len(actual_schedules) and actual_schedules==expected_schedules,'candidate inventory')
                for candidate in candidates:
                    expected=enumerate_score(candidate['arrivals'],future,base,read,detail['service_forecast'],cfg['read_cost'],len(cfg['deadlines']))
                    error=abs(expected-candidate['score'])
                    max_error=max(max_error,error)
                    require(error<2e-12,'candidate service mixture')
                    counters['candidate_scores']+=1
                best=min(candidates,key=lambda v:(-v['score'],len(v['arrivals']),tuple(v['arrivals'])))
                require(best['arrivals']==detail['selected_arrivals'] and best['score']==detail['selected_score'],'MPC choice/ties')
                schedule=best['arrivals']
                expected_action='STOP' if not schedule else ('READ' if schedule[0]==tick+1 else 'WAIT')
                require(action==expected_action,'MPC first action')
            elif not fixed and record['controller']=='multi_read_mpc':
                require(action=='STOP' and (budget<=0 or not any(d>tick for d in cfg['deadlines'])),'MPC terminal STOP')
            if action=='READ':
                require(budget>0 and pending is None,'READ admission')
                budget-=1;reads+=1;pending=tick+1
                if not fixed:counters['read_requests']+=1
            if action=='STOP':stopped=True
            require(row['budget_after']==budget,'budget debit')
        reward=Fraction(sum(v['correct'] for v in outputs.values()),len(cfg['deadlines']))-reads*Fraction(1,25)
        summary=record['summary']
        require(summary['reads']==reads and summary['read_fees']==reads*cfg['read_cost'],'fee summary')
        require(abs(summary['net_reward']-float(reward))<1e-12,'reward arithmetic')
        return reward
    with gzip.open(run/'runs.jsonl.gz','rt') as stream:
        for row in map(json.loads,stream):
            key=(row['condition'],row['index'],row['fit_seed'],row['family'],row['controller'])
            require(key not in records,'duplicate run')
            world=worlds[(row['condition'],row['index'])]
            records[key]=validate(row,world)
            counters['main_runs']+=1
            if row['controller']=='multi_read_mpc':
                fixed=row['fixed_action_replay']
                fixed_reward=validate(fixed,world,True)
                require(fixed['outputs']==row['outputs'] and fixed['access']==row['access'],'fixed successor')
                require([(v['tick'],v['action']) for v in fixed['trace']]==[(v['tick'],v['action']) for v in row['trace']],'fixed actions')
                require(fixed_reward==records[key],'fixed reward')
                counters['fixed_replays']+=1
    require(counters['main_runs']==complete['main_runs']==396,'main count')
    require(counters['fixed_replays']==complete['fixed_action_runs']==132,'fixed count')
    stats={}
    for condition in p['conditions']:
        effects={k:[] for k in ('MPC-light_primary_ordinary','MPC-light_analytic','old-light_primary_ordinary',
                                 'old-light_analytic','A','B','C','D','D-B','interaction','MPC-light_gru','MPC-light_ssm')}
        for wi in range(p['worlds_per_condition']):
            def reward(fs,family,controller):return records[(condition,wi,str(fs),family,controller)]
            def ordinary(controller,family=None):
                return sum(reward(fs,family or freeze['old_ordinary_selections'][str(fs)],controller) for fs in p['ordinary_fits'])/len(p['ordinary_fits'])
            a,b=ordinary('lightweight'),ordinary('multi_read_mpc')
            c,d=reward(91103,'analytic','lightweight'),reward(91103,'analytic','multi_read_mpc')
            values={'A':a,'B':b,'C':c,'D':d,'D-B':d-b,'interaction':(d-c)-(b-a),
                    'MPC-light_primary_ordinary':b-a,'MPC-light_analytic':d-c,
                    'old-light_primary_ordinary':ordinary('old_one_read')-a,
                    'old-light_analytic':reward(91103,'analytic','old_one_read')-c}
            for family in ('gru','ssm'):
                values['MPC-light_'+family]=ordinary('multi_read_mpc',family)-ordinary('lightweight',family)
            for name,value in values.items():effects[name].append(value)
        stats[condition]={name:estimate(values) for name,values in effects.items()}
    result={'status':'passed','checks':checks,'counters':counters,'maximum_candidate_mixture_error':max_error,
            'statistics':stats,'raw_sha256':digest(run/'runs.jsonl.gz'),
            'scope':'record/fee/successor/all schedule mixtures and choices; MC simulated frequencies not independently neural-forward replayed',
            'limits':['6 independent worlds per condition; historical fits not independent worlds',
                      'shared known-law conditional sampler is a model prior, not ordinary learned dynamics',
                      'MPC enumerates open-loop schedules and replans; not optimal feedback DP',
                      'quality and measured full CPU must both be assessed; no energy or memory adoption claim']}
    with output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'checks':checks,'counters':counters,'maximum_candidate_mixture_error':max_error}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    audit(args.run,args.out)
