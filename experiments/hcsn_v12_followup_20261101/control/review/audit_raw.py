"""Independent raw chronology, integer gate arithmetic and exact reward audit."""
import argparse
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
from experiments.hcsn_v10_followup_20261101.control.review.audit_raw import estimate


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(run,out):
    p=json.loads((run/'PLAN.json').read_text())
    complete=json.loads((run/'COMPLETE.json').read_text())
    freeze=json.loads((run/'EVALUATION_FREEZE.json').read_text())
    repo=Path(__file__).resolve().parents[4]
    checks=0
    counters={'main_runs':0,'fixed_runs':0,'outputs':0,'READ_requests':0,'service_failures':0,
              'selection_pools':0,'validation_pools':0,'accepted_deviations':0,'fallback_decisions':0,
              'baseline_state_matches':0}
    def require(ok,label):
        nonlocal checks
        checks+=1
        if not ok:raise AssertionError(label)
    require(sha(run/'runs.jsonl.gz')==complete['raw_sha256'],'main raw hash')
    require(sha(run/'worlds.jsonl.gz')==complete['worlds_sha256'],'worlds hash')
    require(sha(run/'PLAN.json')==freeze['plan_sha256'],'plan hash')
    for section in ('source_sha256','assets_sha256'):
        for path,expected in p[section].items():require(sha(repo/path)==expected,'frozen source/asset')
    require(p['maximum_validation_tests']==12*11*20==2640,'campaign test bound')
    require(p['alpha_per_test']==.05/2640 and p['delta_campaign_model_only']==.05,'alpha allocation')
    require(p['selection_pool_size']==p['validation_pool_size']==512,'fixed pool budgets')
    with gzip.open(run/'worlds.jsonl.gz','rt') as stream:
        worlds={(r['condition'],r['index']):r for r in map(json.loads,stream)}
    require(len(worlds)==12,'world inventory')
    seeds=[seed for w in worlds.values() for pair in w['policy_seeds'] for seed in pair]
    require(len(seeds)==len(set(seeds))==480==p['distinct_pool_namespace_seeds'],'independent pool namespace')
    records={};light_traces={};fallback_by_run={}
    cfg=p['config'];controllers=p['controllers']
    def branch(br,roots,r,b):
        require(len(br['reward_units'])==len(br['correct_counts'])==len(br['read_counts'])==len(roots),'root inventory')
        for label,units,correct,reads in zip(roots,br['reward_units'],br['correct_counts'],br['read_counts']):
            require(len(units)==len(correct)==len(reads)==512,'sample inventory')
            require(all(type(v)is int for values in (units,correct,reads) for v in values),'integer samples')
            require(all(0<=v<=r for v in correct) and all(0<=v<=b for v in reads),'sample budget/output range')
            require(all(u==25*c-4*x for u,c,x in zip(units,correct,reads)),'exact sample rewards')
            if label=='STOP':require(all(v==0 for v in reads),'STOP tail cannot READ')
            if label=='READ':require(all(v>=1 for v in reads),'root READ charged')
        require(len(br['feedback_trace_sha256'])==64,'feedback trace identity')
    def validate(row,world,fixed=False):
        episode=world['episode']
        obs={'time':0.,'x':episode['initial_x'],'refractory_remaining':0.,'content_probs':[1/cfg['classes']]*cfg['classes'],'has_read':False}
        traces={v['tick']:v for v in row['trace']};outputs={v['tick']:v for v in row['outputs']}
        access={v['arrival_tick']:v for v in row['access']}
        require(len(traces)==len(row['trace']) and len(access)==len(row['access']),'unique chronology')
        require(set(outputs)==set(cfg['deadlines']),'mandatory outputs')
        budget=cfg['budget'];pending=None;stopped=False;reads=0;all_fallback=True
        for tick in range(cfg['ticks']+1):
            if pending==tick:
                success=episode['service_uniform'][tick]<.9-.7*tick/20
                if success:
                    probs=[0.]*cfg['classes'];probs[episode['path']['content'][tick]]=1.
                    obs={'time':tick*cfg['dt'],'x':episode['path']['x'][tick],
                         'refractory_remaining':episode['path']['refractory_remaining'][tick],'content_probs':probs,'has_read':True}
                require(access[tick]=={'arrival_tick':tick,'success':success,'fee':cfg['read_cost'],'observation':obs},'actual service successor')
                if not fixed:counters['service_failures']+=not success
                pending=None
            else:require(tick not in access,'unsolicited observation')
            if tick in outputs:
                v=outputs[tick];probs=v['probabilities']
                require(v['observation']==obs and v['truth_for_scoring_only']==episode['path']['content'][tick],'output visible state/truth')
                require(all(math.isfinite(x) and x>=-1e-12 for x in probs) and abs(sum(probs)-1)<1e-9,'finite output law')
                require(v['correct']==int(max(range(len(probs)),key=probs.__getitem__)==v['truth_for_scoring_only']),'output class')
                z=obs['content_probs'][:];expected=[0.]*cfg['classes']
                for weight in v['count_probabilities']:
                    for i in range(len(z)):expected[i]+=weight*z[i]
                    z=[.15*z[i]+.55*z[(i-1)%len(z)]+.30*z[(i+1)%len(z)] for i in range(len(z))]
                require(max(abs(a-b) for a,b in zip(expected,probs))<2e-12,'count-to-content mixture')
                if not fixed:counters['outputs']+=1
            if stopped or tick==cfg['ticks']:
                require(tick not in traces,'post-STOP decision')
                continue
            v=traces[tick];action=v['action'];detail=v['detail']
            require(v['observation']==obs and action in ('STOP','WAIT','READ'),'decision information')
            if not fixed and row['controller']=='feedback_rollout':
                baseline=detail['baseline_action'];future=[d for d in cfg['deadlines'] if d>tick]
                require(baseline in ('STOP','WAIT','READ'),'baseline action')
                light=light_traces.get((row['condition'],row['index'],row['fit_seed'],row['family']),{}).get(tick)
                if light and light['observation']==obs and light['budget_after']==budget-(light['action']=='READ'):
                    require(baseline==light['action'],'same-state baseline policy')
                    counters['baseline_state_matches']+=1
                if 'selection' not in detail:
                    require((not future or budget<=0) and action==baseline=='STOP' and detail['fallback'],'terminal fallback')
                else:
                    counters['selection_pools']+=1
                    require(detail['pool_seeds']==world['policy_seeds'][tick] and len(set(detail['pool_seeds']))==2,'pool seeds')
                    require(detail['pool_size']==512 and detail['alpha']==p['alpha_per_test'],'fixed gate budget/alpha')
                    roots=[baseline]+[a for a in ('STOP','WAIT','READ') if a!=baseline]
                    require(detail['roots']==roots,'root order')
                    branch(detail['selection'],roots,len(future),budget)
                    means=[float(Fraction(sum(values),51200)) for values in detail['selection']['reward_units']]
                    require(means==detail['selection_means'],'exact selection means')
                    candidate=max(range(3),key=lambda i:(means[i],-i))
                    require(detail['candidate_action']==roots[candidate],'pool1 fixed candidate/ties')
                    if candidate==0:
                        require('validation' not in detail and detail['fallback'] and action==baseline,'selection fallback')
                    else:
                        counters['validation_pools']+=1
                        require('validation' in detail,'independent validation required')
                        branch(detail['validation'],[baseline,roots[candidate]],len(future),budget)
                        require(detail['selection_pool_sha256']!=detail['validation_pool_sha256'],'distinct model pool identity')
                        diffs=[b-a for a,b in zip(*detail['validation']['reward_units'])]
                        require(diffs==detail['paired_difference_units'],'paired integer differences')
                        mean=float(Fraction(sum(diffs),51200))
                        bound=Fraction(len(future),4)+Fraction(budget,25)
                        require(all(abs(Fraction(x,100))<=bound for x in diffs),'full-fee paired bound')
                        require(mean==detail['mean_difference'] and abs(detail['bound']-float(bound))<1e-15,'mean and bound')
                        radius=float(bound)*math.sqrt(2*math.log(1/p['alpha_per_test'])/512)
                        require(abs(radius-detail['radius'])<1e-15 and abs(mean-radius-detail['lcb'])<1e-15,'Hoeffding LCB')
                        require(detail['fallback']==(detail['lcb']<=0),'strict LCB gate')
                        require(action==(baseline if detail['fallback'] else roots[candidate]),'gated action')
                    if detail['fallback']:counters['fallback_decisions']+=1
                    else:counters['accepted_deviations']+=1;all_fallback=False
            if action=='READ':
                require(budget>0 and pending is None,'READ admission')
                budget-=1;pending=tick+1;reads+=1
                if not fixed:counters['READ_requests']+=1
            if action=='STOP':stopped=True
            require(v['budget_after']==budget,'budget debit')
        units=25*sum(v['correct'] for v in outputs.values())-4*reads
        require(row['summary']['reward_units']==units and row['summary']['net_reward']==units/100,'actual integer reward')
        require(row['summary']['reads']==reads and row['summary']['read_fees']==reads*cfg['read_cost'],'actual fees')
        return Fraction(units,100),all_fallback
    with gzip.open(run/'runs.jsonl.gz','rt') as stream:
        for row in map(json.loads,stream):
            key=(row['condition'],row['index'],row['fit_seed'],row['family'],row['controller'])
            require(key not in records,'unique run')
            world=worlds[key[:2]]
            reward,all_fallback=validate(row,world)
            records[key]=reward;counters['main_runs']+=1
            policykey=key[:4]
            if row['controller']=='lightweight':
                light_traces[policykey]={v['tick']:v for v in row['trace']}
                fallback_by_run[policykey]=row
            else:
                fixed=row['fixed_action_replay'];fixed_reward,_=validate(fixed,world,True)
                require(fixed['outputs']==row['outputs'] and fixed['access']==row['access'],'fixed actual successors')
                require([(v['tick'],v['action']) for v in fixed['trace']]==[(v['tick'],v['action']) for v in row['trace']],'fixed actual actions')
                require(fixed_reward==reward,'fixed exact reward')
                counters['fixed_runs']+=1
                if all_fallback:
                    light=fallback_by_run[policykey]
                    require(row['outputs']==light['outputs'] and row['access']==light['access'],'all-fallback actual outputs')
                    require([(v['tick'],v['action']) for v in row['trace']]==[(v['tick'],v['action']) for v in light['trace']],'all-fallback light actions')
    require(counters['main_runs']==complete['main_runs']==264 and counters['fixed_runs']==complete['fixed_runs']==132,'complete run inventory')
    require(counters['validation_pools']<=p['maximum_validation_tests'],'campaign test cap')
    stats={}
    for c in p['conditions']:
        effects={k:[] for k in ('A','B','C','D','feedback-light_primary_ordinary','feedback-light_analytic','feedback-light_gru','feedback-light_ssm','D-B','interaction')}
        for wi in range(6):
            def reward(fs,family,controller):return records[(c,wi,str(fs),family,controller)]
            def ordinary(controller,family=None):return sum(reward(fs,family or freeze['old_ordinary_selections'][str(fs)],controller) for fs in p['ordinary_fits'])/5
            a,b=ordinary('lightweight'),ordinary('feedback_rollout')
            c0,d=reward(91103,'analytic','lightweight'),reward(91103,'analytic','feedback_rollout')
            values={'A':a,'B':b,'C':c0,'D':d,'feedback-light_primary_ordinary':b-a,'feedback-light_analytic':d-c0,'D-B':d-b,'interaction':(d-c0)-(b-a)}
            for family in p['ordinary_families']:values['feedback-light_'+family]=ordinary('feedback_rollout',family)-ordinary('lightweight',family)
            for name,value in values.items():effects[name].append(value)
        stats[c]={k:estimate(v) for k,v in effects.items()}
    result={'status':'passed','checks':checks,'counters':counters,'statistics':stats,
            'realized_alpha_spending_descriptive':counters['validation_pools']*p['alpha_per_test'],
            'guaranteed_familywise_delta_model_only':p['delta_campaign_model_only'],
            'scope':'independent record/fee/successor and gate integer arithmetic; simulated branches not all neural-forward replayed',
            'limits':['model-local fixed-prefix bound; no true-world or whole-task improvement guarantee',
                      '6 independent worlds/condition; historical fits averaged within world',
                      'fallback equality is policy preservation, not positive gain or economic adoption']}
    with out.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'status':'passed','checks':checks,'counters':counters}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();audit(args.run,args.out)
