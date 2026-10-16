"""Postseal-only original publisher literal diagnostic; NOT semantic correctness.

Original gold is first read here, never in V19 source-first/model scripts.
"""
from __future__ import annotations
from collections import defaultdict
import argparse
import json
from pathlib import Path
from v17_source_focusing import digest, htext, sealed, read
from v19_windowed_witness import SCHEMA

ARMS=('full_original','single_sentence','window_plus_1','window_plus_2')
COHORTS=('literal_in_annotated_source','not_literal_in_annotated_source')

def paired(plan, v17, v17raw, v18, v18raw, v19raw, source, original):
    if plan.get('schema')!=SCHEMA+'.source-only' or len(plan['cases'])!=32 or len(plan['new_requests'])!=23:
        raise ValueError('missing V19 complete original plan')
    if (v17raw.get('plan_sha256')!=digest(v17) or v18raw.get('plan_sha256')!=digest(v18) or v19raw.get('plan_sha256')!=digest(plan)):
        raise ValueError('unrelated Reader output')
    if not (v17raw.get('requests')==64 and v18raw.get('requests')==58 and v19raw.get('requests')==23):raise ValueError('incomplete original Reader')
    owners={z['sample_id']:z for z in original}
    if len(owners)!=10 or set(owners)!=set(source['families']):raise ValueError('original publisher corpus drift')
    old_cases={z['case_id']:z for z in v17['cases']};v18_cases={z['case_id']:z for z in v18['cases']}
    cohort_stats={k:{arm:dict(n=0,known=0,source_has_answer=0,output_has_answer=0,exact=0,input_tokens=0,output_tokens=0) for arm in ARMS} for k in COHORTS}
    family_stats={fam:{arm:dict(n=0,output_has_answer=0) for arm in ARMS} for fam in ('conv-47','conv-48','conv-49','conv-50')}
    changes={c:{f'{b}_vs_{a}':dict(gain=0,loss=0,identical=0,unjudged=0) for a,b in [('single_sentence','window_plus_1'),('single_sentence','window_plus_2'),('window_plus_1','window_plus_2'),('full_original','window_plus_1'),('full_original','window_plus_2')]} for c in COHORTS}
    total_truly_new=0;exact_reuse=0
    for case in plan['cases']:
        cid=case['case_id'];fam=case['family'];cohort=case['cohort']
        if cid not in old_cases or cohort not in COHORTS or fam not in family_stats:raise ValueError('foreign historical case')
        owner=owners[fam]['qa'][int(cid.split('/q',1)[1])]
        ans=owner.get('answer'); known=type(ans)is str and bool(ans.strip());target=ans.strip().casefold() if known else None
        old=old_cases[cid];witness=case['witness_id'];passages={d['id']:d['text'] for d in source['families'][fam]['passages']};whole=passages[witness]
        responses={}
        for arm in ARMS:
            if arm=='full_original':
                rid=old['arms']['formatted_full']
                row=v17raw['raw_answers'][rid];text_source=whole
            elif arm=='single_sentence':
                v18case=v18_cases[cid];spec=v18case['cross_arms']['focused_full_heading']
                rid=spec['request_id']
                row=(v17raw if spec['reused_v17'] else v18raw)['raw_answers'][rid]
                text_source=whole[old['focus_offsets'][0]:old['focus_offsets'][1]]
            else:
                spec=case['arms'][arm];rid=spec['request_id'];text_source=whole[spec['span'][0]:spec['span'][1]]
                if spec['reuse']=='v17':row=v17raw['raw_answers'][rid];exact_reuse+=1
                else:row=v19raw['raw_answers'][rid];total_truly_new+=1
            if row['case_id']!=cid or row['source_ids']!=case['source_ids'] or row['answer_sha256']!=htext(row['answer_text']):
                raise ValueError('source/model response ID swapped')
            response=row['answer_text'];responses[arm]=int(known and target in response.casefold())
            stat=cohort_stats[cohort][arm];stat['n']+=1;stat['known']+=int(known)
            stat['source_has_answer']+=int(known and target in text_source.casefold())
            stat['output_has_answer']+=responses[arm]
            stat['exact']+=int(known and response.strip().casefold()==target)
            stat['input_tokens']+=row['input_tokens'];stat['output_tokens']+=row['output_tokens']
            famstat=family_stats[fam][arm];famstat['n']+=1;famstat['output_has_answer']+=responses[arm]
        for key,change in changes[cohort].items():
            newer,older=key.split('_vs_');a=responses[older];b=responses[newer]
            if not known:change['unjudged']+=1
            else:
                change['gain']+=int(b and not a);change['loss']+=int(a and not b);change['identical']+=int(a==b)
    if total_truly_new!=24 or exact_reuse!=40 or any(z['n']!=16 for x in cohort_stats.values() for z in x.values()) or any(z['n']!=8 for x in family_stats.values() for z in x.values()):
        # 24 new slots but only 23 unique physical requests.
        raise ValueError('incomplete original V19 source/arm coverage')
    return dict(schema=SCHEMA+'.paired-publisher-literal-postseal.v1',case_count=32,
                source_root_count=4,physical_original_new_requests=23,
                novel_logical_slots=24,reused_verbatim_old_slots=40,
                arms=list(ARMS),cohorts=cohort_stats,per_family=family_stats,paired_contrasts=changes,
                labels_accessed_only_after_original_Reader_seal=True,
                cohort_selected_using_historical_publisher_labels=True,
                original_weak_literal_not_semantic_correctness=True,
                human_source_sufficiency_verified=False,independent_semantic_judge=None,
                stronger_reference_reader_executed=False,official_HF_parity_verified=False,
                future_calendar_windows=0,cell_learning_gain_proven=False,production_authorized=False,decision='HOLD_NO_GO')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('plan','v17-plan','v17-answers','v18-plan','v18-answers','v19-answers','source','original','out'):p.add_argument('--'+name,required=True)
    a=p.parse_args()
    r=paired(read(a.plan),read(a.v17_plan),read(a.v17_answers),read(a.v18_plan),read(a.v18_answers),read(a.v19_answers),read(a.source),read(a.original))
    sealed(a.out,r)
    print(json.dumps({'schema':r['schema'],'decision':r['decision'],'cohorts':r['cohorts'],'paired_contrasts':r['paired_contrasts']},sort_keys=True))
