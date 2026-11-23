"""Compare sealed policy families and score conditional opportunities on the reached path."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from .run import ARMS, AVAIL, SEEDS, cases, check_test_receipt, sha

TOL = 1e-12


def load(path):
    return json.loads(path.read_text())


def spread(x):
    return {'mean':float(np.mean(x)),'min':float(min(x)),'max':float(max(x))}


def direction(d):
    n=len(d); k=int(sum(v>TOL for v in d)); ties=int(sum(abs(v)<=TOL for v in d))
    return dict(groups=n,positive=k,negative=n-k-ties,ties=ties,
        sign_p=sum(math.comb(n,j) for j in range(k,n+1))/2**n)


def paired(left,right):
    """Collapse seed variation inside each creator/master before descriptive source support."""
    groups=sorted(left[0]['per_source']); output={}
    for key in ('per_source','per_source_r1'):
        if any(sorted(r[key])!=groups for r in left+right): raise ValueError('unpaired source identities')
        delta=np.array([[a[key][g]-b[key][g] for g in groups] for a,b in zip(left,right)])
        avg=delta.mean(0); output[key]=dict(zip(groups,avg.tolist()))
        output['utility_delta' if key=='per_source' else 'r1_delta']=spread(delta.mean(1))
        if key=='per_source':
            output.update(source_support=direction(avg),source_support_per_seed=[direction(d) for d in delta],
                          minimum_across_groups_and_seeds=float(delta.min()),minimum_group_each_seed=delta.min(1).tolist())
    return output


def confusion(action,opportunity,mask):
    a=np.asarray(action)[mask]; y=np.asarray(opportunity)[mask]
    return np.array([np.sum(a&y),np.sum(a&~y),np.sum(~a&y),np.sum(~a&~y)],dtype=int)


def realized_opportunities(s,allow_read):
    gold=s['target'][:,None]; free=(s['scores'].argmax(-1)==gold); paid=(s['read_scores'].argmax(-1)==gold)
    t=s['dt'].cumsum(1)-s['dt'][:,:1]; disc=np.exp(-.2*t); cost=2*np.expm1(-.2*t)
    uf=disc*free+cost; uv=disc*(paid.astype(float)-.3)+cost
    legal=np.maximum(uf,uv) if allow_read else uf
    # Strict positive-cost improvement over best current exit by some later legal exit,
    # measured in common time-zero dollars. Final-prefix WAIT is not a decision.
    wait=np.stack([legal[:,i+1:].max(1)-legal[:,i]>TOL for i in range(5)],1)
    return wait,(uv-uf>TOL),free,paid


def timing(s,result,opportunities):
    y_wait,y_read,free,paid=opportunities; end=np.array(result['exit_prefix']); read=np.array(result['terminal_action'])==1
    i=np.arange(len(end)); steps=np.arange(5)[None,:]; reached=steps<=end[:,None]; waits=steps<end[:,None]
    wait_all=confusion(waits,y_wait,reached)
    per_t=[confusion(waits[:,t],y_wait[:,t],reached[:,t]) for t in range(5)]
    acquired=confusion(read,y_read[i,end],np.ones(len(end),dtype=bool))
    current_free,current_paid=free[i,end],paid[i,end]
    use_current=dict(corrected=int(np.sum(read&(~current_free)&current_paid)),broken=int(np.sum(read&current_free&(~current_paid))),
                     both_correct=int(np.sum(read&current_free&current_paid)),both_wrong=int(np.sum(read&(~current_free)&(~current_paid))))
    return dict(wait_at_reached_decisions=wait_all.tolist(),wait_by_prefix=[v.tolist() for v in per_t],
                read_at_chosen_exit=acquired.tolist(),purchased_outcomes=use_current)


def mean_confusion(run):
    summary={}
    for k in ('wait_at_reached_decisions','read_at_chosen_exit','wait_by_prefix'):
        summary[k]=np.mean(np.asarray([r[k] for r in run]),axis=0).tolist()
    summary['purchased_outcomes']={k:float(np.mean([r['purchased_outcomes'][k] for r in run])) for k in run[0]['purchased_outcomes']}
    return summary


def report(data,evidence):
    paths={name:evidence/'confirm'/name for name in cases()}
    if set(p.name for p in (evidence/'confirm').glob('*.json'))!=set(paths): raise ValueError('complete 66-arm confirmations required')
    final=load(evidence/'summary.json'); seal=check_test_receipt(data,evidence)
    with np.load(data/'test.npz',allow_pickle=False) as z: s={k:z[k] for k in ('scores','read_scores','target','dt','group','source','query_id')}
    test_sha=sha(data/'test.npz'); inputs={}; fits={}; identities={k:s[k].astype(str).tolist() for k in ('query_id','group','source')}
    manifest=hashlib.sha256()
    for name,p in sorted(paths.items()):
        row=load(p); fitpath=evidence/'fit'/name; fit=load(fitpath)
        if row['task_resources']!={'test_sha':test_sha,'selection_seal_sha':seal,'sealed_fit_sha':sha(fitpath)} or any(row[k]!=v for k,v in identities.items()):
            raise ValueError('changed confirmation identity or resource '+name)
        if row['immediate_choice']!=fit['immediate_choice'] or row['key']!=name: raise ValueError('changed DEV lock or name')
        k=(row['availability'],row['mode'],row['method'],row['seed'])
        if name!='-'.join(map(str,k))+'.json' or k in inputs: raise ValueError('duplicate or inconsistent arm')
        inputs[k]=row; fits[k]=fit; manifest.update((name+' '+sha(p)+'\n').encode())
    families={a:{} for a in AVAIL}
    for avail in AVAIL:
        opportunity=realized_opportunities(s,avail=='read')
        for mode,method in ARMS:
            name=f'{mode}-{method}'; keys=[(avail,mode,method,seed) for seed in SEEDS]; rows=[inputs[k] for k in keys]; chosen=[r['chosen'] for r in rows]; records=[fits[k] for k in keys]
            refs={'fixed_keep_same_availability':[inputs[avail,'fixed','keep',seed]['chosen'] for seed in SEEDS],
                  'matched_own_keep':[r['keep'] for r in rows],
                  'dev_locked_immediate':[r['immediate_controls'][r['immediate_choice']] for r in rows]}
            if avail=='read':
                refs.update(trained_dynamic_noread=[inputs['noread',mode,method,seed]['chosen'] for seed in SEEDS],
                            same_scores_disable_read=[r['disable_read'] for r in rows])
            gates=final['families'][name] if avail=='read' else {'pass_capability':all(r['pass_capability'] for r in rows)}
            patterns=[timing(s,r,opportunity) for r in chosen]; counts={k:[r[k] for r in chosen] for k in ('reads','waiting_queries','wait_steps','read_after_wait')}
            retain=[r['selected_retain'] for r in records]; orig=[r['report']['attempts'][0]['diagnostics'][0]['retain'] for r in records]
            families[avail][name]=dict(
                macro_utility=spread([r['utility'] for r in chosen]),macro_r1=spread([r['r1'] for r in chosen]),
                utility_by_seed=[r['utility'] for r in chosen],r1_by_seed=[r['r1'] for r in chosen],
                paired={key:paired(chosen,value) for key,value in refs.items()},retain_vs_own_keep=paired(retain,orig),
                dev_locked_immediate_each_seed=[r['immediate_choice'] for r in rows],counts_each_seed=counts,
                all_three_seed_gates=gates,mean_confusion_per_seed=mean_confusion(patterns),confusion_each_seed=patterns)
    compact=[]
    for family,r in families['read'].items():
        e=r['paired']; c=r['counts_each_seed']; g=r['all_three_seed_gates']
        compact.append(dict(family=family,utility=r['macro_utility']['mean'],r1=r['macro_r1']['mean'],
            delta_vs_fixed=e['fixed_keep_same_availability']['utility_delta']['mean'],
            delta_vs_refit_noread=e['trained_dynamic_noread']['utility_delta']['mean'],
            delta_vs_masked_read=e['same_scores_disable_read']['utility_delta']['mean'],
            delta_vs_locked_immediate=e['dev_locked_immediate']['utility_delta']['mean'],
            worst_retain_vs_matched=r['retain_vs_own_keep']['minimum_across_groups_and_seeds'],
            worst_test_vs_matched=e['matched_own_keep']['minimum_across_groups_and_seeds'],
            reads_per_seed=float(np.mean(c['reads'])),waited_per_seed=float(np.mean(c['waiting_queries'])),
            capability=g['pass_capability'],paid_timing=g['positive_paid_timing'],source_supported_timing=g['supported_paid_timing']))
    return dict(selection_seal_sha=seal,confirmation_manifest_sha=manifest.hexdigest(),test_sha=test_sha,seeds=list(SEEDS),
        compact_read_families=compact,queries=len(s['target']),creator_master_groups=len(set(s['group'])),families=families,
        definitions={
          'effect':'Equal-weight creator/master means, paired on identical held queries and seed. Source tables average the three seed differences within each group. Per-seed mean/min/max refer to three macro effects, not 3 independent test sets.',
          'support':'One-sided exact group sign P, counting ties as non-wins. Seed-average support is descriptive. Registered gates use per-seed tests and the all-three-seed condition. Additional comparisons versus fixed and KEEP are descriptive.',
          'retention':'retain_vs_own_keep uses frozen RETAIN selection metrics. paired.matched_own_keep uses paired TEST performance versus the same physical/context incumbent after fitting its linear readout.',
          'confusion':'Counts [true positive,false positive,false negative,true negative] over reached decision points. WAIT compares every available later legal exit to the best immediate legal exit in hindsight. READ compares the paired paid and free scores at the chosen exit after its actual fee. These are retrospective labels, unavailable when acting. Means count one policy seed at a time; prefixes within a query are dependent.',
          'noread':'Can only WAIT or STOP. READ confusion here is descriptive missed/potential benefit had a purchase been available; retrospective WAIT compares legal free exits only.'})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('data',type=Path);p.add_argument('evidence',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args(); r=report(a.data,a.evidence)
    payload=json.dumps(r,separators=(',',':'),allow_nan=False)+'\n'
    with a.output.open('x') as h: h.write(payload)
