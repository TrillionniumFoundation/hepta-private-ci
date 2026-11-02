"""Independent audit of ordinary cores executing the analytic MPC schedule."""
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
    freeze=json.loads((run/'COMMON_ACTIONS_FREEZE.json').read_text())
    complete=json.loads((run/'COMMON_ACTIONS_COMPLETE.json').read_text())
    checks=0
    def require(condition,label):
        nonlocal checks
        checks+=1
        if not condition:raise AssertionError(label)
    require(sha(run/'common_actions.jsonl.gz')==complete['raw_sha256'],'common raw hash')
    require(sha(run/'runs.jsonl.gz')==freeze['main_runs_sha256'],'main source hash')
    require(sha(run/'worlds.jsonl.gz')==freeze['worlds_sha256'],'worlds source hash')
    source=Path(__file__).resolve().parents[1]/'common_actions.py'
    require(sha(source)==freeze['source_sha256'],'common source identity')
    with gzip.open(run/'runs.jsonl.gz','rt') as stream:
        ds={(r['condition'],r['index']):r for r in map(json.loads,stream)
            if r['family']=='analytic' and r['controller']=='feedback_rollout'}
    with gzip.open(run/'worlds.jsonl.gz','rt') as stream:
        worlds={(r['condition'],r['index']):r['episode'] for r in map(json.loads,stream)}
    rows={}
    changed_probabilities=changed_classes=0
    with gzip.open(run/'common_actions.jsonl.gz','rt') as stream:
        for row in map(json.loads,stream):
            key=(row['condition'],row['index'],row['fit_seed'],row['family'])
            require(key not in rows,'duplicate identity')
            d=ds[key[:2]];world=worlds[key[:2]]
            require(row['access']==d['access'],'actual observed successors')
            require([(v['tick'],v['action']) for v in row['trace']]==[(v['tick'],v['action']) for v in d['trace']],'common action schedule')
            require([v['observation'] for v in row['trace']]==[v['observation'] for v in d['trace']],'common decision observations')
            require([v['budget_after'] for v in row['trace']]==[v['budget_after'] for v in d['trace']],'common budget debit')
            require(row['summary']['reads']==d['summary']['reads'] and row['summary']['read_fees']==d['summary']['read_fees'],'common fees')
            require(len(row['outputs'])==4,'mandatory outputs')
            for ordinary,analytic in zip(row['outputs'],d['outputs']):
                require(ordinary['tick']==analytic['tick'] and ordinary['observation']==analytic['observation'],'common output observation')
                tick=ordinary['tick'];obs=ordinary['observation'];probs=ordinary['probabilities']
                require(ordinary['truth_for_scoring_only']==world['path']['content'][tick],'scoring-only truth')
                require(all(math.isfinite(v) and v>=-1e-12 for v in probs) and abs(sum(probs)-1)<1e-9,'finite content law')
                z=obs['content_probs'][:];expected=[0.]*len(z)
                for weight in ordinary['count_probabilities']:
                    for i in range(len(z)):expected[i]+=weight*z[i]
                    z=[.15*z[i]+.55*z[(i-1)%len(z)]+.30*z[(i+1)%len(z)] for i in range(len(z))]
                require(max(abs(a-b) for a,b in zip(expected,probs))<2e-12,'count-to-content')
                prediction=max(range(len(probs)),key=probs.__getitem__)
                require(ordinary['correct']==int(prediction==ordinary['truth_for_scoring_only']),'correctness')
                changed_probabilities+=max(abs(a-b) for a,b in zip(probs,analytic['probabilities']))>1e-12
                changed_classes+=prediction!=max(range(len(probs)),key=analytic['probabilities'].__getitem__)
            reward=Fraction(sum(v['correct'] for v in row['outputs']),4)-row['summary']['reads']*Fraction(1,25)
            d_reward=Fraction(sum(v['correct'] for v in d['outputs']),4)-d['summary']['reads']*Fraction(1,25)
            require(abs(row['summary']['net_reward']-float(reward))<1e-12,'exact reward')
            require(row['summary']['reward_units']==int(reward*100),'integer reward units')
            rows[key]=reward-d_reward
    expected={(c,i,str(s),f) for c in p['conditions'] for i in range(p['worlds_per_condition'])
              for s in p['ordinary_fits'] for f in p['ordinary_families']}
    require(set(rows)==expected,'complete common-action inventory')
    require(len(rows)==complete['ordinary_runs']==120,'complete record count')
    statistics={}
    for c in p['conditions']:
        statistics[c]={f:estimate([sum(rows[c,i,str(s),f] for s in p['ordinary_fits'])/len(p['ordinary_fits'])
                                  for i in range(p['worlds_per_condition'])]) for f in p['ordinary_families']}
    result={'status':'passed','checks':checks,'ordinary_runs':len(rows),'output_comparisons':4*len(rows),
            'all_actions_accesses_observations_and_fees_equal':True,'output_probability_changes':changed_probabilities,
            'output_class_changes':changed_classes,'ordinary_minus_analytic_on_analytic_MPC_schedule':statistics,
            'scope':'same actual actions and observation successors; independent output arithmetic; no full neural-forward replay',
            'raw_sha256':sha(run/'common_actions.jsonl.gz')}
    with out.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('ordinary_minus_analytic_on_analytic_MPC_schedule',)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();audit(args.run,args.out)
