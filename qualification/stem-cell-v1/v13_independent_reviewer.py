"""Independent postseal original-source recount; no producer scorer imports.

Owner opens original publication labels only after ranked routes are immutable.
Does not establish human semantic correctness, calendar provenance or authority.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

EXPECTED_SOURCE="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
ROOTS={"conv-26":199,"conv-30":105,"conv-41":193,"conv-42":260,"conv-43":242,"conv-44":158,
       "conv-47":190,"conv-48":239,"conv-49":196,"conv-50":204}
TEST=("conv-47","conv-48","conv-49","conv-50")
TEST_BM25={"conv-47":76,"conv-48":124,"conv-49":91,"conv-50":81}
ARMS={"bm25","phrase","coverage","char","phrase_char","char_only"}
WORD=re.compile(r"\w+",re.UNICODE)

def raw_sha(path):
    hh=hashlib.sha256()
    with open(path,'rb') as f:
        for p in iter(lambda:f.read(1<<20),b''):hh.update(p)
    return hh.hexdigest()

def canonical_hash(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,separators=(',',':'),sort_keys=True,allow_nan=False).encode()).hexdigest()

def load(path):
    def strict_pairs(rows):
        d={}
        for k,v in rows:
            if k in d:raise ValueError("duplicate JSON key")
            d[k]=v
        return d
    def fail_nonfinite(x):raise ValueError("nonfinite JSON")
    return json.loads(Path(path).read_bytes(),object_pairs_hook=strict_pairs,parse_constant=fail_nonfinite)

def bm25_independent(query,docs):
    """Original V9 numeric expression, independent of V13 rank producer."""
    rows=[list(map(str.lower,WORD.findall(doc["text"]))) for doc in docs]
    terms=set(map(str.lower,WORD.findall(query)))
    n=len(rows);av=sum(len(x) for x in rows)/n
    df=Counter(); tfs=[]
    for w in rows:
        c=Counter(w);tfs.append(c);df.update(c.keys())
    score=[]
    for i,c in enumerate(tfs):
        den=1.2*(0.25+0.75*len(rows[i])/av)
        score.append(sum(math.log1p((n-df[t]+.5)/(df[t]+.5))*(c[t]*2.2)/(c[t]+den)
                         for t in terms if c[t]>0))
    return [docs[i]["id"] for i in sorted(range(n),key=lambda i:(-score[i],docs[i]["id"]))[:3]]

def audit(*,original,source,plan,routes,report):
    if raw_sha(original)!=EXPECTED_SOURCE:raise ValueError("original dataset substitution")
    corpus=load(original);src=load(source);p=load(plan);r=load(routes);sc=load(report)
    if type(corpus)!=list or len(corpus)!=10 or set(x['sample_id'] for x in corpus)!=set(ROOTS):raise ValueError("corpus roots")
    if type(src)!=dict or src.get("original_dataset_sha256")!=EXPECTED_SOURCE or src.get("contains_gold_or_answers") is not False or src.get("production_authorized") is not False:raise ValueError("source disclosure")
    if type(p)!=dict or p.get("source_sha256")!=canonical_hash(src) or p.get("precommitted_primary")!="phrase_char" or p.get("production_authorized") is not False:raise ValueError("plan identity")
    if type(r)!=dict or r.get("source_sha256")!=canonical_hash(src) or r.get("plan_sha256")!=canonical_hash(p) or r.get("publisher_gold_loaded") is not False or r.get("production_authorized") is not False or r.get("model_forward_count")!=0:raise ValueError("unsealed or misleading routes")
    if type(sc)!=dict or sc.get("source_sha256")!=canonical_hash(src) or sc.get("plan_sha256")!=canonical_hash(p) or sc.get("raw_rank_sha256")!=canonical_hash(r) or sc.get("production_authorized") is not False or sc.get("full_task_superiority_verified") is not False or sc.get("future_calendar_windows")!=0 or sc.get("independent_semantic_qa") is not None:raise ValueError("untrusted score authority")
    source_families=src.get('families');by_family={x['sample_id']:x for x in corpus}
    if type(source_families)!=dict or set(source_families)!=set(ROOTS):raise ValueError("source families")
    expected_ids=set()
    gold={};terms={};doc_set={};doc_arr={}
    for f,orig in by_family.items():
        if len(orig['qa'])!=ROOTS[f]:raise ValueError("question count")
        src_family=source_families[f];docs=src_family['passages'];questions=src_family['questions']
        if len(questions)!=ROOTS[f] or len({d['id'] for d in docs})!=len(docs):raise ValueError("source census")
        dids={d['id'] for d in docs}
        if len(dids)<100:raise ValueError("missing source turns")
        doc_set[f]=dids;doc_arr[f]=docs
        for i,qq in enumerate(questions):
            qid=f+'/q'+str(i)
            if qq.get('id')!=qid or qq.get('text')!=orig['qa'][i]['question']:raise ValueError("source question changed")
            expected_ids.add(qid);terms[qid]=qq['text']
            ev=orig['qa'][i].get('evidence')
            gold[qid]=(set(ev) if type(ev)==list and ev and all(type(x)==str and x in dids for x in ev) else None)
    if len(expected_ids)!=1986 or r.get('case_count')!=1986 or r.get('source_turn_count')!=5882:raise ValueError("source census")
    seen=set();count={f:{arm:0 for arm in ARMS} for f in TEST};gainloss={f:{arm:dict(gain=0,loss=0,membership_changed=0) for arm in ARMS if arm!='bm25'} for f in TEST};nonannotated=0
    train_count={arm:0 for arm in ARMS}
    allcounts={f:{arm:0 for arm in ARMS} for f in TEST}
    longcounts={f:{arm:{16:0,32:0} for arm in ARMS} for f in TEST}
    for row in r.get('cases',[]):
        if type(row)!=dict or set(row)!={'id','family','top32'}:raise ValueError("route shape")
        qid=row['id'];fam=row['family']
        if qid not in expected_ids or qid in seen or not qid.startswith(fam+'/'):raise ValueError("duplicate/missing row")
        seen.add(qid)
        rr=row['top32']
        if type(rr)!=dict or set(rr)!=ARMS:raise ValueError("missing arm")
        for arm,ids in rr.items():
            if type(ids)!=list or len(ids)!=32 or len(set(ids))!=32 or not set(ids).issubset(doc_set[fam]):raise ValueError("missing/aliased source")
        if fam in TEST:
            if rr['bm25'][:3]!=bm25_independent(terms[qid],doc_arr[fam]):raise ValueError("BM25 physical parity mismatch")
        ref=gold[qid]
        if ref is None:
            if fam in TEST:nonannotated+=1
            continue
        bm_hit=bool(ref.intersection(rr['bm25'][:3]))
        for arm,ids in rr.items():
            hit=bool(ref.intersection(ids[:3]))
            if fam in TEST:
                count[fam][arm]+=int(hit)
                allcounts[fam][arm]+=int(ref.issubset(set(ids[:3])))
                for k in (16,32):longcounts[fam][arm][k]+=bool(ref.intersection(ids[:k]))
                if arm!='bm25':
                    gainloss[fam][arm]['gain']+=int(hit and not bm_hit)
                    gainloss[fam][arm]['loss']+=int(bm_hit and not hit)
                    gainloss[fam][arm]['membership_changed']+=int(set(ids[:3])!=set(rr['bm25'][:3]))
            else:train_count[arm]+=int(hit)
    if seen!=expected_ids or nonannotated!=7:raise ValueError("incomplete requests or publisher unknown")
    if {f:count[f]['bm25'] for f in TEST}!=TEST_BM25:raise ValueError("original BM25 floor not reproduced")
    for arm in ARMS:
        observed=sc['per_arm'][arm]
        if observed['heldout_any_hit3']!=sum(count[f][arm] for f in TEST) or observed['train_any_hit3']!=train_count[arm] or observed['heldout_all_hit3']!=sum(allcounts[f][arm] for f in TEST):raise ValueError("fake arm score")
        if observed['heldout_any_hit16']!=sum(longcounts[f][arm][16] for f in TEST) or observed['heldout_any_hit32']!=sum(longcounts[f][arm][32] for f in TEST):raise ValueError("fake long-slot score")
        if observed['family_hit3']!={f:count[f][arm] for f in TEST}:raise ValueError("false family totals")
        if observed['family_delta_vs_bm25']!={f:count[f][arm]-count[f]['bm25'] for f in TEST}:raise ValueError("false family delta")
    for f in TEST:
        for arm in ARMS-{'bm25'}:
            x=sc['per_family_pairwise_vs_bm25'][f][arm]
            d=gainloss[f][arm]
            if x!={'gain_vs_bm25':d['gain'],'loss_vs_bm25':d['loss'],'membership_changed':d['membership_changed']}:
                raise ValueError("false paired family event")
    return {'schema':'hepta.stem.v13.independent-original-source-review.v1',
            'source_sha256':canonical_hash(src),'routes_sha256':canonical_hash(r),
            'score_sha256':canonical_hash(sc), 'original_corpus_sha256':EXPECTED_SOURCE,
            'independent_recounted_questions':1986,'source_independent_heldout_roots':4,
            'rechecked_original_bm25_questions':829,'publisher_unknown_heldout':7,
            'bm25_heldout_hit3':372,
            'primary_heldout_hit3':sum(count[f]['phrase_char'] for f in TEST),
            'per_family_primary_delta':{f:count[f]['phrase_char']-count[f]['bm25'] for f in TEST},
            'semantic_correctness':None,'model_training_executed':False,'production_authorized':False,
            'audit_status':'COUNTS_CONSISTENT_NOT_MODEL_SUPERIORITY'}

def main():
    p=argparse.ArgumentParser()
    for name in ('original','source','plan','routes','report','output'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args()
    result=audit(original=a.original,source=a.source,plan=a.plan,routes=a.routes,report=a.report)
    with Path(a.output).open('x') as f:
        json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
