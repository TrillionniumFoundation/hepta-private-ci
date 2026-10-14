"""Read-only, label-blind question/answer sensitivity audit of sealed factorial probes.

This is a descriptive diagnostic, NOT an accuracy test, causal decomposition,
or a claim that a swapped question/candidate has a valid answer label.
"""
from __future__ import annotations
import math
from next_round_matrix import _digest
from multirc_query_factorial import SCHEMA


def review_factorial(report, *, epsilon=0.001, expected_factorial_id):
    if (not isinstance(report, dict) or report.get('schema') != SCHEMA
            or report.get('factorial_id') != expected_factorial_id
            or _digest({k:v for k,v in report.items() if k!='factorial_id'}) != expected_factorial_id):
        raise ValueError('exact sealed factorial observation required')
    if type(epsilon) not in (float,int) or not math.isfinite(epsilon) or not 0 <= epsilon <= .1:
        raise ValueError('finite predeclared descriptive epsilon required')
    rows = report.get('records')
    if (not isinstance(rows,list) or len(rows) != report.get('question_count')
            or len(rows) != report.get('passage_count',0)*2):
        raise ValueError('complete two-question passage inventory required')
    groups={}; seen=set()
    factors=('abs_change_question_only','abs_change_answer_only','abs_change_question_and_answer')
    for row in rows:
        if not isinstance(row,dict) or type(row.get('question_slot')) is not int or row['question_slot'] not in (0,1):
            raise ValueError('invalid question row')
        key=(row.get('source_group'),row.get('question_slot'))
        if not isinstance(key[0],str) or not key[0] or key in seen:
            raise ValueError('duplicate/missing source and question attribution')
        seen.add(key)
        if any(type(row.get(f)) not in (int,float) or not math.isfinite(row[f]) or not 0<=row[f]<=1 for f in factors):
            raise ValueError('nonfinite or impossible probability change')
        groups.setdefault(key[0],[]).append(row)
    if len(groups)!=report['passage_count'] or any(len(v)!=2 or {r['question_slot'] for r in v}!={0,1} for v in groups.values()):
        raise ValueError('missing passage pair')
    outputs=[]
    for group in sorted(groups):
        pair=groups[group]; means={f:sum(r[f] for r in pair)/2 for f in factors}
        outputs.append(dict(source_group=group,question_count=2,
            mean_absolute_probability_shifts=means,
            insensitive_to_question=sum(r[factors[0]]<=epsilon for r in pair),
            insensitive_to_answer=sum(r[factors[1]]<=epsilon for r in pair),
            insensitive_to_both=sum(r[factors[0]]<=epsilon and r[factors[1]]<=epsilon for r in pair)))
    result=dict(schema='hepta.multirc.factorial-descriptive-review.v1',
        source_factorial_id=expected_factorial_id,epsilon=epsilon,
        passage_count=len(groups),question_count=len(rows),by_passage=outputs,
        double_insensitive_question_count=sum(x['insensitive_to_both'] for x in outputs),
        swapped_combinations_have_verified_labels=False,statistical_independence_established=False,
        answer_accuracy=None,question_understanding_established=False,production_authorized=False)
    result['review_id']=_digest(result)
    return result
