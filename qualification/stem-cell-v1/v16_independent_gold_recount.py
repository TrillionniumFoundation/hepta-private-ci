"""Read-only independently implemented ORIGINAL publisher text-label weak scorer.

Not an independently authenticated human semantic evaluator; never emits a win.
"""
from __future__ import annotations
import argparse
import json
from hashlib import sha256
from pathlib import Path
from v16_literal_witness_reader import read, digest, htext, HELD, GROUPS, ARMS, SCHEMA, CORPUS_SHA


def recount(plan,raw,source,original,reported):
    if (plan.get('schema')!=SCHEMA+'.answer-dependent-precommitted-plan'
        or raw.get('schema')!=SCHEMA+'.actual-original-reader-results'
        or reported.get('schema')!=SCHEMA+'.sanitized-historical-literal-diagnostic'):
        raise ValueError('wrong cohort/result format')
    if (raw.get('plan_sha256')!=digest(plan)
        or reported.get('plan_sha256')!=digest(plan)
        or reported.get('original_answer_journal_sha256')!=digest(raw)
        or reported.get('original_dataset_sha256')!=CORPUS_SHA):
        raise ValueError('original source/prediction identity changed')
    rows={x['sample_id']:x for x in original}
    if len(rows)!=10 or set(rows)!=set(source['families']):raise ValueError('original human-source roster altered')
    if len(plan['cases'])!=32 or set(raw['raw_answers'])!=set(plan['requests']):raise ValueError('incomplete actual question/answer roster')
    audit={g:{a:{'cases':0,'publisher_witness_delivered':0,'literal_target_substring':0,
                 'literal_target_exact_casefold':0,'citation_syntax':0,'bad_citations':0,
                 'literal_unknown':0,'input_tokens':0,'output_tokens':0} for a in ARMS} for g in GROUPS}
    family={f:{g:{'cases':0,'changed_retrieved_to_witness':0,'changed_witness_to_lesion':0,
                  'witness_target_substring':0} for g in GROUPS} for f in HELD}
    seen=set()
    for c in plan['cases']:
        ident=c['id'];f=c['family'];grp=c['cohort']
        if (ident in seen or f not in HELD or grp not in GROUPS or ident.split('/q')[0]!=f):
            raise ValueError('duplicate/wrong original family')
        seen.add(ident)
        idx=int(ident.split('/q')[1]);original_qa=rows[f]['qa'][idx]
        ev=original_qa.get('evidence')
        if type(ev)!=list or ev!=[c['witness_id']]:raise ValueError('publisher original witness mismatch')
        original_docs={d['id']:d['text'] for d in source['families'][f]['passages']}
        answer=original_qa.get('answer');has_answer=type(answer)==str and bool(answer.strip())
        expected_present=(has_answer and len(answer.strip())>=4 and answer.strip().casefold() not in {'yes','no','true','false','none','unknown'}
                          and any(x.isalpha() for x in answer.strip()) and answer.strip().casefold() in original_docs[c['witness_id']].casefold())
        if (grp==GROUPS[0])!=bool(expected_present):raise ValueError('source answer-literal classification false')
        texts={}
        for arm in ARMS:
            rq=c['arms'][arm]['request_id'];resp=raw['raw_answers'][rq]
            stat=audit[grp][arm];stat['cases']+=1
            ids=c['arms'][arm]['evidence_ids']
            if resp['source_ids']!=ids:raise ValueError('altered delivered evidence')
            stat['publisher_witness_delivered']+=int(c['witness_id'] in ids)
            txt=resp['answer_text'];texts[arm]=txt
            stat['literal_target_substring']+=int(has_answer and answer.strip().casefold() in txt.casefold())
            stat['literal_target_exact_casefold']+=int(has_answer and answer.strip().casefold()==txt.strip().casefold())
            import re
            cites=re.findall(r'\[E(\d+)\]',txt)
            stat['citation_syntax']+=len(cites)
            stat['bad_citations']+=sum(not 1<=int(num)<=len(ids) for num in cites)
            stat['literal_unknown']+=int(txt.strip().casefold()=='unknown')
            stat['input_tokens']+=resp['input_tokens'];stat['output_tokens']+=resp['output_tokens']
        x=family[f][grp];x['cases']+=1
        x['changed_retrieved_to_witness']+=int(texts['retrieved']!=texts['witness'])
        x['changed_witness_to_lesion']+=int(texts['witness']!=texts['lesion'])
        x['witness_target_substring']+=int(has_answer and answer.strip().casefold() in texts['witness'].casefold())
    if audit!=reported.get('per_cohort_arm') or family!=reported.get('per_original_family'):
        raise ValueError('producer aggregated score disagrees with independent original source recount')
    if reported.get('independently_human_verified_sufficiency') is not False or reported.get('reference_reader_actual_calls')!=0 or reported.get('production_authorized') is not False or reported.get('decision')!='HOLD_NO_GO':
        raise ValueError('false scientific conclusion')
    return {'schema':SCHEMA+'.independent-original-source-recount',
            'model_output_sha256':digest(raw),'sanitized_report_sha256':digest(reported),
            'question_count':len(seen),'source_roots':len(HELD),
            'literal_substring_hit_per_arm':{g:{a:audit[g][a]['literal_target_substring'] for a in ARMS} for g in GROUPS},
            'answer_dependent_historical_cohort':True,
            'independently_verified_semantics':False,
            'stronger_reader_executed':False,
            'production_authorized':False,'status':'RECOUNT_PASS_NO_GO'}


def main():
    p=argparse.ArgumentParser()
    for k in ('plan','answers','source','original','report','output'):p.add_argument('--'+k,required=True)
    a=p.parse_args()
    doc=recount(read(a.plan),read(a.answers),read(a.source),read(a.original),read(a.report))
    from v16_literal_witness_reader import sealed
    sealed(a.output,doc);print(json.dumps(doc,sort_keys=True))

if __name__=='__main__':main()
