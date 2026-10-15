"""Source-only E3 temporal fixed/learned/lesion Reader diagnostics.

Select all candidates by a predeclared label-blind edge-lesion difference;
sample by SHA case IDs, then dispatch original archived Llama. Gold only opens
in a separate postseal phase. No official HF parity or production admission.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json, os, re
from pathlib import Path

from amcn_original_temporal_e3 import (
    PROFILE as E3, ARMS, HELDOUT, canonical, put_new,
    read_pinned, require, sha_bytes, CORPUS_SHA,
)
from amcn_original_text_reader import (
    ArchivedLlama, ArchivedByteLevelBPE, format_archived_chat,
    WEIGHT_SHA256,
)

PROFILE = E3+'.original-four-arm-reader.v1'
TOKENIZER_SHA='9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
MAX_NEW=16
SALT='hepta.e3.temporal-lesion-candidate.v1'


def append_line(path,record):
    with Path(path).open('ab') as f:
        f.write(canonical(record)); f.flush();os.fsync(f.fileno())


def load_lines(path):
    raw=Path(path).read_bytes()
    require(raw.endswith(b'\n') and raw,'torn or absent original Reader journal')
    return [json.loads(line) for line in raw.splitlines()]


def build_plan(public,source_sha,ranks,rank_sha,reader_directory,out_file):
    require(public['profile']==E3+'.source-only.v1' and public['gold_included'] is False
            and ranks['profile']==E3+'.sealed-source-ranks.v1' and
            ranks['ranking_publisher_gold_opened'] is False and
            ranks['source_sha256']==source_sha and
            ranks['original_question_count']==1986 and len(ranks['predictions'])==1986,
            'source bound complete E3 rank required')
    tokenizer=ArchivedByteLevelBPE(Path(reader_directory),expected_tokenizer_sha256=TOKENIZER_SHA)
    by_id={q['case_id']:q for q in public['cases']}
    for row in ranks['predictions']:
        case=by_id[row['case_id']]
        require(row['question_sha256']==case['question_sha256'] and
                row['family']==case['family'] and row['split']==case['split'],
                'original candidate/question switch')
    cases=[]
    inventory=Counter()
    for family in HELDOUT:
        eligible=[r for r in ranks['predictions'] if r['family']==family and
                  r['selected']['temporal_edge_lesion']!=r['selected']['temporal_learned']]
        inventory[family]=len(eligible)
        require(len(eligible)>=3,'not enough original label-blind edge-lesion changes')
        eligible.sort(key=lambda r:(sha_bytes((SALT+'/'+r['case_id']).encode()),r['case_id']))
        for r in eligible[:3]:
            c=by_id[r['case_id']]
            sources={s['id']:s['text'] for s in public['sources'][family]}
            req={}
            for arm in ARMS:
                ids=r['selected'][arm]
                require(len(ids)==3 and len(set(ids))==3 and set(ids)<=set(sources),
                        'unknown original graph evidence candidate')
                prompt=format_archived_chat(c['question'],[sources[s] for s in ids])
                input_ids=tokenizer.encode(prompt)
                require(0<len(input_ids) and len(input_ids)+MAX_NEW<=1024,
                        'no truncation original Reader context')
                req[arm]={'source_ids':ids,'prompt_sha256':sha_bytes(prompt.encode()),
                          'prompt':prompt,'input_tokens':len(input_ids),
                          'input_ids_sha256':sha_bytes(canonical(input_ids))}
            cases.append({'case_id':r['case_id'],'family':family,
                          'split':r['split'],'question_sha256':r['question_sha256'],
                          'requests':req})
    cases.sort(key=lambda c:c['case_id'])
    plan={'profile':PROFILE,'source_sha256':source_sha,'rank_sha256':rank_sha,
          'model_sha256':WEIGHT_SHA256,'tokenizer_sha256':TOKENIZER_SHA,
          'arms':list(ARMS),'cases':cases,'eligible_edge_lesion_changes':dict(inventory),
          'selection_rule':SALT,'final_sources':3,'max_new_tokens':MAX_NEW,
          'independent_future_windows':0,'publisher_gold_used_in_plan':False,
          'official_hf_parity_verified':False,'production_accepted':False}
    require(len(cases)==6,'incomplete precommitted E3 Reader study')
    return put_new(out_file,plan)


def validate_plan(plan,tokenizer):
    require(plan['profile']==PROFILE and plan['model_sha256']==WEIGHT_SHA256 and
            plan['tokenizer_sha256']==TOKENIZER_SHA and
            plan['arms']==list(ARMS) and len(plan['cases'])==6 and
            plan['publisher_gold_used_in_plan'] is False and
            plan['production_accepted'] is False and
            plan['official_hf_parity_verified'] is False and
            plan['independent_future_windows']==0,'fake source or Reader authority')
    require(Counter(c['family'] for c in plan['cases'])==dict.fromkeys(HELDOUT,3),
            'missing independent historical E3 source root')
    for case in plan['cases']:
        require(set(case['requests'])==set(ARMS),'missing graph ablation arm')
        require(case['requests']['temporal_learned']['source_ids'] !=
                case['requests']['temporal_edge_lesion']['source_ids'],
                'not a real graph intervention')
        for arm in ARMS:
            r=case['requests'][arm]
            tokens=tokenizer.encode(r['prompt'])
            require(r['prompt_sha256']==sha_bytes(r['prompt'].encode()) and
                    r['input_ids_sha256']==sha_bytes(canonical(tokens)) and
                    r['input_tokens']==len(tokens) and
                    len(r['source_ids'])==3 and len(set(r['source_ids']))==3,
                    'changed original Reader request bytes')
            require(len(tokens)+MAX_NEW<=1024,'original Reader context ceiling')
    return [(case,arm) for case in plan['cases'] for arm in ARMS]


def generate(plan,reader_directory,output_directory):
    output_directory=Path(output_directory)
    require(not output_directory.exists(),'never overwrite existing original Reader journal')
    tokenizer=ArchivedByteLevelBPE(Path(reader_directory),expected_tokenizer_sha256=TOKENIZER_SHA)
    original=validate_plan(plan,tokenizer)
    output_directory.mkdir(parents=True,mode=0o700)
    model=ArchivedLlama(Path(reader_directory),expected_sha256=WEIGHT_SHA256)
    success=0;failures=0
    for case,arm in original:
        r=case['requests'][arm]
        attempt={'case_id':case['case_id'],'family':case['family'],'arm':arm,
                 'prompt_sha256':r['prompt_sha256'],'source_ids':r['source_ids'],
                 'input_token_count':r['input_tokens']}
        append_line(output_directory/'starts.jsonl',attempt)
        try:
            ids=tokenizer.encode(r['prompt'])
            got=model.generate(ids,max_new_tokens=MAX_NEW)
            text=tokenizer.decode(got)
            result={**attempt,'status':'success','raw_answer':text,
                    'raw_answer_sha256':sha_bytes(text.encode()),
                    'generated_token_ids':got,'generated_count':len(got),
                    'eos':bool(got and got[-1]==2)}
            success+=1
        except Exception as error:
            result={**attempt,'status':'failed','error_class':type(error).__name__}
            failures+=1
        append_line(output_directory/'raw_answers.jsonl',result)
    starts=load_lines(output_directory/'starts.jsonl')
    answers=load_lines(output_directory/'raw_answers.jsonl')
    require(len(starts)==len(answers)==len(original) and
            all(starts[i]['case_id']==answers[i]['case_id'] and
                starts[i]['arm']==answers[i]['arm'] for i in range(len(original))),
            'original durable Reader journal census incomplete')
    s={'profile':PROFILE+'.sealed-original-reader.v1',
       'plan_sha256':sha_bytes(canonical(plan)),
       'start_file_sha256':sha_bytes((output_directory/'starts.jsonl').read_bytes()),
       'answer_file_sha256':sha_bytes((output_directory/'raw_answers.jsonl').read_bytes()),
       'total_attempts':len(original),'success':success,'failed':failures,
       'source_roots':len(set(c['family'] for c in plan['cases'])),
       'publisher_gold_read_before_answer_seal':False,
       'independent_semantic_task_score':None,
       'production_accepted':False}
    seal_sha=put_new(output_directory/'seal.json',s)
    return seal_sha


def recount(plan,reader_root,journal_folder):
    folder=Path(journal_folder)
    tok=ArchivedByteLevelBPE(Path(reader_root),expected_tokenizer_sha256=TOKENIZER_SHA)
    expected=validate_plan(plan,tok)
    seal=json.loads((folder/'seal.json').read_bytes())
    starts=load_lines(folder/'starts.jsonl');answers=load_lines(folder/'raw_answers.jsonl')
    require(seal['plan_sha256']==sha_bytes(canonical(plan)) and
            seal['answer_file_sha256']==sha_bytes((folder/'raw_answers.jsonl').read_bytes()) and
            seal['start_file_sha256']==sha_bytes((folder/'starts.jsonl').read_bytes()) and
            seal['total_attempts']==len(expected)==len(starts)==len(answers),
            'missing original Reader answers or changed evidence')
    for i,(case,arm) in enumerate(expected):
        start=starts[i];a=answers[i];r=case['requests'][arm]
        require((start['case_id'],start['arm'],start['source_ids'],start['prompt_sha256'])==
                (case['case_id'],arm,r['source_ids'],r['prompt_sha256']) and
                {k:start[k] for k in start}=={k:a[k] for k in start},
                'reader question/source/attempt identity drift')
        if a['status']=='success':
            require(a['raw_answer_sha256']==sha_bytes(a['raw_answer'].encode()) and
                    a['raw_answer']==tok.decode(a['generated_token_ids']) and
                    a['generated_count']==len(a['generated_token_ids']) and
                    a['generated_count']<=MAX_NEW,'original raw Reader text/token tampering')
    require(sum(a['status']=='success' for a in answers)==seal['success'] and
            sum(a['status']=='failed' for a in answers)==seal['failed'],
            'failed/incomplete inference hidden')
    return seal,answers


def postseal_score(plan,reader_root,folder,corpus,corpus_sha,heldout,heldout_sha,out_file):
    seal,raw=recount(plan,reader_root,folder)
    require(corpus_sha==CORPUS_SHA and sha_bytes(Path(corpus).read_bytes())==CORPUS_SHA,
            'unregistered original LoCoMo outcome source')
    withheld=read_pinned(heldout,heldout_sha)
    require(withheld['profile']==E3+'.withheld-publisher-weak.v1' and
            withheld['public_sha256']==plan['source_sha256'],'gold/QA source mismatch')
    by={r['case_id']:r for r in withheld['targets']}
    raw_data={sample['sample_id']:sample for sample in json.loads(Path(corpus).read_bytes())}
    totals={arm:Counter() for arm in ARMS};diffs=Counter();family=Counter()
    pair={}
    for row in raw:
        c=row['case_id'];arm=row['arm']; case=next(x for x in plan['cases'] if x['case_id']==c)
        support=set(by[c]['publisher_support']); chosen=set(row['source_ids'])
        stat=totals[arm];stat['attempts']+=1;stat['success']+=int(row['status']=='success')
        stat['weak_any3']+=int(bool(support & chosen))
        stat['weak_all3']+=int(bool(support) and support<=chosen)
        stat['input_tokens']+=row['input_token_count']
        stat['generated_tokens']+=row.get('generated_count',0)
        sample=raw_data[case['family']];q=sample['qa'][int(c.split(':')[-1])]
        # This field is an original publisher STRING diagnostic, not a semantic judge.
        pub=q.get('answer',q.get('adversarial_answer'))
        if row['status']=='success':
            stat['strict_literal']+=int(isinstance(pub,(str,int)) and
                row['raw_answer'].strip()==str(pub).strip())
            pair[(c,arm)]=row['raw_answer']
        family[case['family']]+=int(arm=='bm25')
    for c in plan['cases']:
        if all((c['case_id'],a) in pair for a in ARMS):
            diffs['learned_vs_fixed_different_raw_answer']+=int(
                pair[(c['case_id'],'temporal_learned')]!=pair[(c['case_id'],'temporal_fixed')])
            diffs['lesion_vs_learned_different_raw_answer']+=int(
                pair[(c['case_id'],'temporal_edge_lesion')]!=pair[(c['case_id'],'temporal_learned')])
    require(sum(family.values())==6 and all(t['attempts']==6 for t in totals.values()),
            'missing original E3 Reader treatment/case')
    matched_input=sum(len({c['requests'][a]['input_tokens'] for a in ARMS})==1
                      for c in plan['cases'])
    require(0<=matched_input<=6, 'invalid original Reader token parity count')
    return put_new(out_file,{'profile':PROFILE+'.postseal-descriptive-score.v1',
      'plan_sha256':seal['plan_sha256'],'answer_seal_sha256':sha_bytes((Path(folder)/'seal.json').read_bytes()),
      'original_gold_sha256':heldout_sha,'original_reader_attempts':len(raw),
      'original_reader_failures':seal['failed'],'two_original_retrospective_families':True,
      'arm_totals':{k:dict(v) for k,v in totals.items()},'raw_answer_differences':dict(diffs),
      'whole_reader_task_semantic_success_independently_verified':False,
      'original_cases_with_equal_four_arm_input_tokens':matched_input,
      'all_paired_original_input_tokens_equal':matched_input==len(plan['cases']),
      'official_hf_operator_parity_verified':False,'graph_relation_truth_verified':False,
      'strong_rag_equal_compute_verified':False,'actual_future_calendar_windows':0,
      'production_accepted':False})


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='phase',required=True)
    for phase in ['plan','generate','score']:
        s=sub.add_parser(phase)
        if phase=='plan':
            for name in ['public','public-sha','rank','rank-sha','reader','output']:
                s.add_argument('--'+name,required=True)
        elif phase=='generate':
            for name in ['plan','plan-sha','reader','output-dir']:
                s.add_argument('--'+name,required=True)
        else:
            for name in ['plan','plan-sha','reader','journal','corpus','corpus-sha','heldout','heldout-sha','output']:
                s.add_argument('--'+name,required=True)
    args=p.parse_args()
    if args.phase=='plan':
        a=read_pinned(args.public,args.public_sha)
        b=read_pinned(args.rank,args.rank_sha)
        r=build_plan(a,args.public_sha,b,args.rank_sha,args.reader,args.output)
    elif args.phase=='generate':
        a=read_pinned(args.plan,args.plan_sha)
        r=generate(a,args.reader,args.output_dir)
    else:
        a=read_pinned(args.plan,args.plan_sha)
        r=postseal_score(a,args.reader,args.journal,args.corpus,args.corpus_sha,
                         args.heldout,args.heldout_sha,args.output)
    print(json.dumps({'created_sha256':r},sort_keys=True))

if __name__=='__main__':main()
