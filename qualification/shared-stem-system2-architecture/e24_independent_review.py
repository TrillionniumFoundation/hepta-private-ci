#!/usr/bin/env python3
"""Independent E24 original MultiRC human scorer, post prediction-seal ONLY.

Does not import the producer. Rebuilds frozen real model margins, all four-fold
train-only feature normalizers, and all 80 float64 SGD steps with NumPy. It
compares the sealed held predictions against independently fitted weights before
reopening the E16 original human training-only owner union for scoring. Public
source/owner hashes are integrity pins, not independent human signatures.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
from zipfile import ZipFile
import numpy as np

MODEL_SHA='1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'
OBS='7e4a0dc4ff48688b1ace0640a3290ee90011487843384a30565b65d3d240e7a5'
VAL_SHA='5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'
E16_OWNER_SHA=('cb303e78cbbb1c9db400591e8a372609766a91213ddbdd323acd119ae1afb976',
               'd17c501eb02709ede687c72e7f5c6d6a32e776d365e7f1bbd01ec4587048d4f5',
               '06c0e9abec8d28d09e5b9e6640bfb806b0d5759916d08ed8301620038de31794',
               '85f304240802952b5d2909e73e4548aef23073eb348b43c33d19e1cb106ea5f8')
E15_OWNER_SHA=('cc1c13323cb8377cbd5cdfa5c806796cb85505746e8509f21432d83a1ac4fb2d',
               '8aa9f4b82a4478e9329cba5468adbea4a5a75bd9707b57358eb78a981cf0fd5e',
               'e097d3a3bd210c1b8a84736cc6c219ea2605763c5b83b2c823dd136c00dedec5',
               '8565aa2c841ad067d58e9ca04222247277de509bb4bdac38eb42e7662d13c6b2')
E15_SCORE_SHA=('f332ab92181a0e088d941dbf4c77165ab2e4c40e48e9bbda4915e8d1543aceb8',
               '63da90cb7da7f2f6ef478e44731e548a62a4b3c1a071593864f23b5896290acc')
E16_SCORE_SHA=('8f8ac3c4ed99b4859b9d0258d19c2afdaca1ac194a806130196b3d9980aa91a4',
               '8dc6e34ff5d70eca8d4986a87e574c1cf2a0926b6c2dcf7b972c84e1954d8b60')
FEATURE_ARMS=('conditioned','mean_pool_query_fused','no_evidence')
METHODS=('bce5','pairwise5')

class Denied(ValueError):pass

def require(b,msg):
    if not b:raise Denied(msg)

def canonical(b):
    def unique(kvs):
        d={}
        for k,v in kvs:
            require(k not in d,'duplicate JSON field')
            d[k]=v
        return d
    return json.loads(b, object_pairs_hook=unique,
        parse_constant=lambda v: (_ for _ in ()).throw(Denied('nonfinite JSON')))

def artifact(path,pin,member):
    p=Path(path)
    require(p.is_file() and not p.is_symlink() and 0<p.stat().st_size<2_000_000,'missing ZIP')
    raw=p.read_bytes();require(sha256(raw).hexdigest()==pin,'outer ZIP SHA mismatch')
    with ZipFile(p) as z:
        members=z.namelist()
        require(member in members and len(set(members))==len(members),'bad ZIP inventory')
        return canonical(z.read(member))

def frozen_inputs(path):
    audit=artifact(path,MODEL_SHA,'multirc-native-candidate-audit/audit.json')
    require(audit['observation_id']==OBS and audit['production_authorized'] is False and
            audit['evaluation_labels_loaded'] is False and len(audit['rows'])==33,
            'unqualified original pretrained panel')
    rows=[]
    for i,row in enumerate(audit['rows']):
        margin=[]
        for key in FEATURE_ARMS:
            pr=audit['predictions'][key][i]
            require(pr['task_id']==row['task_id'] and pr['source_group']==row['source_group'],
                    'altered original model pairing')
            margin.append(float(pr['logits'][1]-pr['logits'][0]))
        rows.append((row['task_id'],row['source_group'],row['question_slot'],np.asarray(margin,dtype=np.float64)))
    groups=sorted({r[1] for r in rows})
    require(len(groups)==4 and len({r[0] for r in rows})==33 and
            len({(r[1],r[2]) for r in rows})==8,'bad genuine test census')
    return rows,groups

def independent_original_labels(rows,groups,paths):
    require(len(paths)==4,'four original human label-owner ZIPs required')
    src={tid:g for tid,g,_,_ in rows}
    human=defaultdict(list)
    for i,path in enumerate(paths):
        d=artifact(path,E16_OWNER_SHA[i],f'training-fold-{i}.json')
        require(d['schema']=='hepta.e15.owner-training-only-passage-fold.v1' and
                d['held_group']==groups[i] and d['fold']==i and
                d['source_archive_sha256']==MODEL_SHA and
                d['original_validation_human_label_source_sha256']==VAL_SHA and
                d['authority']=='DENY_ALL' and d['production_accepted'] is False and
                d['held_labels_exposed'] is False,'changed independent human owner')
        expected={tid for tid,g in src.items() if g!=groups[i]}
        given={r['task_id'] for r in d['training_label_rows']}
        require(given==expected and len(d['training_label_rows'])==len(expected),
                'E16 owner exposed held labels or omitted training')
        for label in d['training_label_rows']:
            require(type(label['label']) is int and label['label'] in (0,1),
                    'wrong human binary answer label')
            human[label['task_id']].append(label['label'])
    require(set(human)==set(src) and all(len(v)==3 and len(set(v))==1 for v in human.values()),
            'human labels not triple-reproduced from original independent owner runs')
    truth={tid:v[0] for tid,v in human.items()}
    grouped=defaultdict(list)
    for tid,group,q,_ in rows:grouped[(group,q)].append(truth[tid])
    require(len(grouped)==8 and all(set(v)=={0,1} for v in grouped.values()),
            'true source questions not mixed label')
    return truth

def independently_scaled_features(rows,allowed_ids):
    # Vectorized independent reference; no producer import and no test labels.
    question=defaultdict(list)
    for i,(_,g,q,_) in enumerate(rows):question[(g,q)].append(i)
    r=np.vstack([item[3] for item in rows])
    center=np.zeros((len(rows),3),dtype=np.float64)
    for idx in question.values():
        sub=np.asarray(idx,dtype=np.int64)
        center[sub]=r[sub]-np.mean(r[sub],axis=0)
    ix=np.asarray([i for i,row in enumerate(rows) if row[0] in allowed_ids],dtype=np.int64)
    require(len(ix)==len(allowed_ids),'training identity missing')
    scale=np.maximum(np.sqrt(np.mean(center[ix]**2,axis=0)),1e-8)
    mean=np.mean(r[ix,1]);std=max(np.sqrt(np.mean((r[ix,1]-mean)**2)),1e-8)
    features=np.column_stack((np.ones(len(rows)),center/scale,(r[:,1]-mean)/std))
    return np.clip(features,-12,12), {'center_rms_train':scale,'raw_mean_train':mean,'raw_std_train':std}

def stable_sigmoid(z):
    # z may be a vector; use safe two-branch exp to preserve original math.
    out=np.empty_like(z,dtype=np.float64)
    pos=z>=0
    out[pos]=1/(1+np.exp(-z[pos]))
    ez=np.exp(z[~pos]);out[~pos]=ez/(1+ez)
    return out

def independently_refit(rows,truth,X,mode):
    ids=np.asarray([i for i,row in enumerate(rows) if row[0] in truth],dtype=np.int64)
    trainX=X[ids];trainY=np.asarray([truth[rows[i][0]] for i in ids],dtype=np.float64)
    groups=defaultdict(list)
    for i in ids:groups[(rows[i][1],rows[i][2])].append(i)
    pairs=[]
    for rr in groups.values():
        pos=[i for i in rr if truth[rows[i][0]]==1]
        neg=[i for i in rr if truth[rows[i][0]]==0]
        pairs.extend(X[i]-X[j] for i in pos for j in neg)
    require(len(groups)==6 and len(pairs)>0,'wrong independent human fit census')
    diffX=np.asarray(pairs,dtype=np.float64)
    w=np.zeros(5,dtype=np.float64)
    for step in range(80):
        bce_g=(trainX.T @ (stable_sigmoid(trainX@w)-trainY))/len(ids)
        if mode=='pairwise5':
            pair_g=(diffX.T@(stable_sigmoid(diffX@w)-1))/len(diffX)
            grad=.3*bce_g+.7*pair_g
        else:grad=bce_g
        regularizer=np.array([0.,.002*w[1],.002*w[2],.002*w[3],.002*w[4]])
        w=w-.1*(grad+regularizer)
    return w

def checked_human_receipts(e15,e16):
    require(len(e15)==len(e16)==2,'two historical original review profiles required')
    e15s=[];e16s=[]
    for i in range(2):
        a=artifact(e15[i],E15_SCORE_SHA[i],'original-human-e15-lopo-result.json')
        b=artifact(e16[i],E16_SCORE_SHA[i],'original-human-e16-centered-result.json')
        require(a.get('production_accepted') is False and b.get('production_accepted') is False and
                a['source_archive_sha256']==MODEL_SHA and b['source_archive_sha256']==MODEL_SHA and
                a['human_validation_sha256']==VAL_SHA and
                b['original_validation_source_sha256']==VAL_SHA,
                'original human score version drift')
        e15s.append(a);e16s.append(b)
    for method in ('mean_pool_query_fused','conditioned','no_query'):
        require(e15s[0]['summary'][method]['correct']==e15s[1]['summary'][method]['correct'],
                'independent source/merge historical human scores changed')
    require(e15s[0]['summary']['mean_pool_query_fused']['correct']==17 and
            abs(e15s[0]['summary']['mean_pool_query_fused']['brier']-.49686492717706704)<1e-10 and
            e16s[0]['results']['centered_scaled_5']['correct']==20 and
            e16s[1]['results']['centered_scaled_5']['correct']==20,
            'historical frozen or centered-scale reference changed')
    return e15s[0],e16s[0]

def score(original,combined_path,owner_paths,e15_scores,e16_scores):
    rows,groups=frozen_inputs(original)
    raw=Path(combined_path).read_bytes();obj=canonical(raw)
    require(obj.get('schema')=='hepta.e24.original-label-blind-fourfold.v1' and
            obj.get('original_model_zip_sha256')==MODEL_SHA and
            obj.get('authority')=='DENY_ALL' and obj.get('production_accepted') is False and
            obj.get('model_selected') is False and
            obj.get('held_human_labels_accessed') is False and
            obj.get('new_pretrained_forwards')==0 and
            obj.get('original_cases')==33 and obj.get('original_questions')==8 and
            len(obj.get('folds',[]))==4,'unqualified label-blind frozen model training output')
    # Independent historical human owner labels are accessed ONLY now.
    human=independent_original_labels(rows,groups,owner_paths)
    historical,historical_e16=checked_human_receipts(e15_scores,e16_scores)
    model_ids={t[0] for t in rows};test_predictions={m:{} for m in METHODS}
    channel_masks={name:{} for name in ('without_conditioned_center',
        'without_meanpool_center','without_no_evidence_center','without_meanpool_raw')}
    meters={m:0 for m in METHODS}
    for fold,foldobj in enumerate(obj['folds']):
        require(foldobj.get('fold')==fold and foldobj.get('held_group')==groups[fold] and
                foldobj.get('original_model_zip_sha256')==MODEL_SHA and
                foldobj.get('held_label_accessed') is False and
                foldobj.get('new_pretrained_forward_calls')==0 and
                foldobj.get('training_updates_per_method')==80 and
                foldobj.get('train_only_owner_zip_sha256')==E15_OWNER_SHA[fold],
                'bad folded heldout shape')
        ownerids={x[0] for x in rows if x[1]!=groups[fold]}
        trainer_labels={k:human[k] for k in ownerids}
        X,summary=independently_scaled_features(rows,ownerids)
        recorded=foldobj['train_feature_profile']
        require(np.allclose(recorded['center_rms_train'],summary['center_rms_train'],rtol=1e-11,atol=1e-11) and
                abs(recorded['raw_mean_train']-summary['raw_mean_train'])<1e-10 and
                abs(recorded['raw_std_train']-summary['raw_std_train'])<1e-10,
                'train-only source normalization changed')
        held=[(i,rr) for i,rr in enumerate(rows) if rr[1]==groups[fold]]
        for mode in METHODS:
            m=foldobj['methods'][mode]
            independently=independently_refit(rows,trainer_labels,X,mode)
            require(len(m['weights'])==5 and
                    np.allclose(independently,m['weights'],rtol=5e-10,atol=5e-10),
                    'independent physical 80 SGD steps do not reproduce trained Head')
            require(m['meters']['train_steps']==80 and
                    m['meters']['train_examples']==len(ownerids) and
                    m['meters']['trainable_parameters']==5 and
                    m['meters']['train_cpu_ns']>0,
                    'false original training resource accounting')
            meters[mode]+=m['meters']['train_cpu_ns']
            got=m['predictions'];expect={rr[0] for _,rr in held}
            require({q['task_id'] for q in got}==expect and len(got)==len(held),
                    'test predictions incomplete')
            predictions={q['task_id']:q['probability'] for q in got}
            for index,row in held:
                predicted=float(stable_sigmoid(np.array([X[index]@independently]))[0])
                value=predictions[row[0]]
                require(type(value) is float and 0<value<1 and
                        abs(predicted-value)<2e-10 and row[0] not in test_predictions[mode],
                        'tampered held probability or duplicate original answer')
                test_predictions[mode][row[0]]=value
                if mode=='pairwise5':
                    for channel,component in enumerate(channel_masks, start=1):
                        masked=X[index].copy()
                        masked[channel]=0.
                        channel_masks[component][row[0]]=float(stable_sigmoid(
                            np.asarray([masked@independently]))[0])
    require(all(set(v)==model_ids for v in test_predictions.values()),
            'not all original 33 answers obtained')
    baselines={r[0]:float(stable_sigmoid(np.array([r[3][1]]))[0]) for r in rows}
    tested={**test_predictions, 'frozen_meanpool':baselines}
    # Exploratory fixed trained-weight channel removals; these are NOT physical
    # evidence-removal/re-encoding counterfactuals. All four are reported.
    assert all(set(pred)==model_ids for pred in channel_masks.values())
    tested.update(channel_masks)
    results={}
    for name,pred in tested.items():
        exact=0;complete=0;count=0;passage=defaultdict(int);passage_total=defaultdict(int)
        allgood=defaultdict(list)
        brier=0.
        for tid,g,q,_ in rows:
            truth=human[tid];prob=pred[tid]
            choice=(prob>=.5) if name!='frozen_meanpool' else (prob>.5)
            hit=int(choice==bool(truth))
            count+=hit;passage[g]+=hit;passage_total[g]+=1;allgood[(g,q)].append(hit)
            brier+=2*(prob-truth)**2
        complete=sum(all(v) for v in allgood.values())
        entire=defaultdict(list)
        for (g,q),v in allgood.items():entire[g].extend(v)
        results[name]={'correct':count,'total':33,'brier':brier/33,
                       'complete_questions':complete,'complete_passages':sum(all(v) for v in entire.values()),
                       'passage_correct':dict(sorted(passage.items())),
                       'passage_total':dict(sorted(passage_total.items()))}
    frozen=historical['summary']['mean_pool_query_fused']
    require(results['frozen_meanpool']['correct']==frozen['correct'] and
            abs(results['frozen_meanpool']['brier']-frozen['brier'])<1e-11 and
            results['frozen_meanpool']['passage_correct']==frozen['passage_correct'],
            'independent original historical frozen Human correctness mismatch')
    # Question is the unit of paired whole-task scoring; these counts are
    # historical descriptions, not an iid Bernoulli trial or prospective test.
    paired={}
    def completed_question(prob, group_items, method):
        return all(((prob[tid]>=.5) if method!='frozen_meanpool' else (prob[tid]>.5))
                   ==bool(human[tid]) for tid in group_items)
    byq=defaultdict(list)
    for tid,g,q,_ in rows:byq[(g,q)].append(tid)
    for arm in METHODS:
        alternatives=test_predictions[arm]
        cand_rescued=cand_harmed=0
        for tid,g,q,_ in rows:
            old_hit=(baselines[tid]>.5)==bool(human[tid])
            new_hit=(alternatives[tid]>=.5)==bool(human[tid])
            cand_rescued+=int(not old_hit and new_hit)
            cand_harmed+=int(old_hit and not new_hit)
        questions_rescued=questions_harmed=0
        for group_ids in byq.values():
            before=completed_question(baselines,group_ids,'frozen_meanpool')
            after=completed_question(alternatives,group_ids,arm)
            questions_rescued+=int(not before and after)
            questions_harmed+=int(before and not after)
        paired[arm]={'candidate_rescued':cand_rescued,'candidate_harmed':cand_harmed,
                     'question_rescued':questions_rescued,'question_harmed':questions_harmed,
                     'independent_question_sampling_established':False,
                     'statistical_significance_or_superiority_established':False}
    return {'schema':'hepta.e24.independent-original-human-pairwise-fiveparam.v1',
            'channel_mask_counterfactual_reencodes_evidence':False,
            'channel_mask_arms_are_exploratory_posthoc':True,
            'origin_model_sha256':MODEL_SHA,'human_validation_sha256':VAL_SHA,
            'prelabel_sha256':sha256(raw).hexdigest(),'original_passage_groups':4,
            'original_questions':8,'source_group_independence_certified':False,
            'new_pretrained_forwards':0,'original_real_5param_SGD_updates':4*2*80,
            'trainer_cpu_ns':meters,'historical_e16_scaled_correct':historical_e16['results']['centered_scaled_5']['correct'],
            'historical_e16_scaled_brier':historical_e16['results']['centered_scaled_5']['brier'],
            'results':results,'paired_against_original_frozen':paired,
            'source_family_count':1,'hypothesis_confirmatory_preregistration':False,
            'original-human-parquet-directly-reopened':False,
            'original_pretraining_reexecuted':False,'future_task_utility_gain_established':False,
            'equal_full_lifecycle_compute':False,'reader_sufficient':False,
            'ndu_system2_admitted':False,'production_accepted':False,'model_selected':False,
            'authority_posture':'DENY_ALL'}

def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--original',required=True)
    a.add_argument('--prelabel',required=True)
    for i in range(4):a.add_argument(f'--e16-owner-{i}',required=True)
    for i in range(2):a.add_argument(f'--e15-score-{i}',required=True)
    for i in range(2):a.add_argument(f'--e16-score-{i}',required=True)
    a.add_argument('--out',required=True)
    c=a.parse_args()
    result=score(c.original,c.prelabel,
                 [getattr(c,f'e16_owner_{i}') for i in range(4)],
                 [getattr(c,f'e15_score_{i}') for i in range(2)],
                 [getattr(c,f'e16_score_{i}') for i in range(2)])
    b=(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    with Path(c.out).open('xb') as f:f.write(b)
    print(sha256(b).hexdigest())

if __name__=='__main__': main()
