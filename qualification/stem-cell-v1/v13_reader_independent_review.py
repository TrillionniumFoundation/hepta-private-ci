"""Independent read-only rerecount of 32 original Reader responses, not semantic QA.
This module does not import the V13 Reader producer or original model runtime.
"""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path

CORPUS_SHA='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
MODEL_SHA='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
TOKEN_SHA='9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
SCHEMA='hepta.stem.v13.original-lexical-reader-diagnostic.v1'

def sha_file(path):
    h=sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def canonical(x):return sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def load(path):
    def unique(pairs):
        x={}
        for k,v in pairs:
            if k in x:raise ValueError('duplicate JSON key')
            x[k]=v
        return x
    def no_constant(s):raise ValueError('invalid nonfinite JSON constant')
    return json.loads(Path(path).read_bytes(),object_pairs_hook=unique,parse_constant=no_constant)

def audit(plan_file,original_1,original_2,source_file,registered_file,route_file,gold_file,original_score_file):
    p=load(plan_file);a=load(original_1);b=load(original_2);sc=load(original_score_file)
    if sha_file(gold_file)!=CORPUS_SHA:raise ValueError('original heldout owner changed')
    if p.get('schema')!=SCHEMA+'.source-plan' or p.get('heldout_gold_available_before_generation') is not False or p.get('production_authorized') is not False or p.get('original_reader_model_sha256')!=MODEL_SHA or p.get('original_reader_tokenizer_sha256')!=TOKEN_SHA or p.get('selected_original_cases')!=16 or len(p.get('choices',[]))!=32:
        raise ValueError('reader selection or model changed')
    src=load(source_file);registered=load(registered_file);routes=load(route_file)
    if (p.get('source_sha256')!=canonical(src) or p.get('original_rank_sha256')!=canonical(routes)
        or registered.get('source_sha256')!=canonical(src) or routes.get('plan_sha256')!=canonical(registered)
        or routes.get('source_sha256')!=canonical(src) or routes.get('publisher_gold_loaded') is not False):
        raise ValueError('untrusted source, registered plan or sealed rank')
    selected={f:[] for f in ('conv-47','conv-48','conv-49','conv-50')}
    byid={}
    for row in routes['cases']:
        qid=row['id'];fam=row['family'];byid[qid]=row
        if fam in selected and set(row['top32']['bm25'][:3])!=set(row['top32']['phrase_char'][:3]):
            selected[fam].append(qid)
    expected={f:sorted(selected[f],key=lambda q:(sha256(q.encode()).hexdigest(),q))[:4] for f in selected}
    if p.get('source_only_selection',{}).get('cases_by_family')!=expected:
        raise ValueError('original source-label-blind question selection modified')
    for choice in p['choices']:
        qid=choice['case_id'];rid=choice['request_id'];arm=choice['arm']
        if qid not in expected[choice['family']] or arm not in ('bm25','phrase_char') or p['requests'][rid]['sources']!=byid[qid]['top32'][arm][:3]:
            raise ValueError('original Reader sources detached from ranking')
    if p.get('unique_request_count')!=32 or len(p.get('requests',{}))!=32:
        raise ValueError('source-only complete Reader attempt roster')
    if (a.get('schema')!=SCHEMA+'.original-reader-answers' or b.get('schema')!=SCHEMA+'.original-reader-answers' or
        a.get('source_plan_sha256')!=sha_file(plan_file) or b.get('source_plan_sha256')!=sha_file(plan_file) or
        any(z.get('reader_weights_sha256')!=MODEL_SHA or z.get('reader_tokenizer_sha256')!=TOKEN_SHA or z.get('production_authorized') is not False or z.get('official_HF_model_tokenizer_parity') is not False or z.get('semantic_correctness') is not None for z in (a,b))):
        raise ValueError('changed model-output binding')
    if len(a.get('all_original_raw_answers',{}))!=32 or len(b.get('all_original_raw_answers',{}))!=32:
        raise ValueError('lost original physical attempt')
    normalized1={};normalized2={}
    for packet,target in ((a,normalized1),(b,normalized2)):
        if set(packet['all_original_raw_answers'])!=set(p['requests']) or packet['original_Reader_requests']!=32:
            raise ValueError('wrong request identity')
        for rid,row in packet['all_original_raw_answers'].items():
            orig=p['requests'][rid]
            if set(row)!={'case_id','source_ids','raw_answer','raw_answer_sha256','original_token_ids','input_tokens','output_tokens','cpu_seconds'}:
                raise ValueError('answer fields injected')
            if (orig['case_id']!=row['case_id'] or orig['sources']!=row['source_ids'] or
                row['raw_answer_sha256']!=sha256(row['raw_answer'].encode()).hexdigest() or
                type(row['input_tokens'])!=int or not 1<=row['input_tokens']<=1000 or
                type(row['output_tokens'])!=int or not 1<=row['output_tokens']<=24 or
                type(row['original_token_ids'])!=list or len(row['original_token_ids'])!=row['output_tokens'] or
                any(type(x)!=int or not 0<=x<49152 for x in row['original_token_ids'])):
                raise ValueError('original answer or numeric token modification')
            target[rid]={k:row[k] for k in row if k!='cpu_seconds'}
    if normalized1!=normalized2:raise ValueError('32 original Reader outputs did not reproduce')
    counted_forwards=sum(len(x['original_token_ids'])+(0 if x['original_token_ids'][-1]==2 else 1)
                         for x in normalized1.values())
    if counted_forwards!=a.get('original_Reader_forwards') or counted_forwards!=b.get('original_Reader_forwards'):
        raise ValueError('original Reader forward count does not match emitted tokens')
    if b.get('revalidated_source_file_sha256')!=sha_file(source_file) or b.get('revalidated_rank_file_sha256')!=sha_file(route_file):raise ValueError('latest source Owner not revalidated')
    if sc.get('source_plan_sha256')!=sha_file(plan_file) or sc.get('original_answer_file_sha256')!=sha_file(original_1) or sc.get('source_first_original_cases')!=16 or sc.get('genuine_original_reader_requests')!=32 or sc.get('original_task_semantic_correctness') is not None or sc.get('production_authorized') is not False:raise ValueError('postseal public score modification')
    corpus=load(gold_file)
    qa={f['sample_id']+'/q'+str(i):q for f in corpus for i,q in enumerate(f['qa'])}
    roster={f['sample_id']:{d['dia_id'] for val in f['conversation'].values() if isinstance(val,list) for d in val if isinstance(d,dict) and isinstance(d.get('dia_id'),str)} for f in corpus}
    counts={arm:dict(weak_hits=0,in_tokens=0,out_tokens=0) for arm in ('bm25','phrase_char')}
    perq={}
    for choice in p['choices']:
        qid=choice['case_id'];arm=choice['arm'];rid=choice['request_id'];row=a['all_original_raw_answers'][rid]
        family=qid.split('/')[0]
        refs=qa[qid].get('evidence')
        valid=type(refs)==list and refs and all(type(x)==str and x in roster[family] for x in refs)
        if not valid:raise ValueError('selected original case has ambiguous publisher annotations')
        counts[arm]['weak_hits']+=int(bool(set(refs).intersection(row['source_ids'])))
        counts[arm]['in_tokens']+=row['input_tokens'];counts[arm]['out_tokens']+=row['output_tokens']
        perq.setdefault(qid,{})[arm]=rid
    if len(perq)!=16 or any(set(v)!={'bm25','phrase_char'} for v in perq.values()):raise ValueError('missing matched original questions')
    changed=sum(normalized1[ids['bm25']]['raw_answer']!=normalized1[ids['phrase_char']]['raw_answer'] for ids in perq.values())
    if sc['original_answers_changed_between_routes']!=changed or sc['per_arm']['bm25']['any_weak_support']!=counts['bm25']['weak_hits'] or sc['per_arm']['phrase_char']['any_weak_support']!=counts['phrase_char']['weak_hits']:
        raise ValueError('fabricated postseal paired gain or answer change')
    for arm in counts:
        if sc['per_arm'][arm]['input_tokens']!=counts[arm]['in_tokens'] or sc['per_arm'][arm]['output_tokens']!=counts[arm]['out_tokens']:
            raise ValueError('original Reader token census changed')
    return dict(schema='hepta.stem.v13.original-reader-independent-private-audit.v1',
       source_plan_sha256=sha_file(plan_file), first_original_reader_sha256=sha_file(original_1),
       second_original_reader_sha256=sha_file(original_2), second_source_bounded=True,
       original_reader_answers_reproduced=32, original_reader_tokens_and_text_digest=canonical(normalized1),
       historical_family_roots=4,original_questions=16,original_calls_per_run=32,
       publisher_weak_hits_bm25=counts['bm25']['weak_hits'],
       publisher_weak_hits_primary=counts['phrase_char']['weak_hits'],
       original_changed_answers=changed,
       original_reader_HF_parity=False,semantic_correctness=None,new_future_windows=0,
       production_authorized=False,stem_winner_verified=False,
       status='PRIVATE_ORIGINAL_RECOUNT_NO_GO')

def main():
    import argparse
    p=argparse.ArgumentParser()
    for n in ('plan','original-1','original-2','source','registered','ranked','gold','score','output'):
        p.add_argument('--'+n,required=True)
    a=p.parse_args()
    report=audit(a.plan,a.original_1,a.original_2,a.source,a.registered,a.ranked,a.gold,a.score)
    with Path(a.output).open('x') as f:
        json.dump(report,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps(report,sort_keys=True))
if __name__=='__main__':main()
