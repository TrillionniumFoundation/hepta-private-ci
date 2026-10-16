#!/usr/bin/env python3
"""Independent NumPy numerical + original human reviewer of E25 5P investment controls.

Never imports producer's trainer, optimizer, feature constructor or selector.
Same-author separate implementation, NOT independent signer/hardware attestation.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, zipfile
from pathlib import Path
from collections import defaultdict
import numpy as np

SOURCE={'historic':'1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17',
'public':'b8ea439e3d3300d4c09e5fe1c568bcaa6403d0bda2a86dd42fd28c05e9c761b1',
'model':'d1ff527ddb9ee32f3e258c9cdb206449f242ac5f9b7b21e6d4f163b6c88706d1',
'owner':'89fce74a76a5abe4a43ea9c28ea120b9b81b76cb63e3ade198a80077f8035b35',
'score':'469bb6ef89c70f9329564e794cad2dff4b4fe603e5255971078aaf9500eb6eb8'}
FOLDS=('cc1c13323cb8377cbd5cdfa5c806796cb85505746e8509f21432d83a1ac4fb2d',
'8aa9f4b82a4478e9329cba5468adbea4a5a75bd9707b57358eb78a981cf0fd5e',
'e097d3a3bd210c1b8a84736cc6c219ea2605763c5b83b2c823dd136c00dedec5',
'8565aa2c841ad067d58e9ca04222247277de509bb4bdac38eb42e7662d13c6b2')
ARMS=('conditioned','mean_pool_query_fused','no_evidence','no_query')
CONTROL=('no_update','fixed_8','fixed_48','calibrated_neutral','calibrated_fixed_risk','ndu_discrete','ordinary_same_profile')
LEVELS=(0,8,32,48)


def sha(data):return hashlib.sha256(data).hexdigest()
def canonical(o):return json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def read_zip(path,expected,name):
    p=Path(path)
    if sha(p.read_bytes())!=expected:raise ValueError('immutable upstream artifact bytes altered')
    with zipfile.ZipFile(p) as z:
        if z.namelist().count(name)!=1:raise ValueError('duplicate or missing original member')
        raw=z.read(name)
        if not 0<len(raw)<220000:raise ValueError('unbounded original content')
        return json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('invalid nonfinite data')))

def centered(obs,n_questions):
    rows=obs['rows'];d=defaultdict(list);vals=[]
    for i,row in enumerate(rows):
        m=[]
        for name in ARMS:
            sample=obs['predictions'][name][i]
            if sample['task_id']!=row['task_id'] or sample['source_group']!=row['source_group']:
                raise ValueError('misordered original Reader evidence')
            m.append(float(sample['logits'][1]-sample['logits'][0]))
        key=(row['source_group'],row['question_slot'])
        vals.append((row,key,np.asarray(m,dtype=np.float64)))
        d[key].append(m)
    if len(d)!=n_questions or len(rows) not in (33,51):raise ValueError('invalid question geometry')
    means={k:np.mean(np.asarray(v,dtype=np.float64),axis=0) for k,v in d.items()}
    out=[]
    for row,key,v in vals:
        x=v-means[key]
        out.append((row['task_id'],row['source_group'],row['question_slot'],row['candidate_id'],np.asarray([x[0],x[1],x[2],x[1]*x[2]],dtype=np.float64)))
    if len({r[0] for r in out})!=len(out):raise ValueError('repeated actual answer')
    return out

def numpy_path(rows,labels,levels=LEVELS):
    selected=[r for r in rows if r[0] in labels]
    if len(selected)!=len(labels) or len(selected)<8 or len(selected)>30:raise ValueError('wrong original training label coverage')
    raw=np.asarray([r[4] for r in selected],dtype=np.float64)
    norm=np.maximum(1e-5,np.max(np.abs(raw),axis=0))
    design=np.column_stack((np.ones(len(raw),dtype=np.float64),raw/norm[None,:]))
    y=np.asarray([labels[r[0]] for r in selected],dtype=np.float64)
    w=np.zeros(5,dtype=np.float64)
    result={0:w.copy()}
    for t in range(1,max(levels)+1):
        scores=np.matmul(design,w)
        probs=np.where(scores>=0,1.0/(1.0+np.exp(-scores)),np.exp(scores)/(1.0+np.exp(scores)))
        influence=2.0*(probs-y)*probs*(1.0-probs)
        grad=np.matmul(influence,design)/len(y)
        grad[1:]+=.001*w[1:]
        w=w-.5*grad
        if t in levels:result[t]=w.copy()
    return result,norm

def predict(rows,w,scale):
    arr=np.asarray([r[4] for r in rows],dtype=np.float64)
    x=np.column_stack((np.ones(len(arr),dtype=np.float64),arr/scale[None,:]))
    z=np.matmul(x,w)
    return np.where(z>=0,1/(1+np.exp(-z)),np.exp(z)/(1+np.exp(z)))

def nested_review(records,labels,producer):
    seen_groups=sorted({r[1] for r in records if r[0] in labels})
    if len(seen_groups)!=3:raise ValueError('invalid original source group count')
    complete={step:[] for step in LEVELS}
    if len(producer)!=3:raise ValueError('missing inner physical pilot')
    actual=0
    for p,g in zip(producer,seen_groups,strict=True):
        if p['held_original_group']!=g or p['actual_updates']!=48:raise ValueError('pilot source/order or work mismatch')
        lab={k:y for k,y in labels.items() if next(r[1] for r in records if r[0]==k)!=g}
        weights,scale=numpy_path(records,lab)
        actual+=48
        if not np.allclose(scale,p['scale'],rtol=0,atol=1e-12):raise ValueError('scaled pilot leakage')
        held=[r for r in records if r[1]==g]
        for k in LEVELS:
            if not np.allclose(weights[k],p['parameters'][str(k)],rtol=0,atol=2e-12):raise ValueError('SGD pilot checkpoint mismatch')
            pr=predict(held,weights[k],scale)
            groups=defaultdict(list)
            for r,value in zip(held,pr):groups[r[2]].append((float(value),labels[r[0]]))
            acc=sum(all(int(x>=.5)==y for x,y in xs) for xs in groups.values())/len(groups)
            brier=sum(2*(value-labels[r[0]])**2 for r,value in zip(held,pr))/len(held)
            check=p['observations'][str(k)]
            if abs(acc-check['whole_question_success'])>1e-15 or abs(brier-check['brier'])>2e-12:
                raise ValueError('question-level pilot outcomes tampered')
            complete[k].append((acc,brier))
    if actual!=144:raise ValueError('pilot update census drift')
    return complete,actual

def choose_reference(points,arm):
    if arm=='no_update':return 0,0.0
    if arm=='fixed_8':return 8,0.0
    if arm=='fixed_48':return 48,0.0
    alpha=0. if arm=='calibrated_neutral' else .25
    if arm in ('ndu_discrete','ordinary_same_profile'):
        mean8=sum(v[0] for v in points[8])/3
        alpha=min(.5,max(0.,.25+(.5-mean8)/4))
    values={k:(1-alpha)*sum(v[0] for v in points[k])/3+alpha*min(v[0] for v in points[k])+.01*(1-sum(v[1] for v in points[k])/3)-.001*k for k in LEVELS}
    return sorted(LEVELS,key=lambda k:(-values[k],k))[0],alpha

def recount(paths,seal_path):
    raw=Path(seal_path).read_bytes();s=json.loads(raw)
    if (s['authority']!='DENY_ALL' or s['production_accepted'] is not False or s['new_original_training_labels_used'] or s['new_original_holdout_labels_used'] or s['original_reader_forwards_this_study']!=0):
        raise ValueError('producer NDU research data custody violation')
    old=read_zip(paths['historic'],SOURCE['historic'],'multirc-native-candidate-audit/audit.json')
    new=read_zip(paths['model'],SOURCE['model'],'new-original-candidate-audit.json')
    model_seal=read_zip(paths['model'],SOURCE['model'],'sealed-new-six-blind-model-predictions.json')
    public=read_zip(paths['public'],SOURCE['public'],'blind_slate.json')
    owner=read_zip(paths['owner'],SOURCE['owner'],'human-labels.json')
    external=read_zip(paths['score'],SOURCE['score'],'fixed-pretrained-new-six-original-human-question-score.json')
    if (s['readout_original_frozen_brier_48_exactly_reproduced'] is not True or external['human_truth_read_only_after_seal'] is not True or owner['external_observer_authenticated'] is not False):
        raise ValueError('invalid original E25 labels seal')
    orig=centered(old,8);evalrows=centered(new,12)
    expected=[(r[0],r[3],r[1],r[2]) for r in evalrows]
    got=[(r['task_id'],r['candidate_id'],r['source_group'],r['question_slot']) for r in s['rows']]
    if got!=expected or len(got)!=51:raise ValueError('attempt omitted or forged original candidate')
    new_groups={r[1] for r in evalrows};old_groups={r[1] for r in orig}
    if len(new_groups)!=6 or len(old_groups)!=4 or new_groups&old_groups or len(s['fold_records'])!=4:raise ValueError('source-disjoint geometry falsified')
    if set(owner['labels'])!={r[0] for r in evalrows}:raise ValueError('wrong native original human answer owner')
    reviewer_profiles={arm:[] for arm in CONTROL};counters={arm:{'update':0,'pilot':0} for arm in CONTROL}
    for fold in range(4):
        f=s['fold_records'][fold]
        history=read_zip(paths['folds'][fold],FOLDS[fold],f'training-fold-{fold}.json')
        labels={p['task_id']:p['label'] for p in history['training_label_rows']}
        if (f['fold']!=fold or f['original_historic_training_rows']!=len(labels) or f['original_training_label_sha256']!=sha(canonical(labels)) or
                set(labels)!={r[0] for r in orig if r[1]!=history['held_group']}):raise ValueError('old E15 held labels entered trainer')
        for arm in CONTROL:
            c=f['arm_results'][arm]
            if arm not in ('no_update','fixed_8','fixed_48'):
                points,paid=nested_review(orig,labels,c['pilot_observations'])
            else:
                if c['pilot_observations']:raise ValueError('fixed control falsely charged a pilot')
                points,paid={},0
            chosen,alpha=choose_reference(points,arm)
            if c['chosen_steps']!=chosen or abs(c['dynamic_alpha']-alpha)>1e-14:
                raise ValueError('controller choice differs from separately computed objective')
            expectedw,norm=numpy_path(orig,labels,(0,chosen) if chosen else (0,))
            if not np.allclose(c['weights'],expectedw[chosen],atol=2e-12,rtol=0) or not np.allclose(c['scale'],norm,atol=2e-12,rtol=0):
                raise ValueError('real original Head weights diverged or forged')
            if c['optimizer_updates']!=chosen:raise ValueError('selected output used unpaid SGD')
            reviewer_profiles[arm].append(predict(evalrows,expectedw[chosen],norm))
            counters[arm]['update']+=chosen
            if arm not in ('no_update','fixed_8','fixed_48'):counters[arm]['pilot']+=paid
    if s.get('each_control_trains_own_pilot_not_shared_across_arms') is not True or s.get('physical_total_optimizer_updates_including_all_separate_pilots') != sum(z['update']+z['pilot'] for z in counters.values()):
        raise ValueError('shared speculative pilot masquerading as separately executed learning')
    metrics={};byq=defaultdict(list)
    for r in evalrows:byq[(r[1],r[2])].append(r[0])
    if len(byq)!=12 or any(not 2<=len(ids)<=8 for ids in byq.values()):raise ValueError('not 12 full genuine questions')
    predictions={r['task_id']:r for r in s['rows']}
    for arm in CONTROL:
        c=s['counters'][arm]
        if (c['updates'],c['pilot_updates'],c['actual_optimizer_updates_including_pilots'])!=(counters[arm]['update'],counters[arm]['pilot'],counters[arm]['update']+counters[arm]['pilot']):
            raise ValueError('training-cost conservation fails')
        if c['measured_cached_input_cpu_ns']!=sum(c[k] for k in ('fit_cpu_ns','pilot_cpu_ns','prediction_cpu_ns','selection_cpu_ns')) or c['measured_cached_input_cpu_ns']<=0:
            raise ValueError('missing uncharged local phase')
        p=np.mean(np.stack(reviewer_profiles[arm]),axis=0)
        for r,v in zip(evalrows,p):
            if abs(float(v)-predictions[r[0]]['probabilities'][arm])>3e-13:
                raise ValueError('held prediction not independently reproduced')
        y=np.asarray([owner['labels'][r[0]] for r in evalrows],dtype=np.int64)
        correct=(p>=.5)==y
        perq={f'{group}/{slot}':int(all(((predictions[t]['probabilities'][arm]>=.5)==bool(owner['labels'][t])) for t in task_ids)) for (group,slot),task_ids in byq.items()}
        metrics[arm]={'complete_questions':sum(perq.values()),'correct_candidates':int(sum(correct)),'brier':float(np.mean(2*(p-y)**2)),
                      'question_outcomes':perq,'optimizer_updates_including_pilots':c['actual_optimizer_updates_including_pilots'],
                      'recorded_local_cached_cpu_ns':c['measured_cached_input_cpu_ns'],
                      'declared_update_tariff_utility':c['declared_utility_update_fee'],
                      'complete_service_TCO_qualified':False}
    legacy={r['task_id']:r['probabilities']['e16_scaled_brier_5'] for r in model_seal['rows']}
    if any(abs(legacy[x['task_id']]-x['probabilities']['fixed_48'])>3e-13 for x in s['rows']):raise ValueError('E16 registered source regression')
    if external['methods']['e16_scaled_brier_5']['correct_candidates']!=metrics['fixed_48']['correct_candidates'] or external['methods']['e16_scaled_brier_5']['complete_questions']!=metrics['fixed_48']['complete_questions']:
        raise ValueError('E25 independent original human source score disagrees')
    if any(abs(s['rows'][i]['probabilities']['ndu_discrete']-s['rows'][i]['probabilities']['ordinary_same_profile'])>3e-13 for i in range(51)):
        raise ValueError('NDU and same-objective ordinary control differ without explanation')
    return {'schema':'hepta.ndu.e25-true-head-investment-independent-audit.v1','authority':'DENY_ALL','production_accepted':False,
            'source_family_new':False,'new_source_passage_count':6,'new_question_count':12,'new_candidate_count':51,
            'historic_old_passages_used_in_training':4,'E25_original_human_labels_loaded_after_sealed_head':True,
            'same_author_separate_implementation':True,'independent_authenticated_publisher':False,
            'new_fresh_encoder_calls':0,'new_model_weights_trained':True,
            'full_service_cost_qualified':False,'ndu_specific_superiority_established':False,
            'source_model':SOURCE['model'],'source_owner':SOURCE['owner'],'producer_sha256':sha(raw),
            'metrics':metrics}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('historic','public','model','owner','score','fold0','fold1','fold2','fold3','seal','output'):p.add_argument('--'+key,required=True)
    a=vars(p.parse_args());out=recount({'historic':a['historic'],'public':a['public'],'model':a['model'],'owner':a['owner'],'score':a['score'],'folds':[a[f'fold{i}'] for i in range(4)]},a['seal'])
    p=Path(a['output']);
    if p.exists() or p.is_symlink():raise FileExistsError('refuse overwrite independent review')
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(canonical(out)+b'\n')
    print(json.dumps({'status':'DENY_ALL','verified_native_candidates':51,'real_original_training_rederived':True,'results':{k:[v['complete_questions'],v['correct_candidates'],v['optimizer_updates_including_pilots']] for k,v in out['metrics'].items()}},sort_keys=True))
if __name__=='__main__':main()
