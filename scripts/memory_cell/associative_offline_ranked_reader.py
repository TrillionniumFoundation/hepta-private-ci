"""Actual original-weight offline Smol CPU shadow of the 100 frozen ranked inputs.

Not Hugging Face parity certified; a research-only separate implementation arm.
"""
from collections import Counter, defaultdict
from pathlib import Path
import json
import os
import sys

from offline_smol_reader import OriginalSmol, verify_files
from reader_weight_transport import verify_reader_transport
from associative_question_conditioned import reader_inputs, READER_ARMS, _token_f1, _read_public
from associative_offline_reader_diagnostic import strict_offline_result, READER_SCHEMA as PREMISE_READER_SCHEMA
from associative_locomo_shadow import strict_json, read_regular, exclusive, canonical
from associative_reader_unicode_recovery import _read_source
from associative_cell import sha256

SCHEMA="hepta.offline-smol-ranked-reader.research.v1"
READ_SCHEMA="hepta.offline-smol-ranked-reader-journal.v1"


def run(public_dir, rank_dir, model_dir, out_dir):
    inputs=list(reader_inputs(public_dir,rank_dir,per_family=2))
    if len(inputs)!=100 or len({(x['question_id'],x['arm']) for x in inputs}) !=100:
        raise ValueError('incomplete sealed ranked reader inputs')
    if any((Path(public_dir)/f).exists() for f in ('private.json','answers.json')):
        raise ValueError('private answer artifact in public view')
    from associative_locomo_shadow import strict_json, read_regular
    raw_rank_seal=read_regular(Path(rank_dir)/'seal.json')
    rank_seal=strict_json(raw_rank_seal)
    public,manifest=_read_public(public_dir)
    verify_reader_transport(model_dir)
    verify_files(model_dir)
    import torch
    torch.set_num_threads(2)
    model=OriginalSmol(model_dir)
    output=Path(out_dir);output.mkdir(exist_ok=False)
    rows=[]
    for n,e in enumerate(inputs,1):
        res=strict_offline_result(model,e)
        rows.append(dict(question_id=e['question_id'],family=e['family'],arm=e['arm'],
                         evidence_ids=[v['source_id'] for v in e['evidence']],result=res))
        if os.environ.get('HEPTA_LOCAL_PROGRESS')=='1':print(f'{n}/100 {e["question_id"]} {e["arm"]} {res["status"]}',flush=True)
    model.verify_frozen()
    journal_sha=exclusive(output/'reader-journal.json',rows)
    seal=dict(schema=READ_SCHEMA,ranked_journal_sha256=rank_seal['journal_sha256'],
              public_sha256=manifest['public_sha256'],reader_journal_sha256=journal_sha,
              planned=100,reader_backend='offline-original-smol-fp32',
              offline_model_identity_verified=True,official_reader_parity_certified=False,
              gold_reference_visible=False,production_accepted=False)
    exclusive(output/'reader-seal.json',seal)
    return seal


def review(public_dir,rank_dir,reader_dir,original_file,output):
    inputs=list(reader_inputs(public_dir,rank_dir,per_family=2))
    index={(x['question_id'],x['arm']):x for x in inputs}
    record_raw=read_regular(Path(reader_dir)/'reader-journal.json',maximum=8*1024*1024)
    rows=strict_json(record_raw)
    meta=strict_json(read_regular(Path(reader_dir)/'reader-seal.json'))
    _,manifest=_read_public(public_dir)
    rank_seal=strict_json(read_regular(Path(rank_dir)/'seal.json'))
    if (meta.get('schema')!=READ_SCHEMA or meta.get('reader_journal_sha256')!=sha256(record_raw)
        or meta.get('ranked_journal_sha256')!=rank_seal['journal_sha256']
        or meta.get('public_sha256')!=manifest['public_sha256']
        or meta.get('planned')!=100 or meta.get('official_reader_parity_certified') is not False
        or meta.get('gold_reference_visible') is not False or meta.get('production_accepted') is not False):
        raise ValueError('unsealed Reader run or noncanonical identity')
    if not isinstance(rows,list) or len(rows)!=100:raise ValueError('incomplete Reader census')
    original=_read_source(original_file)
    by_arm=defaultdict(list);status=defaultdict(Counter);paired=defaultdict(dict)
    seen=set();evidence_complete=defaultdict(list)
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'question_id','family','arm','evidence_ids','result'}:
            raise ValueError('foreign attempt')
        k=(row['question_id'],row['arm'])
        if k not in index or k in seen:raise ValueError('duplicate or foreign Reader attempt')
        seen.add(k);item=index[k]
        if row['family']!=item['family'] or row['evidence_ids']!=[e['source_id'] for e in item['evidence']]:
            raise ValueError('evidence hash/identity changed')
        res=row['result']
        if res.get('status') not in ('succeeded','failed','unavailable'):
            raise ValueError('unknown status')
        status[item['arm']][res['status']]+=1
        question_num=int(item['question_id'].rsplit('/q',1)[1])
        gold=original[item['family']]['qa'][question_num]
        ref=gold.get('answer')
        if res['status']=='succeeded':
            if not isinstance(res.get('answer'),str) or not res['answer'].strip():
                raise ValueError('empty success')
            if isinstance(ref,str) and ref.strip():
                val=_token_f1(res['answer'],ref)
                by_arm[item['arm']].append(val)
                paired[item['question_id']][item['arm']]=val
            else:status[item['arm']]['unscorable_reference']+=1
    if seen!=set(index):raise ValueError('missing expected record')
    groupids=sorted({x['question_id'] for x in inputs})
    out=dict(schema=SCHEMA,source_sha256=sha256(read_regular(original_file,maximum=8*1024*1024)),
             source_journal_sha256=rank_seal['journal_sha256'],reader_journal_sha256=meta['reader_journal_sha256'],
             planned=100,questions=20,reader_backend='offline-original-smol-fp32',
             by_arm={arm:dict(planned=20,scored=len(by_arm[arm]),
                   mean_token_f1=sum(by_arm[arm])/len(by_arm[arm]) if by_arm[arm] else None,
                   statuses=dict(status[arm])) for arm in READER_ARMS},
             official_reader_equivalence_certified=False,
             independently_verified_semantic_sufficiency=False,
             memorycell_gain_claim=False,production_accepted=False)
    exclusive(output,out)
    return out

if __name__=='__main__':
    if (sys.argv[1]=='run' and len(sys.argv)!=6) or (sys.argv[1]=='review' and len(sys.argv)!=7) or sys.argv[1] not in ('run','review'):
        raise SystemExit('usage: run PUBLIC RANK MODEL OUTPUT | review PUBLIC RANK READER ORIGINAL OUTPUT')
    if sys.argv[1]=='run':
        print(json.dumps(run(*sys.argv[2:]),sort_keys=True))
    else:
        print(json.dumps(review(*sys.argv[2:]),sort_keys=True))
