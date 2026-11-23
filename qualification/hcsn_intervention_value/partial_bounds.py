"""Original 24-window instrument-policy partial identification. Reads sealed confirmations only."""
import argparse
from collections import Counter
from functools import lru_cache
import json
import math
from pathlib import Path

import numpy as np

PRICE=.30; RATE=.40; RHO=.20; DT=.48
TOL=1e-12
SEEDS=(181391,284729,395201)
ARMS=[('plain','keep')]+[(m,o) for m in ('context','fixed','learned','qvi','external') for o in ('keep','bp')]
PASS='guaranteed_pass'; FAIL='guaranteed_fail'; UNKNOWN='undetermined'


def load(p): return json.loads(p.read_text())


@lru_cache(None)
def utility(t,a,hit):
    elapsed=t*DT
    return math.exp(-RHO*elapsed)*(hit-PRICE*a)+RATE*math.expm1(-RHO*elapsed)/RHO


L=utility(5,1,0)


def interval(x): return [min(x),max(x)]


def gate(r,c,strict=False):
    ok=(lambda x:x>c) if strict else (lambda x:x>=c)
    return PASS if ok(r[0]) else FAIL if not ok(r[1]) else UNKNOWN


def conjunction(states):
    return FAIL if FAIL in states else PASS if all(s==PASS for s in states) else UNKNOWN


def source_mean(rows,groups):
    by={g:[sum(rows[k][j] for k in rows if groups[k]==g)/4 for j in (0,1)] for g in sorted(set(groups.values()))}
    if set(rows)!=set(groups): raise ValueError('original target roster changed')
    return dict(macro=[sum(x[j] for x in by.values())/6 for j in (0,1)],per_source=by,
                worst=[min(x[j] for x in by.values()) for j in (0,1)])


def sign_support(by):
    n=len(by); certain=sum(x[0]>TOL for x in by.values()); possible=sum(x[1]>TOL for x in by.values())
    def tail(nwin): return sum(math.comb(n,k) for k in range(nwin,n+1))/2**n
    p=[tail(possible),tail(certain)]
    return dict(positive_sources=[certain,possible],sign_p=p,
                p_at_most_025=PASS if p[1]<=.025+TOL else FAIL if p[0]>.025+TOL else UNKNOWN)


def legal(availability,variant):
    actions=(0,) if availability=='noread' or variant in ('disable_read','immediate_free') else (0,1)
    if variant=='immediate_paid':
        if availability!='read': raise ValueError('paid control unavailable')
        actions=(1,)
    periods=(0,) if variant.startswith('immediate_') else range(6)
    return [(t,a) for t in periods for a in actions]


def entry_states(availability,variant,known,prefixes,observed_hits):
    options=legal(availability,variant)
    if known is not None:
        if not isinstance(known,dict) or not known: raise ValueError('empty known-policy evidence')
        if 'waited_prefixes' in known:
            n=known['waited_prefixes']
            if type(n)!=int or not 0<=n<=min(5,prefixes): raise ValueError('uncertified wait')
            options=[(t,a) for t,a in options if t>=n]
        if 'exit_prefix' in known:
            t,a=known['exit_prefix'],known['terminal_action']
            pure_paid=(availability=='read' and variant=='immediate_paid' and t==0 and a==1 and 'hit' in known)
            if type(t)!=int or type(a)!=int or (not 0<=t<prefixes and not pure_paid) or (t,a) not in options:
                raise ValueError('uncertified terminal choice')
            options=[(t,a)]
        elif any(k in known for k in ('hit','utility','terminal_action')): raise ValueError('payoff without certified exit')
    values=[(t,a,h,utility(t,a,h)) for t,a in options for h in (0,1)
            if observed_hits.get((t,a),h)==h]
    if not values: raise ValueError('no admissible completion of partial trace')
    return values


def paired_missing(xs,ys,relation):
    resulting=[]
    for t,a,h,u in xs:
        for s,b,j,v in ys:
            if (t,a)==(s,b) and h!=j: continue
            if relation=='identical' and (t,a)!=(s,b): continue
            if relation=='mask_read' and ((a==0 and (s,b)!=(t,0)) or (a==1 and s<t)): continue
            if relation=='same_immediate' and t==0 and (s,b)!=(0,a): continue
            resulting.append(u-v)
    if not resulting: raise ValueError('incompatible partial records for related policies')
    return interval(resulting)


