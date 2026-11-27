"""V17 ten-original-root LoCoMo source-first Reader diagnostic, research only.

Separate public question/utterance material, restricted publisher truth, and
annotation-only evidence IDs. No answer text is passed to physical Reader.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

SCHEMA='hepta.v17.original-locomo-reader.shadow.v1'
CORPUS_SHA='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
ARCHIVE_SHA='07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af'
ROOTS=('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44','conv-47','conv-48','conv-49','conv-50')
N_PER_ROOT=3
ARMS=('none','retrieved','annotated','lesion')
OUTPUT_CAP=24
WORDS=re.compile(r"[\w]+(?:['’][\w]+)?",re.UNICODE)
STOP=set('a an the of in on by to for from and or is are was were as that which what where when who how whose with at did does do have has had it its this those these their he she his her they but about after before been being than more most'.split())


def canon(x):
    return json.dumps(x,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')


def digest(x):return hashlib.sha256(canon(x)).hexdigest()


def sha_text(x):return hashlib.sha256(x.encode('utf-8')).hexdigest()


def sha_file(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def deny_pairs(pairs):
    o={}
    for k,v in pairs:
        if k in o:raise ValueError('duplicate JSON key')
        o[k]=v
    return o


def read(p):
    p=Path(p)
    if not p.is_file() or p.is_symlink() or not 0<p.stat().st_size<12_000_000:
        raise ValueError('missing, symlinked or oversized source')
    return json.loads(p.read_bytes(),object_pairs_hook=deny_pairs,
                      parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write_once(p,x):
    p=Path(p)
    p.parent.mkdir(parents=True,exist_ok=True)
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,'O_NOFOLLOW'):flags|=os.O_NOFOLLOW
    with os.fdopen(os.open(p,flags,0o600),'wb') as f:
        f.write(canon(x)+b'\n');f.flush();os.fsync(f.fileno())


def tokens(s):
    return [w.casefold() for w in WORDS.findall(s) if len(w)>1 and w.casefold() not in STOP]


def material(raw):
    if type(raw) is not list or len(raw)!=10:raise ValueError('missing original ten conversations')
    public=[];hidden={};seen=set()
    for family in raw:
        fid=family.get('sample_id')
        if fid not in ROOTS or fid in seen:raise ValueError('bad family identity')
        seen.add(fid)
        conv=family.get('conversation');qas=family.get('qa')
        if type(conv) is not dict or type(qas) is not list or len(qas)<50:raise ValueError('missing source')
        utterances=[]; ids=set()
        for key,value in conv.items():
            if not (key.startswith('session_') and type(value) is list):continue
            for line in value:
                if type(line) is not dict:raise ValueError('bad utterance')
                aid=line.get('dia_id');txt=line.get('text');who=line.get('speaker')
                if (type(aid) is not str or aid in ids or type(txt) is not str
                        or type(who) is not str or not txt.strip()):raise ValueError('unstable original dialogue source')
                ids.add(aid)
                utterances.append(dict(id=aid,speaker=who,text=txt))
        if len(utterances)<100:raise ValueError('underfilled original source history')
        questions=[]; hidden[fid]={}
        for index,q in enumerate(qas):
            if type(q) is not dict or type(q.get('question')) is not str or not q['question'].strip():
                raise ValueError('bad original question')
            qid=f'{fid}/q{index}'
            questions.append(dict(id=qid,question=q['question']))
            answer=q.get('answer');evidence=q.get('evidence')
            if (type(answer) not in (str,int,float) and answer is not None) or type(evidence) is not list:
                raise ValueError('unreviewable publisher annotation')
            if any(type(s) is not str for s in evidence):
                raise ValueError('untyped publisher annotation')
            hidden[fid][qid]=dict(answer=answer,support_ids=evidence,category=q.get('category'))
        public.append(dict(id=fid,utterances=utterances,questions=questions))
    if seen!=set(ROOTS):raise ValueError('missing original dialogue root')
    return public,hidden


def prepare(source_path,directory):
    if sha_file(source_path)!=CORPUS_SHA:raise ValueError('original LoCoMo SHA differs')
    public,hidden=material(read(source_path))
    output=Path(directory)
    output.mkdir(parents=True,exist_ok=False)
    owner=dict(schema=SCHEMA+'.owner',source_sha256=CORPUS_SHA,archive_sha256=ARCHIVE_SHA,
               public_sha256=digest(public),hidden_sha256=digest(hidden),roots=list(ROOTS),
               publisher_answers_not_in_public=True,source_first_selection=True,
               source_time_prospective=False,model_selected=False,authority='DENY_ALL',
               production_accepted=False)
    write_once(output/'public.json',public)
    write_once(output/'hidden.json',hidden)
    write_once(output/'owner.json',owner)
    return owner


def select(public,owner):
    if (type(public) is not list or len(public)!=10 or type(owner) is not dict
            or owner.get('schema')!=SCHEMA+'.owner' or owner.get('public_sha256')!=digest(public)
            or owner.get('source_sha256')!=CORPUS_SHA or owner.get('archive_sha256')!=ARCHIVE_SHA
            or owner.get('roots')!=list(ROOTS) or owner.get('authority')!='DENY_ALL'
            or owner.get('production_accepted') is not False):raise ValueError('unfrozen root/source owner')
    ids=[]
    for row in public:
        if row['id'] not in ROOTS or type(row['questions']) is not list:
            raise ValueError('bad public root')
        for q in row['questions']:
            if type(q) is not dict or set(q)!={'id','question'}:raise ValueError('gold in public')
        chosen=sorted((q['id'] for q in row['questions']),key=lambda i:(sha_text(i),i))[:N_PER_ROOT]
        if len(chosen)!=N_PER_ROOT:raise ValueError('not enough source-first cases')
        ids.extend(chosen)
    return sorted(ids)


def plan(public_path,owner_path,out):
    public,owner=read(public_path),read(owner_path)
    chosen=select(public,owner)
    row=dict(schema=SCHEMA+'.plan',public_sha256=digest(public),owner_sha256=digest(owner),
             original_source_sha256=CORPUS_SHA,case_ids=chosen,n_cases=len(chosen),
             case_selection='sha256_lowest_three_per_original_root_NO_answer_filter',
             source_roots=list(ROOTS),arms=list(ARMS),max_tokens=OUTPUT_CAP,
             model_weight_sha256='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c',
             no_gold_answer_to_model=True,publisher_witness_not_human_certified_sufficient=True,
             source_time_prospective=False,reader_frozen=True,authority='DENY_ALL',production_accepted=False)
    row['plan_sha256']=digest(row)
    write_once(out,row)
    return row


def annotations(public_path,owner_path,hidden_path,plan_path,out):
    public,owner,hidden,p=map(read,(public_path,owner_path,hidden_path,plan_path))
    if (select(public,owner)!=p.get('case_ids') or p.get('plan_sha256')!=digest({k:v for k,v in p.items() if k!='plan_sha256'})
            or owner.get('hidden_sha256')!=digest(hidden) or set(hidden)!=set(ROOTS)):
        raise ValueError('source-first plan or sealed original label mismatch')
    result={}
    for case in p['case_ids']:
        root=case.split('/')[0]
        gold=hidden[root][case]
        ids=gold['support_ids']
        if not ids:raise ValueError('publisher support missing: no witness substitute')
        result[case]=list(dict.fromkeys(ids))[:3]
    packet=dict(schema=SCHEMA+'.annotation-only',source_sha256=digest(public),plan_sha256=p['plan_sha256'],
                original_hidden_sha256=digest(hidden),source_ids=result,answer_fields_exposed=False,
                publisher_witness_not_certified=True,authority='DENY_ALL')
    packet['packet_sha256']=digest(packet)
    write_once(out,packet)
    return packet


def bm25(question,docs):
    q=Counter(tokens(question)); bags=[Counter(tokens(d['text'])) for d in docs]
    n=len(docs); df=Counter(t for b in bags for t in b)
    avg=sum(sum(b.values()) for b in bags)/n or 1.0
    scores=[]
    for b in bags:
        length=sum(b.values())
        scores.append(sum(min(2,occ)*math.log1p((n-df[t]+.5)/(df[t]+.5))
                          *(b[t]*2.2/(b[t]+1.2*(.25+.75*length/avg)))
                          for t,occ in q.items() if b.get(t)))
    return [docs[i]['id'] for i in sorted(range(n),key=lambda i:(-scores[i],docs[i]['id']))]


def prompt(question,ids,source):
    if any('<|im_start|>' in s or '<|im_end|>' in s for s in [question,*[source[x]['text'] for x in ids]]):
        raise ValueError('role delimiter in original conversation')
    body='\n'.join('[E'+str(k)+'] '+i+' '+source[i]['speaker']+': '+source[i]['text'][:240] for k,i in enumerate(ids,1))
    if not body:body='(no evidence provided)'
    return ('<|im_start|>system\nAnswer concisely from provided evidence only. If not supported, say unknown. Cite the evidence [E1], [E2], etc.\n'
            '<|im_end|>\n<|im_start|>user\nQuestion: '+question+'\nEvidence:\n'+body+
            '\n<|im_end|>\n<|im_start|>assistant\n')


def requests(public_path,owner_path,plan_path,annotations_path,out):
    public,owner,p,annot=map(read,(public_path,owner_path,plan_path,annotations_path))
    if (select(public,owner)!=p.get('case_ids') or p.get('plan_sha256')!=digest({k:v for k,v in p.items() if k!='plan_sha256'})
            or p.get('public_sha256')!=digest(public) or p.get('owner_sha256')!=digest(owner)
            or p.get('arms')!=list(ARMS) or p.get('production_accepted') is not False
            or annot.get('source_sha256')!=digest(public) or annot.get('plan_sha256')!=p['plan_sha256']
            or annot.get('packet_sha256')!=digest({k:v for k,v in annot.items() if k!='packet_sha256'})
            or annot.get('answer_fields_exposed') is not False
            or set(annot.get('source_ids',{}))!=set(p['case_ids'])):
        raise ValueError('publisher-answer contamination or changed original plan')
    byfamily={f['id']:f for f in public}
    result={}
    for case in p['case_ids']:
        family=byfamily[case.split('/')[0]]
        docs={d['id']:d for d in family['utterances']}
        question=next(q['question'] for q in family['questions'] if q['id']==case)
        ranked=bm25(question,family['utterances'])
        annotated=annot['source_ids'][case]
        if not 1<=len(annotated)<=3 or any(s not in docs for s in annotated):raise ValueError('forged witness id')
        sources={'none':[],'retrieved':ranked[:3], 'annotated':annotated,'lesion':annotated[1:]}
        for arm,ids in sources.items():
            pp=prompt(question,ids,docs)
            rid=sha_text(pp)
            request_id=case+'|'+arm
            if request_id in result:
                raise ValueError('duplicate logical condition')
            result[request_id]=dict(case_id=case,arm=arm,source_ids=ids,
                             question_sha256=sha_text(question),source_sha256=digest(family),
                             request_sha256=rid,prompt=pp)
    if len(result)!=4*len(p['case_ids']):raise ValueError('incomplete original Reader case arms')
    packet=dict(schema=SCHEMA+'.model-requests',plan_sha256=p['plan_sha256'],public_sha256=digest(public),
                annotation_packet_sha256=annot['packet_sha256'],requests=result,requests_sha256=digest(result),
                publisher_answer_text_never_supplied=True,reader_model_not_executed=True,
                human_witness_sufficiency_unverified=True,authority='DENY_ALL',production_accepted=False)
    write_once(out,packet)
    return packet


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='action',required=True)
    for name,keys in [('prepare',('source','out')),('plan',('public','owner','out')),
                      ('annotate',('public','owner','hidden','plan','out')),
                      ('requests',('public','owner','plan','annotation','out'))]:
        cmd=sub.add_parser(name)
        for k in keys:cmd.add_argument('--'+k,required=True)
    a=parser.parse_args()
    if a.action=='prepare': obj=prepare(a.source,a.out)
    elif a.action=='plan':obj=plan(a.public,a.owner,a.out)
    elif a.action=='annotate':obj=annotations(a.public,a.owner,a.hidden,a.plan,a.out)
    else:obj=requests(a.public,a.owner,a.plan,a.annotation,a.out)
    print(json.dumps({k:v for k,v in obj.items() if k in ('schema','plan_sha256','packet_sha256','requests_sha256','n_cases')}))


if __name__=='__main__':main()
