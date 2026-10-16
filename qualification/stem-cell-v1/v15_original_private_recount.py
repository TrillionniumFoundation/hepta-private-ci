"""Independent read-only recount of V15 actual original Reader output/journal bytes.

A matching original answer journal attests output consistency only; not the
origin of host execution, correct answers, HF parity, sufficient evidence, or
independent human evaluation.
"""
from __future__ import annotations
from collections import Counter
import json
from pathlib import Path
from v15_original_candidate_four_arm import ARMS,SCHEMA,digest,load,htext,validate_answers


def recount(plan, src, ranks, answers, journal_lines, token_decode=None):
    validate_answers(plan,src,ranks,answers)
    if type(journal_lines)!=list or len(journal_lines)!=len(plan['requests']):
        raise ValueError('missing original durable attempt census')
    starts={}
    for line in journal_lines:
        row=json.loads(line)
        if type(row)!=dict or set(row)!={'request_id','plan_sha256','original_input_token_sha256','original_input_token_count'}:
            raise ValueError('invalid journal record')
        rid=row['request_id']
        if rid not in plan['requests'] or rid in starts or row['plan_sha256']!=digest(plan):
            raise ValueError('duplicate/changed start entry')
        if type(row['original_input_token_count'])!=int or row['original_input_token_count']<1:
            raise ValueError('invalid input counter')
        if row['original_input_token_count']!=answers['raw_answers'][rid]['input_tokens']:
            raise ValueError('answer not bound to original start counter')
        starts[rid]=row
    if set(starts)!=set(plan['requests']):raise ValueError('not all requests physically started')
    predicted_forwards=0
    for rid,row in answers['raw_answers'].items():
        generated=row['token_ids']
        predicted_forwards+=len(generated)+int(generated[-1]!=2)
        if token_decode is not None:
            ids=token_decode.encode(plan['requests'][rid]['prompt'])
            if digest(ids)!=starts[rid]['original_input_token_sha256'] or len(ids)!=starts[rid]['original_input_token_count']:
                raise ValueError('original start was not this tokenizer input')
            if token_decode.decode(generated)!=row['answer_text']:
                raise ValueError('answer text does not match original token IDs')
    if predicted_forwards!=answers['model_forwards']:
        raise ValueError('false physical model forward census')
    cases={}
    for case in plan['cases']:
        ids=[case['arms'][arm]['request_id'] for arm in ARMS]
        cases[case['id']]={arm:answers['raw_answers'][rid]['answer_sha256'] for arm,rid in zip(ARMS,ids)}
    changed=sum(z['retrieved']!=z['annotated_witness'] for z in cases.values())
    return {'schema':SCHEMA+'.private-recount.v1','model_answer_sha256':digest(answers),
            'source_plan_sha256':digest(plan),'starts':len(starts),
            'original_reader_requests':len(answers['raw_answers']),
            'accounted_model_forwards':predicted_forwards,
            'answers_changed_retrieved_to_witness':changed,
            'host_execution_independently_attested':False,
            'sufficient_evidence_independently_judged':False,
            'semantic_task_success_known':False,'production_authorized':False}


def main():
    import argparse
    from v12_reader_runtime import OriginalCandidateBPE
    from v15_original_candidate_four_arm import save_new
    p=argparse.ArgumentParser()
    for n in ('plan','source','bm25','answers','journal','reader','out'):p.add_argument('--'+n,required=True)
    a=p.parse_args()
    tok=OriginalCandidateBPE(a.reader)
    result=recount(load(a.plan),load(a.source),load(a.bm25),load(a.answers),
                   Path(a.journal).read_text().splitlines(),tok)
    save_new(a.out,result)
    print(json.dumps(result,sort_keys=True))
if __name__=='__main__':main()