def canonical_groups(rows):
    ids=[str(r['query_id']) for r in rows]; groups={str(r['query_id']):str(r['group']) for r in rows}
    if len(ids)!=24 or set(Counter(groups.values()).values())!={4} or len(groups)!=24 or len(set(groups.values()))!=6:
        raise ValueError('primary original TEST roster must contain six groups of four unique query windows')
    if any(r.get('split','test')!='test' for r in rows): raise ValueError('mixed roster')
    return groups


def normalize_known(known,fits):
    partial={}
    for q,arms in known.get('partial',{}).items():
        partial[q]={}
        for arm,variants in arms.items():
            fixed={}
            for k,v in variants.items():
                key=fits[arm]['immediate_choice'] if k=='dev_immediate' else k
                if key in fixed and fixed[key]!=v: raise ValueError('source certificate disagrees with DEV-selected immediate')
                fixed[key]=v
            partial[q][arm]=fixed
    return {**known,'partial':partial}


def known_hits(known,missing,arms):
    prefix=known.get('observed_prefixes',{}); partial=known.get('partial',{})
    if set(partial)-missing or set(prefix)-missing: raise ValueError('early records must be missing TEST windows only')
    shared={q:{} for q in missing}
    # The pure camera output remains observed at all six dates, independent of
    # whether the unobservable free controller would actually purchase it.
    for q,frontend in known.get('partial_frontend',{}).items():
        if q not in missing: raise ValueError('unexpected partial frontend query')
        label=frontend['target']
        if label not in (0,1): raise ValueError('bad partial class')
        for a,field in enumerate(('free_probability','paid_probability')):
            prob=np.asarray(frontend[field],dtype=float)
            if prob.size==0: prob=prob.reshape(0,2)
            if (prob.ndim!=2 or prob.shape[1]!=2 or len(prob)>6 or (a==0 and len(prob)!=prefix[q])
                    or not np.isfinite(prob).all() or np.any((prob<0)|(prob>1)) or not np.allclose(prob.sum(1),1.,atol=1e-8,rtol=0)):
                raise ValueError('invalid independently observed partial frontend probabilities')
            for t,guess in enumerate(prob.argmax(1)): shared[q][t,a]=int(guess==label)
    for q,ev in known.get('always_paid',{}).items():
        if q not in shared or ev.get('hit') not in (0,1) or (ev.get('exit_prefix'),ev.get('terminal_action'))!=(0,1):
            raise ValueError('invalid pure-camera hard control')
        h=ev['hit']
        if shared[q].get((0,1),h)!=h or not math.isclose(ev['utility'],utility(0,1,h),abs_tol=1e-10): raise ValueError('camera receipt conflict')
        shared[q][0,1]=int(h)
    for q,details in partial.items():
        if q not in prefix or type(prefix[q])!=int or not 0<=prefix[q]<=5: raise ValueError('unknown admissible prefix count')
        for arm,variants in details.items():
            if arm not in arms: raise ValueError('unknown frozen arm '+arm)
            for kind,ev in variants.items():
                if kind not in ('chosen','keep','disable_read','immediate_free','immediate_paid','immediate_conditional'):
                    raise ValueError('unknown early evidence channel '+kind)
                if not set(ev)<= {'exit_prefix','terminal_action','hit','utility','waited_prefixes'}: raise ValueError('unknown early evidence field')
                entry_states(arm.split('-')[0],kind,ev,prefix[q],{})
                if 'hit' in ev:
                    h=ev['hit']; t,a=ev['exit_prefix'],ev['terminal_action']
                    if h not in (0,1) or not math.isclose(ev.get('utility',utility(t,a,h)),utility(t,a,h),rel_tol=0,abs_tol=1e-10): raise ValueError('invalid certified payoff')
                    if shared[q].get((t,a),h)!=h: raise ValueError('shared terminal observations conflict')
                    shared[q][t,a]=int(h)
                elif 'utility' in ev: raise ValueError('supply hit with known utility')
    return shared


def trace(row,kind):
    return row['immediate_controls'][kind] if kind.startswith('immediate_') else row[kind]


