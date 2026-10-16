"""Independent read-only V17 private original output and publisher-label audit.

No inference, no learner, no human judge. Raw original model/source material stays
outside Git; only sanitized aggregates can be committed.
"""
from __future__ import annotations
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import secrets

from v17_source_focusing import SCHEMA, ARMS, READER_SHA, TOKEN_SHA, READER_CFG_SHA, ANSWER_CAP, verify_plan
from v16_literal_witness_reader import read, digest, htext, SCHEMA as V16_SCHEMA
from v15_original_candidate_four_arm import CORPUS_SHA

CITE=re.compile(r'\[E([0-9]+)\]')
COHORTS=('literal_in_annotated_source','not_literal_in_annotated_source')
FAMILIES=('conv-47','conv-48','conv-49','conv-50')


def audit(plan, src, parent, first, starts, tokenizer, original=None, parent_answers=None):
    """Audit pre/post-seal physical byte census; load labels only in postseal mode."""
    if (plan.get('schema')!=SCHEMA+'.source-only-plan' or plan.get('source_sha256')!=digest(src)
        or plan.get('parent_v16_plan_sha256')!=digest(parent)
        or plan.get('reader_weights_sha256')!=READER_SHA or plan.get('tokenizer_sha256')!=TOKEN_SHA
        or plan.get('reader_config_sha256')!=READER_CFG_SHA or plan.get('production_authorized') is not False
        or plan.get('new_focus_uses_publisher_answers') is not False):raise ValueError('plan provenance incorrect')
    wanted=plan['requests']
    if type(wanted) is not dict or len(wanted)!=64 or len(plan['cases'])!=32:raise ValueError('truncated source evidence')
    if (first.get('schema')!=SCHEMA+'.original-physical-answers' or first.get('plan_sha256')!=digest(plan)
        or first.get('model_sha256')!=READER_SHA or first.get('tokenizer_sha256')!=TOKEN_SHA
        or first.get('reference_reader_executed') is not False or first.get('production_authorized') is not False
        or first.get('official_HF_parity') is not False or first.get('independently_human_reviewed') is not False
        or first.get('requests')!=64):raise ValueError('bad output provenance')
    rows=first.get('raw_answers')
    if type(rows)is not dict or set(rows)!=set(wanted):raise ValueError('missing or substituted answer')
    if type(starts)is not list or len(starts)!=64:raise ValueError('fsync start journal missing')
    seen=set();forward=ni=no=0;entailment_syntax={a:0 for a in ARMS}
    raw_answer_digest=[];tokens_by_arm={a:dict(input=0,output=0) for a in ARMS}
    for start in starts:
        if type(start)is not dict or set(start)!={'request_id','plan_sha256','input_tokens','input_ids_sha256'}:raise ValueError('start metadata modified')
        rid=start['request_id']
        if rid not in wanted or rid in seen:raise ValueError('unexpected/duplicate attempt')
        seen.add(rid);req=wanted[rid];out=rows[rid]
        original_ids=tokenizer.encode(req['prompt'])
        if (not 1<=len(original_ids)<=1000 or start['input_tokens']!=len(original_ids)
            or start['input_ids_sha256']!=digest(original_ids) or start['plan_sha256']!=digest(plan)):
            raise ValueError('original prompt tokenizer or start substituted')
        if type(out)is not dict or set(out)!={'case_id','arm','source_ids','answer_text','answer_sha256','output_ids','input_tokens','output_tokens','cpu_seconds'}:
            raise ValueError('original answer structure wrong')
        ids=out['output_ids']
        if (out['case_id']!=req['case_id'] or out['arm']!=req['arm'] or out['source_ids']!=req['source_ids']
            or type(ids)is not list or not 1<=len(ids)<=ANSWER_CAP
            or any(type(k)is not int or k<0 or k>=49152 for k in ids)
            or out['answer_text']!=tokenizer.decode(ids) or out['answer_sha256']!=htext(out['answer_text'])
            or out['input_tokens']!=len(original_ids) or out['output_tokens']!=len(ids)):
            raise ValueError('token/source/answer mismatch')
        ni+=len(original_ids);no+=len(ids);forward+=len(ids)+(ids[-1]!=2)
        target=out['arm'];tokens_by_arm[target]['input']+=len(original_ids);tokens_by_arm[target]['output']+=len(ids)
        citations=[int(i) for i in CITE.findall(out['answer_text'])]
        if citations and all(1<=i<=len(out['source_ids']) for i in citations):entailment_syntax[target]+=1
        raw_answer_digest.append([rid,out['answer_sha256'],digest(ids)])
    if set(seen)!=set(wanted) or first.get('model_forwards')!=forward:raise ValueError('unaccounted model forward')
    output={'schema':SCHEMA+'.independent-original-audit','exact_original_requests':64,
        'actual_model_forwards':forward,'input_tokens':ni,'output_tokens':no,
        'reader_weights_sha256':READER_SHA,'tokenizer_sha256':TOKEN_SHA,
        'precommitted_plan_sha256':digest(plan),'token_and_answer_digest':digest(sorted(raw_answer_digest)),
        'per_arm_tokens':tokens_by_arm,'syntactic_inrange_citation_cases':entailment_syntax,
        'human_semantic_correctness':None,'human_source_sufficiency':False,
        'independent_future_calendar_windows':0,'reference_reader_executed':False,
        'production_authorized':False,'decision':'BYTE_RECOUNT_ONLY_NO_GO'}
    if original is None and parent_answers is None:return output
    if original is None or parent_answers is None:raise ValueError('postseal label owner and historic Reader jointly required')
    if (type(original)is not list or len(original)!=10 or parent_answers.get('plan_sha256')!=digest(parent)
        or parent_answers.get('model_sha256')!=READER_SHA or parent_answers.get('requests')!=128
        or parent_answers.get('stronger_reference_reader_executed') is not False):raise ValueError('original benchmark or parent model mismatch')
    source_map={s['sample_id']:s for s in original}
    if set(source_map)!=set(src['families']):raise ValueError('publisher source roots substituted')
    parent_cases={c['id']:c for c in parent['cases']}
    score={cohort:{arm:dict(n=0,answer_substring=0,answer_exact=0,changed_vs_original=0,publisher_answer_unknown=0) for arm in (*ARMS,'v16_witness')} for cohort in COHORTS}
    family_counts={fam:{arm:dict(n=0,answer_substring=0) for arm in (*ARMS,'v16_witness')} for fam in FAMILIES}
    pair={cohort:dict(known_answers=0,focus_only_gain=0,focus_only_loss=0,formatted_vs_v16_gain=0,formatted_vs_v16_loss=0) for cohort in COHORTS}
    for case in plan['cases']:
        ident=case['case_id'];fam=case['family'];cohort=case['cohort']
        if fam not in FAMILIES or cohort not in COHORTS or ident not in parent_cases:
            raise ValueError('source independence roster drift')
        qidx=int(ident.split('/q')[1]);ref=source_map[fam]['qa'][qidx]
        witness_ids=ref.get('evidence');p=parent_cases[ident]
        if witness_ids!=[p['witness_id']] or case['witness_id']!=p['witness_id']:
            raise ValueError('publisher witness changed after original seal')
        answer=ref.get('answer')
        valid=type(answer) is str and bool(answer.strip())
        a=answer.strip().casefold() if valid else None
        original_witness=parent_answers['raw_answers'][p['arms']['witness']['request_id']]['answer_text']
        if valid:
            pair[cohort]['known_answers']+=1
            bf=a in original_witness.casefold()
            full=a in rows[case['arms']['formatted_full']]['answer_text'].casefold()
            focused=a in rows[case['arms']['formatted_focused']]['answer_text'].casefold()
            pair[cohort]['focus_only_gain']+=int(focused and not full)
            pair[cohort]['focus_only_loss']+=int(full and not focused)
            pair[cohort]['formatted_vs_v16_gain']+=int(full and not bf)
            pair[cohort]['formatted_vs_v16_loss']+=int(bf and not full)
        for arm in (*ARMS,'v16_witness'):
            response=original_witness if arm=='v16_witness' else rows[case['arms'][arm]]['answer_text']
            z=score[cohort][arm];q=family_counts[fam][arm]
            z['n']+=1;q['n']+=1
            lit=int(valid and a in response.casefold()); z['answer_substring']+=lit;q['answer_substring']+=lit
            z['publisher_answer_unknown']+=int(not valid)
            z['answer_exact']+=int(valid and a==response.strip().casefold())
            z['changed_vs_original']+=int(response!=original_witness)
    if any(t['n']!=16 for cohort in score.values() for t in cohort.values()):raise ValueError('publisher cohort denominators')
    for fam in FAMILIES:
        if any(v['n']!=8 for v in family_counts[fam].values()):raise ValueError('source cluster incorrect')
    output.update({'schema':SCHEMA+'.original-postseal-publisher-weak-report','per_cohort_arm':score,
                   'paired_literal_diagnostics':pair,
                   'per_source_root':family_counts,'publisher_answer_used_during_model_run':False,
                   'cohort_preselected_with_publisher_answer':True,
                   'answer_substring_not_semantic_correctness':True,'full_answer_task_success':None,
                   'decision':'HOLD_NO_GO'})
    return output


