"""Independent bounded re-materialization of V13->V14->V16 original source/requests.

Research-only: uses historical corpus (private on host), never uploads questions,
raw evidence, model weights or model outputs. No neural inference, human review,
training, NDU or activation authority. Comparator hashes are predeclared and
must not be derived from current inputs or altered on failure.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = 'hepta.stem.v21.original-source-independent-plan-rebuild.shadow.v1'
CORPUS_SHA='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
SOURCE_SHA='9d707c297dc743cffe00d94ead04198b7039f72027743dc6d6e02c826a623a8c'
BM25_RANK_SHA='b0b38675d2d5458795d0577d5c861b796dfbdf9e7d4cd089838895c419831697'
V16_PLAN_SHA='26a4d5a4883c98d61d9405f739dda7e49f433370c30290275f0f04441d7067c8'
PRIVATE_ROUTE_SHA='2f8ee6b1a73b63d57f858ad3bcf4f74554952258b8d3649524ecfcfed14e9342'
READER_SHA='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
TOKEN_SHA='9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
READER_CFG_SHA='8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a'
COUNTS={'conv-26':199,'conv-30':105,'conv-41':193,'conv-42':260,'conv-43':242,'conv-44':158,
        'conv-47':190,'conv-48':239,'conv-49':196,'conv-50':204}
HELD=('conv-47','conv-48','conv-49','conv-50')
GROUPS=('literal_in_annotated_source','not_literal_in_annotated_source')
ARMS=('none','retrieved','witness','lesion')
WORDS=re.compile(r'\w+',re.UNICODE)


def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()
def htext(x):return hashlib.sha256(x.encode()).hexdigest()

def read_original(path):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size != 2805274:
        raise ValueError('wrong historical corpus object')
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=CORPUS_SHA: raise ValueError('original LoCoMo corpus bytes mismatch')
    def unique(items):
        obj={}
        for k,v in items:
            if k in obj:raise ValueError('duplicate original JSON key')
            obj[k]=v
        return obj
    return json.loads(raw,object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite original JSON')))

def source_only(original):
    if type(original) is not list or len(original)!=10:raise ValueError('wrong original family count')
    fams={}
    for row in original:
        if type(row) is not dict or row.get('sample_id') not in COUNTS or row['sample_id'] in fams:
            raise ValueError('missing/duplicate original root')
        fam=row['sample_id'];conv=row.get('conversation');qa=row.get('qa')
        if type(conv) is not dict or type(qa) is not list or len(qa)!=COUNTS[fam]:
            raise ValueError('wrong historical episode roster')
        passages=[];questions=[];ids=set()
        for session,turns in conv.items():
            if not re.fullmatch(r'session_\d+',session):continue
            if type(turns) is not list:raise ValueError('invalid session')
            for turn in turns:
                if (type(turn) is not dict or any(type(turn.get(k)) is not str for k in ('speaker','dia_id','text'))
                    or not turn['dia_id'] or turn['dia_id'] in ids or not turn['text'].strip()):
                    raise ValueError('duplicate or changed source turn')
                ids.add(turn['dia_id'])
                passages.append({'id':turn['dia_id'],'text':turn['speaker']+': '+turn['text']})
        if len(passages)<100:raise ValueError('source passages too few')
        for i,q in enumerate(qa):
            if type(q) is not dict or type(q.get('question')) is not str or not q['question'].strip():
                raise ValueError('missing original question')
            questions.append({'id':f'{fam}/q{i}','text':q['question']})
        fams[fam]={'passages':passages,'questions':questions}
    if set(fams)!=set(COUNTS) or sum(len(x['passages']) for x in fams.values())!=5882:
        raise ValueError('original complete source census drift')
    packet={'schema':'hepta.stem.v13.cheap-original-retrieval.shadow.v1.source-only',
            'original_dataset_sha256':CORPUS_SHA,'family_order':sorted(fams), 'families':fams,
            'contains_gold_or_answers':False,'future_windows':0,'production_authorized':False}
    if digest(packet)!=SOURCE_SHA:raise ValueError('independent source feature digest does not match original V13')
    return packet

class BM25:
    """Independently coded V14 BM25Only; stable ID lexicographic ties."""
    def __init__(self,passages):
        if type(passages) is not list or len(passages)<32:raise ValueError('incomplete passages')
        self.passages=passages
        self.tokens=[tuple(x.lower() for x in WORDS.findall(doc['text'])) for doc in passages]
        self.counts=[Counter(row) for row in self.tokens]
        self.document_frequency=Counter(t for row in self.tokens for t in set(row))
        self.average_length=sum(map(len,self.tokens))/len(self.tokens)
        self.idf={t:math.log1p((len(self.tokens)-n+0.5)/(n+0.5))
                  for t,n in self.document_frequency.items()}

    def top32(self,question):
        words=set(w.lower() for w in WORDS.findall(question))
        if not words:raise ValueError('blank original query')
        ranking=[]
        for i,tf in enumerate(self.counts):
            denom_base=1.2*(.25+.75*len(self.tokens[i])/self.average_length)
            score=sum(self.idf.get(t,0.)*(f*2.2)/(f+denom_base) for t in words
                      if (f:=tf.get(t,0))>0)
            if not math.isfinite(score):raise ValueError('nonfinite BM25')
            ranking.append((-score,self.passages[i]['id']))
        ranking.sort()
        return [ident for _,ident in ranking[:32]]


def source_routes(source):
    rows=[]
    for fam in source['family_order']:
        data=source['families'][fam]
        idx=BM25(data['passages'])
        for question in data['questions']:
            rows.append({'id':question['id'],'family':fam,'top32':idx.top32(question['text'])})
    if len(rows)!=1986 or digest(rows)!=BM25_RANK_SHA:
        raise ValueError('independent 1986-query BM25 route parity FAILED')
    packet={'schema':'hepta.stem.v14.original-primary-single-arm-cost.shadow.v1.private-routes',
            'profile':'bm25_only','source_sha256':SOURCE_SHA,
            'rank_sha256':BM25_RANK_SHA,'rows':rows,'gold_present':False}
    if digest(packet)!=PRIVATE_ROUTE_SHA:raise ValueError('original private route envelope differs')
    return packet


def prompt(question, ids, docs):
    if (type(ids) is not list or len(ids)>3 or len(ids)!=len(set(ids)) or
        any(i not in docs for i in ids)):
        raise ValueError('source inclusion invalid')
    instructions=('Answer only from numbered evidence. If not supported, reply unknown. '
                  'Cite supporting evidence using [E1], [E2] or [E3].')
    return ('<|im_start|>system\n'+instructions+'<|im_end|>\n'
            '<|im_start|>user\nQuestion: '+question+'\n'
            +'\n'.join(f'[E{k+1}] {docs[src]}' for k,src in enumerate(ids))
            +'\n<|im_end|>\n<|im_start|>assistant\n')

def _literal(q,text):
    answer=q.get('answer')
    if type(answer) is not str:return False
    answer=answer.strip()
    return (len(answer)>=4 and answer.casefold() not in {'yes','no','true','false','none','unknown'}
            and any(ch.isalpha() for ch in answer) and answer.casefold() in text.casefold())

def v16_requests(source,routes,original):
    original_by_id={x['sample_id']:x for x in original}
    lookup={x['id']:x for x in routes['rows']}
    requests={};cases=[]
    for fam in HELD:
        docs={x['id']:x['text'] for x in source['families'][fam]['passages']}
        questions={x['id']:x['text'] for x in source['families'][fam]['questions']}
        pools={g:[] for g in GROUPS}
        for i,q in enumerate(original_by_id[fam]['qa']):
            cid=f'{fam}/q{i}'
            evidence=q.get('evidence')
            if type(evidence) is not list or len(evidence)!=1 or type(evidence[0]) is not str:continue
            witness=evidence[0]
            if witness not in docs or witness in lookup[cid]['top32'][:3]:continue
            group=GROUPS[0] if _literal(q,docs[witness]) else GROUPS[1]
            pools[group].append((cid,witness))
        for group in GROUPS:
            chosen=sorted(pools[group],key=lambda x:(htext(x[0]),x[0]))[:4]
            if len(chosen)!=4:raise ValueError('missing 4 per family/cohort')
            for cid,witness in chosen:
                top=lookup[cid]['top32'][:3]
                arm_sources={'none':[],'retrieved':list(top),
                             'witness':[witness,top[0],top[1]],'lesion':[top[0],top[1]]}
                arms={}
                for arm in ARMS:
                    sources=arm_sources[arm]
                    text=prompt(questions[cid],sources,docs)
                    rid=htext(text)
                    if rid in requests:raise ValueError('duplicate original source-bound prompt')
                    requests[rid]={'case_id':cid,'family':fam,'arm':arm,'prompt':text,
                                   'source_ids':sources,'question_sha256':htext(questions[cid])}
                    arms[arm]={'request_id':rid,'evidence_ids':sources}
                cases.append({'id':cid,'family':fam,'cohort':group,'witness_id':witness,'arms':arms})
    plan={'schema':'hepta.stem.v16.original-literal-answer-witness.shadow.v1.answer-dependent-precommitted-plan',
          'source_sha256':digest(source),'bm25_routes_sha256':digest(routes),
          'dataset_sha256':CORPUS_SHA,'reader_sha256':READER_SHA,
          'tokenizer_sha256':TOKEN_SHA,'reader_config_sha256':READER_CFG_SHA,
          'frozen_arms':list(ARMS),'source_roots':list(HELD),
          'answer_dependent_historical_selection':True,
          'label_text_entered_model_prompts':False,
          'literal_containment_not_human_sufficiency':True,
          'independent_semantic_adjudication':False,
          'candidate_only_reader':True,'stronger_reference_reader_executed':False,
          'calendar_future_windows':0,'production_authorized':False,
          'max_new_tokens':24,'cases':cases,'requests':requests}
    if len(cases)!=32 or len(requests)!=128 or digest(plan)!=V16_PLAN_SHA:
        raise ValueError('original V16 128-request plan SHAs mismatch')
    return plan


def rebuild(original_path):
    original=read_original(original_path)
    source=source_only(original)
    ranks=source_routes(source)
    plan=v16_requests(source,ranks,original)
    return {'schema':SCHEMA, 'sha256_original_corpus':CORPUS_SHA,
            'sha256_source_only':digest(source), 'sha256_rank_rows':digest(ranks['rows']),
            'sha256_private_routes':digest(ranks),'sha256_v16_plan':digest(plan),
            'original_family_count':10,'source_turn_count':5882,'question_count':1986,
            'historical_roots':4,'original_v16_questions':32,'reference_requests_prepared':128,
            'reader_model_forwards_executed':0,'reference_model_forwards_executed':0,
            'publisher_answer_dependent_historical_selection':True,
            'human_verified_sufficiency':False,'independent_semantic_correctness':None,
            'production_authorized':False,'decision':'SOURCE_RECONSTRUCTION_ONLY_HOLD_NO_GO'},source,ranks,plan


def verify_public_receipt(receipt):
    # Public source-only workflow can check only this frozen, redacted receipt.
    # It does NOT re-open the original corpus or attest the original producer.
    expected={
        'schema':SCHEMA,'sha256_original_corpus':CORPUS_SHA,
        'sha256_source_only':SOURCE_SHA,'sha256_rank_rows':BM25_RANK_SHA,
        'sha256_private_routes':PRIVATE_ROUTE_SHA,'sha256_v16_plan':V16_PLAN_SHA,
        'original_family_count':10,'source_turn_count':5882,'question_count':1986,
        'historical_roots':4,'original_v16_questions':32,'reference_requests_prepared':128,
        'reader_model_forwards_executed':0,'reference_model_forwards_executed':0,
        'publisher_answer_dependent_historical_selection':True,
        'human_verified_sufficiency':False,'independent_semantic_correctness':None,
        'production_authorized':False,'decision':'SOURCE_RECONSTRUCTION_ONLY_HOLD_NO_GO',
    }
    if (type(receipt) is not dict or set(receipt)!=set(expected) or
        any(type(receipt[k]) is not type(v) or receipt[k] != v for k,v in expected.items())):
        raise ValueError('published original data plan report changed or overclaims')
    return {'status':'PUBLIC_DIGEST_PROFILE_ONLY_NOT_PHYSICAL_ATTESTATION',
            'reference_reader_executed':False,'production_authorized':False}

def main():
    ap=argparse.ArgumentParser()
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--original')
    group.add_argument('--public-receipt')
    ap.add_argument('--receipt')
    ap.add_argument('--private-source')
    ap.add_argument('--private-routes')
    ap.add_argument('--private-plan')
    x=ap.parse_args()
    if x.public_receipt:
        if any((x.receipt,x.private_source,x.private_routes,x.private_plan)):
            raise ValueError('public audit must not write private material')
        raw=Path(x.public_receipt).read_bytes()
        if len(raw)>8192:raise ValueError('unbounded public aggregate')
        def no_duplicates(pairs):
            data={}
            for k,v in pairs:
                if k in data:raise ValueError('duplicated public result key')
                data[k]=v
            return data
        result=json.loads(raw,object_pairs_hook=no_duplicates,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite public summary')))
        print(json.dumps(verify_public_receipt(result),sort_keys=True))
        return
    receipt,source,ranks,plan=rebuild(x.original)
    # Real source outputs are private and should never be logged or versioned.
    for output,payload in ((x.private_source,source),(x.private_routes,ranks),(x.private_plan,plan)):
        if output is None:continue
        from v17_reference_reader_physical import write_private
        write_private(output,payload)
    if x.receipt:
        from v17_reference_reader_physical import write_private
        write_private(x.receipt,receipt)
    print(json.dumps(receipt,sort_keys=True))

if __name__=='__main__':main()
