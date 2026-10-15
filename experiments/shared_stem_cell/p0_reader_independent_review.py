#!/usr/bin/env python3
"""Independent, model-free real-source Reader receipt scorer.

Runs only after the four label-blind model artifacts are sealed. Labels stay out
of the model runner's filesystem. A Laya 421M native no-change arm is NOT a
parameter-matched frozen 2K Head and cannot be called a model-selection winner.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import random
import re
import statistics

from p0_squad_materials import (canonical, digest, read, write_new,
                                CONDITIONS, WANTED, Invalid)
from p0_real_reader_cpu import (validate_materials, MODELS, COMPACT_REVISIONS,
                                LAYA_SHA)

SCHEMA = 'hepta.p0.squad-reader-scored.v1'


def quantile(values, q):
    if not values:
        raise Invalid('no numerical observations')
    rows = sorted(values)
    loc = q*(len(rows)-1)
    left=int(loc)
    right=min(len(rows)-1,left+1)
    return rows[left]*(1-(loc-left))+rows[right]*(loc-left)


def checked_positive(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
        raise Invalid('missing real positive resource cost')
    return float(value)


def checked_probability(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
        raise Invalid('bad reported probability')
    return float(value)


def independent_question_only_retrieval(rows):
    """Second, label-free implementation of BM25 for original receipt audit.

    Do not call the producer's bm25_neighbors: independent scoring must detect
    source-side accidental answer injection, donor swaps or drift in corpus scope.
    This is deterministic numerical consistency, NOT independent source truth.
    """
    corpus=defaultdict(dict)
    for row in rows:
        part=row['split']; source_id=row['source_id'];condition=row['condition']
        if condition in corpus[(part,source_id)]:
            raise Invalid('duplicate source-condition in independent retrieval')
        corpus[(part,source_id)][condition]=row
    by_partition=defaultdict(dict)
    for (part,src),arms in corpus.items():
        if set(arms)!=set(CONDITIONS):
            raise Invalid('incomplete independent original retrieval cohort')
        question=arms['sufficient']['joint_input']['question']
        m=re.fullmatch(
            r'Can the supplied passage explicitly support the proposed answer "(.+?)" '
            r'to the question "(.+?)"\?', question)
        if m is None:
            raise Invalid('unregistered original question framing')
        by_partition[part][src]=(m.group(2), arms['sufficient']['joint_input']['state'],arms)
    result={}
    for part,items in by_partition.items():
        n=len(items)
        if n<2:
            raise Invalid('insufficient independent BM25 corpus')
        tokens={src:re.findall('[a-z0-9]+',context.lower()) for src,(_,context,_) in items.items()}
        lengths={src:len(words) for src,words in tokens.items()}
        if not all(lengths.values()):
            raise Invalid('empty independent corpus document')
        mean_length=sum(lengths.values())/n
        # No source answer spans are consulted or used as search terms.
        document_frequency=defaultdict(int)
        for ws in tokens.values():
            for token in set(ws): document_frequency[token]+=1
        conditions=[]
        for src,(question,_,arms) in items.items():
            query=set(re.findall('[a-z0-9]+',question.lower()))
            if not query:raise Invalid('independent question-only query empty')
            ranked=[]
            for donor,doc_tokens in tokens.items():
                count={w:doc_tokens.count(w) for w in query}
                score=0.
                for token,count_value in count.items():
                    if count_value:
                        idf=math.log(1+(n-document_frequency[token]+.5)/(
                            document_frequency[token]+.5))
                        score += idf*count_value*2.2/(
                            count_value+1.2*(.25+.75*lengths[donor]/mean_length))
                ranked.append((-score,donor))
            donor=min(ranked)[1]
            predicted=arms['retrieved']
            if (predicted['retrieved_source_id']!=donor or
                    predicted['joint_input']['state']!=items[donor][1]):
                raise Invalid('independent BM25 found unregistered donor or source text')
            conditions.append(donor==src)
        result[part]={'questions':len(items),'source_hits':sum(conditions),
                      'source_hit_at_1':sum(conditions)/len(items),
                      'other_document_is_unadjudicated':True}
    if set(result)!=set(WANTED):
        raise Invalid('independent scorer missing a research split')
    return result


def score_arm(unseen, labels, arm, *, family):
    body = arm['predictions']
    if type(body) is not list or len(body)!=len(unseen):
        raise Invalid('missing original full question/intervention predictions')
    lookup = {x['case_id']:x for x in unseen}
    scored = {}
    for rec in body:
        if type(rec) is not dict or not {'case_id','view_sha256','positive_probability'} <= set(rec):
            raise Invalid('incomplete original model row')
        k=rec['case_id']
        if k in scored or k not in lookup or rec['view_sha256'] != lookup[k]['view_sha256']:
            raise Invalid('changed/duplicated prediction or input view')
        if any(z in rec for z in ('label','target','correct','answer_label')):
            raise Invalid('future outcome inside model artifact')
        prob = checked_probability(rec['positive_probability'])
        if family=='native_laya':
            latency = checked_positive(rec.get('full_request_ms'))
        else:
            latency = checked_positive(rec.get('encoder_forward_ms')) + checked_positive(rec.get('head_forward_ms'))
        scored[k] = {'p':prob,'ms':latency}
    if set(scored) != set(lookup):
        raise Invalid('incomplete model observation census')
    sums={condition:[] for condition in CONDITIONS}
    n_correct=0; brier=0.; supported_total=0
    paired=defaultdict(dict)
    cheap_correct=0
    for case in unseen:
        k=case['case_id'];cond=case['condition'];p=scored[k]['p']
        label=labels[k]['label']
        # No semantic review has been applied to the *other* retrieved document.
        if cond=='retrieved':
            if label != (1 if case['retrieved_source_id']==case['source_id'] else None):
                raise Invalid('fabricated retrieval semantic label')
        elif label != (1 if cond=='sufficient' else 0):
            raise Invalid('tampered original span or mechanical removal truth')
        span = re.fullmatch(r'Can the supplied passage explicitly support the proposed answer "(.+?)" to the question "(.+?)"\?',case['joint_input']['question'])
        if span is None:
            raise Invalid('unregistered prompt/answer schema')
        literal_answer = span.group(1)
        if label is not None:
            supported_total += 1
            n_correct += int((p>=.5)==bool(label))
            brier += (p-label)**2
            lexical = literal_answer.casefold() in case['joint_input']['state'].casefold()
            cheap_correct += int(lexical == bool(label))
            sums[cond].append({'brier':(p-label)**2,'correct':int((p>=.5)==bool(label))})
        paired[case['source_id']][cond] = p
    if len(paired) != WANTED['test'] or any(set(vals)!=set(CONDITIONS) for vals in paired.values()):
        raise Invalid('missing source-group intervention square')
    gaps=[v['sufficient']-v['premise_removed'] for v in paired.values()]
    both_good=sum(int(v['sufficient'] >= .5 and v['premise_removed'] < .5) for v in paired.values())
    # Cluster bootstrap is descriptive on only 12 source groups, NOT independent future-time efficacy.
    rng=random.Random(20261015)
    bs=[]
    for _ in range(512):
        sample=[gaps[rng.randrange(len(gaps))] for _ in gaps]
        bs.append(sum(sample)/len(sample))
    ms=[v['ms'] for v in scored.values()]
    return {'case_count':len(scored),'scored_label_count':supported_total,
            'retrieved_unreviewed_count':sum(1 for c in unseen if c['condition']=='retrieved' and labels[c['case_id']]['label'] is None),
            'question_only_retrieval_original_source_hit_count':sum(
                1 for c in unseen if c['condition']=='retrieved' and
                c['retrieved_source_id']==c['source_id']),
            'question_only_retrieval_original_source_hit_at_1':sum(
                1 for c in unseen if c['condition']=='retrieved' and
                c['retrieved_source_id']==c['source_id'])/WANTED['test'],
            'nonowner_retrieval_accuracy_unavailable':True,
            'accuracy_on_annotated_and_mechanical_views':n_correct/supported_total,
            'brier_on_annotated_and_mechanical_views':brier/supported_total,
            'lexical_answer_presence_baseline_accuracy':cheap_correct/supported_total,
            'condition_scoring':{k:{'count':len(v),
                                    'accuracy':sum(x['correct'] for x in v)/len(v) if v else None,
                                    'brier':sum(x['brier'] for x in v)/len(v) if v else None}
                                 for k,v in sums.items()},
            'paired_oracle_vs_removed_both_correct':both_good,
            'paired_oracle_vs_removed_groups':len(gaps),
            'oracle_minus_removed_mean_probability_gap':statistics.mean(gaps),
            'oracle_minus_removed_bootstrap_95_descriptive':[
                quantile(bs,.025),quantile(bs,.975)],
            'sum_original_request_local_latency_ms':sum(ms),
            'request_local_inference_latency_ms':{'p50':quantile(ms,.5),
                                                   'p95':quantile(ms,.95),
                                                   'p99':quantile(ms,.99)},
            'request_latency_excludes_load_train_publication_and_queue':True,
            'underpowered_for_model_selection':True}


def review(fit, blind, label_doc, original_reports):
    _, unseen=validate_materials(fit,blind)
    question_only_search = independent_question_only_retrieval(fit['cases']+blind['cases'])
    if (type(label_doc) is not dict or set(label_doc) != {'metadata','cases'} or
            label_doc['metadata'] != blind['metadata'] or type(label_doc['cases']) is not list or
            len(label_doc['cases']) != len(unseen)):
        raise Invalid('changed evaluator label source')
    outcomes={}
    for c in label_doc['cases']:
        if type(c) is not dict or set(c) != {'case_id','source_id','group_id','condition','view_sha256','label'}:
            raise Invalid('invalid independent label row')
        if c['case_id'] in outcomes:
            raise Invalid('repeated evaluation label')
        outcomes[c['case_id']]=c
    if set(outcomes) != {x['case_id'] for x in unseen}:
        raise Invalid('missing independent evaluator labels')
    for c in unseen:
        ref=outcomes[c['case_id']]
        for key in ('source_id','group_id','condition','view_sha256'):
            if ref[key]!=c[key]:
                raise Invalid('tampered evaluator/source row identity')
        if ref['label'] not in (None,0,1) or (ref['label'] is not None and type(ref['label']) is not int):
            raise Invalid('wrong evaluator label class')
    if type(original_reports) is not dict or set(original_reports)!=set(MODELS):
        raise Invalid('all four actual original model arms required')
    reports={}
    expected_fit = digest(canonical(fit)); expected_blind = digest(canonical(blind))
    for name,rep in original_reports.items():
        if type(rep) is not dict or rep.get('schema')!='hepta.p0.squad-physical-reader-receipt.v1' or rep.get('model')!=name:
            raise Invalid('changed model arm source')
        if (rep.get('authority')!='DENY_ALL' or rep.get('production_promotion_permitted') is not False or
            rep.get('model_winner_selected') is not False or
            rep.get('fit_material_sha256')!=expected_fit or
            rep.get('blind_material_sha256')!=expected_blind or
            rep.get('number_blind_cases')!=len(unseen) or
            rep.get('actual_pretrained_execution_claimed') is not True or
            rep.get('source_model_independently_authenticated') is not False or
            rep.get('human_independent_premise_reviewed') is not False or
            rep.get('future_outcomes_verified') is not False):
            raise Invalid('false scientific or authority receipt')
        cpu=checked_positive(rep.get('cpu_process_ms'))
        end=checked_positive(rep.get('end_to_end_wall_ms'))
        rss=checked_positive(rep.get('peak_process_rss_bytes'))
        load=checked_positive(rep.get('model_load_ms'))
        if load>end:
            raise Invalid('model load time exceeds whole lifecycle')
        if name=='laya421_nochange':
            if rep.get('model_revision')!=LAYA_SHA or rep.get('head_mode')!='pretrained_checkpoint_native_noul_nochange_not_equal_head':
                raise Invalid('Laya is not an equal-size Head competitor')
            if rep.get('training') is not None or set(rep.get('control',{}))!={'laya_native_nochange'}:
                raise Invalid('fabricated Laya Head learning')
            controls=rep['control'];family='native_laya'
        else:
            revision,width=COMPACT_REVISIONS[name]
            if rep.get('model_revision')!=revision or rep.get('feature_width')!=width:
                raise Invalid('changed model or feature contract')
            t=rep.get('training')
            if (type(t) is not dict or t.get('steps')!=40 or t.get('seed')!=20261015 or
                t.get('trained_head_parameters')!=2*width+2 or
                t.get('initialized_frozen_weight_sha256')!=t.get('control',{}).get('frozen_head',{}).get('head_sha256') or
                t.get('control',{}).get('trained_head',{}).get('head_sha256')==t.get('initialized_frozen_weight_sha256') or
                set(t['control'])!={'frozen_head','trained_head'} or
                t.get('train_only_gradient_update') is not True):
                raise Invalid('unequal or fake actual Head training control')
            checked_positive(t.get('head_train_ms'))
            checked_positive(rep.get('physical_model_load_and_encodings_ms'))
            if load+t['head_train_ms'] > end+1e-4:
                raise Invalid('model load plus actual training exceeds process wall')
            if rep.get('original_e1_loader_preflight_claimed') is not True:
                raise Invalid('original physical Encoder loader preflight absent')
            if name=='mmbert_small' and rep.get('mmbert_whole_serialized_checkpoint_byte_checked') is not True:
                raise Invalid('mmBERT full original weight audit missing')
            controls=t['control'];family='embedding_head'
        sub={}
        for ctrl_name,ctrl in controls.items():
            sub[ctrl_name]=score_arm(unseen,outcomes,ctrl,family=family)
            if sub[ctrl_name]['sum_original_request_local_latency_ms'] > end+1e-4:
                raise Invalid('claimed request work exceeds complete physical process wall')
        reports[name]={'model_sha256_or_revision':rep['model_revision'],
                       'controls':sub,
                       'reported_process_wall_ms':end,'reported_process_cpu_ms':cpu,
                       'reported_peak_rss_bytes':rss,
                       'reported_model_load_ms':load,
                       'reported_head_train_ms':rep['training']['head_train_ms'] if name!='laya421_nochange' else 0,
                       'laya_is_not_parameter_or_train_budget_matched':name=='laya421_nochange'}
    return {'schema':SCHEMA,
            'source_study':'SQuAD v2 human positive answer-span + mechanically removed sentence',
            'study_data_commit':fit['metadata']['dataset_commit'],
            'fit_material_sha256':expected_fit,
            'blind_material_sha256':expected_blind,
            'label_material_sha256':digest(canonical(label_doc)),
            'source_group_count':WANTED['test'],
            'independently_recomputed_question_only_retrieval':question_only_search,
            'retriever_and_source_selection_revised_v2':True,
            'results':reports,
            'source_data_are_not_prospective_chronological':True,
            'no_independent_semantic_verdict_for_mechanical_negative':True,
            'no_future_task_ndu_quality_established':True,
            'missing_energy_joules':True,
            'paired_lexical_baseline_is_required':True,
            'four_model_equal_training_budget':False,
            'independently_authenticated_host_measures':False,
            'model_selection_permitted':False,
            'production_promotion_permitted':False,
            'authority':'DENY_ALL'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fit',type=Path,required=True)
    ap.add_argument('--blind',type=Path,required=True)
    ap.add_argument('--labels',type=Path,required=True)
    for name in MODELS:
        ap.add_argument('--'+name.replace('_','-'),type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    reports={name:read(getattr(a,name)) for name in MODELS}
    result=review(read(a.fit),read(a.blind),read(a.labels),reports)
    write_new(a.output,result)
    print(json.dumps({'review_file_sha256':digest(canonical(result)),
                      'scored':True,'model_winner_selected':False,
                      'production_promotion_permitted':False},sort_keys=True))


if __name__=='__main__':
    main()
