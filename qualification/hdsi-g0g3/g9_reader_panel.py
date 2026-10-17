"""G9 original LoCoMo HELD Reader-capacity diagnostic (no trained Cell/NDU gain).

Same G8 24/held-root roster. A frozen original four-question subset per root;
original annotator evidence is provided only for ORACLE / LESION diagnostics.
The producer never receives answer gold. Historically public label-observed source
owner builds the test packet; this is NOT a prospective or source-independent task.
"""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from g8_source import build as g8_build
from g6_coverage_model import bm25_all
from g6_coverage_source import canonical,sha
from real_minilm_reference import CHECKSUMS

ROOTS=('conv-47','conv-48','conv-49','conv-50')
ARMS=('none','bm25','oracle','lesion')
DOM=b'hepta.hdsi.g9.reader-capacity-v1\0'
SCHEMA='hepta.hdsi.g9.original-reader-capacity.v1'


def need(v,m):
    if v is not True:raise ValueError(m)


def digest(x):return hashlib.sha256(DOM+canonical(x)).hexdigest()


def from_original(raw:bytes)->dict:
    need(sha(raw)==CHECKSUMS['locomo.json'],'wrong original LoCoMo bytes')
    public=g8_build(raw)
    originals={r['sample_id']:r for r in json.loads(raw)}
    cases=[]
    for r in public['roots']:
        if r['root'] not in ROOTS:continue
        need(r['split']=='HELD','expected original HELD root')
        qa=originals[r['root']]['qa'];docs={d['id']:d for d in r['docs']}
        choices=r['questions'][:4]
        ranks,_=bm25_all(r['docs'],choices)
        for q,rank in zip(choices,ranks):
            index=int(q['id'][1:]);rec=qa[index]
            need(rec['question']==q['text'],'original question index mismatch')
            ev=rec['evidence']
            need(type(ev) is list and 1<=len(ev)<=12,'original support not bounded')
            support=sorted(set(s for s in ev if isinstance(s,str)))
            need(len(support)>0 and set(support)<=set(docs),'original annotated support not available')
            oracle=[docs[d] for d in support]
            bm25=[r['docs'][i] for i in rank[:5]]
            lesion=oracle[1:]
            cases.append({'id':r['root']+'/'+q['id'],'root':r['root'],'question':q['text'],
                          'question_sha':q['text_sha'],
                          'arms':{arm:[{'id':d['id'],'text':d['text'],'text_sha':d['text_sha']} for d in v]
                                  for arm,v in [('none',[]),('bm25',bm25),('oracle',oracle),('lesion',lesion)]}})
    need(len(cases)==16,'incomplete fixed four-root panel')
    packet={'schema':SCHEMA,'original_sha':CHECKSUMS['locomo.json'],
            'reader_weight_sha':'5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c',
            'source_roster_digest':public['digest'],
            'original_held_roots':list(ROOTS),'four_questions_per_root':4,
            'case_source':'original_g8_question_roster_first4_per_held_root',
            'arms':list(ARMS),'oracle_support_uses_publisher_held_evidence_ids':True,
            'historically_public_not_future':True,
            'original_answers_in_packet':False,'reader_tokenizer_parity_verified':False,
            'research_only':True,'production_authorized':False,'disposition':'HOLD_NO_GO',
            'cases':cases}
    packet['digest']=digest(packet)
    validate(packet)
    return packet


def validate(packet:dict)->None:
    need(type(packet) is dict and set(packet)=={'schema','original_sha','reader_weight_sha',
       'source_roster_digest','original_held_roots','four_questions_per_root','case_source',
       'arms','oracle_support_uses_publisher_held_evidence_ids','historically_public_not_future',
       'original_answers_in_packet','reader_tokenizer_parity_verified','research_only',
       'production_authorized','disposition','cases','digest'},'unknown source field')
    need(packet['schema']==SCHEMA and packet['original_sha']==CHECKSUMS['locomo.json']
         and packet['reader_weight_sha']=='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
         and packet['original_held_roots']==list(ROOTS) and packet['four_questions_per_root']==4
         and packet['case_source']=='original_g8_question_roster_first4_per_held_root'
         and packet['arms']==list(ARMS) and packet['oracle_support_uses_publisher_held_evidence_ids'] is True
         and packet['historically_public_not_future'] is True and packet['original_answers_in_packet'] is False
         and packet['reader_tokenizer_parity_verified'] is False and packet['research_only'] is True
         and packet['production_authorized'] is False and packet['disposition']=='HOLD_NO_GO',
         'false claim/scope')
    need(type(packet['cases']) is list and len(packet['cases'])==16,'wrong panel size')
    seen=set()
    for i,case in enumerate(packet['cases']):
        need(type(case) is dict and set(case)=={'id','root','question','question_sha','arms'}
             and case['root']==ROOTS[i//4] and case['id'].startswith(case['root']+'/q')
             and case['id'] not in seen and type(case['question']) is str
             and sha(case['question'].encode())==case['question_sha'], 'case tamper')
        seen.add(case['id'])
        arms=case['arms']
        need(type(arms) is dict and set(arms)==set(ARMS) and arms['none']==[],
             'four complete original evidence arms required')
        for name,docs in arms.items():
            need(type(docs) is list and len(docs)<=12 and (name=='none' or len(docs)>=0),
                 'excess or missing documents')
            if name in ('bm25','oracle'):need(len(docs)>=1,'nonempty evidence arm')
            did=set()
            for d in docs:
                need(type(d) is dict and set(d)=={'id','text','text_sha'}
                     and type(d['id']) is str and d['id'] not in did
                     and re.fullmatch(r'D\d+:\d+',d['id']) is not None
                     and type(d['text']) is str and 0<len(d['text'].encode())<=8192
                     and sha(d['text'].encode())==d['text_sha'], 'source doc tamper')
                did.add(d['id'])
        need(arms['lesion']==arms['oracle'][1:],'lesion must delete first necessary fact')
        need([x['id'] for x in arms['oracle']]==sorted(x['id'] for x in arms['oracle']),
             'oracle evidence id canonical order')
    need(packet['digest']==digest({k:v for k,v in packet.items() if k!='digest'}),'packet digest mismatch')


def write_new(path:Path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:
        f.write(canonical(value)+b'\n');f.flush()
        import os;os.fsync(f.fileno())


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--original',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();out=from_original(a.original.read_bytes());write_new(a.out,out)
    print(json.dumps({'cases':len(out['cases']),'arms':list(ARMS), 'sha':out['digest'],
          'held_answers_exported':False,'future_verified':False},sort_keys=True))

if __name__=='__main__':main()
