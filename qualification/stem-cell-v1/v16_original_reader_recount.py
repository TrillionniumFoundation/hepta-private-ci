"""Independent read-only byte recount of V16 original model journals (no labels)."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path

from v16_literal_witness_reader import read, digest, htext, ARMS, GROUPS, SCHEMA, OUT_CAP, READER_SHA, TOKEN_SHA


def forward_count(token_ids):
    if type(token_ids)!=list or not 1<=len(token_ids)<=OUT_CAP or any(type(t)!=int or not 0<=t<49152 for t in token_ids):
        raise ValueError('invalid original generated tokens')
    return len(token_ids) + (token_ids[-1]!=2)


def recount(plan,raw,starts,tokenizer):
    """Different verifier from the model producer; inspect original input/answer bytes."""
    if type(plan)!=dict or type(raw)!=dict or type(starts)!=list or type(raw.get('raw_answers'))!=dict:
        raise ValueError('missing physical materials')
    if raw.get('schema')!=SCHEMA+'.actual-original-reader-results' or raw.get('plan_sha256')!=digest(plan):
        raise ValueError('wrong exact source/model plan')
    if (raw.get('model_sha256')!=READER_SHA or raw.get('tokenizer_sha256')!=TOKEN_SHA or
        raw.get('human_verified_sufficiency') is not False or raw.get('stronger_reference_reader_executed') is not False or
        raw.get('independent_semantic_correctness') is not None or raw.get('hf_operator_tokenizer_parity') is not False or
        raw.get('production_authorized') is not False):raise ValueError('model / authority forgery')
    wanted=plan['requests'];records=raw['raw_answers']
    if set(wanted)!=set(records) or raw.get('requests')!=len(wanted) or len(starts)!=len(wanted):
        raise ValueError('missing/extra original request')
    seen=set();total_input=total_output=total_forward=0;verified=[]
    for row in starts:
        if type(row)!=dict or set(row)!={'request_id','plan_sha256','input_ids_sha256','input_token_count'}:
            raise ValueError('malformed original starts')
        rid=row['request_id']
        if rid not in wanted or rid in seen or row['plan_sha256']!=digest(plan):raise ValueError('duplicate/changed model start')
        seen.add(rid)
        original=wanted[rid];got=records[rid]
        inp=tokenizer.encode(original['prompt']);ans=got['token_ids']
        if not 1<=len(inp)<=1000 or row['input_ids_sha256']!=digest(inp) or row['input_token_count']!=len(inp):
            raise ValueError('original tokenizer/input drift')
        if (got['case_id']!=original['case_id'] or got['source_ids']!=original['source_ids'] or
            got['arm']!=original['arm'] or got['input_tokens']!=len(inp) or
            type(got['answer_text'])!=str or got['answer_sha256']!=htext(got['answer_text']) or
            got['answer_text']!=tokenizer.decode(ans) or got['output_tokens']!=len(ans)):
            raise ValueError('original token text/source drift')
        total_input+=len(inp);total_output+=len(ans);total_forward+=forward_count(ans)
        verified.append((rid,sha256(json.dumps(ans,separators=(',',':')).encode()).hexdigest(),got['answer_sha256']))
    if type(raw.get('model_forwards'))!=int or raw['model_forwards']!=total_forward:
        raise ValueError('original model physical forward count mismatch')
    if set(seen)!=set(wanted):raise ValueError('incomplete fsynced starts')
    return {'schema':SCHEMA+'.independent-private-recount',
            'plan_sha256':digest(plan),'original_raw_answer_file_sha256':digest(raw),
            'verified_requests':len(seen),'token_input_total':total_input,
            'token_output_total':total_output,'model_forward_calls':total_forward,
            'answer_and_token_lineage_sha256':digest(sorted(verified)),
            'semantic_accuracy':None,'source_sufficiency_human_verified':False,
            'reference_reader_executed':False,'production_authorized':False,
            'review_status':'BYTE_RECOUNT_ONLY_NOT_SCIENTIFIC_ACCEPTANCE'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--plan',required=True);ap.add_argument('--answers',required=True)
    ap.add_argument('--starts',required=True);ap.add_argument('--reader',required=True)
    ap.add_argument('--output',required=True);args=ap.parse_args()
    from v12_reader_runtime import check_original, OriginalCandidateBPE
    check_original(args.reader)
    path=Path(args.starts)
    lines=path.read_text().splitlines()
    def unique(parts):
        obj={}
        for k,v in parts:
            if k in obj:raise ValueError('duplicate json key')
            obj[k]=v
        return obj
    starts=[json.loads(line,object_pairs_hook=unique) for line in lines]
    report=recount(read(args.plan),read(args.answers),starts,OriginalCandidateBPE(args.reader))
    from v16_literal_witness_reader import sealed
    sealed(args.output,report)
    print(json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