def blinded_review_packet(plan,src,parent,first,parent_answers,private_seed:bytes):
    """Prepare independent review tickets; does NOT sign or answer them."""
    if type(private_seed)is not bytes or len(private_seed)<32:raise ValueError('private reviewer blinding seed required')
    if first.get('plan_sha256')!=digest(plan) or parent_answers.get('plan_sha256')!=digest(parent):raise ValueError('answers not source pinned')
    questions={q['id']:q['text'] for fam in src['families'].values() for q in fam['questions']}
    pc={c['id']:c for c in parent['cases']}
    tickets=[];private_map=[]
    for c in plan['cases']:
        cid=c['case_id'];fam=c['family'];docs={v['id']:v['text'] for v in src['families'][fam]['passages']}
        p=pc[cid];base=parent_answers['raw_answers'][p['arms']['witness']['request_id']]
        for name in (*ARMS,'v16_witness'):
            if name=='v16_witness':item=base;source_ids=p['arms']['witness']['evidence_ids']
            else:
                item=first['raw_answers'][c['arms'][name]]
                source_ids=plan['requests'][c['arms'][name]]['source_ids']
            identifier=htext(private_seed.hex()+cid+'::'+name)[:32]
            evidence_texts=[docs[s] for s in source_ids]
            if name=='formatted_focused':
                a,b=c['focus_offsets'];w=c['witness_id']
                if docs[w][a:b].strip()!=docs[w][a:b] or not docs[w][a:b]:raise ValueError('source span cannot be reconstructed')
                evidence_texts[0]=docs[w][a:b]
            tickets.append(dict(ticket=identifier,question=questions[cid],source_texts=evidence_texts,
                                delivered_source_ids=source_ids,model_answer=item['answer_text'],
                                answer_sha256=htext(item['answer_text']),
                                questions=['Is the supplied evidence sufficient to answer?',
                                           'Is the model answer semantically correct?',
                                           'Does each cited source entail the claimed statement?']))
            private_map.append(dict(ticket=identifier,case_id=cid,family=fam,cohort=c['cohort'],arm=name))
    tickets.sort(key=lambda x:x['ticket'])
    if len(tickets)!=96 or len({t['ticket'] for t in tickets})!=96:raise ValueError('incomplete blinded review')
    return dict(schema=SCHEMA+'.private-blind-review-tickets',tickets=tickets,
                publisher_answer_label_field_included=False,human_verdicts_collected=False), private_map


