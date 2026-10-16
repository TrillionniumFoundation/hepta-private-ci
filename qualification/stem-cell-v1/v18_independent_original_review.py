"""Read-only audit for V18 original Reader and label-sealed 2x2 headings/lengths.

Does NOT generate an answer, sign human sufficiency, score semantic correctness,
certify numerical HF parity, or authorize a model/Cell.
"""
from __future__ import annotations
from collections import defaultdict
import json
import math
from pathlib import Path
import re
from v18_factorial_original_reader import SCHEMA, ALL_ARMS, ARMS, READER_SHA, TOKEN_SHA, digest, htext

COHORTS=('literal_in_annotated_source','not_literal_in_annotated_source')
FAMILIES=('conv-47','conv-48','conv-49','conv-50')
CITE=re.compile(r'\[E([0-9]+)\]')


def lines(path):
    path=Path(path)
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]


def recount(plan,new,starts,v17,v17_raw,tokenizer):
    if (plan.get('schema')!=SCHEMA+'.source-only-plan' or plan.get('v17_plan_sha256')!=digest(v17)
        or plan.get('reader_weights_sha256')!=READER_SHA or plan.get('tokenizer_sha256')!=TOKEN_SHA
        or plan.get('publisher_gold_available_to_producer') is not False
        or plan.get('production_authorized') is not False):
        raise ValueError('unbound or authorizing V18 plan')
    requests=plan.get('new_requests')
    if (type(requests)is not dict or len(requests)!=58
        or plan.get('novel_physical_requests')!=58 or plan.get('question_count')!=32
        or plan.get('changed_source_cases')!=29 or plan.get('reused_unchanged_model_requests')!=6):
        raise ValueError('V18 no-source-input-change census')
    if (new.get('schema')!=SCHEMA+'.original-physical-answers'
        or new.get('plan_sha256')!=digest(plan)
        or new.get('model_sha256')!=READER_SHA or new.get('tokenizer_sha256')!=TOKEN_SHA
        or new.get('requests')!=58 or new.get('pretrained_model_executed') is not True
        or new.get('official_HF_parity') is not False or new.get('reference_reader_executed') is not False
        or new.get('independently_human_reviewed') is not False or new.get('production_authorized') is not False):
        raise ValueError('physical model unverified or mislabeled')
    if (v17_raw.get('plan_sha256')!=digest(v17) or v17_raw.get('model_sha256')!=READER_SHA
        or v17_raw.get('requests')!=64 or v17_raw.get('production_authorized') is not False):
        raise ValueError('prior V17 model material not sealed')
    old=v17_raw.get('raw_answers');outs=new.get('raw_answers')
    if type(old)is not dict or set(old)!=set(v17['requests']) or type(outs)is not dict or set(outs)!=set(requests):
        raise ValueError('missing or substituted raw outputs')
    if type(starts)is not list or len(starts)!=58:
        raise ValueError('durable start census incomplete')
    seen=set(); forwards=0; ni=no=0; pairs=[]; arm_totals={a:dict(requests=0,input_tokens=0,output_tokens=0) for a in ARMS}
    for entry in starts:
        if type(entry)is not dict or set(entry)!={'request_id','plan_sha256','input_tokens','input_ids_sha256'}:
            raise ValueError('unexpected start log fields')
        rid=entry['request_id']
        if type(rid)is not str or rid in seen or rid not in requests:
            raise ValueError('injected or repeated request')
        seen.add(rid)
        row=requests[rid];model_out=outs[rid];token_ids=tokenizer.encode(row['prompt'])
        if (not 1<=len(token_ids)<=1000 or entry['plan_sha256']!=digest(plan)
            or entry['input_tokens']!=len(token_ids) or entry['input_ids_sha256']!=digest(token_ids)):
            raise ValueError('source-tokenized prompt changed after sealing')
        if type(model_out)is not dict or set(model_out)!={'case_id','arm','source_ids','answer_text','answer_sha256','output_ids','input_tokens','output_tokens','cpu_seconds'}:
            raise ValueError('wrong answer shape')
        output_ids=model_out['output_ids']
        if (model_out['case_id']!=row['case_id'] or model_out['arm']!=row['arm'] or model_out['source_ids']!=row['source_ids']
            or type(output_ids)is not list or not 1<=len(output_ids)<=plan['max_new_tokens']
            or any(type(t)is not int or not 0<=t<49152 for t in output_ids)
            or model_out['answer_text']!=tokenizer.decode(output_ids)
            or model_out['answer_sha256']!=htext(model_out['answer_text'])
            or type(model_out['cpu_seconds']) not in (int,float) or not math.isfinite(model_out['cpu_seconds'])
            or model_out['cpu_seconds']<0
            or model_out['input_tokens']!=len(token_ids) or model_out['output_tokens']!=len(output_ids)):
            raise ValueError('wrong original answer or source binding')
        forwards+=len(output_ids)+(output_ids[-1]!=2)
        ni+=len(token_ids);no+=len(output_ids)
        stat=arm_totals[row['arm']];stat['requests']+=1;stat['input_tokens']+=len(token_ids);stat['output_tokens']+=len(output_ids)
        pairs.append([rid,model_out['answer_sha256'],digest(output_ids)])
    if seen!=set(requests) or new['model_forwards']!=forwards:
        raise ValueError('model forward count or started request mismatch')
    answer_grid={}; reuse_count=0; same_sources=True
    for case in plan['cases']:
        qid=case['case_id']
        if qid in answer_grid or case['cohort'] not in COHORTS or case['family'] not in FAMILIES:
            raise ValueError('duplicated original source/question')
        lookup={}
        for name in ALL_ARMS:
            if name=='full_full_heading':rid=case[name];answer=old[rid]
            elif name=='focused_focus_heading':rid=case[name];answer=old[rid]
            else:
                spec=case['cross_arms'][name];rid=spec['request_id']
                if spec['reused_v17']:
                    reuse_count+=1
                    if rid not in old:raise ValueError('source-unsound V17 reuse')
                    answer=old[rid]
                else:
                    if rid not in outs:raise ValueError('unforwarded new model input')
                    answer=outs[rid]
            if (answer['case_id']!=qid or answer['source_ids']!=old[case['full_full_heading']]['source_ids']):
                raise ValueError('cross-arm old/new source mismatch')
            lookup[name]=answer
        answer_grid[qid]=lookup
    if len(answer_grid)!=32 or reuse_count!=6:
        raise ValueError('duplicate/omitted full factorial case')
    result={'schema':SCHEMA+'.independent-original-recount',
            'plan_sha256':digest(plan),'model_sha256':READER_SHA,
            'new_original_requests':58,'identical_reused_v17_requests':6,
            'total_factorial_case_arm_slots':128,'independent_source_roots':4,
            'original_model_forwards':forwards,'input_tokens':ni,'output_tokens':no,
            'new_output_token_digest':digest(sorted(pairs)),
            'per_new_arm_tokens':arm_totals,
            'human_semantic_correctness':None,'human_verified_sufficiency':False,
            'official_HF_parity':False,'new_calendar_windows':0,
            'production_authorized':False,'decision':'BYTES_RECOUNTED_NO_GO'}
    return result,answer_grid


