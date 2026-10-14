#!/usr/bin/env python3
"""Independent, read-only E1--E5 evidence *consistency* and paired descriptive review.

No trust anchor is supplied. A claim of a source, model, signature, run or clock
in a JSON file is not proof. Never authorizes production or selects a Stem.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random

OBS_SCHEMA = 'hepta.stem-e1e5-causal-observation.v1'
OUT_SCHEMA = 'hepta.stem-e1e5-independent-outcomes.v1'
READER_SCHEMA = 'hepta.stem-e1e5-reader-four-condition.v1'
READER_CONDITIONS = ('none','retrieved','sufficient','premise_removed')
FUTURES = ('future1','future2','future3')
SPLITS = ('train','calibration','test','future1','future2','future3','ood')
E1_PROFILES = {'granite_97m_r2': (384, 'cls_l2'),
               'mmbert_small': (384, 'mean_l2'),
               'embeddinggemma_2_text': (256, 'matryoshka_256_l2')}
STAGE_COMPARISONS = {
    'E1': {'learned_head': ('no_change','frozen_head')},
    'E2': {'residual_2k': ('no_change','frozen_head','cosine','from_zero'),
           'residual_8k': ('no_change','frozen_head','cosine','from_zero'),
           'residual_16k': ('no_change','frozen_head','cosine','from_zero')},
    'E3': {'learned_bridge': ('text_only','ocr_only','unaligned'),
           'native_multimodal': ('text_only','ocr_only','unaligned')},
    'E4': {'audio_bridge': ('text_only','unaligned'),
           'temporal_adapter': ('text_only','unaligned','temporal_reversed')},
    'E5': {'shared_stem': ('no_change',)},
}
MAX_JSON = 32 * 1024 * 1024
class Invalid(ValueError):
    pass

def _object(pairs):
    out = {}
    for key,value in pairs:
        if key in out: raise Invalid('duplicate key: '+key)
        out[key] = value
    return out

def load(path):
    data = Path(path).read_bytes()
    if not 0 < len(data) <= MAX_JSON: raise Invalid('missing or oversized evidence')
    try:
        obj = json.loads(data, object_pairs_hook=_object,
                         parse_constant=lambda x: (_ for _ in ()).throw(Invalid('nonfinite JSON')))
    except (ValueError,UnicodeError) as e:
        raise Invalid('invalid evidence JSON: '+str(e)) from e
    if type(obj) is not dict: raise Invalid('evidence must be an object')
    return obj,hashlib.sha256(data).hexdigest()

def digest(s):
    if type(s) is not str or len(s)!=64 or s=='0'*64 or any(x not in '0123456789abcdef' for x in s):
        raise Invalid('noncanonical digest')
    return s

def stable(s):
    if type(s) is not str or not 1<=len(s)<=128 or not all(x.isascii() and (x.isalnum() or x in '._:-') for x in s):
        raise Invalid('invalid stable identifier')
    return s

def positive_num(v,zero=True):
    if type(v) not in (int,float) or not math.isfinite(v) or (v<0 if zero else v<=0):
        raise Invalid('invalid numeric measurement')
    return float(v)

def strict_bool(v):
    if type(v) is not bool: raise Invalid('boolean required')
    return v

def _cases(obs):
    if obs.get('schema') != OBS_SCHEMA or obs.get('stage') not in STAGE_COMPARISONS:
        raise Invalid('unknown observation schema/stage')
    if obs.get('production_promotion_permitted') is not False or obs.get('authority')!='DENY_ALL':
        raise Invalid('observational no-authority only')
    for key in ('source_tree_sha256','dataset_sha256','plan_sha256','evaluator_sha256'):
        digest(obs.get(key))
    scope = stable(obs.get('scope'))
    if obs['stage']=='E1':
        profile=E1_PROFILES.get(obs.get('encoder_candidate'))
        if profile is None or obs.get('feature_width') != profile[0] or obs.get('pooling_profile') != profile[1]:
            raise Invalid('unqualified E1 model/width/pooling profile')
        revision=obs.get('upstream_revision')
        if type(revision) is not str or len(revision)!=40 or any(ch not in '0123456789abcdef' for ch in revision):
            raise Invalid('unpinned E1 model revision')
        digest(obs.get('tokenizer_sha256'))
    cases = obs.get('cases')
    if type(cases) is not list or not cases or len(cases)>50000: raise Invalid('invalid bounded cases')
    by_id={};by_group=defaultdict(set);by_input=defaultdict(set);times=defaultdict(list)
    for row in cases:
        if type(row) is not dict: raise Invalid('invalid case')
        ident=stable(row.get('case_id'));group=stable(row.get('source_group'))
        if ident in by_id or row.get('scope')!=scope or row.get('split') not in SPLITS: raise Invalid('duplicate/cross-scope case')
        digest(row.get('input_sha256'))
        if type(row.get('answer_label')) is not int or row['answer_label'] not in (0,1): raise Invalid('binary outcome only')
        t=positive_num(row.get('observed_at'),zero=False)
        by_id[ident]=row;split=row['split']
        by_group[split].add(group);by_input[split].add(row['input_sha256']);times[split].append(t)
    for i,part in enumerate(SPLITS):
        for other in SPLITS[i+1:]:
            if by_group[part]&by_group[other] or by_input[part]&by_input[other]: raise Invalid('cross-window source leakage')
    ordered=[s for s in SPLITS if s!='ood' and times[s]]
    if any(max(times[a])>=min(times[b]) for a,b in zip(ordered,ordered[1:])): raise Invalid('future not chronological')
    arms=obs.get('arms')
    if type(arms) is not list: raise Invalid('missing arms')
    by_arm={}
    for a in arms:
        if type(a) is not dict: raise Invalid('invalid arm')
        name=stable(a.get('name'));digest(a.get('model_sha256'));digest(a.get('head_sha256'))
        if name in by_arm:raise Invalid('duplicate arm')
        if a.get('actual_model_forward') is not True:raise Invalid('model forward claimed missing')
        rows=a.get('predictions')
        if type(rows) is not list or len(rows)!=len(by_id):raise Invalid('unpaired arm predictions')
        preds={}
        for p in rows:
            if type(p) is not dict: raise Invalid('malformed prediction')
            ident=stable(p.get('case_id'))
            if ident not in by_id or ident in preds or p.get('input_sha256')!=by_id[ident]['input_sha256']:
                raise Invalid('prediction mismatch/duplicate')
            if p.get('prelabel_sealed') is not True: raise Invalid('unsealed prediction claim')
            v=positive_num(p.get('positive_probability'))
            if v>1:raise Invalid('bad probability')
            preds[ident]=v
        by_arm[name]=(a,preds)
    for candidate,controls in STAGE_COMPARISONS[obs['stage']].items():
        if candidate not in by_arm or any(control not in by_arm for control in controls): raise Invalid('incomplete control set')
    if obs['stage']=='E1':
        # Same-Encoder Head controls: the independent no-change may be a different model.
        if by_arm['learned_head'][0]['model_sha256'] != by_arm['frozen_head'][0]['model_sha256']:
            raise Invalid('E1 learned/frozen Encoder identity drift')
    if obs['stage']=='E2':
        for name,budget in (('residual_2k',2048),('residual_8k',8192),('residual_16k',16384)):
            arm=by_arm[name][0]
            n=arm.get('trainable_parameters');steps=arm.get('optimizer_steps')
            if type(n) is not int or not 1<=n<=budget or type(steps) is not int or steps<1:
                raise Invalid('E2 Head parameter/optimizer budget absent')
            if arm.get('initial_prediction_matches_baseline') is not True:
                raise Invalid('E2 residual not baseline-preserving')
    return by_id,by_arm

def validate_outcomes(obs,cases,outcomes):
    if outcomes.get('schema')!=OUT_SCHEMA or outcomes.get('dataset_sha256')!=obs['dataset_sha256'] or outcomes.get('plan_sha256')!=obs['plan_sha256']:
        raise Invalid('independent outcome dataset/plan binding')
    producer=stable(outcomes.get('producer_id'))
    if producer==obs.get('observer_producer_id'):raise Invalid('same producer claimed as independent')
    rows=outcomes.get('rows')
    if type(rows) is not list or len(rows)!=len(cases):raise Invalid('incomplete independent outcomes')
    seen=set()
    for r in rows:
        if type(r) is not dict:raise Invalid('bad outcome')
        ident=stable(r.get('case_id'))
        if ident not in cases or ident in seen: raise Invalid('outcome mismatch/duplicate')
        c=cases[ident]
        if any(r.get(k)!=c[k] for k in ('source_group','input_sha256','split','observed_at')) or r.get('label')!=c['answer_label']:
            raise Invalid('outcome disagrees with source case')
        digest(r.get('outcome_sha256'));seen.add(ident)
    return producer

def validate_reader(payload,cases):
    if payload.get('schema')!=READER_SCHEMA:raise Invalid('reader schema')
    rows=payload.get('trials')
    if type(rows) is not list or not rows or len(rows)>50000:raise Invalid('reader trials missing')
    by_task=defaultdict(dict);fixed={};source_groups={}
    by_input={c['input_sha256']:c for c in cases.values()}
    for r in rows:
        if type(r) is not dict:raise Invalid('invalid reader trial')
        task=stable(r.get('task_id'));cond=r.get('condition')
        if cond not in READER_CONDITIONS or cond in by_task[task]:raise Invalid('duplicate/unknown Reader condition')
        shared=(digest(r.get('task_input_sha256')),digest(r.get('reader_model_sha256')),
                digest(r.get('prompt_template_sha256')),r.get('budget_tokens'),r.get('seed'))
        if type(shared[3]) is not int or shared[3]<=0 or type(shared[4]) is not int:
            raise Invalid('Reader budget/seed required')
        if task in fixed and fixed[task]!=shared:raise Invalid('changed Reader model/prompt/budget or task')
        if shared[0] not in by_input:raise Invalid('unbound Reader task input')
        group=stable(r.get('source_group'))
        if group!=by_input[shared[0]]['source_group']:raise Invalid('unbound Reader source group')
        if task in source_groups and source_groups[task]!=group:raise Invalid('Reader group drift')
        strict_bool(r.get('correct'));strict_bool(r.get('abstained'))
        digest(r.get('input_sha256'));digest(r.get('answer_sha256'))
        if cond=='sufficient':
            digest(r.get('reviewed_sufficient_evidence_sha256'))
            stable(r.get('independent_reviewer_id'))
        if cond=='premise_removed':
            digest(r.get('removed_critical_premise_sha256'))
        by_task[task][cond]=r;fixed[task]=shared;source_groups[task]=group
    if len(set(source_groups.values()))!=len(source_groups):raise Invalid('Reader tasks share source group')
    for task,trials in by_task.items():
        if set(trials)!=set(READER_CONDITIONS):raise Invalid('incomplete four-condition Reader task')
        if len({r['input_sha256'] for r in trials.values()})!=4:raise Invalid('Reader evidence conditions not distinct')
    adequate=all(v['sufficient']['correct'] and not v['sufficient']['abstained'] for v in by_task.values())
    observed_splits={by_input[v['sufficient']['task_input_sha256']]['split'] for v in by_task.values()}
    future_coverage=all(split in observed_splits for split in FUTURES)
    premise_flip=sum(v['sufficient']['correct'] and (not v['premise_removed']['correct'] or v['premise_removed']['abstained']) for v in by_task.values())
    return {'tasks':len(by_task),'all_sufficient_correct':adequate,'all_future_windows_represented':future_coverage,'premise_removed_changed_outcome_count':premise_flip,
            'independent_review_receipts_cryptographically_verified':False}

def temporal_pairs(obs,cases):
    if obs['stage']!='E4':return {'paired_video_cases':0,'validated_reversal_pairs':0}
    pairs=defaultdict(list)
    for c in cases.values():
        if c.get('modality')!='video':continue
        pair=stable(c.get('counterfactual_pair_id'))
        digest(c.get('frame_order_sha256'));digest(c.get('frame_content_multiset_sha256'))
        pairs[pair].append(c)
    if not pairs:raise Invalid('no actual temporal pairs')
    for group,rows in pairs.items():
        if len(rows)!=2 or len({r['frame_order_sha256'] for r in rows})!=2 or len({r['frame_content_multiset_sha256'] for r in rows})!=1:
            raise Invalid('invalid reversed frame order or changed content')
        if len({r['answer_label'] for r in rows})!=2 or len({r['source_group'] for r in rows})!=1 or len({r['split'] for r in rows})!=1:
            raise Invalid('reversal must flip label in same source group and split')
    return {'paired_video_cases':sum(map(len,pairs.values())),'validated_reversal_pairs':len(pairs)}

def scale_trace(obs):
    if obs['stage']!='E5':return {'reported_active_cell_coverage':None}
    n=obs.get('logical_cells');active=obs.get('active_cells')
    if type(n) is not int or n not in (64,256,1024,4096) or type(active) is not int or not 1<=active<=n:
        raise Invalid('unsupported scale cohort')
    trace=obs.get('worker_trace')
    if type(trace) is not dict or trace.get('worker_receipt_type')!='research_unverified_worker_trace_v1':
        raise Invalid('missing native worker trace')
    digest(trace.get('stem_sha256'));digest(trace.get('target_host_sha256'))
    records=trace.get('requests')
    if type(records) is not list or not active<=len(records)<=50000: raise Invalid('incomplete worker requests')
    seen=set();cell_ids=set();miss_by_forward={};hits=0
    for r in records:
        if type(r) is not dict:raise Invalid('bad worker record')
        rid=stable(r.get('request_id'));cell=stable(r.get('cell_id'))
        scope=stable(r.get('scope'));generation=r.get('generation')
        if type(generation) is not int or generation<1: raise Invalid('generation missing')
        source=digest(r.get('input_sha256'));forward=stable(r.get('forward_id'))
        batch=stable(r.get('backend_batch_id'))
        if rid in seen or r.get('final_use_checked') is not True:raise Invalid('duplicate request or missing final use')
        seen.add(rid);cell_ids.add(cell)
        is_hit=strict_bool(r.get('cache_hit'))
        key=(scope,generation,trace['stem_sha256'],source)
        if is_hit:
            hits+=1
            if forward not in miss_by_forward or miss_by_forward[forward]!=key:
                raise Invalid('unjustified hit or cross-scope feature reuse')
        elif forward in miss_by_forward:raise Invalid('repeated forward ID for distinct misses')
        else:miss_by_forward[forward]=key
        if not batch: raise Invalid('missing batch')
    if len(cell_ids)!=active:raise Invalid('declared active Cells not covered')
    return {'reported_active_cell_coverage':len(cell_ids),'reported_requests':len(records),
            'reported_unique_forwards':len(miss_by_forward),'reported_cache_hits':hits,
            'physical_worker_signature_verified':False}

def _group_metric(by_id,preds,reference,split):
    diffs=defaultdict(list)
    for ident,c in by_id.items():
        if c['split']!=split:continue
        y=c['answer_label']
        candidate=float((preds[ident]>=.5)==bool(y))
        control=float((reference[ident]>=.5)==bool(y))
        diffs[c['source_group']].append(candidate-control)
    return [sum(v)/len(v) for v in diffs.values()]

def _lower_bound(groups,seed,alpha):
    if not groups:return None
    rng=random.Random(seed)
    n=len(groups);res=[]
    for _ in range(2000):
        res.append(sum(groups[rng.randrange(n)] for _ in range(n))/n)
    res.sort();index=max(0,min(len(res)-1,math.floor((alpha/2)*len(res))))
    return res[index]

def review(obs,outcomes,reader):
    by_id,arms=_cases(obs)
    producer=validate_outcomes(obs,by_id,outcomes)
    reader_report=validate_reader(reader,by_id)
    temporal=temporal_pairs(obs,by_id);scale=scale_trace(obs)
    report=[]
    n_tests=sum(len(controls)*len(FUTURES) for controls in STAGE_COMPARISONS[obs['stage']].values())
    for candidate,controls in sorted(STAGE_COMPARISONS[obs['stage']].items()):
        for control in controls:
            windows=[]
            for split in FUTURES:
                grouped=_group_metric(by_id,arms[candidate][1],arms[control][1],split)
                if len(grouped)<50:
                    windows.append({'split':split,'independent_groups':len(grouped),'lcb_accuracy_gain':None,
                                    'sufficient_groups':False})
                else:
                    salt=hashlib.sha256((obs['plan_sha256']+'|'+candidate+'|'+control+'|'+split).encode()).digest()
                    seed=int.from_bytes(salt[:8],'big')
                    windows.append({'split':split,'independent_groups':len(grouped),
                                    'mean_accuracy_gain':sum(grouped)/len(grouped),
                                    'lcb_accuracy_gain':_lower_bound(grouped,seed,0.05/max(1,n_tests)),
                                    'sufficient_groups':True})
            report.append({'candidate':candidate,'control':control,'windows':windows})
    return {'schema':'hepta.stem-e1e5-confirmatory-consistency.v1','stage':obs['stage'],
            'reader':reader_report,'temporal':temporal,'scale':scale,
            'comparisons':report,'outcome_producer_claim':producer,
            'independent_outcome_signatures_verified':False,
            'model_weights_and_forwards_independently_verified':False,
            'prelabel_timestamp_authority_verified':False,
            'target_host_physical_cost_independently_verified':False,
            'future_ndu_utility_independently_verified':False,
            'all_acceptance_gates_passed':False,'production_promotion_permitted':False,'authority':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--observations',type=Path,required=True)
    p.add_argument('--outcomes',type=Path,required=True)
    p.add_argument('--reader-trials',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    source,osource=load(a.observations);out,ohash=load(a.outcomes);reader,rhash=load(a.reader_trials)
    report=review(source,out,reader)
    report['input_sha256']={'observations':osource,'outcomes':ohash,'reader':rhash}
    data=(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with a.output.open('xb') as f:f.write(data)

if __name__=='__main__':main()