def bind_observed(r,s):
    n=len(r['query_id']); t=np.asarray(r['exit_prefix']); a=np.asarray(r['terminal_action']); h=np.asarray(r['episode_hit']); u=np.asarray(r['episode_utility'])
    if any(v.shape!=(n,) for v in (t,a,h,u)) or t.dtype.kind not in 'iu' or a.dtype.kind not in 'iu' or not (np.isin(t,np.arange(6)).all() and np.isin(a,[0,1]).all() and np.isin(h,[0,1]).all()):
        raise ValueError('bad complete episode traces')
    physical=np.array([utility(int(i),int(j),int(k)) for i,j,k in zip(t,a,h)])
    if not np.allclose(physical,u,rtol=0,atol=1e-10): raise ValueError('complete utilities violate task law')
    if s is not None:
        i=np.arange(n); truth=np.where(a==1,s['read_scores'][i,t].argmax(1),s['scores'][i,t].argmax(1))==s['target']
        if not np.array_equal(truth,h): raise ValueError('complete payoff mismatched canonical paired observation')
    return {key:(int(ti),int(ai),int(hi),float(ui)) for key,ti,ai,hi,ui in zip(r['query_id'],t,a,h,u)}


def bounds(groups,observed,missing,known,shared,arm,kind):
    slots={}; a=arm.split('-')[0]
    for q in groups:
        if q in missing:
            ev=known.get('partial',{}).get(q,{}).get(arm,{}).get(kind)
            slots[q]=entry_states(a,kind,ev,known.get('observed_prefixes',{}).get(q,0),shared[q])
        else: slots[q]=[observed[q]]
    return slots


def absolute(slots,groups):
    stats={}
    for key,fn in [('utility',lambda s:s[3]),('r1',lambda s:s[2])]:
        stats[key]=source_mean({q:interval([fn(v) for v in states]) for q,states in slots.items()},groups)
    for key,fn in [('reads',lambda v:v[1]),('waiting_queries',lambda v:int(v[0]>0))]:
        counts=[interval([fn(v) for v in st]) for st in slots.values()]
        stats[key]=[sum(c[i] for c in counts) for i in (0,1)]
    return stats


def paired(left,right,groups,relation=None):
    r=source_mean({q:paired_missing(left[q],right[q],relation) for q in groups},groups)
    r['source_support']=sign_support(r['per_source']); return r


def assess(full,noread,instant,keep,masked,groups,*,identity=False,conditional=False):
    a=absolute(full,groups); nr=paired(full,noread,groups); fast=paired(full,instant,groups,'same_immediate' if conditional else None)
    retention=paired(full,keep,groups,'identical' if identity else None); ablated=paired(full,masked,groups,'mask_read')
    u=gate(a['utility']['macro'],.60-TOL); r=gate(a['r1']['macro'],.70-TOL); safety=gate(retention['worst'],-.05-TOL)
    paid=gate(nr['macro'],TOL,True); timed=gate(fast['macro'],TOL,True)
    bought=gate(a['reads'],1); waited=gate(a['waiting_queries'],1); abs_status=conjunction([u,r,safety]); positive=conjunction([paid,timed,bought,waited])
    supported=conjunction([positive,nr['source_support']['p_at_most_025'],fast['source_support']['p_at_most_025']]); joint=conjunction([abs_status,supported])
    return dict(absolute=a,paired={'trained_dynamic_noread':nr,'dev_locked_immediate':fast,'matched_keep':retention,'same_scores_disable_read':ablated},
       gates=dict(utility_at_least_060=u,r1_at_least_070=r,worst_keep_delta_at_least_minus005=safety,
                  absolute=abs_status,paid_gain=paid,timing_gain_vs_immediate=timed,any_reads=bought,any_waits=waited,
                  positive_paid_timing=positive,supported_paid_timing=supported,joint=joint))


