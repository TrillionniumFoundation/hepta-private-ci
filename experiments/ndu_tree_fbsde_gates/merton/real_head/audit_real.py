"""Post-seal original-human score and separately implemented SGD/choice replay.

Same author, separate implementation/process; not an independent signer.
CPU counters are self-observations, not authenticated hardware measurements.
"""
from __future__ import annotations
import argparse
import math
import time
from fractions import Fraction as Q
from pathlib import Path
from material import LOCKS, canonical, load_sources, sha, strict_loads, write_new
from learning import ARMS, HORIZONS, STEPS, SOURCES, spec


def prob(z):
    if z<0:
        e=math.exp(z);return e/(1+e)
    return 1/(1+math.exp(-z))


def ref_fit(rows,n):
    weights=[0.0]*5
    if n==0:return {'weights':weights,'scales':[1.0]*4},[]
    scales=[max(math.sqrt(sum(row['x'][j]*row['x'][j] for row in rows)/len(rows)),1e-6) for j in range(4)]
    group={}
    for row in rows:group.setdefault((row['group'],row['question']),[]).append(row)
    trace=[]
    for step in range(n):
        gradient=[0.0]*5;loss=0.0
        for row in rows:
            xx=[row['x'][j]/scales[j] for j in range(4)]+[1.0]
            p=prob(row['base']+sum(weights[j]*xx[j] for j in range(5)))
            target=row['label']; mass=1/(len(group)*len(group[row['group'],row['question']]))
            # Independent two-class expression, rather than calling learner loss/gradient.
            residual_positive=p-target;residual_negative=(1-p)-(1-target)
            loss+=mass*(residual_positive**2+residual_negative**2)
            coefficient=mass*2*(residual_positive-residual_negative)*p*(1-p)
            for j in range(5):gradient[j]+=coefficient*xx[j]
        for j in range(5):weights[j]-=0.1*gradient[j]
        trace.append(loss)
    return {'weights':weights,'scales':scales},trace


def ref_predict(head,rows):
    return [prob(row['base']+sum(head['weights'][j]*row['x'][j]/head['scales'][j] for j in range(4))+head['weights'][4]) for row in rows]


def close(a,b,tol=1e-10):
    if len(a)!=len(b) or any(not math.isfinite(x) or not math.isfinite(y) or abs(x-y)>tol for x,y in zip(a,b)):
        raise ValueError('numeric replay mismatch')


def qscore(rows, probs, labels):
    output={}
    for row,p in zip(rows,probs):
        key=row['group']+'/'+str(row['question'])
        output[key]=output.get(key,True) and (int(p>0.5)==labels[row['id']])
    return output


