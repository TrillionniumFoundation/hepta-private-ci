"""Original LoCoMo source-first SINGLE-arm natural-reader SHADOW diagnostic.

Three independent phases; execute receives public source/questions ONLY and no
publisher gold. Bounded deterministic BM25 evidence control, original archived
BF16 Llama+GPT2-ByteLevel tokenizer in FP32, raw uncensored answer recording,
then post-seal publisher-gold exact-string *descriptive* scoring. Does NOT test
nine Cell arms, independent future windows, HF parity, or production readiness.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import log
import os
from pathlib import Path
import regex
import time
import torch

from amcn_original_text_reader import ArchivedLlama, ArchivedByteLevelBPE, file_sha, format_archived_chat

PROFILE = 'hepta.amcn.original-locomo-single-arm-text-reader.shadow.v1'
CORPUS_SHA256 = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
TOKENIZER_SHA256 = '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
WORD = regex.compile(r'\w+',regex.UNICODE)
MAX_CASES = 24


def canonical(payload):
    return json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False,
                      separators=(',',':')).encode()


def sha(payload):
    return sha256(canonical(payload)).hexdigest()


def sealed_write(path, payload):
    path=Path(path)
    if path.is_symlink() or path.exists():
        raise ValueError('create-only source/reviewer receipt')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as dest:
        dest.write(canonical(payload)+b'\n');dest.flush();os.fsync(dest.fileno())


def open_pinned(path,expected_sha, *,maximum=12*1024*1024):
    path=Path(path)
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= maximum:
        raise ValueError('missing/oversized/linked source')
    raw=path.read_bytes()
    if sha256(raw).hexdigest()!=expected_sha:
        raise ValueError('external exact source SHA changed')
    def strict(items):
        z={}
        for k,v in items:
            if k in z:raise ValueError('duplicate JSON key')
            z[k]=v
        return z
    obj=json.loads(raw,object_pairs_hook=strict)
    if not isinstance(obj,dict):raise ValueError('source JSON object expected')
    return obj


def conversation_sources(sample):
    meta=sample['conversation']
    rows=[]
    for key,value in meta.items():
        if not key.startswith('session_') or not isinstance(value,list):
            continue
        date=meta.get(key+'_date_time', 'unknown date')
        for record in value:
            if isinstance(record,dict) and type(record.get('text')) is str:
                rows.append({'id':record['dia_id'],
                             'root':str(sample['sample_id']),
                             'text':f"Session date: {date}. {record['speaker']}: {record['text']}"})
    if len({r['id'] for r in rows})!=len(rows) or not rows:
        raise ValueError('duplicate or missing original dialogue IDs')
    return rows


def bm25(question,rows):
    terms=set(WORD.findall(question.casefold()))
    bags=[Counter(WORD.findall(r['text'].casefold())) for r in rows]
    n=len(rows);avg=max(1.,sum(sum(b.values()) for b in bags)/n)
    df=Counter()
    for bag in bags:
        for t in terms:df[t]+=int(t in bag)
    result=[]
    for row,bag in zip(rows,bags):
        width=sum(bag.values());sc=0.
        for term in terms:
            tf=bag[term]
            if tf:
                sc+=log(1+(n-df[term]+0.5)/(df[term]+0.5))*2.2*tf/(
                    tf+1.2*(0.25+0.75*width/avg))
        result.append((sc,row['id'],row))
    result.sort(key=lambda x:(-x[0],x[1]))
    return [x[2] for x in result]


def prepare(source_root, public_path, withheld_path, *, family_indices=(0,1),
            question_indices=(0,1,2,3,4,5), top_k=3):
    if len(family_indices)!=len(set(family_indices)) or not 1<=len(family_indices)<=3:
        raise ValueError('too many or repeated source families')
    if len(question_indices)!=len(set(question_indices)) or not 1<=len(question_indices)<=8:
        raise ValueError('invalid fixed question sample count')
    if type(top_k) is not int or not 1<=top_k<=8:
        raise ValueError('source-first final evidence budget')
    corpus_path=Path(source_root)/'locomo.json'
    if file_sha(corpus_path)!=CORPUS_SHA256:
        raise ValueError('original LoCoMo source bytes changed')
    corpus=json.loads(corpus_path.read_bytes())
    selected=[];gold=[]
    for fi in family_indices:
        if type(fi) is not int or fi<0 or fi>=len(corpus):
            raise ValueError('unknown original source family')
        sample=corpus[fi]
        inv=conversation_sources(sample)
        for qi in question_indices:
            if type(qi) is not int or qi<0 or qi>=len(sample['qa']):
                raise ValueError('unknown original question')
            record=sample['qa'][qi]
            question=record['question']
            if not isinstance(question,str) or not question or len(question)>512:
                raise ValueError('unbounded question')
            retrieved=bm25(question,inv)[:top_k]
            passages=[x['text'] for x in retrieved]
            if any(len(p.encode())>640 for p in passages):
                raise ValueError('oversize original source; no label-driven truncation')
            case_id=f"{sample['sample_id']}:{qi}"
            selected.append({'case_id':case_id,'family':str(sample['sample_id']),
                'question':question,'source_ids':[r['id'] for r in retrieved],
                'passages':passages,
                'question_sha256':sha256(question.encode()).hexdigest()})
            gold.append({'case_id':case_id,'family':str(sample['sample_id']),
                'publisher_answer':str(record['answer']),
                'publisher_evidence':[str(v) for v in record['evidence']]})
    if not 1<=len(selected)<=MAX_CASES:
        raise ValueError('bounded heldout question census')
    public={'schema':PROFILE+'.public.v1','original_dataset_sha256':CORPUS_SHA256,
            'top_k':top_k,'cases':selected,'training_labels_or_publisher_gold_present':False,
            'original_calendar_future_windows':0}
    withheld={'schema':PROFILE+'.withheld-publisher-gold.v1',
              'public_payload_sha256':sha(public),'gold_cases':gold,
              'independent_semantic_entailment':False,'calendar_future_windows':0}
    if Path(public_path).exists() or Path(withheld_path).exists():
        raise ValueError('create-only public/withheld outputs')
    sealed_write(public_path,public)
    sealed_write(withheld_path,withheld)
    return {'cases':len(selected),'families':len(family_indices),
            'public_file_sha256':file_sha(Path(public_path)),
            'withheld_file_sha256':file_sha(Path(withheld_path))}


def generate(public_path,public_sha256,reader_dir,output,*, max_new_tokens=48):
    if type(max_new_tokens) is not int or not 1<=max_new_tokens<=96:
        raise ValueError('bounded output token count')
    source=open_pinned(Path(public_path),public_sha256)
    if set(source)!={'schema','original_dataset_sha256','top_k','cases',
                    'training_labels_or_publisher_gold_present','original_calendar_future_windows'}:
        raise ValueError('unexpected gold/source fields')
    if (source['schema']!=PROFILE+'.public.v1'
            or source['training_labels_or_publisher_gold_present'] is not False
            or source['original_dataset_sha256']!=CORPUS_SHA256
            or source['original_calendar_future_windows']!=0):
        raise ValueError('not a label-isolated original corpus')
    cases=source['cases']
    if not isinstance(cases,list) or not 1<=len(cases)<=MAX_CASES:
        raise ValueError('missing original source-first cases')
    if Path(output).exists() or Path(output).is_symlink():
        raise ValueError('original answers are create-only')
    reader_dir=Path(reader_dir)
    tokenizer=ArchivedByteLevelBPE(reader_dir,
                   expected_tokenizer_sha256=TOKENIZER_SHA256)
    torch.set_num_threads(2)
    model=ArchivedLlama(reader_dir)
    receipt={'schema':PROFILE+'.raw-model-answers.v1','public_file_sha256':public_sha256,
             'public_payload_sha256':sha(source),
             'original_reader_model_sha256':file_sha(reader_dir/'model.safetensors'),
             'original_reader_tokenizer_sha256':tokenizer.sha256,
             'parity_with_official_hf_not_yet_verified':True,
             'cases':[],'gold_opened_during_model_execution':False,
             'model_answers_generated':0,'original_weak_bm25_evidence_only':True,
             'independent_eval':False,'strong_hybrid_rag':False,
             'nine_cell_arms':False,'production_accepted':False}
    seen=set()
    for case in cases:
        if not isinstance(case,dict) or set(case)!={
            'case_id','family','question','source_ids','passages','question_sha256'}:
            raise ValueError('unreviewed source/question fields')
        if case['case_id'] in seen or len(case['source_ids'])!=source['top_k']:
            raise ValueError('duplicate or changed evidence count')
        seen.add(case['case_id'])
        if len(case['passages'])!=source['top_k'] or sha256(case['question'].encode()).hexdigest()!=case['question_sha256']:
            raise ValueError('changed original source-first question')
        prompt=format_archived_chat(case['question'],case['passages'])
        tokens=tokenizer.encode(prompt)
        if len(tokens)+max_new_tokens>1024:
            raise ValueError('insufficient original Reader token budget; no silent truncation')
        started=time.perf_counter()
        generated=model.generate(tokens,max_new_tokens=max_new_tokens)
        raw=tokenizer.decode(generated)
        receipt['cases'].append({'case_id':case['case_id'],'family':case['family'],
             'source_ids':case['source_ids'],'request_sha256':sha256(prompt.encode()).hexdigest(),
             'input_tokens':len(tokens),'generated_token_ids':generated,
             'output_tokens':len(generated),'raw_answer':raw,
             'raw_answer_sha256':sha256(raw.encode()).hexdigest(),
             'observed_wall_seconds':time.perf_counter()-started,
             'stopped_on_eos':bool(generated and generated[-1]==2),
             'reached_output_ceiling':bool(len(generated)==max_new_tokens)})
        receipt['model_answers_generated']+=1
    sealed_write(output,receipt)
    return {'cases':len(cases),'answer_file_sha256':file_sha(Path(output)),
            'model_answers_generated':receipt['model_answers_generated']}


def descriptive_score(original_answers,original_answers_sha256,
                      withheld,withheld_sha256,output):
    a=open_pinned(Path(original_answers),original_answers_sha256)
    gold=open_pinned(Path(withheld),withheld_sha256)
    if (a.get('schema')!=PROFILE+'.raw-model-answers.v1' or
            gold.get('schema')!=PROFILE+'.withheld-publisher-gold.v1' or
            a.get('production_accepted') is not False or
            gold.get('public_payload_sha256') != a.get('public_payload_sha256') or
            a.get('model_answers_generated') != len(a.get('cases', [])) or
            a.get('gold_opened_during_model_execution') is not False):
        raise ValueError('unreviewed score input or publisher answer/public plan drift')
    raw_cases=a.get('cases')
    golden=gold.get('gold_cases')
    if not isinstance(raw_cases,list) or not isinstance(golden,list):
        raise ValueError('malformed score census')
    left={r['case_id']:r for r in raw_cases}
    right={r['case_id']:r for r in golden}
    if len(left)!=len(raw_cases) or len(right)!=len(golden) or set(left)!=set(right):
        raise ValueError('missing/duplicate publisher targets or model attempts')
    exact_count=0;recovered=0;observed=[]
    for qid,row in sorted(left.items()):
        target=right[qid]
        if target['family'] != row['family'] or row['raw_answer_sha256'] != sha256(
                row['raw_answer'].encode()).hexdigest():
            raise ValueError('source-family/Reader-original-answer binding drift')
        normalize=lambda s:' '.join(s.lower().strip().split())
        raw=normalize(row['raw_answer'])
        gold_text=normalize(target['publisher_answer'])
        success=int(raw==gold_text)
        exact_count+=success
        recovered+=int(bool(set(row['source_ids'])&set(target['publisher_evidence'])))
        observed.append({'case_id_sha256':sha256(qid.encode()).hexdigest(),
            'publisher_literal_exact_match':bool(success),
            'publisher_support_in_original_topk':bool(set(row['source_ids'])&set(target['publisher_evidence'])),
            'response_reached_token_ceiling':row['reached_output_ceiling']})
    summary={'schema':PROFILE+'.historical-publisher-weak-descriptive.v1',
             'original_answer_file_sha256':original_answers_sha256,
             'withheld_publisher_file_sha256':withheld_sha256,
             'questions':len(left),'families':len({r['family'] for r in raw_cases}),
             'literal_exact_matches':exact_count,'weak_evidence_recovered_questions':recovered,
             'individual_results':observed,'reader_hf_parity_required':True,
             'independent_semantic_success_metric':None,'independent_evaluator':False,
             'true_future_calendar_windows':0,'nine_arm_superiority':False,
             'production_accepted':False}
    sealed_write(output,summary)
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser()
    commands=parser.add_subparsers(dest='mode',required=True)
    a=commands.add_parser('prepare')
    a.add_argument('--source-root',type=Path,required=True)
    a.add_argument('--public',type=Path,required=True)
    a.add_argument('--withheld',type=Path,required=True)
    a.add_argument('--question-indices',type=str,default='0,1,2,3,4,5')
    b=commands.add_parser('generate')
    b.add_argument('--public',type=Path,required=True)
    b.add_argument('--public-sha256',required=True)
    b.add_argument('--reader',type=Path,required=True)
    b.add_argument('--output',type=Path,required=True)
    b.add_argument('--max-new-tokens',type=int,default=48)
    c=commands.add_parser('score')
    c.add_argument('--answers',type=Path,required=True)
    c.add_argument('--answers-sha256',required=True)
    c.add_argument('--withheld',type=Path,required=True)
    c.add_argument('--withheld-sha256',required=True)
    c.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.mode=='prepare':
        try:
            chosen=tuple(int(v) for v in args.question_indices.split(','))
        except ValueError as exc:
            raise ValueError('invalid precommitted question indices') from exc
        return prepare(args.source_root,args.public,args.withheld,question_indices=chosen)
    if args.mode=='generate':return generate(args.public,args.public_sha256,args.reader,args.output,
                                            max_new_tokens=args.max_new_tokens)
    return descriptive_score(args.answers,args.answers_sha256,args.withheld,
                             args.withheld_sha256,args.output)


if __name__=='__main__':
    print(json.dumps(main(),sort_keys=True))
