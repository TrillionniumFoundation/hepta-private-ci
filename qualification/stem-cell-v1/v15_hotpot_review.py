"""Independent stdlib-only review of sealed HotpotQA *evidence*, not answers.

Question gold must be absent from ranking stage; this reviewer does not import
ranking implementation, and never treats answer-text presence as answer accuracy.
"""
from collections import defaultdict
import argparse
import json
import math
from pathlib import Path
import time

from v15_hotpot_source import digest, load, write_once, N_EXPECTED, SCHEMA

ARMS = ('bm25', 'title_link', 'scrambled_link', 'hash_random')
BUDGETS = (2, 5)
SCHEMA_PRED = 'hepta.v15.hotpotqa-sourceblind-evidence.v1'


def audit(public_file, owner_file, hidden_file, plan_file, seal_file, output_file):
    started=time.process_time_ns()
    public,owner,hidden,plan,pred = (load(p) for p in (public_file,owner_file,hidden_file,plan_file,seal_file))
    ids = [x['id'] for x in public]
    if (type(public) is not list or len(public) != N_EXPECTED or len(set(ids)) != len(ids)
            or owner.get('schema') != SCHEMA or owner.get('public_sha256') != digest(public)
            or owner.get('hidden_sha256') != digest(hidden)
            or owner.get('original_cases') != N_EXPECTED
            or plan.get('plan_sha256') != digest({k:v for k,v in plan.items() if k!='plan_sha256'})
            or plan.get('public_sha256') != digest(public)
            or plan.get('owner_manifest_sha256') != digest(owner)
            or plan.get('arms') != list(ARMS) or plan.get('budgets') != list(BUDGETS)
            or pred.get('schema') != SCHEMA_PRED
            or pred.get('source_sha256') != digest(public)
            or pred.get('source_owner_sha256') != digest(owner)
            or pred.get('plan_sha256') != plan['plan_sha256']
            or pred.get('proposal_sha256') != digest(pred.get('proposals'))
            or set(pred.get('proposals',{})) != set(ids)
            or set(hidden) != set(ids)
            or pred.get('answers_or_gold_never_read') is not True
            or pred.get('pretrained_calls') != 0 or pred.get('optimizer_updates') != 0
            or pred.get('actual_answer_generation') is not False
            or pred.get('authority') != 'DENY_ALL' or pred.get('production_accepted') is not False):
        raise ValueError('original gold/public, sealed predictions, fixed budget or research authority mismatch')
    grouped = defaultdict(lambda: dict(n=0,f1=0.,precision=0.,recall=0.,exact=0,
                                      doc_recall=0.,answer_text_presence=0,
                                      gold_sentences=0,predicted_sentences=0))
    per_question = {}
    distinct_title_sets=set()
    for row in public:
        qid=row['id']; gold=hidden[qid]
        if not isinstance(gold,dict) or set(gold) != {'answer','supporting_facts','type','level'}:
            raise ValueError('full original gold schema required')
        sentences={(title,index): text for title,para in row['context'] for index,text in enumerate(para)}
        true={tuple(x) for x in gold['supporting_facts']}
        if (not true or not true <= set(sentences) or not isinstance(gold['answer'],str)
                or gold['type'] not in ('bridge','comparison')
                or gold['level'] not in ('easy','medium','hard')):
            raise ValueError('hidden gold facts missing from original, complete public evidence')
        doc_gold = {title for title,_ in true}
        distinct_title_sets.add(tuple(sorted(doc_gold)))
        one = pred['proposals'][qid]
        if not isinstance(one,dict) or set(one) != set(ARMS):
            raise ValueError('fixed arm universe / missing prediction')
        record = {}
        for arm in ARMS:
            entry=one[arm]
            if type(entry) is not dict or set(entry) != {str(k) for k in BUDGETS}:
                raise ValueError('registered same-K comparison requires all budgets')
            for budget in BUDGETS:
                choices=entry[str(budget)]
                if (not isinstance(choices,list) or len(choices) != min(budget,len(sentences))
                        or any(not isinstance(x,list) or len(x)!=2
                               or type(x[0]) is not str or type(x[1]) is not int
                               or tuple(x) not in sentences for x in choices)
                        or len({tuple(x) for x in choices})!=len(choices)):
                    raise ValueError('candidate evidence was fabricated, duplicated or breached budget')
                picked={tuple(x) for x in choices}
                match=len(picked & true)
                precision = match/len(picked)
                recall = match/len(true)
                f1 = 2*precision*recall/(precision+recall) if (precision+recall) else 0.
                docs_picked={title for title,_ in picked}
                drecall = len(docs_picked & doc_gold)/len(doc_gold)
                # This checks availability of the *known* answer in selected citations,
                # NOT the actual answer sent by any reader (none is generated here).
                answer_presence = int(gold['answer'].casefold() in ' '.join(sentences[k] for k in picked).casefold()) \
                    if gold['answer'].casefold() not in ('yes','no') else 0
                key=(arm,budget,gold['type'],gold['level'])
                stats=grouped[key]
                stats['n']+=1;stats['f1']+=f1;stats['precision']+=precision
                stats['recall']+=recall;stats['exact']+=int(picked == true)
                stats['doc_recall']+=drecall;stats['answer_text_presence']+=answer_presence
                stats['gold_sentences']+=len(true);stats['predicted_sentences']+=len(picked)
                record[f'{arm}/{budget}'] = (f1, recall)
        per_question[qid]=record
    all_scores=[]
    for (arm,k,kind,level),r in sorted(grouped.items()):
        n=r['n']
        all_scores.append(dict(arm=arm,budget=k,type=kind,level=level,questions=n,
            support_F1_macro=r['f1']/n, support_precision_macro=r['precision']/n,
            support_recall_macro=r['recall']/n,support_exact_rate=r['exact']/n,
            document_recall_macro=r['doc_recall']/n,
            answer_string_in_selected_sentences_rate=r['answer_text_presence']/n,
            mean_gold_support_sentences=r['gold_sentences']/n,
            mean_selected_sentences=r['predicted_sentences']/n))
    summaries=[]
    for arm in ARMS:
        for k in BUDGETS:
            selected=[r for r in all_scores if r['arm']==arm and r['budget']==k]
            if sum(r['questions'] for r in selected) != N_EXPECTED:
                raise ValueError('incomplete independent original natural question population')
            summaries.append(dict(arm=arm,budget=k,questions=N_EXPECTED,
                support_F1_macro=sum(r['support_F1_macro']*r['questions'] for r in selected)/N_EXPECTED,
                support_recall_macro=sum(r['support_recall_macro']*r['questions'] for r in selected)/N_EXPECTED,
                evidence_exact_rate=sum(r['support_exact_rate']*r['questions'] for r in selected)/N_EXPECTED,
                document_recall_macro=sum(r['document_recall_macro']*r['questions'] for r in selected)/N_EXPECTED))
    result=dict(schema='hepta.v15.original-hotpotqa-independent-postseal.v1',
                dataset='hotpotqa-dev-distractor',official_source_sha256=owner['original_sha256'],
                public_sha256=digest(public),restricted_truth_sha256=digest(hidden),
                prediction_sha256=pred['proposal_sha256'],reviewed_questions=N_EXPECTED,
                unique_gold_article_sets=len(distinct_title_sets),
                summary=summaries,by_type_level=all_scores,
                same_question_paired_controls=True, not_prospective=True,
                original_gold_article_overlap_not_independent=True,
                evaluate_answers=False, answer_string_presence_not_generated_answer=True,
                formal_entity_graph_not_proven=True, no_training_or_pretrained_forwards=True,
                held_truth_only_loaded_in_independent_score_job=True,
                review_cpu_ns=time.process_time_ns()-started,
                model_selected=False,production_accepted=False,authority='DENY_ALL')
    result['result_sha256'] = digest(summaries)
    write_once(output_file,result)
    return result


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    for key in ('public','owner','hidden','plan','seal','output'):
        cli.add_argument('--'+key,required=True)
    a=cli.parse_args()
    r=audit(a.public,a.owner,a.hidden,a.plan,a.seal,a.output)
    print(json.dumps(dict(questions=r['reviewed_questions'],result_sha256=r['result_sha256'],summary=r['summary'],authority=r['authority'])))


if __name__ == '__main__':
    main()
