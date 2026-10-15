"""V12: source-first exhaustive V11 Head vs cheap control evidence membership disagreement.

Three segregated stages. No model training or promotion. Only selected original
source texts and original question strings enter the Reader. Postseal weak
publisher references are never accessible during preparation/Reader.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import time

PRED_SHA='3dabcb167a676d124ae36ff271bb14de3d58b557b00fbbef5619030b857c8a9a'
SOURCE_SHA='1cb2d1d7194137cdea48ef8a13e8002c6612a9c98a1ffa71e28e7263c61bf84c'
SCHEMA='hepta.stem.v12.original-disagreement-reader.shadow.v1'
MODEL_WEIGHT_SHA='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'


def hash_file(p):
    h=sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def jd(x):return sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def write_new(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write((json.dumps(data,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n').encode());f.flush();os.fsync(f.fileno())
    except Exception:
        raise

def read_exact(path,expected=None):
    p=Path(path)
    if not p.is_file() or p.is_symlink():raise ValueError('unsafe missing file')
    if expected and hash_file(p)!=expected:raise ValueError('exact upstream source bytes changed')
    def no_duplicate(pairs):
        out={}
        for key,value in pairs:
            if key in out:raise ValueError('duplicate JSON field')
            out[key]=value
        return out
    def no_constant(value):raise ValueError('nonfinite JSON numeric value')
    return json.loads(p.read_bytes(),object_pairs_hook=no_duplicate,parse_constant=no_constant)

def disagreement_inventory(predictions):
    if predictions.get('schema')!='hepta.stem.v11.original-minilm-lexical-residual.shadow.v1.sealed-predictions' or predictions.get('labels_read_before_seal') is not False or predictions.get('production_authorized') is not False:
        raise ValueError('original model plan or labels changed')
    rows=predictions['predictions']
    if len(rows)!=829:raise ValueError('incomplete 829 heldout roster')
    counters={str(seed):dict(ordered=0,membership=0) for seed in (41,47,53)}
    selected={}
    for qid,rs in sorted(rows.items()):
        if not qid.startswith(('conv-47/q','conv-48/q','conv-49/q','conv-50/q')):raise ValueError('outside original withheld source roots')
        if set(rs)!=set(['bm25_full','dense_full']+[f'seed{s}/{a}' for s in (41,47,53) for a in ('residual','safe_two')]):raise ValueError('modified arm inventory')
        for arr in rs.values():
            if not isinstance(arr,list) or len(arr)!=3 or len(set(arr))!=3 or any(not isinstance(i,str) for i in arr):raise ValueError('malformed evidence ids')
        for seed in (41,47,53):
            a=rs[f'seed{seed}/residual'];b=rs[f'seed{seed}/safe_two'];c=counters[str(seed)]
            if a!=b:c['ordered']+=1
            if set(a)!=set(b):
                c['membership']+=1
                selected.setdefault(qid,[]).append(seed)
    return counters,selected

def prepare(prediction_file,source_file,out):
    p=read_exact(prediction_file,PRED_SHA)
    s=read_exact(source_file,SOURCE_SHA)
    if s.get('source_contains_publisher_gold') is not False or s.get('production_authorized') is not False or len(s.get('families',{}))!=10:raise ValueError('source packet not original source-only')
    count,selected=disagreement_inventory(p)
    if count!={'41':{'ordered':68,'membership':3},'47':{'ordered':7,'membership':0},'53':{'ordered':46,'membership':1}} or len(selected)!=3 or sum(map(len,selected.values()))!=4:
        raise ValueError('source first exhaustive selection changed; do not silently select others')
    requests={};choices=[]
    for qid,seeds in sorted(selected.items()):
        fam=qid.split('/')[0];f=s['families'][fam]
        passages={x['id']:x['text'] for x in f['passages']}
        questions={q['id']:q['text'] for q in f['questions']}
        if qid not in questions or not isinstance(questions[qid],str) or not questions[qid].strip():raise ValueError('missing original question')
        for seed in seeds:
            routes={'bm25_full':p['predictions'][qid]['bm25_full'], 'safe_two':p['predictions'][qid][f'seed{seed}/safe_two'], 'residual':p['predictions'][qid][f'seed{seed}/residual']}
            for arm,ids in routes.items():
                if not all(i in passages and isinstance(passages[i],str) and passages[i].strip() for i in ids):raise ValueError('absent original passage')
                prompt='<|im_start|>system\nAnswer only from numbered evidence. If not supported, reply unknown. Cite supporting evidence using [E1], [E2] or [E3].<|im_end|>\n<|im_start|>user\nQuestion: '+questions[qid]+'\n' + '\n'.join(f'[E{i+1}] {passages[k]}' for i,k in enumerate(ids))+'\n<|im_end|>\n<|im_start|>assistant\n'
                id_=sha256(prompt.encode()).hexdigest()
                if id_ in requests and requests[id_]['prompt']!=prompt:raise ValueError('hash collision')
                requests.setdefault(id_,dict(case_id=qid,prompt=prompt,source_ids=ids,question_sha256=sha256(questions[qid].encode()).hexdigest()))
                choices.append(dict(case_id=qid,seed=seed,arm=arm,request_id=id_))
    data=dict(schema=SCHEMA+'.source-plan',source_sha256=SOURCE_SHA,prediction_sha256=PRED_SHA,original_reader_sha256=MODEL_WEIGHT_SHA,
              selected_source_only_no_labels=True,selected_case_count=len(selected),membership_events=4,census=count,choices=choices,requests=requests,
              publisher_gold_present=False,future_calendar_windows=0,production_authorized=False)
    write_new(out,data)
    return data

def perform(plan_file,reader_root,out,*,max_tokens=18):
    from v12_reader_runtime import OriginalCandidateLlama,OriginalCandidateBPE,check_original,file_sha
    p=read_exact(plan_file)
    if p['schema']!=SCHEMA+'.source-plan' or p['publisher_gold_present'] is not False or p['membership_events']!=4 or len(p['requests'])>12 or p['selected_case_count']!=3:raise ValueError('plan not precommitted')
    check_original(reader_root)
    tok=OriginalCandidateBPE(reader_root)
    torch=__import__('torch');torch.set_num_threads(2)
    reader=OriginalCandidateLlama(reader_root)
    results={};t0=time.process_time();t1=time.perf_counter()
    for id_,q in sorted(p['requests'].items()):
        if sha256(q['prompt'].encode()).hexdigest()!=id_:raise ValueError('source plan tamper')
        ids=tok.encode(q['prompt'])
        if len(ids)>1006:raise ValueError('original input too long')
        start=time.process_time()
        output_ids=reader.generate(ids,max_tokens=max_tokens)
        answer=tok.decode(output_ids)
        results[id_]=dict(case_id=q['case_id'],source_ids=q['source_ids'],original_prompt_sha256=id_,
                          original_text=answer,output_ids=output_ids,original_text_sha256=sha256(answer.encode()).hexdigest(),
                          input_tokens=len(ids),output_tokens=len(output_ids),cpu_seconds=time.process_time()-start)
    outcome=dict(schema=SCHEMA+'.original-answers',source_plan_sha256=hash_file(plan_file),weights_sha256=MODEL_WEIGHT_SHA,
                 tokenizer_sha256=file_sha(tok.root/'tokenizer.json'),
                 actual_completed_reader_requests=len(results),physical_forward_calls=reader.calls,
                 original_answers=results,reader_manual_operator_HF_parity_verified=False,
                 semantic_answer_correctness=None,isolated_original_model_execution=True,
                 cpu_seconds=time.process_time()-t0,wall_seconds=time.perf_counter()-t1,production_authorized=False)
    write_new(out,outcome);return outcome

def score(plan_file,answers_file,original_gold_file,out):
    """After sealed model answers, open independent original publisher weak evidence."""
    p=read_exact(plan_file);a=read_exact(answers_file)
    if a.get('schema')!=SCHEMA+'.original-answers' or a.get('source_plan_sha256')!=hash_file(plan_file):raise ValueError('original answers do not match plan')
    if set(a['original_answers'])!=set(p['requests']) or a['actual_completed_reader_requests']!=len(p['requests']):raise ValueError('missing or altered original answer')
    for key,row in a['original_answers'].items():
        if (row['original_prompt_sha256']!=key or row['case_id']!=p['requests'][key]['case_id']
            or row['source_ids']!=p['requests'][key]['source_ids']
            or row['original_text_sha256']!=sha256(row['original_text'].encode()).hexdigest()
            or type(row['input_tokens'])!=int or row['input_tokens']<1
            or type(row['output_tokens'])!=int or not 1<=row['output_tokens']<=18
            or type(row['output_ids'])!=list or len(row['output_ids'])!=row['output_tokens']
            or any(type(k)!=int or not 0<=k<49152 for k in row['output_ids'])):raise ValueError('original answer corrupt')
    original=read_exact(original_gold_file)
    qa={str(c['sample_id'])+f'/q{i}':q for c in original for i,q in enumerate(c['qa'])}
    groups={};choice_rows=[]
    for c in p['choices']:
        id_=c['request_id'];key=c['case_id']; evidence=qa[key].get('evidence',[])
        # Some publisher annotations are ambiguous; this is exact reference matching only.
        if not isinstance(evidence,list):evidence=[]
        source_ids=a['original_answers'][id_]['source_ids'];hits=len(set(evidence).intersection(source_ids))
        choice_rows.append(dict(seed=c['seed'],arm=c['arm'],case_id=key,publisher_any_annotated_source_in_top3=hits>0,
                                raw_answer_sha256=a['original_answers'][id_]['original_text_sha256']))
        groups.setdefault((key,c['seed']),{})[c['arm']]=id_
    paired=[]
    for (qid,seed),group in sorted(groups.items()):
        if set(group)!={'bm25_full','safe_two','residual'}:raise ValueError('missing exact 3-arm contrast')
        r=a['original_answers'];left=r[group['residual']];cheap=r[group['safe_two']]
        paired.append(dict(case_id=qid,seed=seed,evidence_set_changed=set(left['source_ids'])!=set(cheap['source_ids']),
                           original_answer_bytes_changed=left['original_text']!=cheap['original_text'],
                           input_tokens_residual=left['input_tokens'],input_tokens_control=cheap['input_tokens']))
    if len(paired)!=4 or any(not v['evidence_set_changed'] for v in paired):raise ValueError('not exhaustive physical comparisons')
    return_data=dict(schema=SCHEMA+'.postseal-negative',source_plan_sha256=hash_file(plan_file),original_answers_sha256=hash_file(answers_file),
            original_gold_sha256=hash_file(original_gold_file),unique_original_cases=3,original_membership_events=4,
            independent_source_roots=len({q['case_id'].split('/')[0] for q in choice_rows}),
            real_original_reader_calls=a['actual_completed_reader_requests'],
            original_reader_input_tokens=sum(v['input_tokens'] for v in a['original_answers'].values()),
            original_reader_output_tokens=sum(v['output_tokens'] for v in a['original_answers'].values()),
            residual_vs_cheap_changed_answers=sum(v['original_answer_bytes_changed'] for v in paired),
            residual_vs_cheap_membership_contrasts=4,
            any_publisher_weak_source_hit_rows=sum(v['publisher_any_annotated_source_in_top3'] for v in choice_rows),
            individual_human_semantic_answer_correctness=None,independent_future_calendar_windows=0,
            equal_total_compute=False,pretrained_operator_HF_parity_verified=False,full_task_superiority_verified=False,
            head_specific_incremental_success_verified=False,production_authorized=False,paired=paired)
    write_new(out,return_data);return return_data

if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='stage',required=True)
    s=sub.add_parser('prepare');s.add_argument('--predictions',required=True);s.add_argument('--source',required=True);s.add_argument('--out',required=True)
    s=sub.add_parser('run');s.add_argument('--plan',required=True);s.add_argument('--reader-root',required=True);s.add_argument('--out',required=True)
    s=sub.add_parser('score');s.add_argument('--plan',required=True);s.add_argument('--original-answers',required=True);s.add_argument('--gold',required=True);s.add_argument('--out',required=True)
    args=parser.parse_args()
    if args.stage=='prepare':data=prepare(args.predictions,args.source,args.out)
    elif args.stage=='run':data=perform(args.plan,args.reader_root,args.out)
    else:data=score(args.plan,args.original_answers,args.gold,args.out)
    print(json.dumps({k:v for k,v in data.items() if k not in ('requests','choices','original_answers','paired')},sort_keys=True))
