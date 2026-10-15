"""Independent E15 held-out original-human MultiRC score / numeric fit replay.

Re-downloads original human labels AFTER four trained fold predictions seal.
Neither optimistic data-reuse counts nor model-tuned thresholds grant authority.
No E15 original-human outcome is claimed from the label-blind fitter.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from math import exp, isclose, isfinite
from pathlib import Path
from e14_multirc_route import (ARMS, ARCHIVE_SHA, OBS_ID, SLATE, positive,
                               read_prelabel, strict_json, write_once)
from e14_multirc_score import original_labels, read_validation, historical_owner_score, VAL_SHA

SCHEMA='hepta.e15.independent-original-human-lopo-head-score.v1'
TRAIN_SCHEMA='hepta.e15.owner-training-only-passage-fold.v1'
PRED_SCHEMA='hepta.e15.label-separated-trained-cell-head.v1'
METHODS=('learned_linear_5','learned_gated_3')


def sha(obj):
    from json import dumps
    return sha256(dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def sigmoid(value):
    if not isfinite(value) or abs(value)>10000:raise ValueError('invalid score')
    a=exp(-abs(value))
    return (1/(1+a)) if value>=0 else (a/(1+a))


def independent_features(obs):
    # Rebuild all features WITHOUT importing the proposer/optimizer code.
    sums={};rows=obs['rows']
    logit=[]
    for i,r in enumerate(rows):
        li=tuple(obs['predictions'][a][i]['logits'][1]-obs['predictions'][a][i]['logits'][0] for a in ARMS)
        if len(li)!=4 or any(type(x) not in (float,int) or not isfinite(x) or abs(x)>100 for x in li):
            raise ValueError('nonfinite historical pretrained logits')
        logit.append(li)
        key=(r['source_group'],r['question_slot'])
        sums.setdefault(key,[]).append(li)
    if len(sums)!=8:raise ValueError('lost independent source question')
    means={k:tuple(sum(row[j] for row in x)/len(x) for j in range(4)) for k,x in sums.items()}
    feature=[]
    for meta,scores in zip(rows,logit,strict=True):
        key=(meta['source_group'],meta['question_slot'])
        p=tuple(sigmoid(s) for s in scores)
        feature.append(dict(task_id=meta['task_id'],group=meta['source_group'],
                            question=meta['question_slot'],candidate_id=meta['candidate_id'],
                            x=(1.0,)+scores,
                            gate=(1.0,scores[1]-means[key][1], scores[2]-means[key][2]),p=p))
    return feature


def independently_fit(data,train_labels,method):
    """Separate gradient implementation: Brier loss, exact 48 fixed full-batch steps."""
    count=5 if method=='learned_linear_5' else 3
    selected=[(v,train_labels[v['task_id']]) for v in data if v['task_id'] in train_labels]
    if len(selected)<20 or len(selected)>30:raise ValueError('independent train group inventory')
    weight=[0.0 for _ in range(count)]
    for _step in range(48):
        derivatives=[]
        for record,truth in selected:
            xx=record['x'] if count==5 else record['gate']
            h=sigmoid(sum(a*b for a,b in zip(weight,xx,strict=True)))
            if count==5:
                pred=h
                scale=2*(pred-truth)*h*(1-h)
            else:
                pred=record['p'][0]*(1-h)+record['p'][1]*h
                scale=2*(pred-truth)*(record['p'][1]-record['p'][0])*h*(1-h)
            derivatives.append(tuple(scale*a for a in xx))
        for j in range(count):
            average=sum(d[j] for d in derivatives)/len(selected)
            penalty=(0.001*weight[j]) if j>0 else 0
            weight[j]=weight[j]-0.5*(average+penalty)
    if any(not isfinite(w) for w in weight):raise ValueError('failed independent physical fit')
    return weight


def independent_probability(record,weight,method):
    if method=='learned_linear_5':
        return sigmoid(sum(a*b for a,b in zip(record['x'],weight,strict=True)))
    g=sigmoid(sum(a*b for a,b in zip(record['gate'],weight,strict=True)))
    return record['p'][0]*(1-g)+record['p'][1]*g


def derive_training_material(obs,labels,fold):
    # Independent re-derivation from the ORIGINAL annotations, after all
    # candidate folds were sealed and historical source bytes re-fetched.
    groups=sorted({r['source_group'] for r in obs['rows']})
    held=groups[fold]
    training=[{'task_id':r['task_id'],'label':labels[r['task_id']]}
              for r in obs['rows'] if r['source_group']!=held]
    return dict(schema=TRAIN_SCHEMA,authority='DENY_ALL',fold=fold,held_group=held,
                original_observation_id=OBS_ID,source_archive_sha256=ARCHIVE_SHA,
                slate_id=SLATE,original_validation_human_label_source_sha256=VAL_SHA,
                training_label_rows=training,held_labels_exposed=False,
                future_observation_window=False,production_accepted=False)


def verify_score(archive, validation_parquet, sealed_paths, seals):
    if len(sealed_paths)!=4 or len(seals)!=4:
        raise ValueError('all four original leave-passage-out seals required')
    obs=read_prelabel(archive)
    labels=original_labels(read_validation(validation_parquet),obs['rows'])
    owner=historical_owner_score(archive)
    x=independent_features(obs)
    groups=sorted({r['source_group'] for r in obs['rows']})
    if len(groups)!=4 or len(x)!=33 or set(labels)!={r['task_id'] for r in x}:
        raise ValueError('human annotations or original feature census incomplete')
    base={arm:{'correct':0,'brier_sum':0.,'group':{}} for arm in ARMS}
    head={arm:{'correct':0,'brier_sum':0.,'group':{}} for arm in METHODS}
    held_seen=set();train_cost=0; infer_cost=0;fold_receipts=[]; all_prediction_ids=set()
    for fold,(path,expected_sha) in enumerate(zip(sealed_paths,seals,strict=True)):
        raw=Path(path).read_bytes()
        if sha256(raw).hexdigest()!=expected_sha:
            raise ValueError('unsealed or substituted fold prediction')
        record=strict_json(raw)
        if (type(record) is not dict or set(record)!={
            'schema','authority','original_archive_sha256','original_observation_id',
            'fold','held_group','train_only_label_input_sha256','train_only_group_count',
            'held_original_human_labels_accessed','training_profile','new_pretrained_forwards',
            'original_reader_weights_unchanged','full_training_cost_included','methods',
            'weights','meters','predictions','production_accepted',
            'causal_improvement_established'} or record['schema']!=PRED_SCHEMA
                or record['authority']!='DENY_ALL' or record['original_archive_sha256']!=ARCHIVE_SHA
                or record['original_observation_id']!=OBS_ID or type(record['fold']) is not int
                or record['fold']!=fold or record['held_group']!=groups[fold]
                or record['train_only_group_count']!=3
                or record['held_original_human_labels_accessed'] is not False
                or record['new_pretrained_forwards']!=0 or record['full_training_cost_included'] is not False
                or record['original_reader_weights_unchanged'] is not True
                or record['training_profile']!='48-full-batch-SGD-0.5-Brier-L2-0.001'
                or record['production_accepted'] is not False
                or record['causal_improvement_established'] is not False
                or record['methods']!=list(METHODS)
                or type(record['weights']) is not dict or set(record['weights'])!=set(METHODS)
                or type(record['meters']) is not dict or set(record['meters'])!=set(METHODS)):
            raise ValueError('unsupported promoted or compromised fold')
        training=derive_training_material(obs,labels,fold)
        if record['train_only_label_input_sha256']!=sha(training):
            raise ValueError('training-only label lineage changed')
        ytrain={r['task_id']:r['label'] for r in training['training_label_rows']}
        held=[r for r in x if r['group']==groups[fold]]
        pred=record['predictions']
        if type(pred) is not list or len(pred)!=len(held):
            raise ValueError('incomplete held prediction slate')
        weights={}
        for method in METHODS:
            actual=record['weights'][method]
            reference=independently_fit(x,ytrain,method)
            if (type(actual) is not list or len(actual)!=len(reference)
                    or any(type(z) is not float or not isfinite(z) or
                           not isclose(z,r,abs_tol=2e-12,rel_tol=0) for z,r in zip(actual,reference,strict=True))):
                raise ValueError('forged learned Head parameters')
            weights[method]=reference
            meter=record['meters'][method]
            if (type(meter) is not dict or set(meter)!={'train_cpu_ns','held_cpu_ns','physical_parameter_count','train_steps'}
                    or any(type(meter[k]) is not int or not 0<meter[k]<10**12 for k in ('train_cpu_ns','held_cpu_ns'))
                    or meter['physical_parameter_count']!=len(actual) or meter['train_steps']!=48):
                raise ValueError('unaccounted training or inference work')
            train_cost+=meter['train_cpu_ns'];infer_cost+=meter['held_cpu_ns']
        for original,candidate in zip(held,pred,strict=True):
            if (type(candidate) is not dict or set(candidate)!={'task_id','source_group','question_slot','candidate_id','probs'}
                    or candidate['task_id']!=original['task_id']
                    or candidate['source_group']!=groups[fold]
                    or candidate['question_slot']!=original['question']
                    or candidate['candidate_id']!=original['candidate_id']
                    or type(candidate['probs']) is not dict or set(candidate['probs'])!=set(METHODS)):
                raise ValueError('held data/content was altered')
            task=original['task_id']
            if task in all_prediction_ids:raise ValueError('overlapping held samples')
            all_prediction_ids.add(task)
            truth=labels[task]
            for method in METHODS:
                pp=candidate['probs'][method];expected=independent_probability(original,weights[method],method)
                if type(pp) is not float or not isfinite(pp) or not isclose(pp,expected,abs_tol=2e-12,rel_tol=0):
                    raise ValueError('learned real-task output not reproducible')
                b=head[method];b['correct']+=int((pp>=.5)==bool(truth));b['brier_sum']+=2*(pp-truth)**2
                b['group'].setdefault(groups[fold],[]).append(int((pp>=.5)==bool(truth)))
        held_seen.add(groups[fold]);fold_receipts.append({'fold':fold,'held_group':groups[fold],
                               'held_count':len(held),'learned_weight_replay':True})
    if held_seen!=set(groups) or all_prediction_ids!=set(labels):
        raise ValueError('not a complete four-passage out-of-group panel')
    for original in x:
        truth=labels[original['task_id']]
        for j,arm in enumerate(ARMS):
            pp=original['p'][j]
            b=base[arm];b['correct']+=int((pp>=.5)==bool(truth));b['brier_sum']+=2*(pp-truth)**2
            b['group'].setdefault(original['group'],[]).append(int((pp>=.5)==bool(truth)))
    for arm in ARMS:
        reference=owner['results'][arm]
        if (base[arm]['correct']!=reference['correct'] or
                not isclose(base[arm]['brier_sum']/33,reference['brier'],abs_tol=2e-12,rel_tol=0)):
            raise ValueError('original four Reader human-label result changed')
    results={}
    for arm,metrics in {**base,**head}.items():
        results[arm]={"correct":metrics['correct'],"total":33,
            "accuracy":metrics['correct']/33,"brier":metrics['brier_sum']/33,
            "passage_correct":{k:sum(v) for k,v in metrics['group'].items()},
            "passage_total":{k:len(v) for k,v in metrics['group'].items()}}
    qgroups={}
    for original in x:
        k=(original['group'],original['question'])
        qgroups.setdefault(k,[]).append((original['task_id'],original['p'][0],labels[original['task_id']]))
    if len(qgroups)!=8 or any(set(y for _,_,y in group)!={0,1} for group in qgroups.values()):
        raise ValueError('missing mixed original human-label candidate group')
    spans=[max(p for _,p,_ in v)-min(p for _,p,_ in v) for v in qgroups.values()]
    exact_ties=sum(v==0 for v in spans)
    if sum(v<=.001 for v in spans)!=8 or exact_ties!=4:
        raise ValueError('original frozen Reader within-question discrimination result changed')
    return dict(schema=SCHEMA,authority='DENY_ALL',source_archive_sha256=ARCHIVE_SHA,
                human_validation_sha256=VAL_SHA,model_forwards_new=0,physical_held_label_observer=False,
                original_question_count=8,original_candidate_count=33,original_passage_groups=4,
                original_human_label_mixed_question_count=8,conditioned_exact_tie_question_count=exact_ties,
                conditioned_span_le_0_001_question_count=8,
                fold_receipts=fold_receipts,summary=results,
                self_reported_CPU_ns={'head_training':train_cost,'held_head_inference':infer_cost},
                original_pretrained_work_reused_not_reexecuted=True,
                training_data_were_same_validation_source_family=True,
                independent_future_generations_established=False,
                matched_whole_service_cost_established=False,
                trained_cell_head_production_admitted=False,
                source_group_independence_and_statistical_power_not_established=True,
                production_accepted=False)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for i in range(4):
        ap.add_argument(f'--fold-{i}',required=True)
        ap.add_argument(f'--fold-{i}-sha256',required=True)
    for name in ('archive','validation-parquet','output'):
        ap.add_argument('--'+name,required=True)
    args=ap.parse_args()
    files=[getattr(args,f'fold_{i}') for i in range(4)]
    hashes=[getattr(args,f'fold_{i}_sha256') for i in range(4)]
    result=verify_score(args.archive,args.validation_parquet,files,hashes)
    print(write_once(args.output,result),'DENY_ALL')

if __name__=='__main__':main()