def check_row(r,fold,labels):
    train=fold['train'];held=fold['held_inputs']
    arm,horizon=r['arm'],r['horizon_scenario']
    if r['source_fold_sha256']!=sha(canonical(fold)):raise ValueError('fold binding')
    if r['held_group']!=fold['held_group'] or r['policy_loaded_heldout_labels'] is not False:raise ValueError('test label leakage')
    if r['fresh_encoder_forwards']!=0 or r['neural_preference_updates']!=0:raise ValueError('fabricated model work')
    for k in ('lifecycle_cpu_ns','lifecycle_wall_ns'):
        if type(r[k]) is not int or r[k]<0:raise ValueError('invalid process time')
    if any(type(v) is not int or v<0 for v in r['stages'].values()):raise ValueError('invalid phase time')
    if sum(r['stages'].values())>r['lifecycle_cpu_ns']:raise ValueError('double-counted stage time')
    fits=r['fits'];search=arm not in ('no_update','fixed_32')
    expected_count=13 if search else 1
    if len(fits)!=expected_count:raise ValueError('missing executed fit')
    pilots={};ref_heads={}
    for fit in fits:
        n=fit['steps']
        if type(n) is not int or n not in STEPS:raise ValueError('wrong actual training budget')
        subset=train if fit['role']=='final' else [x for x in train if x['group']!=fit['validation_group']]
        if fit['role'] not in ('pilot','final'):raise ValueError('unknown fit role')
        wanted=[] if n==0 else [x['id'] for x in subset]
        wanted_digest=None if n==0 else sha(canonical([[x['id'],x['label']] for x in subset]))
        if fit['train_ids']!=wanted or fit['train_label_digest']!=wanted_digest or fit['train_rows']!=(len(subset) if n else 0):
            raise ValueError('training exposure leak or mismatch')
        for k in ('cpu_ns','wall_ns'):
            if type(fit[k]) is not int or fit[k]<0 or (n>0 and fit[k]==0):raise ValueError('invalid fit metering')
        head,trace=ref_fit(subset,n)
        close(head['weights'],fit['head']['weights']);close(head['scales'],fit['head']['scales']);close(trace,fit['loss_trace'])
        if fit['role']=='pilot':
            key=(fit['validation_group'],n)
            if key in pilots:raise ValueError('duplicate pilot')
            pilots[key]=fit;ref_heads[key]=head
        else:
            final_head=head
            if n!=r['selected_steps']:raise ValueError('selected fit mismatch')
    if sum(x['steps'] for x in fits)!=r['update_steps_actually_executed']:raise ValueError('fabricated optimizer steps')
    candidates={};alpha=Q(0)
    if search:
        groups=sorted({x['group'] for x in train})
        expected={(g,k) for g in groups for k in STEPS}
        if set(pilots)!=expected or len(r['calibration'])!=12:raise ValueError('pilot census')
        crs={}
        for cr in r['calibration']:
            key=(cr['group'],cr['steps']);subset=[x for x in train if x['group']==cr['group']]
            if key in crs or key not in expected:raise ValueError('calibration census')
            probabilities=ref_predict(ref_heads[key],subset)
            if cr['ids']!=[x['id'] for x in subset]:raise ValueError('calibration row binding')
            close(probabilities,cr['probabilities'])
            q=qscore(subset,probabilities,labels)
            outcomes=[int(q[g]) for g in sorted(q)]
            if outcomes!=cr['complete_questions']:raise ValueError('false whole-question gain')
            if type(cr['scoring_cpu_ns']) is not int or cr['scoring_cpu_ns']<=0:raise ValueError('missing calibration cost')
            crs[key]=cr
        for n in STEPS:
            fs=[pilots[g,n] for g in groups];cs=[crs[g,n] for g in groups]
            quote=Q(0) if n==0 else sum((Q(f['cpu_ns']*len(train),f['train_rows']) for f in fs),Q(0))/3
            candidates[str(n)]={'passage_success':[str(Q(sum(c['complete_questions']),len(c['complete_questions']))) for c in cs],
                'estimated_refit_cpu_ns':str(quote),
                'observed_inference_cpu_ns_per_question':str(sum((Q(c['scoring_cpu_ns'],len(c['complete_questions'])) for c in cs),Q(0))/3)}
        if candidates!=r['candidate_quotes']:raise ValueError('cost or utility quote mismatch')
        alpha=Q(0) if arm=='budget_neutral' else Q(1,4)
        if arm in ('ndu_discrete','augmented_same_profile'):
            for g in groups:
                for good in crs[g,0]['complete_questions']:
                    alpha=max(Q(0),min(Q(1,2),alpha-(Q(1,8) if good else -Q(1,4))))
        values={}
        for n in STEPS:
            c=candidates[str(n)];qs=[Q(q) for q in c['passage_success']]
            utility=(1-alpha)*sum(qs,Q(0))/3+alpha*min(qs)
            cost=(Q(c['estimated_refit_cpu_ns'])+horizon*Q(c['observed_inference_cpu_ns_per_question']))/1_000_000_000
            values[n]=horizon*utility-cost
        chosen=sorted(STEPS,key=lambda k:(-values[k],k))[0]
        if r['selection_values']!={str(k):str(v) for k,v in values.items()}:raise ValueError('selection value mismatch')
        if r['selected_steps']!=chosen or r['same_profile_reference_steps']!=chosen:raise ValueError('nonoptimal same-profile choice')
    else:
        if r['selected_steps']!=(0 if arm=='no_update' else 32):raise ValueError('baseline drift')
        if r['calibration'] or r['candidate_quotes'] or r['selection_values']:raise ValueError('free baseline unexpectedly searches')
    if r['preference']!=str(alpha):raise ValueError('preference profile drift')
    close(final_head['weights'],r['selected_head']['weights']);close(final_head['scales'],r['selected_head']['scales'])
    out=r['test_probabilities']
    if [x['id'] for x in out]!=[x['id'] for x in held]:raise ValueError('heldout census')
    pp=ref_predict(final_head,held);close(pp,[x['p'] for x in out])
    return pp


