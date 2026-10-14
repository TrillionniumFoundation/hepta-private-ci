"""Independent stdlib audit of recorded CPU FIFO arrival/batch replay evidence.

No torch, repository models, selectors, or scorers imported. Recomputes cache
misses from SOURCE frame SHA and dispatch group order. Clock evidence is still
self-reported, never an independent OS or energy attestation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

POLICIES=((1,0),(2,0),(4,0),(4,2_000_000),(4,8_000_000))
WORKLOADS=(("paired",8,2,0),("paired",8,8,0),
           ("paired",8,2,4_000_000),("paired",8,8,4_000_000),
           ("paired",16,2,12_000_000),("paired",16,8,12_000_000))
FIRST_FACTOR=1.5; IMPROVEMENT=.05

def require(test,message):
    if not test:raise ValueError(message)

def digest(raw):return hashlib.sha256(raw).hexdigest()

def read(path):
    raw=Path(path).read_bytes()
    require(len(raw)<=16*1024**2,'bounded source required')
    def pairs(vals):
        x={}
        for k,v in vals:
            require(k not in x,'duplicate JSON object key')
            x[k]=v
        return x
    return json.loads(raw,object_pairs_hook=pairs,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON value')))

def rank(vals,p):
    require(bool(vals) and all(type(x) is int and x>=0 for x in vals),'valid latency samples')
    return sorted(vals)[(p*len(vals)+99)//100-1]

def choice(all_runs):
    names=[f'{a}:{b}' for a,b in POLICIES]
    require(set(all_runs)==set(names),'registered complete timing grid')
    metrics={}
    for name in names:
        runs=all_runs[name]
        require(2<=len(runs)<=7,'bounded calibration repetitions')
        metrics[name]={k:int(statistics.median([v[k] for v in runs]))
                        for k in ('first_response_ns','latency_p95_ns','end_to_end_wall_ns')}
    base=metrics['1:0']
    good=[name for name in names[1:] if
          metrics[name]['latency_p95_ns'] <= (1-IMPROVEMENT)*base['latency_p95_ns']
          and metrics[name]['first_response_ns'] <= FIRST_FACTOR*base['first_response_ns']
          and metrics[name]['end_to_end_wall_ns'] <= 1.1*base['end_to_end_wall_ns']]
    winner=min(good,key=lambda k:(metrics[k]['latency_p95_ns'],
               metrics[k]['first_response_ns'],names.index(k))) if good else names[0]
    return winner,good,metrics


def check_run(record,expected_cases,depth,gap,policy):
    cap,wait=policy
    require(record['policy_key']==f'{cap}:{wait}' and record['depth']==depth
            and record['gap_ns']==gap,'wrong policy/depth/arrivals')
    groups=record['groups'];rows=record['records'];n=len(expected_cases)
    require(len(rows)==n and 1<=len(groups)<=n,'complete groups/rows')
    expected_ids=[c['case_id'] for c in expected_cases]
    require(record['case_ids']==expected_ids and record['arrival_offsets_ns']==[i*gap for i in range(n)],
            'fixed source-bound release schedule')
    by_id={r['case_id']:r for r in rows}
    require(len(by_id)==n and set(by_id)==set(expected_ids),'one completion per Cell')
    cache=set(); calls=0; frames=0; all_batch_sizes=[];tally=[]
    first_end=0;prior_end=0;position=0
    for index,g in enumerate(groups):
        ids=g['case_ids'];count=len(ids)
        require(1<=count<=cap and ids==expected_ids[position:position+count],
                'FIFO no dropped or reordered Cells')
        require(g['group_id']==index and g['policy_key']==record['policy_key'],
                'stable group/policy identity')
        dispatch=g['dispatch_offset_ns'];end=g['completion_offset_ns'];duration=g['service_wall_ns']
        require(all(type(z) is int and z>=0 for z in (dispatch,end,duration)), 'monotone numeric clocks')
        require(dispatch>=prior_end and end>=dispatch and duration>0 and duration<=end-dispatch,
                'nonpreemptive ordered service times')
        require(g['first_release_offset_ns']==position*gap
                and g['admission_deadline_offset_ns']==position*gap+wait,
                'admission deadline is fixed at FIRST release')
        # A ready backlog is permitted; no Cell can start before its release.
        require(dispatch >= (position+count-1)*gap,'batch contains future request')
        if count<cap and position+count<n:
            # If further requests were already released, the worker must have
            # admitted them; otherwise the fixed window has expired.
            require(dispatch < (position+count)*gap or count==cap,
                    'ready pending request omitted from batch')
            require(dispatch>=position*gap+wait,
                    'batch dispatched before admission deadline without reaching capacity')
        frame_events=g['frame_events']
        require(len(frame_events)==depth//2,'exact Reader depth event count')
        for d,event in zip(range(2,depth+1,2),frame_events):
            expected=[f['sha256'] for c in expected_cases[position:position+count]
                      for f in c['inputs']['video'][d-2:d]]
            require(event['frame_end']==d and event['requested_sha256']==expected,
                    'requested frame identities or ordering changed')
            new=set(expected)-cache
            require(event['unique_new_frames']==len(new)
                    and event['physical_forward_calls']==int(bool(new)),
                    'cache miss, physical Conv2d call or receipt forged')
            if new:
                # Each physical call contains only newly encoded frames, up to
                # the frozen bounded batch. Same SHA repeated in group is reused.
                all_batch_sizes.append(len(new))
            cache.update(new);calls+=int(bool(new));frames+=len(new)
        for j,cid in enumerate(ids):
            k=position+j;r=by_id[cid]
            require(r['depth']==depth and r['source_id']==expected_cases[k]['group']
                    and r['group_id']==index,'Cell not bound to its source/group')
            require(r['scheduled_arrival_offset_ns']==k*gap and r['dispatch_offset_ns']==dispatch
                    and r['completion_offset_ns']==end and r['response_latency_ns']==end-k*gap,
                    'per-Cell arrival/response clock forged')
            p=r['probabilities']
            require(isinstance(p,list) and len(p)==2 and all(isinstance(x,(int,float))
                    and math.isfinite(x) and 0<=x<=1 for x in p)
                    and abs(sum(p)-1)<1e-4 and r['prediction']==int(p[1]>p[0]),
                    'invalid frozen Reader output')
            tally.append(r['response_latency_ns'])
        first_end=first_end or end
        prior_end=end;position+=count
    require(position==n and [r['case_id'] for r in rows]==expected_ids,'exact output order')
    require(record['first_response_ns']==first_end
            and record['latency_p50_ns']==rank(tally,50)
            and record['latency_p95_ns']==rank(tally,95)
            and record['latency_p99_ns']==rank(tally,99),
            'response quantile or first completion forged')
    require(record['max_dispatch_lag_ns']==max(r['dispatch_offset_ns']-r['scheduled_arrival_offset_ns'] for r in rows),
            'max dispatch lag forged')
    require(record['physical_forward_calls']==calls
            and record['unique_frames']==frames==len(cache)
            and record['conv_batch_sizes']==all_batch_sizes
            and record['requested_frame_rows']==n*depth,
            'whole-run physical call/cache/row accounting forged')
    require(record['conv_forward_ns']>0 and record['preprocess_ns']>0
            and record['source_bytes']>0 and record['whole_run_wall_ns']>=prior_end,
            'incomplete physical work or reported elapsed time')
    require(record['pretrained_clip_executed'] is False and record['energy_joules'] is None,
            'unqualified model execution or fake energy')
    return {"physical_calls":calls,"unique_frames":frames}


def audit(root,output):
    root,output=Path(root),Path(output)
    manifest_bytes=(root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    protocol=read(output/'protocol.json');training=read(output/'training.json')
    calibration=read(output/'calibration.json');selection=read(output/'selection.json')
    evaluation=read(output/'evaluation.json');predictions=read(output/'holdout-predictions.json')
    report=read(output/'report.json')
    require(protocol['schema']=='hepta.video-arrival-aware-cpu-protocol.v1'
            and report['schema']=='hepta.video-arrival-aware-cpu-executed.v1'
            and selection['schema']=='hepta.video-arrival-aware-batch-choice.v1',
            'exact research-only protocol schema')
    require(protocol['policies']==[list(x) for x in POLICIES]
            and protocol['workloads'] and all(tuple(w) in WORKLOADS for w in protocol['workloads'])
            and len(set(tuple(w) for w in protocol['workloads']))==len(protocol['workloads']),
            'not preregistered policy/workload grid')
    require(protocol['warmups']==0 and report['warmup_wall_ns']==0
            and report['warmup_calls']==0 and report['warmup_frames']==0,
            'unsealed warmup runs forbidden in this protocol')
    require(report['manifest_sha256']==protocol['manifest_sha256']==digest(manifest_bytes),
            'source manifest identity')
    for field,file in [('protocol_sha256','protocol.json'),('calibration_sha256','calibration.json'),
                       ('selection_sha256','selection.json'),('evaluation_sha256','evaluation.json'),
                       ('holdout_predictions_sha256','holdout-predictions.json')]:
        require(report[field]==digest((output/file).read_bytes()),'sealed file drift: '+file)
    require(selection['protocol_sha256']==report['protocol_sha256']
            and selection['calibration_sha256']==report['calibration_sha256']
            and predictions['selection_sha256']==report['selection_sha256']
            and evaluation['selection_sha256']==report['selection_sha256']
            and evaluation['holdout_prediction_sha256']==report['holdout_predictions_sha256']
            and predictions['before_holdout_label_score'] is True,
            'decision/prediction/evaluation causal hash ordering')
    require(training['training_reader']['sha256']==report['reader_sha256']==selection['reader_sha256']
            and training['frozen_network']['sha256']==report['frozen_network_sha256']==protocol['frozen_network_sha256']
            and report['pretrained_clip_executed'] is False
            and report['production_accepted'] is False and report['energy_joules'] is None
            and selection['holdout_labels_used'] is False,
            'weights or certification changed after selection')
    dataset_bytes=(root/manifest['dataset']['path']).read_bytes()
    cohort_bytes=(root/manifest['cohort']['path']).read_bytes()
    require(digest(dataset_bytes)==manifest['dataset']['sha256']
            and digest(cohort_bytes)==manifest['cohort']['sha256'],
            'registered dataset/cohort content drift')
    cases=[json.loads(row) for row in dataset_bytes.splitlines()]
    cohort=json.loads(cohort_bytes)
    require(len(cases)==len(cohort)==80 and [r['case_id'] for r in cases]==[c['case_id'] for c in cohort],
            'full original video pair/source cohort required')
    parts={x:{'paired':[],'forward_only':[]} for x in ('train','calibration','holdout')}
    sources={x:set() for x in parts};labels={}
    for c,meta in zip(cases,cohort):
        fold=c['split'];require(fold in parts and fold==meta['split']
                and c['group']==meta['source_id'],'source/fold disjointness')
        sources[fold].add(c['group']);labels[c['case_id']]=c['label']
        parts[fold]['paired'].append(c)
        if meta['direction']=='forward':parts[fold]['forward_only'].append(c)
        else:require(meta['direction']=='reverse','original reverse pair label')
    require([len(sources[k]) for k in sources]==[6,2,2]
            and len(set.union(*sources.values()))==10
            and report['source_groups']==selection['source_groups']==training['source_groups']
            and all(sorted(v)==report['source_groups'][k] for k,v in sources.items()),
            'six/two/two original source separation')
    require(calibration['source_groups']==sorted(sources['calibration'])
            and evaluation['source_groups']==sorted(sources['holdout']),
            'calibration and holdout are different video sources')
    reqs={};scored={}
    charged_calls=charged_frames=charged_conv=charged_pre=charged_bytes=charged_wall=run_count=0
    for work in protocol['workloads']:
        profile,n,depth,gap=work;name=':'.join(str(x) for x in work)
        cal=parts['calibration'][profile][:n];test=parts['holdout'][profile][:n]
        require(len(cal)==len(test)==n,'registered exact source fold/size')
        observed={};ref=None
        for fold,fold_cases,container,iterations in (
                ('calibration',cal,calibration['measurements'],protocol['calibration_rounds']),
                ('holdout',test,evaluation['measurements'],protocol['evaluation_rounds'])):
            by_policy=container[name]
            require(set(by_policy)=={f'{a}:{b}' for a,b in POLICIES},'complete physical control grid')
            for policy in POLICIES:
                pk=f'{policy[0]}:{policy[1]}'
                rows=by_policy[pk];require(len(rows)==iterations,'all measured arms present')
                for iteration,item in enumerate(rows):
                    require(item['iteration']==iteration and item['fold']==fold
                            and item['workload']==name and item['policy_key']==pk
                            and item['batch_size']==policy[0] and item['max_wait_ns']==policy[1],
                            'experiment arm/iteration/fold changed')
                    check_run(item,fold_cases,depth,gap,policy)
                    data=[(r['case_id'],r['prediction'],r['probabilities']) for r in item['records']]
                    slot=(fold,iteration)
                    if slot not in observed:observed[slot]=data
                    else:
                        require([a[:2] for a in data]==[a[:2] for a in observed[slot]],
                                'Reader prediction changed with batch size')
                        for a,b in zip(data,observed[slot]):
                            require(max(abs(x-y) for x,y in zip(a[2],b[2]))<=2e-5,
                                    'Reader probabilities outside batch equivalence')
                    run_count+=1;charged_wall+=item['whole_run_wall_ns']
                    charged_calls+=item['physical_forward_calls']
                    charged_frames+=item['unique_frames']
                    charged_conv+=item['conv_forward_ns'];charged_pre+=item['preprocess_ns']
                    charged_bytes+=item['source_bytes']
        grid={pk:[{'first_response_ns':v['first_response_ns'],
                   'latency_p95_ns':v['latency_p95_ns'],
                   'end_to_end_wall_ns':v['whole_run_wall_ns']} for v in vals]
              for pk,vals in calibration['measurements'][name].items()}
        winner,qualified,metrics=choice(grid)
        decision=selection['by_workload'][name]
        require(decision['policy_key']==winner and decision['qualified_non_scalar']==qualified
                and decision['calibration_metrics']==metrics
                and decision['batch_size']==int(winner.split(':')[0])
                and decision['max_wait_ns']==int(winner.split(':')[1]),
                'recomputed calibration choice differs or heldout policy leak')
        pred=predictions['records'][name]
        require(pred['selected_policy_key']==winner
                and pred['case_ids']==[c['case_id'] for c in test]
                and pred['predictions']==[r[2] for r in observed[('holdout',0)]],
                'holdout prediction coverage/model selection drift')
        calculated_correct=sum(int(max(range(2),key=lambda i:p[i])==labels[c['case_id']])
                               for p,c in zip(pred['predictions'],test))
        calculated_nll=sum(-math.log(max(1e-12,p[labels[c['case_id']]]))
                           for p,c in zip(pred['predictions'],test))/len(test)
        score=report['holdout_scores'][name]
        require(score['total']==len(test) and score['correct']==calculated_correct
                and abs(score['nll']-calculated_nll)<1e-10,'holdout classification/NLL drift')
        opts={pk:{'p95_response_median_ns':int(statistics.median([v['latency_p95_ns'] for v in vals])),
                  'first_response_median_ns':int(statistics.median([v['first_response_ns'] for v in vals])),
                  'whole_run_wall_median_ns':int(statistics.median([v['whole_run_wall_ns'] for v in vals])),
                  'physical_calls_per_run':[v['physical_forward_calls'] for v in vals]}
              for pk,vals in evaluation['measurements'][name].items()}
        summ=report['summaries'][name]
        require(summ['selected_policy_key']==winner and summ['by_policy']==opts
                and summ['scalars']==opts['1:0']
                and abs(summ['selected_vs_scalar_p95_ratio']
                         - opts['1:0']['p95_response_median_ns']/opts[winner]['p95_response_median_ns'])<1e-12
                and abs(summ['selected_vs_scalar_full_wall_ratio']
                         - opts['1:0']['whole_run_wall_median_ns']/opts[winner]['whole_run_wall_median_ns'])<1e-12
                and summ['selected_is_faster_p95']==(opts[winner]['p95_response_median_ns']
                                                       < opts['1:0']['p95_response_median_ns']),
                'holdout latency summary/window bias')
        reqs[name]=winner;scored[name]=score['correct']
    for field,value in [('all_measured_arm_calls',charged_calls),
                        ('all_measured_arm_unique_frames',charged_frames),
                        ('all_measured_arm_conv_ns',charged_conv),
                        ('all_measured_arm_preprocess_ns',charged_pre),
                        ('all_measured_arm_source_bytes',charged_bytes),
                        ('all_measured_arm_wall_ns',charged_wall),
                        ('all_arm_execution_count_including_warmups',run_count)]:
        if protocol['warmups']==0:
            require(report[field]==value,'whole-study physical accounting drift: '+field)
    require(report['whole_study_wall_ns'] >= charged_wall,
            'whole-study wall cannot exclude executed calibration/holdout arms')
    require(report['all_arm_calls_plus_training_and_warmups']==charged_calls
            + report['warmup_calls']+training['training_work']['training_physical_tower_calls'],
            'training/benchmark reference model cost omitted')
    return {'audited_workloads':reqs,'heldout_correct':scored,
            'total_accounted_arm_calls':charged_calls,
            'real_pretrained_clip':False,'independently_attested_latency':False,
            'production_accepted':False}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(audit(args.root,args.output),sort_keys=True))