def cli():
    import argparse
    from v12_reader_runtime import OriginalCandidateBPE,check_original
    parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);parser.add_argument('--source',required=True);parser.add_argument('--ranks',required=True)
    parser.add_argument('--v16-plan',required=True);parser.add_argument('--answers',required=True)
    parser.add_argument('--starts',required=True);parser.add_argument('--reader',required=True)
    parser.add_argument('--original');parser.add_argument('--v16-answers');parser.add_argument('--out',required=True)
    a=parser.parse_args()
    check_original(a.reader)
    def strict(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate original journal property')
            d[k]=v
        return d
    starts=[json.loads(line,object_pairs_hook=strict) for line in Path(a.starts).read_text().splitlines()]
    raw_original=json.loads(Path(a.original).read_bytes()) if a.original else None
    parent=read(a.v16_answers) if a.v16_answers else None
    if raw_original is not None and sha256(Path(a.original).read_bytes()).hexdigest()!=CORPUS_SHA:
        raise ValueError('original corpus byte digest mismatch')
    p=read(a.plan);s=read(a.source);v=read(a.v16_plan)
    verify_plan(p,s,read(a.ranks),v)
    out=audit(p,s,v,read(a.answers),starts,
              OriginalCandidateBPE(a.reader),raw_original,parent)
    from v16_literal_witness_reader import sealed
    sealed(a.out,out)
    print(json.dumps({'requests':out['exact_original_requests'],'decision':out['decision']}))

if __name__=='__main__':cli()
