"""Post-seal original-human E25 six NEW-source scoring, no retraining or tuning.

Independently reconstructs genuine native candidate truth from exact Parquet;
uses separate fsum/tanh? exp-logistic and question-center math from proposer.
Reports complete questions and passage paired counts, denies all deployment.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from math import comb,exp,fsum,isclose,isfinite
from pathlib import Path

from e25_unseen_material import VAL_SHA,write_once
from e25_fixed_policy_transfer import (ARMS,METHODS,POLICY_SHA,SCHEMA,source_json,frozen)

SCORE_SCHEMA='hepta.e25.new-six-original-source-complete-question-score.v1'


def truth_from_parquet(parquet_path,slate,owner_labels):
    raw=Path(parquet_path).read_bytes()
    if sha256(raw).hexdigest()!=VAL_SHA:raise ValueError('original validation Parquet SHA changed')
    import pyarrow.parquet as pq
    src=pq.read_table(parquet_path,columns=['paragraph','question','answer','label','idx']).to_pylist()
    if type(src) is not list:
        raise ValueError('original independent source rows are malformed')
    required={c['task_id']:{'group':group['source_group'],'slot':q['question_slot'],
                            'aid':c['candidate_id'],'answer':c['answer'],'question':q['question']}
        for group in slate['rows'] for q in group['questions'] for c in q['candidates']}
    if not 24<=len(required)<=96 or len(required)!=sum(len(q['candidates']) for p in slate['rows'] for q in p['questions']):
        raise ValueError('candidate slate missing or duplicated source')
    source_to_text={p['source_group']:p['evidence'] for p in slate['rows']}
    if len(source_to_text)!=6:raise ValueError('not six complete source passages')
    found={};all_q=defaultdict(set)
    for entry in src:
        idx=entry['idx'];txt=entry['paragraph']
        if not isinstance(txt,str):continue
        if any(type(idx[k]) is not int for k in ('paragraph','question','answer')):raise ValueError('source index malformed')
        h=sha256(json.dumps(txt,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        group=sha256(f'validation:passage:{idx["paragraph"]}:{h}'.encode()).hexdigest()[:32]
        if group not in source_to_text:continue
        if txt!=source_to_text[group]:raise ValueError('same source group changed text')
        task=sha256(f'{group}:q{idx["question"]}:a{idx["answer"]}'.encode()).hexdigest()[:32]
        if task not in required:continue
        exp_row=required[task]
        if (group!=exp_row['group'] or idx['answer']!=exp_row['aid']
            or entry['answer']!=exp_row['answer'] or entry['question']!=exp_row['question']
            or type(entry['label']) is not int or entry['label'] not in (0,1)
            or task in found):
            raise ValueError('original human candidate/source was changed')
        found[task]=entry['label'];all_q[(group,idx['question'])].add(task)
    if (set(found)!=set(required) or len(all_q)!=12
        or any(not 2<=len(v)<=8 for v in all_q.values())):
        raise ValueError('independent 12-question source reconstruction failed')
    if (type(owner_labels) is not dict or owner_labels.get('labels')!=found
        or owner_labels.get('slate_id')!=slate['slate_id']
        or owner_labels.get('external_observer_authenticated') is not False):
        raise ValueError('material-owner human truth differs from exact original Parquet')
    return found


def reference_sigmoid(z):
    if not isfinite(z) or abs(z)>1000:raise ValueError('nonfinite physical model probability')
    return exp(z)/(1+exp(z)) if z<=0 else 1/(1+exp(-z))


def independently_predictions(audit,slate,policy):
    ids=[(c['task_id'],p['source_group'],q['question_slot']) for p in slate['rows']
         for q in p['questions'] for c in q['candidates']]
    if (audit.get('rows') is None or len(audit['rows'])!=len(ids)
        or any((r['task_id'],r['source_group'],r['question_slot'])!=triple
               for r,triple in zip(audit['rows'],ids,strict=True))):
        raise ValueError('reordered original source rows')
    margins={}
    groups=defaultdict(list)
    for i,(case,group,slot) in enumerate(ids):
        m=[]
        for arm in ARMS:
            item=audit['predictions'][arm][i]
            z=item['logits']
            if type(z) is not list or len(z)!=2 or any(type(v) not in (float,int) or not isfinite(v) for v in z):
                raise ValueError('modified source logits')
            m.append(z[1]-z[0])
        margins[case]=m;groups[(group,slot)].append(case)
    if len(groups)!=12:raise ValueError('not twelve unique original groups')
    result={}
    for case,group,slot in ids:
        m=margins[case];mates=groups[(group,slot)]
        mean=[fsum(margins[i][j] for i in mates)/len(mates) for j in range(4)]
        center=[m[j]-mean[j] for j in range(4)]
        x=(center[0],center[1],center[2],center[1]*center[2])
        out={arm:reference_sigmoid(m[j]) for j,arm in enumerate(ARMS)}
        for name in METHODS:
            vv=[]
            for fold in policy['folds']:
                scale=fold['scale'];w=fold['weights'][name]
                z=fsum([w[0]]+[w[k+1]*(x[k]/scale[k]) for k in range(4)])
                if not -1000<z<1000:raise ValueError('unbounded new-source candidate')
                vv.append(reference_sigmoid(z))
            out[name]=fsum(vv)/4
        result[case]=out
    return result


def sign_flip_paired_passages(baseline,other,passages):
    # Exact exhaustive two-sided sign-flip across six source clusters;
    # descriptive only. Posthoc effect size is not confirmatory.
    diffs=[other[k]-baseline[k] for k in passages]
    observed=abs(sum(diffs))
    tail=sum(abs(sum((1 if (i>>k)&1 else -1)*d for k,d in enumerate(diffs)))>=observed-1e-12
             for i in range(2**len(diffs)))
    return f'{tail}/{2**len(diffs)}'


def review(blind_path,blind_sha, audit_path,slate_path,policy_path,owner_labels_path,val_parquet):
    raw=Path(blind_path).read_bytes()
    if sha256(raw).hexdigest()!=blind_sha:raise ValueError('pre-score original-human blind seal missing')
    blind=source_json(blind_path);audit=source_json(audit_path);slate=source_json(slate_path)
    owner=source_json(owner_labels_path);policy=frozen(policy_path)
    if (blind.get('schema')!=SCHEMA or blind.get('authority')!='DENY_ALL'
        or blind.get('production_accepted') is not False
        or blind.get('human_validation_labels_read_before_seal') is not False
        or blind.get('new_reader_train_anchor_slate_evidence_forwards')!=20
        or blind.get('original_checkpoint_probe_forwards_additional_and_not_in_reader_count') is not True
        or blind.get('new_validation_passages')!=6 or blind.get('new_validation_questions')!=12
        or blind.get('policy_sha256')!=POLICY_SHA
        or blind.get('slate_id')!=slate['slate_id']
        or blind.get('historical_reader_weights_reproduced') is not True
        or blind.get('new_time_or_data_family') is not False
        or blind.get('learning_or_model_selected') is not False
        or blind.get('complete_service_cost_measured') is not False):
        raise ValueError('physical source or authority violated')
    exp=independently_predictions(audit,slate,policy)
    expected_ids=[c['task_id'] for p in slate['rows'] for q in p['questions'] for c in q['candidates']]
    if (type(blind.get('rows')) is not list or len(blind['rows'])!=len(expected_ids)
        or [r.get('task_id') for r in blind['rows']]!=expected_ids
        or blind.get('new_validation_candidates')!=len(expected_ids)):
        raise ValueError('missing/disordered original blind predictions')
    for item in blind['rows']:
        if (set(item)!={'task_id','source_group','question_slot','candidate_id','probabilities'}
            or type(item['probabilities']) is not dict or set(item['probabilities'])!=set(ARMS)|set(METHODS)):
            raise ValueError('unregistered physical prediction')
        reference=exp[item['task_id']]
        for name,estimate in item['probabilities'].items():
            if (type(estimate) is not float or not isfinite(estimate)
                or not isclose(estimate,reference[name],abs_tol=3e-12,rel_tol=0)):
                raise ValueError('blind prediction differs from second independent algorithm')
    truth=truth_from_parquet(val_parquet,slate,owner)
    question=defaultdict(list)
    brier=defaultdict(list)
    by_passage=defaultdict(lambda:defaultdict(list))
    all_methods=ARMS+METHODS
    for row in blind['rows']:
        task=row['task_id'];y=truth[task];p=row['source_group'];q=row['question_slot']
        for name in all_methods:
            prob=exp[task][name]
            hit=int((prob>=0.5)==bool(y))
            question[(name,p,q)].append(hit)
            by_passage[name][p].append(hit)
            brier[name].append(2*(prob-y)**2)
    summaries={}
    for name in all_methods:
        q_rows={(p,q):v for (n,p,q),v in question.items() if n==name}
        if len(q_rows)!=12:raise ValueError('whole question missing original native alternatives')
        summaries[name]=dict(correct_candidates=sum(sum(v) for v in q_rows.values()),
          total_candidates=len(expected_ids),complete_questions=sum(all(v) for v in q_rows.values()),
          total_questions=12,complete_passages=sum(all(v) for v in by_passage[name].values()),
          total_passages=6,brier=fsum(brier[name])/len(expected_ids),
          per_passage_candidate_correct={p:sum(v) for p,v in sorted(by_passage[name].items())},
          per_passage_complete_question={p:sum(all(v) for (pg,q),v in q_rows.items() if pg==p)
                for p in sorted(by_passage[name])})
    passages=sorted(by_passage[ARMS[1]])
    paired={name:{'paired_candidate_gain':summaries[name]['correct_candidates']-summaries[ARMS[1]]['correct_candidates'],
      'paired_whole_question_gain':summaries[name]['complete_questions']-summaries[ARMS[1]]['complete_questions'],
      'six_cluster_sign_flip_descriptive':sign_flip_paired_passages(
        summaries[ARMS[1]]['per_passage_candidate_correct'],summaries[name]['per_passage_candidate_correct'],passages)}
        for name in METHODS}
    return dict(schema=SCORE_SCHEMA,authority='DENY_ALL',production_accepted=False,
       original_validation_source_sha256=VAL_SHA,human_truth_read_only_after_seal=True,
       actual_new_reader_train_anchor_slate_evidence_forwards=20,
       original_checkpoint_probe_forwards_additional_not_in_count=True,original_pretrained_four_readers_newly_fitted=True,
       original_passages_in_new_holdout=0,new_holdout_passages=6,
       novel_source_family=False,prospective_time_window=False,statistical_superiority_established=False,
       tau_chosen_posthoc_on_original_historical_groups=True,
       fourfold_ensemble_not_five_scalar_single_head=True,
       whole_service_training_inference_energy_and_verifier_cost_established=False,
       model_selected=False,all_source_original_human_labels_are_public_annotations=True,
       methods=summaries,paired=paired,blind_sha256=blind_sha,
       independent_reference_recomputed=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('blind','blind-sha256','candidate-audit','candidate-slate','frozen-policy',
              'owner-labels','validation-parquet','output'):
        ap.add_argument('--'+n,required=True)
    a=ap.parse_args()
    rec=review(a.blind,a.blind_sha256,a.candidate_audit,a.candidate_slate,a.frozen_policy,
               a.owner_labels,a.validation_parquet)
    print(write_once(a.output,rec),'DENY_ALL')

if __name__=='__main__':main()
