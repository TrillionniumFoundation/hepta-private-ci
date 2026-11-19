"""Source/scalar replay plus independent joint-likelihood and maximal-error enumeration."""
from __future__ import annotations
import argparse
import statistics
import sys
import time
from fractions import Fraction as Q
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'compiled'))
from audit_compiled import (verify_prior, verify_table, reference, reference_row,
                            scalar_softmax, equal, read_training, original)
from compile_policy import SharedPolicy
from material_news import encode, loads, packet, sha, write
from study import config as scenarios
from trial_guard import sources,config
from exact_null import trace, certificate


def audit(archive, material, run, output):
    c0,w0=time.process_time_ns(),time.perf_counter_ns()
    a,receipt=packet(material/'worker.npz')
    src,features,parts=original(archive)
    for role,dest in (('train','train'),('calibration','cal'),('holdout','holdout')):
        ix=parts[role]
        if not np.array_equal(a['x_'+dest],features[ix]) or a[dest+'_ids'].tolist()!=[src[i]['case_id'] for i in ix]:
            raise ValueError('original source/feature drift')
        if role!='holdout' and a['y_'+dest].tolist()!=[src[i]['label'] for i in ix]:
            raise ValueError('original allowed label drift')
    s=loads((run/'sealed.json').read_bytes());prior=loads((run/'prior.json').read_bytes())
    data=loads((run/'policy.json').read_bytes())
    if s['schema']!='hepta.merton.predictive-guard-seal.v1' or s['posture']!='RESEARCH_ONLY_DENY_ALL':
        raise ValueError('schema or authority claim')
    if s['source_sha256']!=sources() or s['protocol_sha256']!=sha((HERE/'protocol.json').read_bytes()):
        raise ValueError('source/protocol drift')
    for key,value in {'prior_fits_physically_executed':1,'prior_updates':512,'shared_table_owners':1,
                      'new_sources':0,'fresh_encoder_calls':0,'heldout_labels_loaded':False,
                      'guard_is_accuracy_guarantee':False,'fleet_wide_error_bound':False}.items():
        if type(s[key]) is not type(value) or s[key]!=value:raise ValueError('unsupported claim or census')
    if s['worker_sha256']!=receipt['worker_sha256'] or s['prior_sha256']!=sha((run/'prior.json').read_bytes()):
        raise ValueError('source binding')
    asset=SharedPolicy(run/'policy.json',s['compilation']['asset_sha256'],s['worker_sha256'],s['prior_sha256'])
    if data['curves']!=prior['curves']:raise ValueError('prior drift')
    table_checks=verify_table(data)
    tx,ty,tids=read_training(run/'train.npz')
    if not np.array_equal(tx,a['x_train']) or not np.array_equal(ty,a['y_train']) or not np.array_equal(tids,a['train_ids']):
        raise ValueError('prior training mismatch')
    if sha((run/'train.npz').read_bytes())!=prior['training_sha256']:raise ValueError('train hash')
    prior_checks=verify_prior(tx,ty,tids,prior)
    raw=tuple(tuple(float(v) for v in row) for row in tx);labels=tuple(map(int,ty))
    mean,scale,weights,losses=reference(raw,labels);weights={int(k):v for k,v in weights.items()}
    equal(mean,s['mean']);equal(scale,s['scale'])
    cal={t:[scalar_softmax(reference_row(row,mean,scale),weights[t]) for row in a['x_cal']] for t in weights}
    hold={t:[scalar_softmax(reference_row(row,mean,scale),weights[t]) for row in a['x_holdout']] for t in weights}
    if a['cal_hashes'].tolist()!=[sha(src[i]['text'].encode()) for i in parts['calibration']]:raise ValueError('cal order')
    order=np.argsort(a['cal_hashes'],kind='stable').tolist();truth=[src[i]['label'] for i in parts['holdout']]
    wanted={(r,t['name'],arm) for r in range(config()['repeats']) for t in scenarios()['scenarios'] for arm in config()['arms']}
    keys=[(r['repeat'],r['scenario'],r['arm']) for r in s['rows']]
    if len(set(keys))!=len(keys) or set(keys)!=wanted:raise ValueError('missing/duplicate run')
    journal=[];scored=[];checks=0;guard_checks=0
    for row in s['rows']:
        scenario=next(t for t in scenarios()['scenarios'] if t['name']==row['scenario'])
        arm=row['arm'];fixed=arm in ('fixed8','no_update');guarded=arm.startswith('guarded_')
        events=[{'kind':'start'}];h=[];t=0;seen={0};ids=[];gr=[];alarm=False
        if row['solver_constructions']!=0 or row['online_model_nodes']!=0:raise ValueError('hidden solver')
        if type(row['predictive_alarm']) is not bool:raise ValueError('strict alarm flag')
        if any(type(row[k]) is not int or row[k]<0 for k in ('actual_steps','selected_steps','calibration_calls','repeat')):
            raise ValueError('strict physical counters')
        while True:
            if guarded and h:
                j=len(h)-1;n=(8,8,16)[j];start=sum((8,8,16)[:j]);ix=order[start:start+n]
                e=trace(tuple(map(tuple,prior['curves'])),tuple(h))[-1]
                gr.append({'history_before':h[:-1],'step':t,'count':h[-1],'size':n,
                           'ids':a['cal_ids'][ix].tolist(),**e,'threshold':'20'})
                alarm=e['alarm'];guard_checks+=1
            if fixed:
                dest=8 if arm=='fixed8' else 0;take=t<dest<=scenario['budget']
                d={'action':'continue' if take else 'stop','to_step':dest if take else None,
                   'selected_steps':t,'reason':'fixed_schedule'}
            elif alarm:
                d={'action':'stop','to_step':None,'selected_steps':8,
                   'reason':'predictive_model_rejected_use_executed_fixed8','model_value_unavailable':True}
            else:
                mode=arm.split('_',1)[1];key=','.join(map(str,h))
                d=data['tables'][scenario['name']+'/'+mode][key]
            if guarded and h:d=dict(d)|{'predictive_guard':gr[-1]}
            events.append({'kind':'decision','history':list(h),'actual_steps':t,**d})
            if d['action']=='stop':selected=d['selected_steps'];break
            target=d['to_step'];events.append({'kind':'train_start','from_step':t,'to_step':target})
            equal(weights[target],row['checkpoints'][str(target)]);checks+=1;seen.add(target);t=target
            events.append({'kind':'train_done','actual_steps':t,'weights_sha256':sha(encode(row['checkpoints'][str(t)]))})
            if not fixed:
                n=(8,8,16)[len(h)];start=sum((8,8,16)[:len(h)]);ix=order[start:start+n]
                count=sum(max(range(4),key=lambda k:cal[t][i][k])==int(a['y_cal'][i]) for i in ix)
                used=a['cal_ids'][ix].tolist();ids.extend(used);h.append(count)
                events.append({'kind':'observation','step':t,'count':count,'size':n,'ids':used})
        events.append({'kind':'success','actual_steps':t,'selected_steps':selected})
        if (events!=row['events'] or gr!=row['predictive_records'] or alarm!=row['predictive_alarm']
            or row['guard_scope']!=(asset.scope_digest if guarded else None) or row['history']!=h
            or row['actual_steps']!=t or row['selected_steps']!=selected or t>scenario['budget']
            or row['calibration_calls']!=len(h) or row['calibration_ids']!=ids
            or set(row['checkpoints'])!={str(v) for v in seen}):raise ValueError('execution/guard/charge drift')
        equal(weights[0],row['checkpoints']['0']);equal(weights[selected],row['weights'])
        equal(losses[:t],row['losses']);equal(hold[selected],row['probabilities'])
        if row['holdout_ids']!=a['holdout_ids'].tolist():raise ValueError('held identity drift')
        for k in ('cpu_ns','wall_ns'):
            if type(row[k]) is not int or row[k]<0:raise ValueError('invalid measured time')
        for phase in row['phases']:
            if any(type(phase[k]) is not int or phase[k]<0 for k in ('cpu_ns','wall_ns')):raise ValueError('invalid phase time')
        if sum(p['cpu_ns'] for p in row['phases'])>row['cpu_ns']:raise ValueError('phase outside lifecycle')
        journal.extend({'repeat':row['repeat'],'scenario':row['scenario'],'arm':arm,**e} for e in events)
        correct=sum(max(range(4),key=lambda k:hold[selected][i][k])==y for i,y in enumerate(truth))
        fee=Q(scenario['step_fee'])*t+Q(scenario['calibration_fee'])*len(h)
        scored.append({'repeat':row['repeat'],'scenario':row['scenario'],'arm':arm,'correct':correct,
                       'denominator':32,'actual_updates':t,'calibration_calls':len(h),'alarm':alarm,
                       'net_under_declared_tariff':str(scenario['horizon']*Q(correct,32)-fee),
                       'cpu_ms':row['cpu_ns']/1e6,'wall_ms':row['wall_ns']/1e6})
    if sum(r['actual_steps'] for r in s['rows'])!=s['actual_online_updates']:raise ValueError('work census')
    jr=(run/'journal.jsonl').read_bytes()
    if sha(jr)!=s['journal_sha256'] or [loads(x) for x in jr.splitlines()]!=journal:raise ValueError('journal drift')
    for row in s['rows']:
        if loads((run/f'{row["repeat"]}-{row["scenario"]}-{row["arm"]}.json').read_bytes())!=row:raise ValueError('unsealed row')
    summary=[]
    for scenario in scenarios()['scenarios']:
        for arm in config()['arms']:
            group=[r for r in scored if r['scenario']==scenario['name'] and r['arm']==arm]
            summary.append({'scenario':scenario['name'],'arm':arm,'correct':group[0]['correct'],
                            'actual_updates':group[0]['actual_updates'],'alarm':group[0]['alarm'],
                            'median_cpu_ms':statistics.median(r['cpu_ms'] for r in group)})
    paired=0
    for row in s['rows']:
        if row['arm'].startswith('guarded_'):
            other=next(r for r in s['rows'] if r['repeat']==row['repeat'] and r['scenario']==row['scenario'] and r['arm']=='shared_'+row['arm'][8:])
            if not row['predictive_alarm']:
                for k in ('weights','probabilities','losses'):equal(row[k],other[k])
                behavior=[{k:v for k,v in e.items() if k!='predictive_guard'} for e in row['events']]
                if behavior!=other['events']:raise ValueError('no-alarm changes behavior')
            paired+=1
    report={'schema':'hepta.merton.predictive-guard-audit.v1','posture':'RESEARCH_ONLY_DENY_ALL',
            'source_sha256':sources(),'seal_sha256':sha((run/'sealed.json').read_bytes()),
            'verified_lifecycles':len(scored),'guard_observations_checked':guard_checks,
            'guard_vs_shared_pairs':paired,'online_checkpoints':checks,'prior_checkpoints':prior_checks,
            'rational_policy_nodes':table_checks,'prior_updates':512,'online_updates':s['actual_online_updates'],
            'new_sources':0,'fresh_encoder_calls':0,'null_certificate':certificate(tuple(map(tuple,prior['curves']))),
            'real_model_calibration_established':False,'task_accuracy_guaranteed':False,
            'ndu_specific_superiority':False,'production_accepted':False,
            'audit_cpu_ns':time.process_time_ns()-c0,'audit_wall_ns':time.perf_counter_ns()-w0,
            'rows':scored,'summaries':summary}
    write(output,report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('archive','material','run','output'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();r=audit(a.archive,a.material,a.run,a.output)
    print(encode({k:r[k] for k in ('verified_lifecycles','guard_observations_checked','online_updates')}).decode())
