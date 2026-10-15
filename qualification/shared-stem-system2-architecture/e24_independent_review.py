"""E24 independent original-human question-level audit (SHADOW / DENY_ALL).

Re-fit each source-held tiny Head by a second gradient implementation.
The independent label file or owner receipts are opened ONLY after all four
trained heldout predictions have been byte-sealed. This reviewer cannot
authenticate independent human signers or a prospective untouched test family.
"""
from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from math import comb
from hashlib import sha256
from math import exp, fsum, isclose, isfinite
from pathlib import Path
import argparse
import json

from e14_multirc_route import read_prelabel, write_once, ARCHIVE_SHA, OBS_ID
from e14_multirc_score import original_labels, read_validation, VAL_SHA
from e15_independent_score import sha as training_sha
from e15_reader_crossfit import sigmoid
from e16_independent_score import separate_geometry, fit_independent, probability
from e23_original_owner_question_gate import (E15_OWNERS,E16_OWNERS,original_owner_labels)
from e24_question_risk import METHODS, TAU, SCHEMA as PRODUCER_SCHEMA, blind_identity

REVIEW_SCHEMA='hepta.e24.independent-original-human-question-risk-review.v1'


def strict_document(path,limit=150000):
    raw=Path(path).read_bytes()
    if not 0<len(raw)<limit:raise ValueError('unsealed or oversized artifact')
    def pairs(vals):
        obj={}
        for k,v in vals:
            if k in obj:raise ValueError('duplicate JSON key')
            obj[k]=v
        return obj
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x))),sha256(raw).hexdigest()


def reference_features(obs):
    # Original E16 second algorithm, NOT producer's e16_answer_centered.features.
    return separate_geometry(obs)


def ref_sigmoid(v):
    if not isfinite(v) or abs(v)>1000:raise ValueError('nonfinite independent margin')
    # Different stable function branch than the producer's logistic helper.
    return exp(v)/(1+exp(v)) if v<0 else 1/(1+exp(-v))


def reference_train(rows,training,method):
    """Separate source-group/tau gradient loop, math.fsum, original fold-only scale."""
    if method==METHODS[0]:
        w,scale,_ = fit_independent(rows,training,'centered_scaled_5')
        return w,scale
    if method not in TAU:raise ValueError('unregistered independent research hypothesis')
    sample={r['task_id']:r for r in rows}
    if not 20<=len(training)<=30 or any(k not in sample or type(v) is not int or v not in (0,1) for k,v in training.items()):
        raise ValueError('invalid original train-only labels')
    train=[sample[k] for k in training]
    scale=[max(1e-5,max(abs(r['centered'][j]) for r in train)) for j in range(4)]
    grouped={}
    for rec in train:
        grouped.setdefault((rec['group'],rec['question']),[]).append(rec)
    if len(grouped)!=6 or len({k[0] for k in grouped})!=3 or any(not 2<=len(v)<=8 for v in grouped.values()):
        raise ValueError('missing complete original training question')
    tau=TAU[method]
    w=[0.]*5
    for _ in range(48):
        contributions=[[] for _ in range(5)]
        for key in sorted(grouped):
            samples=[]
            for row in grouped[key]:
                x=(1.0,)+tuple(row['centered'][i]/scale[i] for i in range(4))
                p=ref_sigmoid(fsum(w[j]*x[j] for j in range(5)))
                y=training[row['task_id']]
                samples.append((x,p,y,(p-y)**2))
            top=max(z[3] for z in samples)
            exponentials=[exp((z[3]-top)/tau) for z in samples]
            denom=fsum(exponentials)
            for z,(x,p,y,loss) in enumerate(samples):
                weight=(exponentials[z]/denom)/len(grouped)
                factor=weight*2*(p-y)*p*(1-p)
                for j in range(5):contributions[j].append(factor*x[j])
        nextgrad=[fsum(vals) for vals in contributions]
        for j in range(5):
            w[j]=w[j]-0.5*(nextgrad[j]+(.001*w[j] if j else 0))
        if any(not isfinite(a) or abs(a)>128 for a in w):raise ValueError('unstable independent SGD')
    return w,scale


def ref_predict(row,w,scale):
    z=fsum([w[0]]+[w[i+1]*row['centered'][i]/scale[i] for i in range(4)])
    return ref_sigmoid(z)


