#!/usr/bin/env python3
"""Actual 5-parameter CPU Head SGD and paid investment-control study on E25's six original passages.

SOURCE CUSTODY: this worker reads the FOUR historic E15 TRAIN-ONLY fold labels,
but never E25 evaluation owner labels. Human scoring is a separate stage.
Same original ModernBERT Reader logits, not new Encoder calls; DENY_ALL.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, time, zipfile
from collections import defaultdict
from pathlib import Path

ROOT='TrillionniumFoundation/hepta-private-ci'
ORIGINAL='1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'
E25_ARCHIVES={
    'public':('b8ea439e3d3300d4c09e5fe1c568bcaa6403d0bda2a86dd42fd28c05e9c761b1','blind_slate.json'),
    'model':('d1ff527ddb9ee32f3e258c9cdb206449f242ac5f9b7b21e6d4f163b6c88706d1','new-original-candidate-audit.json'),
    'sealed':('d1ff527ddb9ee32f3e258c9cdb206449f242ac5f9b7b21e6d4f163b6c88706d1','sealed-new-six-blind-model-predictions.json'),
}
E15_ARCHIVES=((11949081037,'cc1c13323cb8377cbd5cdfa5c806796cb85505746e8509f21432d83a1ac4fb2d'),
              (11948881417,'8aa9f4b82a4478e9329cba5468adbea4a5a75bd9707b57358eb78a981cf0fd5e'),
              (11948806536,'e097d3a3bd210c1b8a84736cc6c219ea2605763c5b83b2c823dd136c00dedec5'),
              (11948681555,'8565aa2c841ad067d58e9ca04222247277de509bb4bdac38eb42e7662d13c6b2'))
FAMILY=('conditioned','mean_pool_query_fused','no_evidence','no_query')
STEPS=(0,8,32,48)
CONTROLS=('no_update','fixed_8','fixed_48','calibrated_neutral','calibrated_fixed_risk','ndu_discrete','ordinary_same_profile')
L2=0.001
LR=0.5
TARIFF=0.001  # declared utility per optimizer update; not currency or measured CPU price


def sha(data): return hashlib.sha256(data).hexdigest()
def canonical(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def parse(raw):
    def no_repeated(kvs):
        out={}
        for k,v in kvs:
            if k in out:raise ValueError('duplicate JSON key')
            out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=no_repeated,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))

def member(file,expected_sha,name):
    p=Path(file);raw=p.read_bytes()
    if sha(raw)!=expected_sha:raise ValueError('original ZIP SHA256 mismatch')
    if len(raw)>200000 or len(raw)<200:raise ValueError('invalid historical archive size')
    with zipfile.ZipFile(p) as z:
        if len({i.filename for i in z.infolist()})!=len(z.infolist()):raise ValueError('duplicate ZIP member')
        i=z.getinfo(name)
        if not 0<i.file_size<220000:raise ValueError('oversized historical data')
        return parse(z.read(name))

def sigmoid(z):
    if not math.isfinite(z) or abs(z)>15000:raise ValueError('divergent logit')
    return 1/(1+math.exp(-z)) if z>=0 else math.exp(z)/(1+math.exp(z))

def feature_rows(obs,question_count):
    if len(obs['rows']) not in (33,51):raise ValueError('wrong original candidate census')
    if set(obs['predictions'])!=set(FAMILY):raise ValueError('wrong original 4-Reader family')
    records=[];q=defaultdict(list)
    for i,r in enumerate(obs['rows']):
        raw=[]
        for arm in FAMILY:
            v=obs['predictions'][arm][i]
            if any(v[k]!=r[k] for k in ('task_id','source_group','question_slot')):raise ValueError('misaligned real Reader logits')
            logits=v['logits']
            if type(logits) is not list or len(logits)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>128 for x in logits):raise ValueError('invalid real logits')
            raw.append(float(logits[1]-logits[0]))
        key=(r['source_group'],r['question_slot']);q[key].append(tuple(raw))
        records.append((r,tuple(raw),key))
    if len(q)!=question_count or any(not 2<=len(v)<=8 for v in q.values()):raise ValueError('incomplete native answer slate')
    means={key:[sum(v[j] for v in seq)/len(seq) for j in range(4)] for key,seq in q.items()}
    out=[]
    for row,raw,key in records:
        v=[raw[j]-means[key][j] for j in range(4)]
        x=(v[0],v[1],v[2],v[1]*v[2])
        if any(not math.isfinite(t) or abs(t)>128 for t in x):raise ValueError('invalid question-centered geometry')
        out.append({'task_id':row['task_id'],'source_group':row['source_group'],'question_slot':row['question_slot'],'candidate_id':row['candidate_id'],'x':x})
    if len({r['task_id'] for r in out})!=len(out):raise ValueError('duplicate original native candidate')
    return out

def get_data(paths):
    old=member(paths['historic'],ORIGINAL,'multirc-native-candidate-audit/audit.json')
    slate=member(paths['public'],E25_ARCHIVES['public'][0],'blind_slate.json')
    e25=member(paths['model'],E25_ARCHIVES['model'][0],E25_ARCHIVES['model'][1])
    sealed=member(paths['model'],E25_ARCHIVES['sealed'][0],E25_ARCHIVES['sealed'][1])
    original=member(paths['historic'],ORIGINAL,'multirc-run/predictions.json')
    if (e25['model_snapshot_sha256']!=original['model_snapshot_sha256'] or e25['actual_candidate_count']!=51
        or e25['actual_reader_calls']!=204 or e25['evaluation_labels_loaded'] is not False or
        e25['previous_v1_training_unchanged'] is not True or sealed['human_validation_labels_read_before_seal'] is not False
        or sealed['slate_id']!=slate['slate_id'] or e25['slate_id']!=slate['slate_id']):
        raise ValueError('unverified original Reader or hidden E25 labels accessed')
    old_rows=feature_rows(old,8);new_rows=feature_rows(e25,12)
    if len(old_rows)!=33 or len(new_rows)!=51:raise ValueError('incomplete real features')
    old_groups=sorted({r['source_group'] for r in old_rows});new_groups=sorted({r['source_group'] for r in new_rows})
    if len(old_groups)!=4 or len(new_groups)!=6 or set(old_groups)&set(new_groups):raise ValueError('source groups not disjoint')
    source_slate=[(r['task_id'],r['candidate_id'],r['source_group'],r['question_slot']) for r in new_rows]
    actual_slate=[(c['task_id'],c['candidate_id'],g['source_group'],q['question_slot']) for g in slate['rows'] for q in g['questions'] for c in q['candidates']]
    if source_slate!=actual_slate:raise ValueError('not the full authentic E25 candidate slate')
    folds=[]
    for index,(art_id,expect) in enumerate(E15_ARCHIVES):
        t=member(paths['folds'][index],expect,f'training-fold-{index}.json')
        if t['schema']!='hepta.e15.owner-training-only-passage-fold.v1' or t['source_archive_sha256']!=ORIGINAL or t['held_labels_exposed'] is not False or t['production_accepted'] is not False or t['fold']!=index or t['held_group']!=old_groups[index]:
            raise ValueError('original human training-only E15 contract mismatch')
        lab={x['task_id']:x['label'] for x in t['training_label_rows']}
        allowed={r['task_id'] for r in old_rows if r['source_group']!=t['held_group']}
        if set(lab)!=allowed or len(lab)!=len(t['training_label_rows']) or any(type(v) is not int or v not in (0,1) for v in lab.values()):
            raise ValueError('held original human labels leaked into TRAIN')
        folds.append(lab)
    old_ref={r['task_id']:r for r in old_rows}
    return old_rows,new_rows,folds,slate,sealed

def scales(rows,train_ids):
    train=[r for r in rows if r['task_id'] in train_ids]
    if len(train)!=len(train_ids) or len(train)<8:raise ValueError('wrong training cohort')
    return tuple(max(1e-5,max(abs(r['x'][j]) for r in train)) for j in range(4))

def design(row,scale):return (1.,)+tuple(v/u for v,u in zip(row['x'],scale,strict=True))

def train_path(rows,labels,checkpoints=STEPS):
    if type(labels) is not dict or not 8<=len(labels)<=30:raise ValueError('invalid historic label isolation')
    norm=scales(rows,set(labels))
    data=[(design(r,norm),labels[r['task_id']]) for r in rows if r['task_id'] in labels]
    weights=[0.]*5;record={0:weights[:]};start=time.process_time_ns()
    for step in range(1,max(checkpoints)+1):
        grad=[0.]*5
        for x,y in data:
            p=sigmoid(sum(weights[j]*x[j] for j in range(5)))
            m=2*(p-y)*p*(1-p)
            for j in range(5):grad[j]+=m*x[j]
        for j in range(5):weights[j]-=LR*(grad[j]/len(data)+(L2*weights[j] if j else 0.0))
        if any(not math.isfinite(w) or abs(w)>128 for w in weights):raise ValueError('invalid actual SGD')
        if step in checkpoints:record[step]=weights[:]
    cpu=time.process_time_ns()-start
    return record,norm,cpu,max(checkpoints)

def prob(row,weights,scale):
    v=design(row,scale)
    return sigmoid(sum(a*b for a,b in zip(weights,v,strict=True)))

def pilot(old_rows,labels):
    started_total=time.process_time_ns()
    source={r['task_id']:r['source_group'] for r in old_rows}
    groups=sorted(set(source[t] for t in labels))
    if len(groups)!=3:raise ValueError('original historic three train groups required')
    judgments={k:[] for k in STEPS};receipt=[];ops=0;cpu=0
    for held in groups:
        fit_labels={k:y for k,y in labels.items() if source[k]!=held}
        params,scale,fit_cpu,updates=train_path(old_rows,fit_labels)
        ops+=updates;cpu+=fit_cpu
        held_rows=[r for r in old_rows if source[r['task_id']]==held]
        q=defaultdict(list)
        per_step={}
        for step in STEPS:
            start=time.process_time_ns()
            rps=[prob(r,params[step],scale) for r in held_rows]
            predict_cpu=time.process_time_ns()-start
            cpu+=predict_cpu
            for r,p in zip(held_rows,rps):q[r['question_slot']].append((p,labels[r['task_id']]))
            complete=sum(all(int(p>=.5)==y for p,y in rows) for rows in q.values())/len(q)
            brier=sum(2*(p-y)**2 for rows in q.values() for p,y in rows)/len(held_rows)
            score={'whole_question_success':complete,'brier':brier,'correct_candidates':sum(int(p>=.5)==y for rows in q.values() for p,y in rows),'source_group':held}
            per_step[step]=score
            judgments[step].append(score)
            q.clear()
        receipt.append({'held_original_group':held,'training_rows':len(fit_labels),'actual_updates':updates,'train_cpu_ns':fit_cpu,'parameters':{str(k):v for k,v in params.items()},'scale':scale,'observations':{str(k):v for k,v in per_step.items()}})
    if ops!=144:raise ValueError('missing actual calibration fits')
    return judgments,receipt,ops,time.process_time_ns()-started_total

def control_steps(judgments,arm):
    if arm=='no_update':return 0,0.0,{str(k):0.0 for k in STEPS}
    if arm=='fixed_8':return 8,0.0,{str(k):0.0 for k in STEPS}
    if arm=='fixed_48':return 48,0.0,{str(k):0.0 for k in STEPS}
    if arm not in CONTROLS:raise ValueError('unknown controller')
    alpha=0.0 if arm=='calibrated_neutral' else .25
    # Declared bounded observation-dependent preference; its same-objective
    # ordinary enumerator intentionally obtains EXACTLY the same result.
    if arm in ('ndu_discrete','ordinary_same_profile'):
        mean8=sum(x['whole_question_success'] for x in judgments[8])/3
        alpha=max(0.,min(.5,.25+(.5-mean8)/4))
    vals={}
    for k in STEPS:
        obs=judgments[k];mean=sum(x['whole_question_success'] for x in obs)/3
        worst=min(x['whole_question_success'] for x in obs)
        brier=sum(x['brier'] for x in obs)/3
        vals[str(k)]=(1-alpha)*mean+alpha*worst +.01*(1-brier)-TARIFF*k
    selected=max(STEPS,key=lambda k:(vals[str(k)],-k))
    return selected,alpha,vals

def study(paths):
    old,new,fold_labels,slate,sealed=get_data(paths)
    all_probs={arm:[] for arm in CONTROLS};all_weights={arm:[] for arm in CONTROLS}
    receipts=[];counters={arm:{'updates':0,'pilot_updates':0,'fit_cpu_ns':0,'pilot_cpu_ns':0,'prediction_cpu_ns':0,'selection_cpu_ns':0} for arm in CONTROLS}
    for fold,labels in enumerate(fold_labels):
        experiments={};run_receipt={}
        for arm in CONTROLS:
            is_search=arm not in ('no_update','fixed_8','fixed_48')
            if is_search:
                judgments,recorded,cal_steps,cal_cpu=pilot(old,labels)
                counters[arm]['pilot_updates']+=cal_steps
                counters[arm]['pilot_cpu_ns']+=cal_cpu
            else:
                judgments={};recorded=[]
            choose_started=time.process_time_ns()
            step,alpha,values=control_steps(judgments,arm)
            counters[arm]['selection_cpu_ns']+=time.process_time_ns()-choose_started
            start=time.process_time_ns()
            weights,scale,_,actual_updates=train_path(old,labels,tuple(k for k in STEPS if k<=step)) if step>0 else ({0:[0.]*5},scales(old,set(labels)),0,0)
            fit_cpu=time.process_time_ns()-start
            counters[arm]['updates']+=actual_updates;counters[arm]['fit_cpu_ns']+=fit_cpu
            start=time.process_time_ns()
            ps=[prob(r,weights[step],scale) for r in new]
            infer_cpu=time.process_time_ns()-start
            counters[arm]['prediction_cpu_ns']+=infer_cpu
            all_probs[arm].append(ps)
            all_weights[arm].append(weights[step])
            experiments[arm]={'chosen_steps':step,'dynamic_alpha':alpha,'selection_values':values,'scale':scale,'weights':weights[step],'optimizer_updates':actual_updates,'train_cpu_ns':fit_cpu,'predict_cpu_ns':infer_cpu,'pilot_observations':recorded}
        receipts.append({'fold':fold,'original_historic_training_rows':len(labels),'original_training_label_sha256':sha(canonical(labels)),'arm_results':experiments})
    outputs=[]
    for i,row in enumerate(new):
        outputs.append({'task_id':row['task_id'],'candidate_id':row['candidate_id'],'source_group':row['source_group'],'question_slot':row['question_slot'],
                        'probabilities':{arm:sum(all_probs[arm][fold][i] for fold in range(4))/4 for arm in CONTROLS}})
    old_reference={r['task_id']:r['probabilities']['e16_scaled_brier_5'] for r in sealed['rows']}
    if len(old_reference)!=51 or max(abs(r['probabilities']['fixed_48']-old_reference[r['task_id']]) for r in outputs)>1e-13:
        raise ValueError('FAIL: original E25 frozen Brier Head weights/probabilities not exactly reproduced')
    for arm in CONTROLS:
        c=counters[arm]
        c['actual_optimizer_updates_including_pilots']=c['updates']+c['pilot_updates']
        c['measured_cached_input_cpu_ns']=c['fit_cpu_ns']+c['pilot_cpu_ns']+c['prediction_cpu_ns']+c['selection_cpu_ns']
        c['declared_utility_update_fee']=TARIFF*c['actual_optimizer_updates_including_pilots']
        c['full_pretrained_reader_execution_cost_qualified']=False
    return {'schema':'hepta.ndu.e25-original-true-head-investment-study.v1','authority':'DENY_ALL','production_accepted':False,
            'posthoc_same_public_family_crosspassage':True,'prospective_source_generalization':False,
            'original_reader_forwards_this_study':0,'historical_actual_new_original_reader_forwards_reused':True,
            'new_original_training_labels_used':False,'new_original_holdout_labels_used':False,
            'source_ids_sha256':sha(canonical([r['task_id'] for r in new])),
            'readout_original_frozen_brier_48_exactly_reproduced':True,
            'source_commit':'1ab2615004fc524ca18d47aaa97f6dc59356d533',
            'original_reader_archive_sha256':ORIGINAL,
            'source_original_zip_sha256':{'public':E25_ARCHIVES['public'][0],'model':E25_ARCHIVES['model'][0]},
            'training_only_e15_original_sha256':[v[1] for v in E15_ARCHIVES],
            'tariff_utility_per_optimizer_update':TARIFF,
            'counters':counters,'physical_total_optimizer_updates_including_all_separate_pilots':sum(c['actual_optimizer_updates_including_pilots'] for c in counters.values()),'each_control_trains_own_pilot_not_shared_across_arms':True,'fold_records':receipts,'rows':outputs}

def write_once(path,obj):
    p=Path(path)
    if p.exists() or p.is_symlink():raise FileExistsError('refuse replace original sealed result')
    raw=canonical(obj)+b'\n';p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return sha(raw)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('historic','public','model','fold0','fold1','fold2','fold3','output'):p.add_argument('--'+k,required=True)
    a=vars(p.parse_args());paths={'historic':a['historic'],'public':a['public'],'model':a['model'],'folds':[a[f'fold{i}'] for i in range(4)]}
    body=study(paths);digest=write_once(a['output'],body)
    print(json.dumps({'seal_sha256':digest,'roles':'old_train_only_new_E25_blind','arms':len(CONTROLS),'rows':len(body['rows']),'cost_counts':{arm:r['actual_optimizer_updates_including_pilots'] for arm,r in body['counters'].items()},'production_accepted':False},sort_keys=True))
if __name__=='__main__':main()
