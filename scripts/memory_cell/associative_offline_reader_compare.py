"""Post-seal independent ledger of 140 original-weight, FP32 research Reader attempts.

This is not a Hugging Face parity or semantic sufficiency certificate. Truth
annotations are opened only here, after both immutable prediction journals.
"""
from collections import Counter, defaultdict
from pathlib import Path
import json
import platform
import re
import sys

from associative_cell import sha256
from associative_locomo_shadow import exclusive, read_regular, strict_json
from associative_question_conditioned import _token_f1, READER_ARMS
from associative_reader_unicode_recovery import _read_source, read_plan, ARMS
from associative_offline_reader_diagnostic import READER_SCHEMA as PREMISE_SCHEMA
from associative_offline_ranked_reader import READ_SCHEMA as RANKED_SCHEMA

SCHEMA = 'hepta.offline-reader-140-diagnostic.research.v1'


def _rows(directory, meta_schema, binding_key, binding_sha, expected_count):
    directory=Path(directory)
    raw=read_regular(directory/'reader-journal.json',maximum=8*1024*1024)
    meta=strict_json(read_regular(directory/'reader-seal.json'))
    if (meta.get('schema') != meta_schema or meta.get('reader_journal_sha256') != sha256(raw)
        or meta.get(binding_key)!=binding_sha
        or meta.get('planned') != expected_count
        or meta.get('production_accepted') is not False):
        raise ValueError('missing or changed registered sealed Reader journal')
    rows=strict_json(raw)
    if not isinstance(rows,list) or len(rows)!=expected_count:
        raise ValueError('incomplete original Reader attempt census')
    return rows, meta


def _score(rows, controls, original):
    annotated={(e['question_id'],e['arm']):e for e in controls}
    counts=defaultdict(Counter)
    f1=defaultdict(list)
    by_question=defaultdict(dict)
    markers=defaultdict(Counter)
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'question_id','family','arm','evidence_ids','result'}:
            raise ValueError('foreign Reader record shape')
        k=row['question_id'],row['arm']
        if k not in annotated or k in seen:raise ValueError('Reader output has missing or duplicate condition')
        seen.add(k)
        e=annotated[k]
        if row['family']!=e['family'] or row['evidence_ids']!=[x['source_id'] for x in e['evidence']]:
            raise ValueError('Reader evidence source identity changed')
        res=row['result']
        if not isinstance(res,dict) or res.get('status') not in ('succeeded','failed','unavailable'):
            raise ValueError('unscored or unknown Reader status')
        arm=e['arm'];counts[arm][res['status']]+=1
        if res['status']!='succeeded':continue
        answer=res.get('answer')
        if not isinstance(answer,str) or not answer.strip():raise ValueError('successful Reader has no original text')
        labels=re.findall(r'\[E([0-9]+)\]',answer)
        present={s['label'] for s in e['evidence']}
        markers[arm]['markers']+=len(labels)
        markers[arm]['valid_source_labels']+=sum('E'+m in present for m in labels)
        markers[arm]['answered_without_markers']+=not labels
        markers[arm]['abstention_phrases']+='do not have enough evidence' in answer.lower()
        qi=int(e['question_id'].rsplit('/q',1)[1])
        gold=original[e['family']]['qa'][qi].get('answer')
        if isinstance(gold,str) and gold.strip():
            score=_token_f1(answer,gold)
            f1[arm].append(score)
            by_question[e['question_id']][arm]=score
        else:counts[arm]['unscorable_reference']+=1
    if set(annotated)!=seen:raise ValueError('missing expected Reader output')
    return dict(by_arm={arm:dict(planned=len([x for x in controls if x['arm']==arm]),
                                statuses=dict(counts[arm]),scored=len(f1[arm]),
                                mean_token_f1=sum(f1[arm])/len(f1[arm]) if f1[arm] else None,
                                citation=dict(markers[arm]))
                         for arm in sorted({e['arm'] for e in controls})},
                scored=by_question)


def audit(premise_dir, ranked_public_dir, ranked_dir, premise_results_dir, ranked_results_dir, dataset_file, output_file):
    plan,seal=read_plan(premise_dir)
    premise=plan['entries']
    from associative_question_conditioned import reader_inputs, _read_public
    rank=list(reader_inputs(ranked_public_dir,ranked_dir,per_family=2))
    prem_questions={x['question_id'] for x in premise}
    rank_questions={x['question_id'] for x in rank}
    if prem_questions!=rank_questions or len(prem_questions)!=20 or len(rank)!=100:
        raise ValueError('reader question populations differ')
    public,manifest=_read_public(ranked_public_dir)
    rank_meta=strict_json(read_regular(Path(ranked_dir)/'seal.json'))
    prem_rows,prem_meta=_rows(premise_results_dir,PREMISE_SCHEMA,'plan_sha256',seal['plan_sha256'],40)
    rank_rows,rank_receipt=_rows(ranked_results_dir,RANKED_SCHEMA,'ranked_journal_sha256',rank_meta['journal_sha256'],100)
    if (prem_meta.get('same_as_hf_reference_reader_verified') is not False
        or rank_receipt.get('official_reader_parity_certified') is not False
        or rank_receipt.get('public_sha256')!=manifest['public_sha256']):
        raise ValueError('research Reader profile authenticity changed')
    original=_read_source(dataset_file)
    p=_score(prem_rows,premise,original)
    v=_score(rank_rows,rank,original)
    pairs={qid:(scores.get('annotated_all'),scores.get('annotated_minus_one'))
           for qid,scores in p['scored'].items()}
    diffs=[a-b for a,b in pairs.values() if a is not None and b is not None]
    if len(pairs)!=15 or len(diffs)!=15:raise ValueError('original answer score/census changed')
    wins=sum(d>1e-12 for d in diffs)
    losses=sum(d< -1e-12 for d in diffs)
    ties=len(diffs)-wins-losses
    source_arms={'annotated_all','annotated_minus_one'}
    all_caps={arm: len([e for e in premise if e['arm']==arm]) for arm in source_arms}
    by_evidence_size=Counter('single' if len(e['evidence'])==1 else 'multi'
                             for e in premise if e['arm']=='annotated_all')
    return_data=dict(schema=SCHEMA,source_sha256=sha256(read_regular(dataset_file,maximum=8*1024*1024)),
        premise_journal_sha256=prem_meta['reader_journal_sha256'],
        ranked_journal_sha256=rank_receipt['reader_journal_sha256'],
        fixed_questions=20,source_groups=10,
        actual_offline_frozen_weight_reader_attempts=140,
        premise_diagnostic={k:v for k,v in p.items() if k!='scored'},
        ranked_reader={k:v for k,v in v.items() if k!='scored'},
        lesion_paired=dict(scored=len(diffs),wins=wins,losses=losses,ties=ties,
            mean_full_minus_removed=sum(diffs)/len(diffs),
            complete_evidence_count_by_case=dict(by_evidence_size)),
        official_transformers_bf16_equivalence_certified=False,
        independent_semantic_entailment_verified=False,
        independent_source_family_authentication_verified=False,
        memorycell_superiority_claim=False,production_accepted=False)
    exclusive(output_file,return_data)
    return return_data

if __name__=='__main__':
    if len(sys.argv)!=8:
        raise SystemExit('usage: PREMISE_DIR PUBLIC_DIR RANK_DIR PREMISE_RESULTS RANK_RESULTS ORIGINAL_JSON OUTPUT_JSON')
    print(json.dumps(audit(*sys.argv[1:]),sort_keys=True))