def independent_question_summary(obs,labels,predictions):
    questions=defaultdict(list)
    brier={name:[] for name in predictions}
    for row in obs['rows']:
        key=(row['source_group'],row['question_slot'])
        task=row['task_id']; truth=labels[task]
        for name,score in predictions.items():
            p=score[task]
            if type(p) is not float or not isfinite(p) or not 0<p<1:
                raise ValueError('changed probability or missing truth')
            hit=int((p>=.5)==bool(truth))
            questions[(name,key)].append(hit)
            brier[name].append(2*(p-truth)**2)
    if len({q for name,q in questions})!=8 or any(len(v)<2 or len(v)>8 for v in questions.values()):
        raise ValueError('original full-question census missing')
    result={}
    for name in predictions:
        by_question={f'{g}:{i}':int(all(items)) for (n,(g,i)),items in questions.items() if n==name}
        if len(by_question)!=8:raise ValueError('incomplete learned question')
        source_group=defaultdict(list)
        for k,v in by_question.items():source_group[k.split(':')[0]].append(v)
        by_passage={k:int(all(v)) for k,v in source_group.items()}
        hits=sum(sum(items) for (n,_),items in questions.items() if n==name)
        result[name]={'correct':hits,'candidates':33,'brier':fsum(brier[name])/33,
            'complete_questions':sum(by_question.values()),'complete_passages':sum(by_passage.values()),
            'by_question':by_question,'by_passage':by_passage,
            'candidate_accuracy':hits/33}
    return result