def compare_repeat(plan,first,second):
    if (first.get('plan_sha256')!=digest(plan) or second.get('plan_sha256')!=digest(plan)
        or first.get('model_forwards')!=second.get('model_forwards') or first.get('requests')!=58 or second.get('requests')!=58):
        raise ValueError('different model runs or incomplete duplicate')
    a=first['raw_answers'];b=second['raw_answers']
    if set(a)!=set(b):raise ValueError('different request census')
    for rid in a:
        for field in ('case_id','arm','source_ids','input_tokens','output_tokens','output_ids','answer_text','answer_sha256'):
            if a[rid][field]!=b[rid][field]:raise ValueError('physical Reader repeat diverged '+field)
    return {'schema':SCHEMA+'.double-original-repeat','identical_requests':58,
            'forwards_each':first['model_forwards'],'real_model_answers_reproduced':True,
            'semantic_correctness':None,'production_authorized':False}


def score_original_answers(plan,grid,original):
    """Runs ONLY after original answers were completed; no labels in planning/reader."""
    if len(grid)!=32 or type(original)is not list or len(original)!=10:
        raise ValueError('missing original outcome material')
    owner={x['sample_id']:x for x in original}
    if set(owner)!={'conv-26','conv-30','conv-41','conv-42','conv-43','conv-44','conv-47','conv-48','conv-49','conv-50'}:
        raise ValueError('original source roots changed')
    cohorts={k:{arm:dict(n=0,unknown=0,substring=0,exact=0) for arm in ALL_ARMS} for k in COHORTS}
    families={k:{arm:dict(n=0,substring=0) for arm in ALL_ARMS} for k in FAMILIES}
    contrasts={k:{'known':0,'length_effect_full_heading_gain':0,'length_effect_full_heading_loss':0,
                  'length_effect_focus_heading_gain':0,'length_effect_focus_heading_loss':0,
                  'heading_effect_full_body_gain':0,'heading_effect_full_body_loss':0,
                  'heading_effect_focus_body_gain':0,'heading_effect_focus_body_loss':0,
                  'interaction_sum':0} for k in COHORTS}
    def gain_loss(a,b,k,pre):
        k[pre+'_gain']+=int(b and not a);k[pre+'_loss']+=int(a and not b)
    for row in plan['cases']:
        fam=row['family'];cohort=row['cohort'];cid=row['case_id'];idx=int(cid.split('/q',1)[1])
        original_case=owner[fam]['qa'][idx]
        answer=original_case.get('answer');known=type(answer)is str and bool(answer.strip())
        target=answer.strip().casefold() if known else None
        reference={arm:grid[cid][arm]['answer_text'] for arm in ALL_ARMS}
        outcome={arm:int(known and target in reference[arm].casefold()) for arm in ALL_ARMS}
        for arm in ALL_ARMS:
            c=cohorts[cohort][arm];f=families[fam][arm]
            c['n']+=1;f['n']+=1;c['unknown']+=int(not known)
            c['substring']+=outcome[arm];f['substring']+=outcome[arm]
            c['exact']+=int(known and target==reference[arm].strip().casefold())
        if known:
            c=contrasts[cohort];c['known']+=1
            ff=outcome['full_full_heading']; fH=outcome['full_focus_heading']
            Ff=outcome['focused_full_heading']; FF=outcome['focused_focus_heading']
            gain_loss(ff,Ff,c,'length_effect_full_heading')
            gain_loss(fH,FF,c,'length_effect_focus_heading')
            gain_loss(ff,fH,c,'heading_effect_full_body')
            gain_loss(Ff,FF,c,'heading_effect_focus_body')
            c['interaction_sum']+=(FF-fH)-(Ff-ff)
    if any(t['n']!=16 for cohort in cohorts.values() for t in cohort.values()):raise ValueError('cohort denominators corrupted')
    if any(t['n']!=8 for family in families.values() for t in family.values()):raise ValueError('family denominators corrupted')
    return {'schema':SCHEMA+'.publisher-literal-original-postseal',
            'cohort_counts':cohorts,'family_counts':families,'paired_factorial_contrasts':contrasts,
            'outcome_data_unavailable_to_source_first_producer':True,
            'publisher_substring_not_semantic_truth':True,
            'model_ability_sufficient_evidence_unverified':True,
            'independent_human_judgments':0,'independent_future_windows':0,
            'cell_learning_gain':False,'production_authorized':False,
            'decision':'HOLD_NO_GO'}


def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--new-answers',required=True)
    p.add_argument('--new-starts',required=True);p.add_argument('--v17-plan',required=True)
    p.add_argument('--v17-answers',required=True);p.add_argument('--reader-dir',required=True)
    p.add_argument('--original',default=None);p.add_argument('--out',required=True)
    a=p.parse_args();from v12_reader_runtime import OriginalCandidateBPE
    from v18_factorial_original_reader import sealed
    plan=json.load(open(a.plan));new=json.load(open(a.new_answers));v17=json.load(open(a.v17_plan));old=json.load(open(a.v17_answers));tok=OriginalCandidateBPE(a.reader_dir)
    reviewed,grid=recount(plan,new,lines(a.new_starts),v17,old,tok)
    if a.original is not None:
        scored=score_original_answers(plan,grid,json.load(open(a.original)))
        reviewed['postseal']=scored
    sealed(a.out,reviewed)
    print(json.dumps({k:v for k,v in reviewed.items() if k not in ('postseal',)},sort_keys=True))

if __name__=='__main__':main()