def audit(paths,material_dir,run_dir,output):
    c,w=time.process_time_ns(),time.perf_counter_ns()
    source_rows,labels,provenance=load_sources(paths)
    run_dir=Path(run_dir);sealed=strict_loads((run_dir/'sealed.json').read_bytes())
    spec_data=strict_loads((run_dir/'spec.json').read_bytes())
    if spec_data!=spec() or sealed['spec_sha256']!=sha(canonical(spec_data)):raise ValueError('objective/spec drift')
    expected_sources={n:sha(Path(__file__).with_name(n).read_bytes()) for n in SOURCES}
    if sealed['source_sha256']!=expected_sources or sealed['authority']!='DENY_ALL':raise ValueError('source or authority mismatch')
    for k in ('new_encoder_forwards','new_original_reader_forwards','new_future_sources'):
        if sealed[k]!=0:raise ValueError('fabricated fresh-model evidence')
    groups=sorted({r['group'] for r in source_rows});folds={}
    for i,g in enumerate(groups):
        expected={'schema':'hepta.merton.real-head.fold.v1','fold':i,'held_group':g,
            'train':[dict(r,label=labels[r['id']]) for r in source_rows if r['group']!=g],
            'held_inputs':[r for r in source_rows if r['group']==g],'provenance':provenance}
        actual=strict_loads((Path(material_dir)/f'fold-{i}.json').read_bytes())
        if actual!=expected:raise ValueError('prepared material changed from archived sources')
        folds[i]=expected
    wanted={(i,a,h) for i in range(4) for a in ARMS for h in HORIZONS}
    rows=sealed['rows'];keys=[(r['fold'],r['arm'],r['horizon_scenario']) for r in rows]
    if len(keys)!=len(set(keys)) or set(keys)!=wanted:raise ValueError('missing/duplicate/foreign lifecycle')
    totals={};row_audit=[]
    for r in rows:
        f=folds[r['fold']];pp=check_row(r,f,labels);held=f['held_inputs']
        q=qscore(held,pp,labels)
        key=(r['arm'],r['horizon_scenario'])
        total=totals.setdefault(key,{'correct':0,'brier_sum':0.0,'candidates':0,'questions':{},'cpu_ns':0,
                                    'wall_ns':0,'optimizer_steps':0,'selected_steps':[], 'candidate_decisions':{}})
        for x,p in zip(held,pp):
            total['correct']+=int(int(p>0.5)==labels[x['id']]);total['brier_sum']+=2*(p-labels[x['id']])**2
            total['candidate_decisions'][x['id']]=int(p>0.5)
        total['candidates']+=len(held);total['questions'].update(q)
        total['cpu_ns']+=r['lifecycle_cpu_ns'];total['wall_ns']+=r['lifecycle_wall_ns']
        total['optimizer_steps']+=r['update_steps_actually_executed'];total['selected_steps'].append(r['selected_steps'])
        row_audit.append({'fold':r['fold'],'arm':r['arm'],'horizon':r['horizon_scenario'],
                         'whole_question_successes':sum(q.values()),'selected_steps':r['selected_steps'],
                         'same_profile_reference_agreement':r['arm'] not in ('no_update','fixed_32')})
    if sum(t['optimizer_steps'] for t in totals.values())!=sealed['actual_update_steps']:raise ValueError('total step mismatch')
    trained=sum(f['steps']>0 for r in rows for f in r['fits'])
    if trained!=sealed['new_residual_heads_trained']:raise ValueError('fit-call census')
    summary=[]
    for (arm,h),t in totals.items():
        baseline=totals['no_update',h]
        if t['candidates']!=33 or len(t['questions'])!=8:raise ValueError('inflated unique source census')
        success=sum(t['questions'].values());cpu_ms=t['cpu_ns']/1_000_000
        summary.append({'arm':arm,'horizon_scenario_not_observed_reuse':h,
            'complete_questions':success,'question_count':8,'candidate_correct':t['correct'],'candidate_count':33,
            'two_class_brier':t['brier_sum']/33,'selected_steps_by_held_passage':t['selected_steps'],
            'actual_optimizer_steps_including_all_pilots':t['optimizer_steps'],
            'actual_lifecycle_cpu_ms':cpu_ms,'actual_lifecycle_wall_ms':t['wall_ns']/1_000_000,
            'local_marginal_net_at_declared_cpu_price':success-0.001*cpu_ms,
            'rescued_questions':sum(t['questions'][q] and not baseline['questions'][q] for q in t['questions']),
            'harmed_questions':sum(not t['questions'][q] and baseline['questions'][q] for q in t['questions']),
            'source_group_results':{g:sum(v for k,v in t['questions'].items() if k.startswith(g+'/')) for g in groups}})
    result={'schema':'hepta.merton.real-head.audit.v1','authority':'DENY_ALL','rows_verified':len(rows),
        'same_profile_choices_verified':sum(x['same_profile_reference_agreement'] for x in row_audit),
        'actual_optimizer_steps':sealed['actual_update_steps'],'actual_nonzero_fit_calls':trained,
        'real_head_training_executed':True,'fresh_encoder_forwards':0,'fresh_original_reader_forwards':0,
        'independent_source_passages':4,'unique_questions':8,'unique_candidates':33,
        'selections_are_not_additional_independent_tasks':True,'new_future_sources':0,
        'original_human_parquet_redownloaded':False,'source_sha256':expected_sources,
        'source_artifact_sha256':{k:v[1] for k,v in LOCKS.items()},
        'sealed_sha256':sha((run_dir/'sealed.json').read_bytes()),'summary':summary,'row_audit':row_audit,
        'complete_online_lifecycle_cost_qualified':False,'cost_scope':'current cached-input CPU; source acquisition and historic Encoder/Reader shown separately, no fresh energy/p99/serving claim',
        'independent_hardware_observer':False,'independent_signer':False,'general_fbsde':False,
        'production_or_model_promotion':False,'reader_gain_gate':any(x['rescued_questions']>x['harmed_questions'] for x in summary),
        'audit_cpu_ns':time.process_time_ns()-c,'audit_wall_ns':time.perf_counter_ns()-w}
    write_new(output,result);print({'verified':len(rows),'actual_optimizer_steps':sealed['actual_update_steps'],
                                  'reader_gain_gate':result['reader_gain_gate']})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for role in LOCKS:p.add_argument('--'+role.replace('_','-'),required=True,type=Path)
    for name in ('material','run','output'):p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();audit({r:getattr(a,r) for r in LOCKS},a.material,a.run,a.output)
