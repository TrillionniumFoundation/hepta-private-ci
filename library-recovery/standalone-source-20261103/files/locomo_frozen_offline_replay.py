"""Independent label-blind replay of the pinned 10-family LoCoMo source-only retrieval.

Three subprocess stages: retrieve(PUBLIC ZIP), select(PUBLIC ZIP + decisions +
selection targets), evaluate(PUBLIC ZIP + sealed policy + evaluation targets).
No model weights, no answer generation, no future-source or semantic claims.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import os
import zipfile

SOURCE_SHA = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
COMMIT = 'fcc24ad653700ad5f47f09350cf7815242dc5de8'
POP_SHA = 'f53ee0986825f30ec4503b1698639e230832d1c05351c689cb55ebdc4f01d6de'
HIST_SHA = 'b42a90e01df2eb8d2da8a77e6218dc1124b7c19005f52d23ef8c1acd0aeed5cc'
ARMS = ('lexical_k2','lexical_k4','lexical_k8','recent_k2','recent_k4','recent_k8')
SPLITS = ('train','selection','evaluation')
WORD = re.compile(r'[a-z0-9]+')

def canonical(v):
    return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()

def sha(v):return hashlib.sha256(v).hexdigest()
def digest(v):return sha(canonical(v))
def read_bytes(p,max_bytes=32*1024*1024):
    p=Path(p)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>max_bytes:raise ValueError('unbounded or linked file')
    return p.read_bytes()
def strict_json(raw):
    def no_dupes(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate key')
            d[k]=v
        return d
    return json.loads(raw, object_pairs_hook=no_dupes,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
def zip_file(path,name,expected=None):
    with zipfile.ZipFile(path) as z:
        fs=z.infolist()
        if any(v.is_dir() or v.filename.startswith('/') or '..' in Path(v.filename).parts or v.file_size>10*1024*1024 for v in fs):raise ValueError('unsafe ZIP member')
        if len({v.filename for v in fs})!=len(fs):raise ValueError('duplicate ZIP entry')
        if name not in z.namelist():raise ValueError('missing member '+name)
        data=z.read(name)
    if expected and sha(data)!=expected:raise ValueError('source pin mismatch: '+name)
    return data

def read_public(path):
    with zipfile.ZipFile(path) as z:
        if set(z.namelist())!={'histories.jsonl','histories-manifest.json','population.json'}:raise ValueError('public census')
    pop=strict_json(zip_file(path,'population.json',POP_SHA))
    man=strict_json(zip_file(path,'histories-manifest.json'))
    blob=zip_file(path,'histories.jsonl',HIST_SHA)
    if pop['schema']!='hepta.memorycell.locomo-family-only-pilot.v1' or pop['source_sha256']!={'locomo':SOURCE_SHA} or pop['generating_source_commit']!=COMMIT or pop['model_input_contains_answers'] is not False or pop['production_accepted'] is not False:raise ValueError('public source or contract drift')
    if man['original_source_sha256']!=SOURCE_SHA or man['source_commit']!=COMMIT or man['population_sha256']!=POP_SHA or man['histories_sha256']!=HIST_SHA or man['target_file_in_reader_inputs'] is not False:raise ValueError('manifest drift')
    docs=[strict_json(x) for x in blob.splitlines()]
    if len(docs)!=5882 or man['original_document_count']!=5882:raise ValueError('history census drift')
    byid={d['identity']:d for d in docs}
    if len(byid)!=len(docs):raise ValueError('duplicate original source')
    qids=[]; families={}; roots={}
    for split in SPLITS:
        for q in pop['splits'][split]:
            fid=q['family_proxy_digest'];qids.append(q['question_id']);families.setdefault(split,set()).add(fid)
            sources=[byid[key] for key in q['source_ids']]
            if len(sources)!=len(q['source_ids']) or len({d['identity'] for d in sources})!=len(sources) or any(d['scope']!=q['scope'] for d in sources):raise ValueError('source count/scope drift')
            census=[(d['identity'],d['root'],d['observed_at'],sha(d['content'].encode())) for d in sources]
            if digest(census)!=q['source_census_sha256'] or digest(sorted({d['root'] for d in sources}))!=q['source_roots_digest']:raise ValueError('content identity drift')
            for d in sources:
                if d['root'] in roots and roots[d['root']]!=split:raise ValueError('root cross-family leak')
                roots[d['root']]=split
    if len(set(qids))!=80 or {k:len(families[k]) for k in SPLITS}!={'train':6,'selection':2,'evaluation':2} or len(set.union(*families.values()))!=10:raise ValueError('family split/census drift')
    return pop,byid

def observed_time(value):
    for fmt in ('%Y/%m/%d (%a) %H:%M','%I:%M %p on %d %B, %Y'):
        try:return datetime.strptime(value,fmt).replace(tzinfo=timezone.utc)
        except (TypeError,ValueError):pass
    try:
        d=datetime.fromisoformat(value.replace('Z','+00:00'))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    except (ValueError,TypeError,AttributeError):raise ValueError('unknown time '+str(value))

def rank(q,docs):
    lengths=[len(WORD.findall(d['content'].lower())) for d in docs]
    counts=[Counter(WORD.findall(d['content'].lower())) for d in docs]
    n=len(docs);avgdl=sum(lengths)/n
    terms=set(WORD.findall(q['question'].lower()))
    df={t:sum(t in count for count in counts) for t in terms}
    scores=[]
    for d,cnt,length in zip(docs,counts,lengths):
        s=0.
        for term in terms:
            tf=cnt[term]
            if tf:
                idf=math.log1p((n-df[term]+0.5)/(df[term]+0.5))
                s+=idf*tf*2.2/(tf+1.2*(0.25+0.75*length/max(avgdl,1)))
        scores.append((s,d['identity']))
    lexical=[key for _,key in sorted(scores,key=lambda x:(-x[0],x[1]))]
    recent=[d['identity'] for d in sorted(docs,key=lambda d:(observed_time(d['observed_at']),d['identity']),reverse=True)]
    return lexical,recent

def create(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())

def recreate(public_zip):
    pop,byid=read_public(public_zip)
    out=[]
    for split in SPLITS:
        for row in pop['splits'][split]:
            docs=[byid[k] for k in row['source_ids']]
            lex,rec=rank(row,docs)
            for arm in ARMS:
                chosen=(lex if arm.startswith('lexical') else rec)[:int(arm.rsplit('k',1)[1])]
                out.append(dict(question_id=row['question_id'],split=split,family_proxy_digest=row['family_proxy_digest'],source_census_sha256=row['source_census_sha256'],arm=arm,selected=chosen,selected_source_bytes=sum(len(byid[s]['content'].encode()) for s in chosen)))
    if len(out)!=480 or len({(r['question_id'],r['arm']) for r in out})!=480:raise ValueError('decision census missing')
    raw=b''.join(canonical(row)+b'\n' for row in out)
    return pop,out,raw

def get_decisions(public_zip,decision_dir):
    pop,expected,raw=recreate(public_zip)
    written=read_bytes(Path(decision_dir)/'decisions.jsonl',max_bytes=16*1024*1024)
    receipt=strict_json(read_bytes(Path(decision_dir)/'receipt.json'))
    if written!=raw or receipt['original_decisions_sha256']!=sha(raw) or receipt['labels_opened'] is not False or receipt['model_generations']!=0 or receipt['population_sha256']!=POP_SHA:raise ValueError('frozen choices invalid')
    return pop,expected,receipt

def score_split(pop,decisions,split,targets):
    questions=pop['splits'][split]
    if set(targets)!={x['question_id'] for x in questions}:raise ValueError('wrong private target partition')
    lookup={(x['question_id'],x['arm']):x for x in decisions};results={}
    for arm in ARMS:
        valid_count=covered=unknown=total_bytes=0;families={}
        for q in questions:
            t=targets[q['question_id']];selected=lookup[(q['question_id'],arm)]
            total_bytes+=selected['selected_source_bytes']
            fam=families.setdefault(q['family_proxy_digest'],dict(eligible=0,covered=0))
            if not isinstance(t.get('support'),list) or type(t.get('unanswerable')) is not bool or not isinstance(t.get('unresolved_support'),list):raise ValueError('target shape')
            valid=bool(t['support']) and not t['unanswerable'] and not t['unresolved_support']
            if valid:
                valid_count+=1;fam['eligible']+=1
                if set(t['support']).issubset(selected['selected']):covered+=1;fam['covered']+=1
            else:unknown+=1
        results[arm]=dict(planned=len(questions),eligible=valid_count,full_annotated_support_covered=covered,unknown_or_unanswerable=unknown,selected_source_bytes=total_bytes,per_family=families,missing_outcome_lower=covered/len(questions),missing_outcome_upper=(covered+unknown)/len(questions))
    return results

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='phase',required=True)
    pre=sub.add_parser('retrieve');pre.add_argument('public_zip');pre.add_argument('output_dir')
    sel=sub.add_parser('select');sel.add_argument('public_zip');sel.add_argument('decision_dir');sel.add_argument('selection_target_zip');sel.add_argument('policy_file')
    ev=sub.add_parser('evaluate');ev.add_argument('public_zip');ev.add_argument('decision_dir');ev.add_argument('policy_file');ev.add_argument('evaluation_target_zip');ev.add_argument('report_file')
    a=p.parse_args()
    if a.phase=='retrieve':
        pop,decisions,raw=recreate(a.public_zip)
        o=Path(a.output_dir);o.mkdir(parents=True,exist_ok=False)
        create(o/'decisions.jsonl',raw)
        receipt=dict(schema='hepta.memorycell.locomo-frozen-retrieval.v1',generating_commit=COMMIT,population_sha256=POP_SHA,histories_sha256=HIST_SHA,original_decisions_sha256=sha(raw),planned_questions=80,planned_arms=len(ARMS),model_generations=0,labels_opened=False,independent_semantic_judgement=False,production_accepted=False)
        create(o/'receipt.json',canonical(receipt)+b'\n')
        print(json.dumps(receipt,sort_keys=True))
    if a.phase=='select':
        pop,decisions,receipt=get_decisions(a.public_zip,a.decision_dir)
        labels=strict_json(zip_file(a.selection_target_zip,'targets.json'))
        scores=score_split(pop,decisions,'selection',labels)
        chosen=sorted(ARMS,key=lambda arm:(-scores[arm]['full_annotated_support_covered'],scores[arm]['selected_source_bytes'],arm))[0]
        result=dict(schema='hepta.memorycell.locomo-frozen-retrieval.v1',phase='selection',selection_arm=chosen,selection_scores=scores,source_commit=receipt['generating_commit'],retrieval_sha256=receipt['original_decisions_sha256'],selected_before_evaluation_targets_opened=True,heldout_labels_opened=False,model_generations=0,independent_future_family_count=0,production_accepted=False)
        create(a.policy_file,canonical(result)+b'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='selection_scores'},sort_keys=True))
    if a.phase=='evaluate':
        pop,decisions,receipt=get_decisions(a.public_zip,a.decision_dir)
        policy_raw=read_bytes(a.policy_file);policy=strict_json(policy_raw)
        if policy['source_commit']!=COMMIT or policy['retrieval_sha256']!=receipt['original_decisions_sha256'] or policy['heldout_labels_opened'] is not False:raise ValueError('unsealed selection policy')
        labels=strict_json(zip_file(a.evaluation_target_zip,'targets.json'))
        scores=score_split(pop,decisions,'evaluation',labels)
        result=dict(schema='hepta.memorycell.locomo-frozen-retrieval-evaluation.v1',source_sha256=SOURCE_SHA,frozen_source_commit=COMMIT,retrieval_sha256=receipt['original_decisions_sha256'],selection_policy_sha256=sha(policy_raw),chosen_by_selection_only=policy['selection_arm'],evaluation=scores,frozen_choice_on_evaluation=scores[policy['selection_arm']],selected_family_proxies=2,evaluated_family_proxies=2,model_answers_generated=0,independent_future_source_families=0,independent_semantic_judgement=False,production_accepted=False)
        create(a.report_file,canonical(result)+b'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='evaluation'},sort_keys=True))
if __name__=='__main__':main()
