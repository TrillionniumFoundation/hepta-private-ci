"""Independent V24 source-ID citation contract and postseal historical weak-label review.

No generation, train, model selection or authority. Reconstructs the frozen 32
lesion input strings independent of the V24 producer. Structural citation IDs
are NOT source entailment; historical literal answer matches are NOT semantic QA.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re

from v21_original_plan_rebuilder import (
    READER_SHA, TOKEN_SHA, READER_CFG_SHA, V16_PLAN_SHA, GROUPS, HELD,
    digest, htext, read_original, canonical,
)
from v22_original_crosshost_execute import (
    read_private, seal, validate_inputs,
)
from v22_original_crosshost_review import verify_raw, strict_start_lines

SCHEMA = 'hepta.stem.v24.original-lesion-citation-scope.shadow.v1'
OLD_CLAUSE = 'Cite supporting evidence using [E1], [E2] or [E3].'
NEW_CLAUSE = 'Cite supporting evidence using [E1] or [E2].'
REFERENCES = re.compile(r'\[E([0-9]+)\]')


def structural_cites(answer, evidence_ids):
    if type(answer) is not str or type(evidence_ids) is not list or len(evidence_ids)!=2:
        raise ValueError('unbound answer/source')
    parsed=[int(x) for x in REFERENCES.findall(answer)]
    if any(not 1<=x<=len(evidence_ids) for x in parsed):return 'out_of_range'
    return 'in_range' if parsed else 'absent'


def check_public(r):
    """Only type/consistency guard for sanitized result; cannot attest model bytes."""
    fixed={
        'schema':SCHEMA+'.sanitized-original-physical-comparison',
        'original_plan_sha256':V16_PLAN_SHA,
        'original_model_sha256':READER_SHA,
        'tokenizer_sha256':TOKEN_SHA,
        'reader_config_sha256':READER_CFG_SHA,
        'total_historical_lesion_cases':32,
        'retrospective_answer_dependent_cohort':True,
        'correlated_source_roots':4,
        'baseline_structural_citations':{'in_range':22,'absent':7,'out_of_range':3},
        'historical_original_gold_unknown':5,
        'source_ids_and_evidence_text_same':True,
        'changes_only_reference_range_instruction':True,
        'reference_qwen_executed':False,
        'semantic_accuracy':None,
        'independent_human_review':False,
        'original_model_hf_parity':False,
        'cell_split_or_ndu_gain_claimed':False,
        'production_authorized':False,
        'decision':'SOURCE_SCOPED_CITATION_MECHANISM_ONLY_HOLD_NO_GO',
    }
    variables={'source_scope_private_plan_sha256','private_source_scoped_answer_sha256',
               'baseline_original_answer_sha256','output_lineage_sha256',
               'source_scope_input_identity_sha256','source_scoped_model_forwards','source_scoped_input_tokens',
               'source_scoped_output_tokens','source_scoped_cpu_seconds','source_scoped_wall_seconds',
               'source_scoped_structural_citations','paired_structural_transitions',
               'original_publisher_answer_weak_proxy','per_correlated_root',
               'physical_execution_reported','publisher_labels_opened_postseal'}
    if type(r)is not dict or set(r)!=set(fixed)|variables:
        raise ValueError('missing/extra public report fields')
    for k,v in fixed.items():
        if type(r[k])is not type(v) or r[k]!=v:
            raise ValueError('published outcome/authority distortion: '+k)
    def is_sha(s):return type(s)is str and len(s)==64 and all(c in '0123456789abcdef' for c in s)
    for k in ('source_scope_private_plan_sha256','private_source_scoped_answer_sha256',
              'baseline_original_answer_sha256','output_lineage_sha256',
              'source_scope_input_identity_sha256'):
        if not is_sha(r[k]):raise ValueError('missing exact digest: '+k)
    for k in ('source_scoped_model_forwards','source_scoped_input_tokens','source_scoped_output_tokens'):
        if type(r[k]) is not int or not 1<=r[k]<=25000:raise ValueError('nonphysical token count')
    for k in ('source_scoped_cpu_seconds','source_scoped_wall_seconds'):
        if type(r[k])not in (int,float) or not math.isfinite(r[k]) or not 0<r[k]<3000:
            raise ValueError('invalid total measured time')
    c=r['source_scoped_structural_citations']
    if (type(c) is not dict or set(c)!={'in_range','absent','out_of_range'}
        or any(type(v) is not int or not 0<=v<=32 for v in c.values())
        or sum(c.values())!=32):raise ValueError('incomplete citation outcome denominator')
    trans=r['paired_structural_transitions']
    if (type(trans) is not dict or any(type(k) is not str or '->' not in k for k in trans)
        or any(type(v) is not int or v<0 for v in trans.values()) or sum(trans.values())!=32):
        raise ValueError('paired baseline/intervention transition count invalid')
    allowed={'in_range','absent','out_of_range'}
    for k in trans:
        a,b=k.split('->',1)
        if a not in allowed or b not in allowed:raise ValueError('foreign citation category')
    for state in allowed:
        if sum(v for k,v in trans.items() if k.startswith(state+'->'))!=fixed['baseline_structural_citations'][state]:
            raise ValueError('baseline transition row census changed')
        if sum(v for k,v in trans.items() if k.endswith('->'+state))!=c[state]:
            raise ValueError('new transition column census changed')
    weak=r['original_publisher_answer_weak_proxy']
    if (type(weak) is not dict or set(weak)!=set(GROUPS)):
        raise ValueError('missing cohort')
    for group in GROUPS:
        z=weak[group]
        if (type(z) is not dict or set(z) != {'n','known','unknown','baseline_literal','source_scoped_literal',
                                         'gained_literal','lost_literal'}
            or z['n']!=16 or z['known']!=(16 if group==GROUPS[0] else 11)
            or z['unknown']!=(0 if group==GROUPS[0] else 5)
            or any(type(t) is not int or not 0<=t<=16 for t in z.values())):
            raise ValueError('false weak-label cohort denominator')
        if z['baseline_literal']!=(0 if group==GROUPS[0] else 1):
            raise ValueError('original prior lesion weak literal baseline drift')
        if z['source_scoped_literal']!=z['baseline_literal']+z['gained_literal']-z['lost_literal']:
            raise ValueError('weak-label paired gain/loss mismatch')
    roots=r['per_correlated_root']
    if type(roots) is not dict or set(roots)!=set(HELD) or any(roots[f]!=8 for f in HELD):
        raise ValueError('historical source roots overstated')
    if r['physical_execution_reported'] is not True or r['publisher_labels_opened_postseal'] is not True:
        raise ValueError('missing physical/postseal provenance claim')
    return {'status':'SOURCE_ONLY_SANITIZED_COUNTS_CONSISTENT_NO_GO',
            'original_real_model_execution_independently_attested_by_this_check':False,
            'semantic_correctness':None,'production_authorized':False}


def review(source,routes,original,intervention_plan,baseline,baseline_starts,
           new,starts,tokenizer,gold):
    validate_inputs(source,routes,original)
    baseline_check=verify_raw(original,baseline,baseline_starts,tokenizer)
    if baseline_check['verified_original_requests']!=128 or baseline_check['physical_forward_calls']!=2951:
        raise ValueError('original physical baseline absent')
    if (type(intervention_plan)is not dict or intervention_plan.get('schema')!=SCHEMA+'.private-frozen-plan'
        or intervention_plan.get('original_plan_sha256')!=V16_PLAN_SHA
        or intervention_plan.get('original_source_ids_and_text_unchanged') is not True
        or intervention_plan.get('changed_clause_only') is not True
        or intervention_plan.get('original_gold_available_to_producer') is not False
        or intervention_plan.get('human_semantic_accuracy') is not None
        or intervention_plan.get('production_authorized') is not False):
        raise ValueError('invalid source-first intervention')
    old={row['case_id']:(rid,row) for rid,row in original['requests'].items() if row['arm']=='lesion'}
    reqs=intervention_plan.get('requests')
    if type(reqs)is not dict or len(reqs)!=32 or len(old)!=32:
        raise ValueError('32 exact lesion requests required')
    rebuilt={};lineage=[]
    for case,(old_id,row) in sorted(old.items()):
        if row['prompt'].count(OLD_CLAUSE)!=1 or len(row['source_ids'])!=2:
            raise ValueError('wrong original lesion source clause')
        p=row['prompt'].replace(OLD_CLAUSE,NEW_CLAUSE)
        rid=htext(p)
        if rid in rebuilt or rid in original['requests']:raise ValueError('intervention collision')
        rebuilt[rid]={'old_request_id':old_id,'case_id':case,'family':row['family'],
                      'source_ids':row['source_ids'],'question_sha256':row['question_sha256'],
                      'prompt':p}
        lineage.append([old_id,rid,row['source_ids']])
    required={'schema','original_plan_sha256','source_sha256','routes_sha256','original_model_sha256',
      'tokenizer_sha256','reader_config_sha256','changed_clause_only','original_source_ids_and_text_unchanged',
      'original_gold_available_to_producer','answer_dependent_retrospective_cohort',
      'original_correlated_roots','original_lesion_cases','max_new_tokens','lineage_sha256','requests',
      'human_semantic_accuracy','reference_qwen_executed','production_authorized'}
    if (set(intervention_plan)!=required or reqs!=rebuilt
        or intervention_plan['lineage_sha256']!=digest(sorted(lineage,key=lambda x:x[0]))
        or intervention_plan['source_sha256']!=original['source_sha256']
        or intervention_plan['routes_sha256']!=original['bm25_routes_sha256']
        or intervention_plan['original_model_sha256']!=READER_SHA
        or intervention_plan['tokenizer_sha256']!=TOKEN_SHA
        or intervention_plan['reader_config_sha256']!=READER_CFG_SHA
        or intervention_plan['max_new_tokens']!=24
        or intervention_plan['original_lesion_cases']!=32
        or intervention_plan['answer_dependent_retrospective_cohort'] is not True
        or intervention_plan['original_correlated_roots']!=4
        or intervention_plan['reference_qwen_executed'] is not False):
        raise ValueError('source-first independent prompt reconstruction differs')
    if (type(new) is not dict or set(new)!={'schema','plan_sha256','original_plan_sha256',
         'original_model_sha256','tokenizer_sha256','reader_config_sha256','physical_requests',
         'model_forwards','original_model_input_tokens','original_model_output_tokens',
         'cpu_seconds','wall_seconds','raw_answers','true_pretrained_backend','original_labels_loaded',
         'human_semantic_accuracy','qwen_reference_executed','production_authorized'}
        or new['schema']!=SCHEMA+'.physical-answers'
        or new['plan_sha256']!=digest(intervention_plan)
        or new['original_plan_sha256']!=V16_PLAN_SHA
        or new['original_model_sha256']!=READER_SHA or new['tokenizer_sha256']!=TOKEN_SHA
        or new['reader_config_sha256']!=READER_CFG_SHA
        or new['physical_requests']!=32 or new['true_pretrained_backend'] is not True
        or new['original_labels_loaded'] is not False or new['qwen_reference_executed'] is not False
        or new['human_semantic_accuracy'] is not None or new['production_authorized'] is not False):
        raise ValueError('not original selected pretrained model or forged production result')
    answers=new['raw_answers']
    if type(answers)is not dict or set(answers)!=set(rebuilt):raise ValueError('new physical answers missing')
    if type(starts)is not list or len(starts)!=32:raise ValueError('fsynced start ledger incomplete')
    observed=set();forward=ni=no=0;compared={};token_lineage=[]
    for start in starts:
        if type(start)is not dict or set(start)!={'request_id','plan_sha256','input_ids_sha256','input_tokens'}:
            raise ValueError('unexpected journal line')
        rid=start['request_id']
        if type(rid)is not str or rid in observed or rid not in rebuilt:
            raise ValueError('duplicate/out-of-scope journal')
        observed.add(rid);row=rebuilt[rid];result=answers[rid]
        input_ids=tokenizer.encode(row['prompt'])
        if (not 1<=len(input_ids)<=1000 or start['input_ids_sha256']!=digest(input_ids)
            or start['plan_sha256']!=digest(intervention_plan)
            or start['input_tokens']!=len(input_ids)):
            raise ValueError('physical tokenizer/input bytes incorrect')
        ids=result.get('token_ids')
        if (set(result)!={'case_id','family','source_ids','answer_text','answer_sha256',
                          'token_ids','input_tokens','output_tokens','cpu_seconds'}
            or result['case_id']!=row['case_id'] or result['family']!=row['family']
            or result['source_ids']!=row['source_ids']
            or type(ids)is not list or not 1<=len(ids)<=24
            or any(type(x)is not int or not 0<=x<49152 for x in ids)
            or result['answer_text']!=tokenizer.decode(ids)
            or result['answer_sha256']!=htext(result['answer_text'])
            or result['input_tokens']!=len(input_ids)
            or result['output_tokens']!=len(ids)
            or type(result['cpu_seconds'])not in(int,float)
            or not math.isfinite(result['cpu_seconds']) or result['cpu_seconds']<0):
            raise ValueError('physical original answer/token mismatch')
        forward+=len(ids)+(ids[-1]!=2);ni+=len(input_ids);no+=len(ids)
        token_lineage.append((rid,digest(ids),result['answer_sha256']))
        compared[row['case_id']]=(baseline['raw_answers'][row['old_request_id']],result)
    if (observed!=set(rebuilt) or forward!=new['model_forwards']
        or ni!=new['original_model_input_tokens'] or no!=new['original_model_output_tokens']):
        raise ValueError('physical actual work not conserved')
    if not all(type(new[k]) in (int,float) and math.isfinite(new[k]) and 0<new[k]<3000
               for k in ('cpu_seconds','wall_seconds')):
        raise ValueError('model CPU/wall invalid')
    bins_old=Counter();bins_new=Counter();paired=Counter()
    for case,(old_answer,new_answer) in compared.items():
        old_category=structural_cites(old_answer['answer_text'],old_answer['source_ids'])
        new_category=structural_cites(new_answer['answer_text'],new_answer['source_ids'])
        bins_old[old_category]+=1;bins_new[new_category]+=1
        paired[old_category+'->'+new_category]+=1
    for label,count in {'in_range':22,'absent':7,'out_of_range':3}.items():
        if bins_old[label]!=count:raise ValueError('V22 prior actual lesion citation baseline changed')
    if type(gold) is not list or len(gold)!=10:
        raise ValueError('original labels available only in postseal reviewer')
    # Weak original publisher answer string is opened only in this review process.
    original_by_fam={x['sample_id']:x for x in gold}
    if len(original_by_fam)!=10:raise ValueError('duplicate original publisher roots')
    count_per_root=Counter(); per_cohort={g:dict(n=0,known=0,unknown=0,baseline_literal=0,
                                             source_scoped_literal=0,gained_literal=0,lost_literal=0)
                                    for g in GROUPS}
    for case in original['cases']:
        fam=case['family'];grp=case['cohort'];caseid=case['id']
        if grp not in per_cohort or fam not in HELD:raise ValueError('foreign historical cohort')
        count_per_root[fam]+=1
        target=original_by_fam[fam]['qa'][int(caseid.split('/q')[1])].get('answer')
        if target is not None and type(target)is not str:
            raise ValueError('non-string publisher answer')
        r=per_cohort[grp];r['n']+=1
        if type(target)is not str or not target.strip():
            r['unknown']+=1;continue
        r['known']+=1
        old_answer,new_answer=compared[caseid]
        old_target=target.strip().casefold() in old_answer['answer_text'].casefold()
        new_target=target.strip().casefold() in new_answer['answer_text'].casefold()
        r['baseline_literal']+=int(old_target);r['source_scoped_literal']+=int(new_target)
        r['gained_literal']+=int(new_target and not old_target)
        r['lost_literal']+=int(old_target and not new_target)
    if (dict(count_per_root)!={f:8 for f in HELD} or
        per_cohort[GROUPS[0]]['known']!=16 or per_cohort[GROUPS[1]]['known']!=11 or
        per_cohort[GROUPS[1]]['unknown']!=5 or
        per_cohort[GROUPS[0]]['baseline_literal']!=0 or per_cohort[GROUPS[1]]['baseline_literal']!=1):
        raise ValueError('historical source/censored gold weak counts changed')
    sanitized={
        'schema':SCHEMA+'.sanitized-original-physical-comparison',
        'original_plan_sha256':V16_PLAN_SHA,
        'original_model_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
        'reader_config_sha256':READER_CFG_SHA,
        'total_historical_lesion_cases':32,'retrospective_answer_dependent_cohort':True,
        'correlated_source_roots':4,
        'source_scope_private_plan_sha256':digest(intervention_plan),
        'private_source_scoped_answer_sha256':digest(new),
        'baseline_original_answer_sha256':digest(baseline),
        'output_lineage_sha256':digest(sorted(token_lineage)),
        'source_scope_input_identity_sha256':digest(sorted(rebuilt)),
        'source_scoped_model_forwards':forward,
        'source_scoped_input_tokens':ni,'source_scoped_output_tokens':no,
        'source_scoped_cpu_seconds':new['cpu_seconds'],'source_scoped_wall_seconds':new['wall_seconds'],
        'baseline_structural_citations':dict(sorted(bins_old.items())),
        'source_scoped_structural_citations':{t:bins_new[t] for t in ('in_range','absent','out_of_range')},
        'paired_structural_transitions':dict(sorted(paired.items())),
        'original_publisher_answer_weak_proxy':per_cohort,
        'per_correlated_root':dict(count_per_root),
        'source_ids_and_evidence_text_same':True,
        'changes_only_reference_range_instruction':True,
        'historical_original_gold_unknown':5,
        'physical_execution_reported':True,
        'publisher_labels_opened_postseal':True,
        'reference_qwen_executed':False,'semantic_accuracy':None,
        'independent_human_review':False,'original_model_hf_parity':False,
        'cell_split_or_ndu_gain_claimed':False,'production_authorized':False,
        'decision':'SOURCE_SCOPED_CITATION_MECHANISM_ONLY_HOLD_NO_GO',
    }
    check_public(sanitized)
    return sanitized


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--public-receipt')
    for k in ('source','routes','original-plan','new-plan','old-answers','old-starts',
              'new-answers','new-starts','reader','original-gold','output'):
        p.add_argument('--'+k)
    a=p.parse_args()
    if a.public_receipt:
        if any(getattr(a,k.replace('-','_')) is not None for k in ('source','routes','original-plan','new-plan',
                 'old-answers','old-starts','new-answers','new-starts','reader','original-gold','output')):
            raise ValueError('public receipt checking cannot read private experimental evidence')
        print(json.dumps(check_public(read_private(a.public_receipt,40_000)),sort_keys=True))
        return
    names=('source','routes','original_plan','new_plan','old_answers','old_starts','new_answers',
           'new_starts','reader','original_gold','output')
    if any(getattr(a,k) is None for k in names):
        raise ValueError('complete original on-host evidence required')
    from v12_reader_runtime import check_original, OriginalCandidateBPE
    check_original(a.reader)
    receipt=review(read_private(a.source),read_private(a.routes),read_private(a.original_plan),
                  read_private(a.new_plan), read_private(a.old_answers,2_000_000),
                  strict_start_lines(a.old_starts),read_private(a.new_answers,2_000_000),
                  strict_start_lines(a.new_starts),OriginalCandidateBPE(a.reader),
                  read_original(a.original_gold))
    seal(a.output,receipt)
    print(json.dumps({k:v for k,v in receipt.items() if 'sha256' not in k},sort_keys=True))

if __name__=='__main__':main()