def reviewer(archive,blind_path,held_paths,held_sha,owner_e15,owner_e16,
             validation_parquet=None):
    """Post-seal review. Four original train-only receipts; never leak held to fit."""
    if any(type(v) is not list or len(v)!=4 for v in (held_paths,held_sha,owner_e15,owner_e16)):
        raise ValueError('all four independently sealed folds/owners required')
    obs=read_prelabel(archive)
    blind,blindsha=strict_document(blind_path)
    if blind!=blind_identity(obs) or blind['label_read'] is not False:
        raise ValueError('source-blind scope or SHA changed')
    a,a_owner=original_owner_labels(obs,owner_e15,E15_OWNERS,name='E15 original human owner')
    b,b_owner=original_owner_labels(obs,owner_e16,E16_OWNERS,name='E16 original human owner')
    if a!=b:raise ValueError('two original owner materials disagree')
    externally_verified=False
    if validation_parquet:
        original=original_labels(read_validation(validation_parquet),obs['rows'])
        if original!=a:raise ValueError('actual immutable original validation parquet differs from training owners')
        externally_verified=True
    rows=reference_features(obs)
    source_groups=sorted({r['group'] for r in rows})
    if len(rows)!=33 or len(source_groups)!=4 or set(a)!={r['task_id'] for r in rows}:
        raise ValueError('incomplete original source panel')
    true_groups=defaultdict(set)
    for r in rows:true_groups[(r['group'],r['question'])].add(a[r['task_id']])
    if len(true_groups)!=8 or any(v!={0,1} for v in true_groups.values()):
        raise ValueError('original human questions not genuine mixed true/false')
    all_preds={name:{} for name in METHODS}
    total_train={name:0 for name in METHODS}
    total_held={name:0 for name in METHODS}
    receipts=[]
    for fold in range(4):
        doc,digest=strict_document(held_paths[fold])
        if digest!=held_sha[fold]:raise ValueError('pre-scoring held output bytes not sealed')
        keys={'schema','authority','production_accepted','model_selected','incremental_system2_admitted',
              'original_model_archive_sha256','original_model_observation_id','fold','held_source_group',
              'train_only_material_sha256','held_human_truth_read','real_pretrained_model_forwards_new',
              'original_three_group_training_question_count','training_steps',
              'temperature_grid_exploratory_after_observing_historical_family','methods',
              'training_only_scale','weights','meters','held_predictions',
              'whole_service_cost_certified','future_source_family_gain',
              'original_training_label_owner_authenticates_independent_human_rater'}
        if (type(doc) is not dict or set(doc)!=keys or doc['schema']!=PRODUCER_SCHEMA
                or doc['authority']!='DENY_ALL' or doc['production_accepted'] is not False
                or doc['model_selected'] is not False or doc['incremental_system2_admitted'] is not False
                or doc['original_model_archive_sha256']!=ARCHIVE_SHA or doc['original_model_observation_id']!=OBS_ID
                or type(doc['fold']) is not int or doc['fold']!=fold
                or doc['held_source_group']!=source_groups[fold]
                or doc['held_human_truth_read'] is not False
                or type(doc['real_pretrained_model_forwards_new']) is not int or doc['real_pretrained_model_forwards_new']!=0
                or doc['original_three_group_training_question_count']!=6 or doc['training_steps']!=48
                or doc['temperature_grid_exploratory_after_observing_historical_family'] is not True
                or doc['methods']!=list(METHODS)
                or doc['whole_service_cost_certified'] is not False
                or doc['future_source_family_gain'] is not False
                or doc['original_training_label_owner_authenticates_independent_human_rater'] is not False
                or type(doc['weights']) is not dict or set(doc['weights'])!=set(METHODS)
                or type(doc['meters']) is not dict or set(doc['meters'])!=set(METHODS)):
            raise ValueError('unsupported or promoted original Student source')
        train={r['task_id']:a[r['task_id']] for r in rows if r['group']!=source_groups[fold]}
        # Do NOT synthesize owner schema from loose metadata: read the ORIGINAL
        # E15 owner file, independently checked by original_owner_labels().
        import zipfile
        with zipfile.ZipFile(owner_e15[fold]) as f:
            raw=f.read(f'training-fold-{fold}.json')
        original_doc=json.loads(raw)
        if doc['train_only_material_sha256']!=training_sha(original_doc):
            raise ValueError('train-only original human owner bytes changed')
        held=[r for r in rows if r['group']==source_groups[fold]]
        if len(doc['held_predictions'])!=len(held):raise ValueError('incomplete held source predictions')
        refscale=None;fold_weights={}
        for method in METHODS:
            weight,scaling=reference_train(rows,train,method)
            claimed=doc['weights'][method]
            if (type(claimed) is not list or len(claimed)!=5 or any(type(v) is not float or not isfinite(v)
               or abs(v-weight[i])>1e-11 for i,v in enumerate(claimed))):
                raise ValueError('original true-label learned weights independent mismatch')
            if refscale is None:refscale=scaling
            elif any(abs(x-y)>1e-13 for x,y in zip(scaling,refscale)):raise ValueError('mixed train-only feature normalizers')
            fold_weights[method]=(weight,scaling)
            met=doc['meters'][method]
            if (type(met) is not dict or set(met)!={'train_cpu_ns','held_cpu_ns','physical_parameter_count',
                'optimizer_updates','training_question_count','training_candidate_count'}
                or any(type(met[k]) is not int or met[k]<=0 or met[k]>=10**12 for k in ('train_cpu_ns','held_cpu_ns'))
                or met['physical_parameter_count']!=5 or met['optimizer_updates']!=48
                or met['training_question_count']!=6 or met['training_candidate_count']!=len(train)):
                raise ValueError('missing matched physical compute or false train cost')
            total_train[method]+=met['train_cpu_ns'];total_held[method]+=met['held_cpu_ns']
        if (type(doc['training_only_scale']) is not list or len(doc['training_only_scale'])!=4
                or any(type(v) is not float or abs(v-refscale[j])>1e-13 for j,v in enumerate(doc['training_only_scale']))):
            raise ValueError('held group normalization leaked or falsified')
        for r,item in zip(held,doc['held_predictions'],strict=True):
            if (type(item) is not dict or set(item)!={'task_id','source_group','question_slot','candidate_id','probabilities'}
               or item['task_id']!=r['task_id'] or item['source_group']!=r['group']
               or item['question_slot']!=r['question'] or item['candidate_id']!=r['candidate_id']
               or type(item['probabilities']) is not dict or set(item['probabilities'])!=set(METHODS)):
                raise ValueError('changed original held prediction task/source')
            for method in METHODS:
                p=item['probabilities'][method]
                ref=ref_predict(r,*fold_weights[method])
                if type(p) is not float or not isfinite(p) or abs(p-ref)>1e-11:
                    raise ValueError('changed original true-label held predicted probability')
                all_preds[method][r['task_id']]=ref
        receipts.append({'fold':fold,'held_source_group':source_groups[fold],
                         'full_training_question_count':6,'held_candidate_count':len(held),
                         'independent_original_label_replay':True})
    if any(len(v)!=33 for v in all_preds.values()):raise ValueError('incomplete independent full source held panel')
    result=independent_question_summary(obs,a,all_preds)
    if result[METHODS[0]]['correct']!=20 or abs(result[METHODS[0]]['brier']-.4679101347990239)>2e-11 or result[METHODS[0]]['complete_questions']!=0:
        raise ValueError('original E16 known source/held learner baseline not replayed')
    # Exploratory, extremely low-power four-source sign flips; compare entire
    # QUESTIONS, not 33 dependent candidate-level Bernoulli trials.
    # The original annotation family was already studied before this grid.
    control=result[METHODS[0]]
    contrasts={}
    ps=[]
    for method in METHODS[1:]:
        target=result[method]
        delta={g:sum(v for k,v in target['by_question'].items() if k.startswith(g+':'))
                 -sum(v for k,v in control['by_question'].items() if k.startswith(g+':'))
               for g in source_groups}
        ups=sum(v>0 for v in delta.values());downs=sum(v<0 for v in delta.values())
        n=ups+downs
        exact=Fraction(1) if n==0 else min(Fraction(1),Fraction(2*sum(comb(n,k) for k in range(min(ups,downs)+1)),2**n))
        contrasts[method]={'candidate_correct_delta':target['correct']-control['correct'],
                           'complete_question_delta':target['complete_questions']-control['complete_questions'],
                           'passage_question_success_deltas':delta,
                           'source_cluster_exact_signflip_unadjusted':str(exact),
                           'full_passage_success_delta':target['complete_passages']-control['complete_passages']}
        ps.append((method,exact))
    # Three-arm Holm correction; descriptive only and not a confirmatory trial.
    adjusted=Fraction(0)
    for i,(name,p) in enumerate(sorted(ps,key=lambda x:x[1])):
        adjusted=max(adjusted,min(Fraction(1),p*(len(ps)-i)))
        contrasts[name]['three_objective_Holm_descriptive_only']=str(adjusted)
    return {'schema':REVIEW_SCHEMA,'authority':'DENY_ALL','production_accepted':False,
            'model_selected':False,'system2_fbsde_permitted':False,
            'source_sha256':ARCHIVE_SHA,'original_validation_parquet_sha256':VAL_SHA,
            'original_human_parquet_reopened':externally_verified,
            'E15_original_owner':a_owner,'E16_original_owner':b_owner,
            'original_owner_source_not_independent_human_signer':True,
            'original_HUMAN_labels_reconstructed_only_after_held_prediction_seal':True,
            'exact_original_4_passages':4,'exact_original_8_mixed_questions':8,'exact_original_33_candidates':33,
            'source_blind_sha256':blindsha,
            'four_original_real_SGD_holdout_replays':receipts,
            'registered_methods':list(METHODS),
            'results':result,'exploratory_original_question_contrasts':contrasts,
            'three_temperature_hypotheses_checked_after_original_labels_were_previously_seen':True,
            'physical_local_Python_CPU_ns_not_target_hardware':{'train':total_train,'held':total_held},
            'source_family_reused_after_prior_analysis':True,
            'all_group_loss_variants_exploratory_not_prospectively_preregistered':True,
            'statistical_superiority_or_independent_future_benefit':False,
            'full_online_source_and_model_cost_measured':False,
            'complete_question_task_ready_for_production':False}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--archive',required=True)
    cli.add_argument('--blind',required=True)
    for i in range(4):
        for name in ('held','held-sha','e15-owner','e16-owner'):
            cli.add_argument(f'--{name}-{i}',required=True)
    cli.add_argument('--validation-parquet',default=None)
    cli.add_argument('--output',required=True)
    x=cli.parse_args()
    out=reviewer(x.archive,x.blind,
      [getattr(x,f'held_{i}') for i in range(4)],
      [getattr(x,f'held_sha_{i}') for i in range(4)],
      [getattr(x,f'e15_owner_{i}') for i in range(4)],
      [getattr(x,f'e16_owner_{i}') for i in range(4)],
      x.validation_parquet)
    print(write_once(x.output,out),'DENY_ALL')

if __name__=='__main__':main()