def calculate(groups,outcomes,fits,known,valid_data=None):
    ids=next(iter(outcomes.values()))['query_id']; missing=set(groups)-set(ids)
    if len(set(ids))!=len(ids) or set(ids)-set(groups) or not missing: raise ValueError('expected incomplete subset of original roster')
    known=normalize_known(known,fits)
    prefixes=known.get('observed_prefixes',{}); shared=known_hits(known,missing,set(outcomes)); by_arm={}
    for key,row in outcomes.items():
        if row['query_id']!=ids or [groups[q] for q in ids]!=row['group']: raise ValueError('complete row allocation changed')
    @lru_cache(None)
    def states(arm,kind):
        row=outcomes[arm]; trace_=trace(row,kind); tr={**trace_,'query_id':ids}
        return bounds(groups,bind_observed(tr,valid_data),missing,known,shared,arm,kind)
    for mode,method in ARMS:
        for seed in SEEDS:
            arm=f'read-{mode}-{method}-{seed}'; narm=f'noread-{mode}-{method}-{seed}'; choice=fits[arm]['immediate_choice']
            if choice!=outcomes[arm]['immediate_choice']: raise ValueError('changed strongest immediate DEV lock')
            same=fits[arm]['head']==fits[arm]['keep_head'] and fits[arm]['theta']==fits[arm]['keep_theta']
            result=assess(states(arm,'chosen'),states(narm,'chosen'),states(arm,choice),states(arm,'keep'),states(arm,'disable_read'),groups,
                          identity=same,conditional=choice=='immediate_conditional')
            result['dev_locked_immediate']=choice; result['exactly_same_as_keep']=same
            result['comparator_absolute']={'trained_dynamic_noread':absolute(states(narm,'chosen'),groups),'dev_locked_immediate':absolute(states(arm,choice),groups),'matched_keep':absolute(states(arm,'keep'),groups)}
            by_arm[arm]=result
    family={}
    for mode,method in ARMS:
        rows=[by_arm[f'read-{mode}-{method}-{s}'] for s in SEEDS]; first=rows[0]
        statuses={k:conjunction([r['gates'][k] for r in rows]) for k in first['gates']}
        avg=lambda intervals:[sum(a[j] for a in intervals)/len(intervals) for j in (0,1)]
        family[f'{mode}-{method}']=dict(all_three_seed_gates=statuses,
            mean_seed_utility=avg([r['absolute']['utility']['macro'] for r in rows]),mean_seed_r1=avg([r['absolute']['r1']['macro'] for r in rows]),
            mean_seed_deltas={k:avg([r['paired'][k]['macro'] for r in rows]) for k in first['paired']},
            worst_source_across_seeds=[min(r['paired']['matched_keep']['worst'][j] for r in rows) for j in (0,1)])
    return dict(original_queries=24,complete_queries=len(ids),missing=sorted(missing),counts_per_group=dict(Counter(groups.values())),
                observed_prefixes=prefixes,known_terminal_rewards={q:len(v) for q,v in shared.items()},
                unconditioned_absolute_utility_support=[L,1.],unconditioned_r1_support=[0,1],unconditioned_paired_support=[L-1.,1.-L],
                families=family,read_arms=by_arm)


def table_calculation(groups,valid_data,registered,known):
    ids=valid_data['query_id'].astype(str).tolist(); missing=set(groups)-set(ids)
    table=registered['policy']; lock=table['immediate_baseline']; mapping={'full':('read-table','chosen'),
        'refit_no_read':('noread-table','chosen'),'mask_read':('read-table','disable_read'),
        'always_stop':('read-table','immediate_free'),'always_read':('read-table','immediate_paid'),
        'immediate':('read-table','immediate_conditional')}
    if 'table_dev_immediate' in known and known['table_dev_immediate']!=lock: raise ValueError('table DEV immediate disagrees')
    partial={}
    for q,tables in known.get('table',{}).items():
        arms={}; partial[q]=arms
        for k,v in tables.items():
            arm,kind=mapping[k]; arms.setdefault(arm,{})[kind]=v
    table_known={**known,'partial':partial}; shared=known_hits(table_known,missing,{'read-table','noread-table'}); slots={}
    for key,(arm,kind) in mapping.items():
        tr=table['policies'][key]
        if tr['query_ids']!=ids: raise ValueError('table rows changed')
        obs=bind_observed({**tr,'query_id':ids},valid_data)
        slots[key]=bounds(groups,obs,missing,table_known,shared,arm,kind)
    abs_values={k:absolute(v,groups) for k,v in slots.items()}
    comp={k:paired(slots['full'],slots[k],groups,'same_immediate' if k=='immediate' else 'mask_read' if k=='mask_read' else None) for k in slots if k!='full'}
    paid=gate(comp['refit_no_read']['macro'],TOL,True); timed=gate(comp[lock]['macro'],TOL,True)
    active=conjunction([paid,timed,gate(abs_values['full']['reads'],1),gate(abs_values['full']['waiting_queries'],1)])
    return dict(absolute=abs_values,paired=comp,dev_locked_immediate=lock,gates={
        'utility_at_least_060':gate(abs_values['full']['utility']['macro'],.60-TOL),
        'r1_at_least_070':gate(abs_values['full']['r1']['macro'],.70-TOL),
        'paid_gain':paid,'timing_gain_vs_immediate':timed,'positive_paid_timing':active,
        'supported_paid_timing':conjunction([active,comp['refit_no_read']['source_support']['p_at_most_025'],comp[lock]['source_support']['p_at_most_025']])})


