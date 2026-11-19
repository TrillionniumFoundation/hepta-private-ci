#!/usr/bin/env python3
"""Independent four-original-E16-ZIP source-blind answer geometry replay.

No true labels are opened; this is *necessary* discrimination evidence only.
All original model/Head artefacts must match their exact archived byte SHA.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from zipfile import ZipFile

SOURCE_SHA='1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'
OBS='7e4a0dc4ff48688b1ace0640a3290ee90011487843384a30565b65d3d240e7a5'
E16_HEAD='09d0528d95ca2cab997d4e17f499b098dc1fdb29'
METHODS=('centered_raw_5','centered_scaled_5')
SOURCE_SCHEMA='hepta.multirc.genuine-answer-slate-frozen-readers.v1'
E16_SCHEMA='hepta.e16.answer-centered-real-logits.v1'
E22_SCHEMA='hepta.e22.original-pretrained-e16-e15-eight-arm-blind.v1'
SCHEMA='hepta.e24.actual-E16-true-archive-prelabel-question-geometry.v1'
FOLDS=(
 ('1ad37a6ce022e8d051467db52a59a9ea2a683aa57f04c9b51867f4c7db136ab9','62f55e09ab8e669e0337c184a911ac5e4b00ff2adbd899f127bdeaea53cb93bd'),
 ('67dff7033303ddef4fedd06b8b4e7af105b24d154eb4069072c69525bca2991e','fc8eba10607f3b33c61b9c05607f71946fc5c4521fdd8356b2bf8a51da3b355d'),
 ('990ba455578abe57ac8cb031633d3a73cc1dd488f5a418f20045334f845b9eaa','f1ae0d287973ba942b05d57e0da3e5735c1505eae7f19b6fc7eda77c700f9c21'),
 ('ff172d1c44f31c134c5793520127a9fd166d9ad26138f88f86ce95191550f934','5913dc0fb5d61f480db50225382b76b0556c34cf773c2b4a2f7157e771bb1eb2'),
)

class Denied(ValueError):
    pass

def need(ok:bool,why:str)->None:
    if not ok:raise Denied(why)

def digest(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def strict(raw:bytes):
    def pairs(kv):
        d={}
        for k,v in kv:
            need(k not in d,'duplicate JSON field')
            d[k]=v
        return d
    try:
        return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(Denied('nonfinite JSON')))
    except (UnicodeError,json.JSONDecodeError) as e:raise Denied('malformed original JSON') from e

def archive(path:Path,sha:str,names:tuple[str,...]):
    need(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<4_000_000,'missing bounded exact model archive')
    need(digest(path.read_bytes())==sha,'wrong original ZIP SHA')
    with ZipFile(path) as z:
        entries=z.infolist()
        need(len(entries)<=100 and len({x.filename for x in entries})==len(entries) and
             all(x.file_size<=1_000_000 and not x.filename.startswith('/') and '..' not in x.filename.split('/') for x in entries),
             'unbounded or ambiguous archive')
        need(set(names)<=set(z.namelist()),'missing exact model member')
        return {n:z.read(n) for n in names}

def original_cases(path:Path):
    obj=archive(path,SOURCE_SHA,('multirc-native-candidate-audit/audit.json',
                                'multirc-native-candidate-audit/COMMITTED.json'))
    rows=strict(obj['multirc-native-candidate-audit/audit.json'])
    committed=strict(obj['multirc-native-candidate-audit/COMMITTED.json'])
    need(rows.get('schema')==SOURCE_SCHEMA and rows.get('observation_id')==OBS and
         rows.get('evaluation_labels_loaded') is False and rows.get('production_authorized') is False and
         committed.get('observation_sha256')==digest(obj['multirc-native-candidate-audit/audit.json']) and
         committed.get('observation_id')==OBS,'not original pretrained source-only receipt')
    metas=rows.get('rows')
    need(type(metas) is list and len(metas)==33 and len({r['task_id'] for r in metas})==33 and
         len({r['source_group'] for r in metas})==4 and
         len({(r['source_group'],r['question_slot']) for r in metas})==8,
         'original MultiRC candidate/question census drift')
    need(all(set(r)=={'task_id','source_group','question_slot','candidate_id','original_v1_candidate'}
             and type(r['original_v1_candidate']) is bool for r in metas),
         'untrusted source candidate fields')
    return metas

def review(source:Path,fold_files:list[Path],e22_blind:Path|None=None):
    need(type(fold_files) is list and len(fold_files)==4,'four physically trained held folds required')
    rows=original_cases(source)
    ids={r['task_id']:r for r in rows}
    groups=sorted({r['source_group'] for r in rows})
    seen=set();probabilities={};meter=[]
    for fold,(path,(outer,inner)) in enumerate(zip(fold_files,FOLDS,strict=True)):
        obj=archive(path,outer,('held-prediction.json','held-prediction.sha256','source-head.txt'))
        need(digest(obj['held-prediction.json'])==inner and
             obj['held-prediction.sha256'].decode().split()[0]==inner and
             obj['source-head.txt'].decode().strip()==E16_HEAD,
             'source/head/prediction seal differs from original E16')
        record=strict(obj['held-prediction.json'])
        need(record.get('schema')==E16_SCHEMA and record.get('authority')=='DENY_ALL' and
             record.get('production_accepted') is False and
             record.get('held_human_labels_accessed') is False and
             record.get('natural_future_task_gain') is False and
             record.get('original_archive_sha256')==SOURCE_SHA and
             record.get('original_observation_id')==OBS and
             record.get('methods')==list(METHODS) and
             record.get('fold')==fold and record.get('held_group')==groups[fold] and
             record.get('physical_train_steps_completed')==48 and
             record.get('original_model_forwards_new')==0 and
             record.get('train_only_past_groups')==3 and
             record.get('reader_semantic_adequacy_proven') is False,
             'invalid original trained five-param Head scope')
        ps=record.get('predictions');cost=record.get('meters')
        need(type(ps) is list and len(ps)==sum(r['source_group']==groups[fold] for r in rows)
             and type(cost) is dict and set(cost)==set(METHODS),'incomplete original fold')
        for method in METHODS:
            m=cost[method]
            need(type(m) is dict and set(m)=={'train_cpu_ns','held_cpu_ns','parameter_count','steps'}
                 and type(m['train_cpu_ns']) is int and m['train_cpu_ns']>0 and
                 type(m['held_cpu_ns']) is int and m['held_cpu_ns']>0 and
                 m['parameter_count']==5 and m['steps']==48,'fake model fit or CPU meter')
            meter.append({'fold':fold,'method':method,**m})
        for p in ps:
            tid=p.get('task_id')
            need(tid in ids and tid not in seen and p.get('source_group')==groups[fold] and
                 p.get('question_slot')==ids[tid]['question_slot'] and
                 p.get('candidate_id')==ids[tid]['candidate_id'] and
                 type(p.get('probabilities')) is dict and set(p['probabilities'])==set(METHODS),
                 'changed authentic held answer identity')
            for m,val in p['probabilities'].items():
                need(type(val) is float and math.isfinite(val) and 0<val<1,'nonfinite held model output')
            probabilities[tid]=p['probabilities'];seen.add(tid)
    need(set(probabilities)==set(ids),'missing original answer alternatives')
    if e22_blind is not None:
        need(e22_blind.is_file() and e22_blind.stat().st_size<1_000_000,'missing E22 blind evidence')
        b=strict(e22_blind.read_bytes())
        need(type(b) is dict and b.get('schema')==E22_SCHEMA and b.get('authority')=='DENY_ALL' and
             b.get('human_labels_opened') is False and b.get('production_accepted') is False and
             b.get('source_archive_sha256')==SOURCE_SHA and b.get('e16_head')==E16_HEAD,
             'wrong E22 original source-only scorer')
        existing=b.get('rows')
        need(type(existing) is list and len(existing)==33 and
             {r['task_id'] for r in existing}==set(probabilities),'not same E22 33 case inventory')
        for item in existing:
            tid=item['task_id']
            need(all(item['probs'][m]==probabilities[tid][m] for m in METHODS),
                 'independent original fold logits disagree with E22 producer')
        meters=b.get('e16_observed_student_CPU_ns')
        need(type(meters) is list and len(meters)==8 and
             sorted(meters,key=lambda x:(x['fold'],x['method']))==
             sorted(meter,key=lambda x:(x['fold'],x['method'])),
             'E22 physical fit/CPU registry differs from original E16 folds')
    q=defaultdict(list)
    for r in rows:q[(r['source_group'],r['question_slot'])].append(r['task_id'])
    arms={}
    for method in METHODS:
        hard_constant=exact=near=0
        spans=[];details=[]
        for (g,slot),members in sorted(q.items()):
            vals=[probabilities[tid][method] for tid in members]
            invariant=len({int(p>=.5) for p in vals})==1
            score_invariant=len(set(vals))==1
            span=max(vals)-min(vals)
            hard_constant+=invariant
            exact+=score_invariant
            near+=span<=.001
            spans.append(span)
            details.append({'source_group':g,'question_slot':slot,'original_candidates':len(members),
                            'hard_class_constant':invariant,'exact_score_constant':score_invariant})
        costs=[m for m in meter if m['method']==method]
        arms[method]={'constant_hard_questions':hard_constant,
                      'questions_with_two_predicted_classes':8-hard_constant,
                      'exactly_constant_score_questions':exact,
                      'span_le_0p001_questions':near,
                      'largest_probability_span':round(max(spans),15),
                      'four_original_train_cpu_ns':sum(m['train_cpu_ns'] for m in costs),
                      'four_original_held_cpu_ns':sum(m['held_cpu_ns'] for m in costs),
                      'four_original_optimizer_steps':sum(m['steps'] for m in costs),
                      'original_trainable_parameters_per_fold':5,
                      'per_question':details}
    need(arms['centered_raw_5']['constant_hard_questions']==8 and
         arms['centered_scaled_5']['constant_hard_questions']==2,
         'original archived E16 discrimination result changed')
    return {'schema':SCHEMA,'authority':'DENY_ALL','production_accepted':False,
            'source_archive_sha256':SOURCE_SHA,'e16_source_head':E16_HEAD,
            'original_question_count':8,'original_passages':4,'original_candidates':33,
            'real_original_archive_bytes_reopened':True,
            'e22_independent_prediction_replay_passed':e22_blind is not None,
            'original_human_labels_or_score_zip_opened':False,
            'new_pretrained_forwards_or_training_steps':0,
            'e16_scaled_correct_answer_gain_established_by_this_blind_report':False,
            'complete_question_success_established':False,
            'source_generalization_or_cost_adjusted_win_certified':False,
            'NDU_System2_reader_sufficiency_admitted':False,
            'arms':arms}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--original',type=Path,required=True)
    for i in range(4):ap.add_argument(f'--e16-{i}',type=Path,required=True)
    ap.add_argument('--e22-blind',type=Path)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    obj=review(a.original,[getattr(a,f'e16_{i}') for i in range(4)],a.e22_blind)
    with a.out.open('x',encoding='utf8') as f:f.write(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
    print('ORIGINAL_E16_TWO_HEAD_REAL_ZIP_PRELABEL_GEOMETRY / DENY_ALL')

if __name__=='__main__':main()
