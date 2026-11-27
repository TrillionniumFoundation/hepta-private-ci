"""Original-data replay of nested exclusion, physical SGD, decisions and forecasts.

The inherited scalar SGD and exact rational tree are independent of the producer.
This is same-author numerical review, not independent institutional custody.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from fractions import Fraction as Q
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
for p in (HERE.parent,HERE.parent.parent):sys.path.insert(0,str(p))
from material_news import encode, loads, original, sha, write
from audit_news import equal, reference_row, scalar_softmax
from review import rational_plan, scalar_fold
from nested import sources, config, POSTURE


def partition(ids,n,domain):
    ranked=sorted(range(len(ids)),key=lambda i:sha(('hepta-nested-'+domain+'-v1:'+ids[i]).encode()))
    return [tuple(i for pos,i in enumerate(ranked) if pos%n==f) for f in range(n)]


def numerical(raw,mean,scale,weights):
    return np.array([scalar_softmax(reference_row(r,mean,scale),weights) for r in raw])


def forecast_score(curve_counts,step_index,observed):
    """Finite model predictive distribution, not an empirical confidence interval."""
    rates=[Q(c[step_index]+1,18) for c in curve_counts]
    law=[sum(math.comb(16,k)*p**k*(1-p)**(16-k) for p in rates)/len(rates) for k in range(17)]
    if sum(law)!=1:raise ValueError('predictive law not normalized')
    def quantile(q):
        total=Q(0)
        for k,p in enumerate(law):
            total+=p
            if total>=q:return k
        raise ValueError('incomplete probability distribution')
    low,high=quantile(Q(1,40)),quantile(Q(39,40))
    mean=sum(rates)/len(rates)
    return {'predicted_accuracy':float(mean),'observed_accuracy':observed/16,
            'signed_error':float(mean)-observed/16,'absolute_error':abs(float(mean)-observed/16),
            'negative_log_predictive_count_probability':-math.log(float(law[observed])),
            'model_interval95_counts':[low,high],'inside_model_interval':low<=observed<=high,
            'predictive_count_mass':[str(p) for p in law]}


def verify_fit(row,ref,expected_updates=128):
    mean,scale,weights,losses,_=ref
    if type(row['actual_updates']) is not int or row['actual_updates']!=expected_updates:
        raise ValueError('unpaid or false optimizer work')
    stops=[t for t in (0,8,32,128) if t<=expected_updates]
    if set(row['checkpoints'])!={str(t) for t in stops}:raise ValueError('missing or unexecuted checkpoint')
    equal(row['mean'],mean);equal(row['scale'],scale);equal(row['losses'],losses[:expected_updates])
    for t in stops:equal(row['checkpoints'][str(t)],weights[str(t)])
    return len(stops)


def audit(archive,material,runs,output):
    c0,w0=time.process_time_ns(),time.perf_counter_ns()
    rows,features,parts=original(archive);cfg=config()
    manifest=loads((material/'manifest.json').read_bytes())
    if (manifest['protocol_sha256']!=sha((HERE/'protocol.json').read_bytes()) or
        manifest['archive_sha256']!=cfg['archive_sha256'] or manifest['posture']!=POSTURE):
        raise ValueError('material protocol or archive mismatch')
    pool=parts['train'];cal=parts['calibration'];ids=[rows[i]['case_id'] for i in pool]
    excluded=[rows[i]['case_id'] for i in parts['holdout']]
    if manifest['excluded_original_holdout_ids']!=excluded or len(manifest['folds'])!=4:
        raise ValueError('original HOLDOUT exclusion missing')
    fullraw=tuple(tuple(float(v) for v in row) for row in features[pool])
    fully=tuple(rows[i]['label'] for i in pool)
    outer=partition(ids,4,'outer');checks=0;decisions=0;forecasts=[];scored=[];total_updates=0
    for f,held in enumerate(outer):
        rec=manifest['folds'][f];folder=material/f'fold-{f}';run=runs/f'fold-{f}'
        train=tuple(i for i in range(64) if i not in held)
        if (rec['fold']!=f or rec['fit_ids']!=[ids[i] for i in train] or rec['eval_ids']!=[ids[i] for i in held]):
            raise ValueError('outer assignment or held-label leakage')
        label_raw=(folder/'labels.json').read_bytes()
        expected_labels={ids[i]:fully[i] for i in held}
        if sha(label_raw)!=rec['labels_sha256'] or loads(label_raw)!=expected_labels:
            raise ValueError('original held-label owner mismatch')
        worker=(folder/'worker.npz').read_bytes()
        if sha(worker)!=rec['worker_sha256']:raise ValueError('worker tamper')
        with np.load(folder/'worker.npz',allow_pickle=False) as z:
            required={'fit_x','fit_y','fit_ids','cal_x','cal_y','cal_ids','cal_hashes','eval_x','eval_ids'}
            if set(z.files)!=required:raise ValueError('evaluation label smuggling')
            a={k:z[k].copy() for k in z.files}
        for kind,ix in (('fit',[pool[i] for i in train]),('eval',[pool[i] for i in held]),('cal',cal)):
            if not np.array_equal(a[kind+'_x'],features[ix]) or a[kind+'_ids'].tolist()!=[rows[i]['case_id'] for i in ix]:
                raise ValueError('source feature or identity drift')
            if kind!='eval' and a[kind+'_y'].tolist()!=[rows[i]['label'] for i in ix]:
                raise ValueError('source permitted label drift')
        hashes=[sha(rows[i]['text'].encode()) for i in cal]
        if a['cal_hashes'].tolist()!=hashes:raise ValueError('calibration order drift')
        seal=loads((run/'sealed.json').read_bytes())
        expected_seal={'schema','posture','source_sha256','worker_sha256','forecast_sha256','prior_sha256',
            'diagnostic_sha256','journal_sha256','rows','prior_updates','diagnostic_updates','policy_updates',
            'target_labels_loaded','original_holdout_used','new_sources','runtime'}
        if set(seal)!=expected_seal or seal['schema']!='hepta.nested-transfer.seal.v1' or seal['posture']!=POSTURE:
            raise ValueError('invalid seal schema or authority')
        if (seal['source_sha256']!=sources() or seal['worker_sha256']!=rec['worker_sha256'] or
            seal['target_labels_loaded'] is not False or seal['original_holdout_used'] is not False or seal['new_sources']!=0):
            raise ValueError('source or scientific claim drift')
        for file,field in (('prior.json','prior_sha256'),('forecast.json','forecast_sha256'),
                           ('diagnostic.json','diagnostic_sha256'),('journal.jsonl','journal_sha256')):
            if sha((run/file).read_bytes())!=seal[field]:raise ValueError('record digest mismatch')
        prior=loads((run/'prior.json').read_bytes());diag=loads((run/'diagnostic.json').read_bytes())
        forecast=loads((run/'forecast.json').read_bytes())
        if prior['actual_updates']!=384 or prior['scoring_calls']!=12 or len(prior['fits'])!=3:
            raise ValueError('incorrect prior work census')
        curves=[];inner=partition(a['fit_ids'].tolist(),3,'inner')
        for k,valid_local in enumerate(inner):
            valid=tuple(train[i] for i in valid_local)
            fitted=tuple(i for i in train if i not in valid)
            rr=prior['fits'][k]
            if (rr['fold']!=k or rr['train_ids']!=[ids[i] for i in fitted] or rr['valid_ids']!=[ids[i] for i in valid]):
                raise ValueError('nested prior contains excluded records')
            ref=scalar_fold(fullraw,fully,fitted,valid)
            checks+=verify_fit(rr,ref)
            if rr['counts']!=ref[4]:raise ValueError('prior curve score mismatch')
            curves.append(tuple(ref[4]))
        if prior['curves']!=[list(c) for c in curves]:raise ValueError('prior summary tamper')
        expected_forecast={'prior_rates':{str(t):[(c[j]+1)/18 for c in curves] for j,t in enumerate((0,8,32,128))},
                           'eval_ids':[ids[i] for i in held],'target_labels_loaded':False,'worker_sha256':rec['worker_sha256']}
        if forecast!=expected_forecast:raise ValueError('forecast changed after scoring')
        ref=scalar_fold(fullraw,fully,train,held);mean,scale,weights,losses,actual_counts=ref
        checks+=verify_fit(diag,ref)
        expected_journal=[{'phase':'prior','kind':'start'}, {'phase':'prior','kind':'success','updates':384}]
        keys=[(r['scenario'],r['arm']) for r in seal['rows']]
        if len(keys)!=len(set(keys)) or set(keys)!={(s['name'],arm) for s in cfg['scenarios'] for arm in cfg['arms']}:
            raise ValueError('missing or duplicated policy')
        for r in seal['rows']:
            s=next(s for s in cfg['scenarios'] if s['name']==r['scenario']);arm=r['arm']
            if any(type(r[k]) is not int or r[k]<0 for k in ('actual_updates','calibration_calls','cpu_ns','wall_ns')):
                raise ValueError('invalid physical cost count')
            if loads((run/(arm+'.json')).read_bytes())!=r:raise ValueError('row-seal mismatch')
            updates=0;history=[];selected=None;authorized=None;awaiting=False
            events=r['events']
            if events[0]!={'kind':'start','fit_ids':[ids[i] for i in train]}:raise ValueError('missing physical start')
            for pos,e in enumerate(events):
                expected_journal.append({'phase':'policy','arm':arm,'scenario':s['name'],**e})
                if e['kind']=='start':
                    if pos!=0:raise ValueError('duplicate start')
                elif e['kind']=='decision':
                    if awaiting or authorized is not None or selected is not None or e['history']!=history:
                        raise ValueError('anticipative or duplicate decision')
                    if arm.startswith('belief_'):
                        value,stop,cont,best,target,alpha,mass=rational_plan(tuple(curves),tuple(s.items()),arm[7:],tuple(history))
                        equal(e['value'],float(value));equal(e['stop_value'],float(stop));equal(e['posterior'],[float(v) for v in mass])
                        if e['alpha']!=alpha or e['selected_steps']!=best or e['to_step']!=target:
                            raise ValueError('independent exact decision mismatch')
                        if e['pruned']:
                            nxt=(8,32,128)[len(history)]
                            bound=max(Q(c+1,18) for curve in curves for c in curve)*s['horizon']-Q(s['step_fee'])*(nxt-updates)-Q(s['calibration_fee'])
                            equal(e['continue_value_upper_bound'],float(bound))
                            if cont is None or cont>bound or bound>stop or e['continue_value'] is not None:
                                raise ValueError('invalid pruning upper bound')
                        elif cont is not None:equal(e['continue_value'],float(cont))
                        decisions+=1
                    else:
                        desired=int(arm[5:]);target=desired if updates<desired<=s['budget'] else None;best=updates
                    if e['action']!=('stop' if target is None else 'continue'):
                        raise ValueError('action differs from reference')
                    if target is None:selected=best
                    else:authorized=target
                elif e['kind']=='train_start':
                    if pos==0 or events[pos-1]['kind']!='decision' or authorized!=e['to_step'] or e['from_step']!=updates or e['to_step']>s['budget']:
                        raise ValueError('unapproved optimizer work')
                elif e['kind']=='train_done':
                    if pos==0 or events[pos-1]['kind']!='train_start' or e['step']!=authorized:
                        raise ValueError('training not bracketed')
                    updates=authorized;authorized=None;awaiting=arm.startswith('belief_')
                    if e['weights_sha256']!=sha(encode(r['checkpoints'][str(updates)])):
                        raise ValueError('physical weight digest mismatch')
                elif e['kind']=='observation':
                    if not awaiting or e['step']!=updates:raise ValueError('unpaid or unexecuted observation')
                    sizes=(8,8,16);j=len(history);order=sorted(range(32),key=lambda i:hashes[i])
                    ix=order[sum(sizes[:j]):sum(sizes[:j+1])]
                    cp=numerical(a['cal_x'][ix],mean,scale,weights[str(updates)])
                    count=int(np.sum(cp.argmax(axis=1)==a['cal_y'][ix]))
                    if type(e['count']) is not int or e['count']!=count or e['ids']!=a['cal_ids'][ix].tolist():
                        raise ValueError('calibration changed or target label used')
                    history.append(count);awaiting=False
                elif e['kind']=='success':
                    if pos!=len(events)-1 or selected is None or authorized is not None or awaiting:
                        raise ValueError('premature completion')
                    if e!={'kind':'success','actual_updates':updates,'selected_steps':selected}:raise ValueError('success drift')
                else:raise ValueError('unknown event')
            if events[-1]['kind']!='success' or r['actual_updates']!=updates or r['selected_steps']!=selected or r['history']!=history:
                raise ValueError('incomplete physical trajectory')
            if r['calibration_calls']!=len(history) or r['evaluation_ids']!=[ids[i] for i in held]:raise ValueError('exposure drift')
            checks+=verify_fit(r,ref,updates)
            predicted=numerical(a['eval_x'],mean,scale,weights[str(selected)])
            equal(r['probabilities'],predicted)
            # Label access here is after the model seal; original archive is reviewer input.
            lab=np.array([fully[i] for i in held]);correct=(predicted.argmax(axis=1)==lab).astype(int).tolist()
            fee=Q(s['step_fee'])*updates+Q(s['calibration_fee'])*len(history)
            prior_fee=Q(s['step_fee'])*384+Q(s['calibration_fee'])*12 if arm.startswith('belief_') else Q(0)
            model_accuracy=None
            if arm.startswith('belief_'):
                _,_,_,_,_,_,mass=rational_plan(tuple(curves),tuple(s.items()),arm[7:],tuple(history))
                t=(0,8,32,128).index(selected)
                model_accuracy=float(sum(p*Q(c[t]+1,18) for p,c in zip(mass,curves)))
            scored.append({'fold':f,'arm':arm,'scenario':s['name'],'correct':sum(correct),'correct_vector':correct,
                'denominator':16,'selected_steps':selected,'actual_updates':updates,'calibration_calls':len(history),
                'model_expected_accuracy_at_selected':model_accuracy,'accuracy':sum(correct)/16,
                'net_online':str(s['horizon']*Q(sum(correct),16)-fee),
                'net_cold':str(s['horizon']*Q(sum(correct),16)-fee-prior_fee),
                'cpu_ns':r['cpu_ns'],'cold_cpu_ns':r['cpu_ns']+(prior['cpu_ns'] if arm.startswith('belief_') else 0)})
        expected_journal += [{'phase':'diagnostic','kind':'start'},{'phase':'diagnostic','kind':'success','updates':128}]
        actual_journal=[loads(line) for line in (run/'journal.jsonl').read_bytes().splitlines()]
        if actual_journal!=expected_journal:raise ValueError('complete journal ordering mismatch')
        if seal['prior_updates']!=384 or seal['diagnostic_updates']!=128 or seal['policy_updates']!=sum(r['actual_updates'] for r in seal['rows']):
            raise ValueError('cold-start or diagnostic cost omitted')
        total_updates+=512+seal['policy_updates']
        for j,t in enumerate((0,8,32,128)):
            pp=numerical(a['eval_x'],mean,scale,weights[str(t)])
            equal(diag['probabilities'][str(t)],pp)
            forecasts.append({'fold':f,'step':t,'observed_correct':actual_counts[j],
                              'prior_curves':[list(c) for c in curves],**forecast_score(curves,j,actual_counts[j])})
    summaries=[]
    for arm in cfg['arms']:
        rr=[r for r in scored if r['arm']==arm]
        summaries.append({'arm':arm,'correct':sum(r['correct'] for r in rr),'denominator':64,
            'actual_updates':sum(r['actual_updates'] for r in rr),'calibration_calls':sum(r['calibration_calls'] for r in rr),
            'selected_steps':[r['selected_steps'] for r in rr],'cpu_ms':sum(r['cpu_ns'] for r in rr)/1e6,
            'cold_cpu_ms':sum(r['cold_cpu_ns'] for r in rr)/1e6})
    result={'schema':'hepta.nested-transfer.audit.v1','posture':POSTURE,'source_sha256':sources(),
        'verified_folds':4,'prior_fit_count':12,'policy_lifecycles':len(scored),'checkpoint_checks':checks,
        'rational_decision_checks':decisions,'actual_updates':total_updates,'prior_updates':1536,'diagnostic_updates':512,
        'policy_updates':total_updates-2048,'unique_evaluation_records':64,'original_holdout_used':False,
        'new_sources':0,'independent_task_family_count':None,'new_encoder_calls':0,'neural_preference_training':False,
        'outer_label_exclusion_verified':True,'transfer_qualified':False,'production_accepted':False,
        'forecast_mean_absolute_error':sum(r['absolute_error'] for r in forecasts)/len(forecasts),
        'forecast_signed_bias':sum(r['signed_error'] for r in forecasts)/len(forecasts),
        'inside_model_interval_count':sum(r['inside_model_interval'] for r in forecasts),
        'forecast_coordinate_count':16,'forecasts':forecasts,'rows':scored,'summaries':summaries,
        'cpu_ns':time.process_time_ns()-c0,'wall_ns':time.perf_counter_ns()-w0}
    write(output,result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','material','runs','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=audit(a.archive,a.material,a.runs,a.output)
    print(encode({k:r[k] for k in ('policy_lifecycles','actual_updates','forecast_mean_absolute_error','summaries')}).decode())