def main():
    from .run import check_test_receipt,sha
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('roster',type=Path); parser.add_argument('data',type=Path); parser.add_argument('evidence',type=Path)
    parser.add_argument('--known',type=Path); parser.add_argument('--output',type=Path); arg=parser.parse_args()
    rows=load(arg.roster); groups=canonical_groups(rows); seal=check_test_receipt(arg.data,arg.evidence); ready=sha(arg.data/'test.npz')
    if not (arg.evidence/'summary.json').is_file(): raise ValueError('all registered confirmation outcomes required')
    with np.load(arg.data/'test.npz',allow_pickle=False) as z: data={k:z[k] for k in ('query_id','scores','read_scores','dt','target')}
    if set(groups)-set(data['query_id'].astype(str))!={'commons-112833470-w01','commons-31045040-w04'} or len(data['query_id'])!=22:
        raise ValueError('unexpected complete-query roster for the original instrument workload')
    if not np.allclose(data['dt'],DT,rtol=0,atol=1e-12): raise ValueError('physical clock changed')
    outcomes={}; fits={}
    for name in [f'{v}-{m}-{o}-{s}' for v in ('read','noread') for m,o in ARMS for s in SEEDS]:
        path=arg.evidence/'fit'/(name+'.json'); fits[name]=load(path); r=load(arg.evidence/'confirm'/(name+'.json'))
        if (r['task_resources']!={'test_sha':ready,'sealed_fit_sha':sha(path),'selection_seal_sha':seal} or r['query_id']!=data['query_id'].astype(str).tolist()): raise ValueError('confirmation resource mismatch')
        outcomes[name]=r
    registered=load(arg.data/'heldout_controls.json')
    baseline=calculate(groups,outcomes,fits,{},data)
    baseline['registered_table']=table_calculation(groups,data,registered,{})
    result=dict(original_roster_sha=sha(arg.roster),observed_archive_sha=ready,selection_seal_sha=seal,without_early_exit_audit=baseline,
       scope='Original six equally weighted groups and original four queries per group. Unknown utility/hit/paired differences are bounded for the target that would have been measured with a complete recording. No assumptions about why the audio is missing. Group sign ranges describe the registered rule; they do not by themselves establish population generalization.',
       tightening='Dynamic noREAD cannot buy. Locked immediate rules act at prefix zero and immediate_paid always incurs the fee. Identical sealed head and edit imply identical policy to its own KEEP. Masking READ preserves a STOP trajectory and cannot stop earlier than the first full-policy purchase. Equal terminal time and action share the same binary retrieval outcome. The hard immediate-purchase baseline can be identified at prefix zero from independently verified pure-video scores even where free audio is absent. Optional early observations constrain only externally certified prefixes; observed rewards at identical (query,time,action) can be shared across policies.',
       limitations='Conjunctive and family gates use marginal outer bounds. Undetermined permits either verdict under these bounds; it need not prove both joint completions are feasible given shared model parameters or data. No distributional imputation or source independence assumption is needed for the deterministic finite-roster intervals.')
    if arg.known:
        known=load(arg.known)
        if known['ready_hash']!=ready or known['selection_seal']!=seal: raise ValueError('partial-prefix evidence not bound to complete evaluation')
        if known.get('partial_frontend') and load(arg.data/'frontend_seal.json')['selected']!='imagenet_visual':
            raise ValueError('all-date camera payoffs require a pure-vision selected frontend')
        result['early_evidence_sha']=sha(arg.known);result['with_certified_prefixes']=calculate(groups,outcomes,fits,known,data)
        result['with_certified_prefixes']['registered_table']=table_calculation(groups,data,registered,known)
    payload=json.dumps(result,allow_nan=False,separators=(',',':'))+'\n'
    if arg.output:
        with arg.output.open('x') as handle: handle.write(payload)
    else: print(payload,end='')


if __name__=='__main__': main()
