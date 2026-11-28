"""Recount per-photo evidence, source-selected time budgets and group-paired uncertainty."""
import argparse
from pathlib import Path

import numpy as np

from confirmation import ARMS,CLOCK,GALLERIES,MODES,read,sha,write
from report import contrast


def elapsed(ledger):
    return sum(ledger[k] for k in ('train_wall_s','validation_cumulative_s','startup_cumulative_s','checkpoint_cumulative_s'))


def run(work):
    doc=read(work/'seal.json');prep=doc['data']['elapsed_s'];early=read(work/'early-clock-brackets.json')
    chosen={g:{a:{} for a in (*ARMS,'linear')} for g in GALLERIES}
    seed_metrics={g:{} for g in GALLERIES};groups={};records={}
    candidates=[{'arm':'linear','seed':0,'events':[{'step':0}],'by_clock':{'linear':0},'selected':0}]+doc['models']
    def name(arm,seed,step):return f'{arm}-{seed}-{step}'
    for trial in candidates:
        arm,seed=trial['arm'],trial['seed']
        for event in trial['events']:
            step=event['step'];key=name(arm,seed,step);path=work/'cold'/key;desc=read(path.with_suffix('.json'))
            assert sha(path.with_suffix('.npz'))==desc['sha256']
            cold=read(path.with_suffix('.process.json'))['wall_s']
            r=dict(arm=arm,seed=seed,step=step,cold_process_s=cold,galleries={})
            if arm!='linear':r['endpoint']=event
            with np.load(path.with_suffix('.npz')) as z:
                for g in GALLERIES:
                    group=z[g+'_group'];im=z[g+'_id']
                    if g not in groups:groups[g]=(group,im)
                    assert np.array_equal(group,groups[g][0]) and np.array_equal(im,groups[g][1])
                    modes={s:z[g+'_'+s] for s in MODES}
                    sc=float(modes['pair'][:,:,0].mean(dtype=np.float64))
                    r['galleries'][g]={'concordance':sc,'shuffle':float(modes['shuffle'][:,:,0].mean(dtype=np.float64))}
                    if step!=trial['selected']:continue
                    micro={s:float(arr[:,:,0].mean(dtype=np.float64)) for s,arr in modes.items()}
                    micro.update(i2t=modes['pair'][:,0,:].mean(0,dtype=np.float64).tolist(),t2i=modes['pair'][:,1,:].mean(0,dtype=np.float64).tolist(),lexical_hard=z[g+'_hard'].mean((0,1),dtype=np.float64).tolist())
                    chosen[g][arm][seed]=(modes['pair'][:,:,0].mean(1,dtype=np.float64),z[g+'_hard'][:,:,0].mean(1,dtype=np.float64))
                    seed_metrics[g].setdefault(arm,{})[str(seed)]=micro
            records[key]=r
    compare={}
    for g in GALLERIES:
        means={a:np.stack(list(x.values())).mean(0) for a,x in chosen[g].items()}
        compare[g]={'primary':{a:float(x[0].mean()) for a,x in means.items()},'lexical_hard':{a:float(x[1].mean()) for a,x in means.items()},
                    'paired_primary':{a:contrast(means['literal'][0],means[a][0],groups[g][0]) for a in (*ARMS[1:],'linear')},
                    'paired_hard':{a:contrast(means['literal'][1],means[a][1],groups[g][0]) for a in (*ARMS[1:],'linear')},
                    'n':len(groups[g][0]),'caption_groups':len(np.unique(groups[g][0]))}
    primary=compare['sydney'];specific=all(primary['paired_primary'][a]['caption_cluster_ci95'][0]>0 for a in ('smooth','sdpa')) and all(abs(v['shuffle']-.5)<=.05 for v in seed_metrics['sydney']['literal'].values())
    joint={};budget_rows={};updates={};d=doc['linear']
    for arm in (*ARMS,'linear'):
        ts=[x for x in candidates if x['arm']==arm];calls={}
        for key in (('linear',) if arm=='linear' else tuple(str(b) for b in CLOCK)):
            family=[]
            for t in ts:
                step=t['by_clock'][key];rec=records[name(arm,t['seed'],step)]
                if arm=='linear':cost=d['wall_s'];fitcpu=d['cpu_s'];bounds=[cost,cost]
                else:
                    edge=next(e for e in t['events'] if int(key) in e['budgets'])
                    cost=elapsed(edge);fitcpu=edge['train_cpu_s']
                    initial=early.get(f"{arm}-{t['seed']}",{})
                    child=edge.get('process_startup_to_event_plus_previous_calls_s',0.)
                    bounds=[child+initial.get(k,0.) for k in ('observed_lower_s','observed_upper_s')]
                    assert bounds[1]>0
                family.append(dict(seed=t['seed'],selected_step=step,source_selection_wall_components_s=cost,train_cpu_s=fitcpu,cold_wall_s=rec['cold_process_s'],
                                   worker_span_bracket_s=bounds,prepared_worker_and_cold_wall_bracket_s=[prep+b+rec['cold_process_s'] for b in bounds],cached_measured_wall_s=cost+rec['cold_process_s'],prepared_measured_wall_s=prep+cost+rec['cold_process_s'],scores=rec['galleries']))
            calls[key]=family
        budget_rows[arm]=calls
        for threshold in (.60,.65,.70):
            joint.setdefault(arm,{})[str(threshold)]=next((k for k,rows in calls.items() if all(row['scores'][g]['concordance']>=threshold and abs(row['scores'][g]['shuffle']-.5)<=.05 for row in rows for g in ('rs_test','nw_test','sydney'))),None)
        if arm!='linear':
            common=sorted(set.intersection(*[{e['step'] for e in t['events'] if e['update_endpoint']} for t in ts]))
            updates[arm]={str(s):[{'seed':t['seed'],'scores':records[name(arm,t['seed'],s)]['galleries'],'endpoint':records[name(arm,t['seed'],s)]['endpoint']} for t in ts] for s in common}
    receipt={'seal_sha256':sha(work/'seal.json'),'metrics_fields':['concordance','exact R@1 with random tie-breaking','same-caption R@1','positive minus mean negative cosine'],
             'uncertainty':'Fixed-gallery paired bootstrap over normalized caption groups, conditional on these seeds and negatives. The three independently trained seed scores are also supplied.',
             'timing':'Per budget includes selection through its terminal candidate (including validation), one cold four-gallery candidate process and optional shared preparation. Source extraction/download before reuse, Python import time for training workers, some restart-snapshot I/O and OS wait outside training/validation are excluded from component totals. Independent worker-span brackets include interpreter startup, all previous worker spans and selection; four earliest workers use adjacent durable filesystem timestamp brackets. The active final training child is timed through publication of its selected event, before final process teardown. The linear row uses its measured solver process body. Raw corpora already resident are inputs. Online data transfer time is not included. Do not report a complete device-independent end-to-end latency advantage from component sums.',
             'specific_sydney_pass':specific,'summary':compare,'seeds':seed_metrics,'quality_gate_first_source_selected_budget':joint,'time_budgets':budget_rows,'equal_update_states':updates,'all_raw_checkpoints':records}
    write(work/'results.json',receipt)
    print({k:v['primary'] for k,v in compare.items()},joint,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);run(p.parse_args().work)
