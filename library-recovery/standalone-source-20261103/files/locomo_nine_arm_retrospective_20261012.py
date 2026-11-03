"""Offline reproduction of 9 fixed retrieval arms on an ALREADY EXPOSED LoCoMo cut.

Retrospective only: never claim a nine-arm hosted run, blind new population,
model answer accuracy, independent future groups or production acceptance.
The script writes the public original-source decisions before loading labels.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path

from locomo_six_arm_external_replay import (
    secure_zip, read_json, digest, source_time, rerank, tokenize,
    PIN_COMMIT, PIN_SOURCE, SPLITS,
)

ROOT = Path('/mnt/data')
ARMS = tuple(f'{mode}_k{k}' for mode in ('lexical','recent','fusion') for k in (2,4,8))


def canonical(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False).encode()


def fixed_fusion(lexical, recent):
    if len(lexical) != len(set(lexical)) or len(recent) != len(set(recent)) or set(lexical) != set(recent):
        raise ValueError('fusion pools do not match')
    la={identity:i for i,identity in enumerate(lexical,1)}
    ra={identity:i for i,identity in enumerate(recent,1)}
    return sorted(la,key=lambda key:(-(1/(60+la[key])+1/(60+ra[key])),key))


def freeze():
    pub, zsha = secure_zip('reader-public')
    public=read_json(pub['population.json'])
    meta=read_json(pub['histories-manifest.json'])
    hist=pub['histories.jsonl']
    if public['generating_source_commit']!=PIN_COMMIT or public['source_sha256']['locomo']!=PIN_SOURCE:
        raise ValueError('unexpected published LoCoMo source')
    if meta['source_commit']!=PIN_COMMIT or meta['population_sha256']!=sha256(pub['population.json']).hexdigest():
        raise ValueError('published original corpus drift')
    if meta['histories_sha256']!=sha256(hist).hexdigest() or meta['target_file_in_reader_inputs'] is not False:
        raise ValueError('original document or target embargo drift')
    if {s:len(public['splits'][s]) for s in SPLITS} != {'train':48,'selection':16,'evaluation':16}:
        raise ValueError('changed public 48/16/16 census')
    if public['census']['split_family_proxies'] != {'train':6,'selection':2,'evaluation':2}:
        raise ValueError('changed original source-family proxies')
    docs=[read_json(z) for z in hist.splitlines()]
    entries={d['identity']:d for d in docs}
    if len(docs)!=len(entries) or len(docs)!=meta['original_document_count'] or len(docs)!=5882:
        raise ValueError('original source document census drift')
    rows=[]
    seen={}
    for split in SPLITS:
        for q in public['splits'][split]:
            ds=[entries[k] for k in q['source_ids']]
            if len(ds)!=len(set(d['identity'] for d in ds)) or not ds:
                raise ValueError('duplicate/missing original source')
            for d in ds:
                if d['scope'] != q['scope'] or source_time(d['observed_at'])>source_time(q['observation_time']):
                    raise ValueError('leak or future source')
                if d['identity'] in seen and seen[d['identity']]!=split:
                    raise ValueError('source ID crosses family cut')
                seen[d['identity']]=split
            census=[(d['identity'],d['root'],d['observed_at'],sha256(d['content'].encode()).hexdigest()) for d in sorted(ds,key=lambda d:d['identity'])]
            if digest(census)!=q['source_census_sha256']:
                raise ValueError('original source-byte census mismatch')
            lexical,recent=rerank(q,ds)
            fusion=fixed_fusion(lexical,recent)
            order={'lexical':lexical,'recent':recent,'fusion':fusion}
            for arm in ARMS:
                kind, k=arm.rsplit('_k',1)
                selected=order[kind][:int(k)]
                rows.append(dict(question_id=q['question_id'],split=split,
                                 family_proxy_digest=q['family_proxy_digest'],
                                 source_census_sha256=q['source_census_sha256'],
                                 arm=arm,selected=selected,
                                 selected_source_bytes=sum(len(entries[key]['content'].encode()) for key in selected)))
    if len(rows)!=720 or len({(r['question_id'],r['arm']) for r in rows})!=720:
        raise ValueError('incomplete nine-arm census')
    output=ROOT/'locomo-nine-arm-retrospective-decisions.jsonl'
    if output.exists():raise FileExistsError(output)
    b=b''.join(canonical(row)+b'\n' for row in rows)
    with output.open('xb') as f:f.write(b);f.flush();import os;os.fsync(f.fileno())
    pin=dict(schema='hepta.memorycell.locomo-nine-arm-retrospective.v1',
             published_source_commit=PIN_COMMIT,
             published_source_sha256=PIN_SOURCE,
             public_zip_sha256=zsha,
             public_population_sha256=meta['population_sha256'],
             public_histories_sha256=meta['histories_sha256'],
             original_corpus_documents=5882,
             question_census=80,planned_arms=9,decision_count=720,
             decisions_sha256=sha256(b).hexdigest(),
             no_private_labels_opened_during_decisions=True,
             all_evaluation_questions_previously_exposed=True,
             model_generations=0,independent_future_families=0,
             production_accepted=False)
    receipt=ROOT/'locomo-nine-arm-retrospective-public-pin.json'
    if receipt.exists():raise FileExistsError(receipt)
    with receipt.open('xb') as f:f.write(canonical(pin)+b'\n');f.flush();os.fsync(f.fileno())
    print('FREEZE_OK',len(rows),pin['decisions_sha256'])


def score_one(public,decisions,targets,split):
    questions=public['splits'][split]
    if len(questions)!=16 or set(targets)!={q['question_id'] for q in questions}:
        raise ValueError('private label partition mismatch')
    byarm={}
    for arm in ARMS:
        eligible=covered=unknown=out_of_pool=totalbytes=0
        families={}
        for q in questions:
            t=targets[q['question_id']]
            row=decisions[(q['question_id'],arm)]
            totalbytes+=row['selected_source_bytes']
            fam=families.setdefault(q['family_proxy_digest'],{'eligible':0,'covered':0})
            if type(t['unanswerable']) is not bool or not isinstance(t['support'],list) or not isinstance(t['unresolved_support'],list):raise ValueError('bad target')
            if set(t['support'])-set(q['source_ids']):out_of_pool+=1
            valid=bool(t['support']) and not t['unanswerable'] and not t['unresolved_support'] and not bool(set(t['support'])-set(q['source_ids']))
            if valid:
                eligible+=1;fam['eligible']+=1
                if set(t['support']).issubset(row['selected']):covered+=1;fam['covered']+=1
            else:unknown+=1
        byarm[arm]=dict(planned=16,eligible=eligible,full_annotated_support_covered=covered,
                        unknown_or_unanswerable=unknown,annotated_support_outside_original_pool=out_of_pool,
                        selected_source_bytes=totalbytes,per_family=families,
                        missing_outcome_lower=covered/16,missing_outcome_upper=(covered+unknown)/16)
    return byarm


def selection():
    pin=read_json((ROOT/'locomo-nine-arm-retrospective-public-pin.json').read_bytes())
    raw=(ROOT/'locomo-nine-arm-retrospective-decisions.jsonl').read_bytes()
    if sha256(raw).hexdigest()!=pin['decisions_sha256'] or len(raw.splitlines())!=720:raise ValueError('original selection drift')
    pub,_=secure_zip('reader-public');p=read_json(pub['population.json'])
    rows=[read_json(r) for r in raw.splitlines()]
    decisions={(r['question_id'],r['arm']):r for r in rows}
    if len(decisions)!=720:raise ValueError('duplicate')
    # Open only the SELECTION partition labels, no held-out labels in this process.
    z,_=secure_zip('selection-targets')
    targets=read_json(z['targets.json'])
    scores=score_one(p,decisions,targets,'selection')
    choice=sorted(ARMS,key=lambda arm:(-scores[arm]['full_annotated_support_covered'],scores[arm]['selected_source_bytes'],arm))[0]
    out=dict(schema=pin['schema'],source_commit=PIN_COMMIT,
             decision_sha256=pin['decisions_sha256'],
             selection_policy=choice,selection_scores=scores,
             heldout_labels_opened=False,model_generations=0,
             has_prior_six_arm_exposure=True,production_accepted=False)
    path=ROOT/'locomo-nine-arm-retrospective-policy.json'
    if path.exists():raise FileExistsError(path)
    with path.open('xb') as f:f.write(canonical(out)+b'\n');f.flush();import os;os.fsync(f.fileno())
    print('SELECT_OK',choice, 'coverage',scores[choice]['full_annotated_support_covered'])


def evaluate():
    pin=read_json((ROOT/'locomo-nine-arm-retrospective-public-pin.json').read_bytes())
    raw=(ROOT/'locomo-nine-arm-retrospective-decisions.jsonl').read_bytes()
    policyraw=(ROOT/'locomo-nine-arm-retrospective-policy.json').read_bytes()
    policy=read_json(policyraw)
    if sha256(raw).hexdigest()!=pin['decisions_sha256'] or policy['decision_sha256']!=pin['decisions_sha256']:
        raise ValueError('frozen public decisions moved')
    if policy['heldout_labels_opened'] is not False or policy['selection_policy'] not in ARMS:
        raise ValueError('unsealed selection policy')
    pub,_=secure_zip('reader-public');public=read_json(pub['population.json'])
    rows=[read_json(r) for r in raw.splitlines()]
    decisions={(r['question_id'],r['arm']):r for r in rows}
    if len(decisions)!=720:raise ValueError('incomplete original decisions')
    # Separate process: only now open held-out evaluation original answers.
    z,_=secure_zip('evaluation-targets')
    ev=read_json(z['targets.json'])
    results=score_one(public,decisions,ev,'evaluation')
    report=dict(schema=pin['schema'],source_commit=PIN_COMMIT,source_sha256=PIN_SOURCE,
                nine_arm_hosted_run_completed=False,
                original_published_data_and_outcomes_previously_exposed=True,
                observed_source_only_decisions=720,source_doc_count=5882,
                public_decisions_sha256=pin['decisions_sha256'],
                selected_policy_sha256=sha256(policyraw).hexdigest(),
                selected_arm=policy['selection_policy'],
                selection=policy['selection_scores'],evaluation=results,
                selected_evaluation=results[policy['selection_policy']],
                model_generations=0,independent_future_families=0,
                independent_semantic_judgement=False,production_accepted=False)
    output=ROOT/'locomo-nine-arm-retrospective-evaluation-20261012.json'
    if output.exists():raise FileExistsError(output)
    output.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print('EVALUATE_OK',policy['selection_policy'],{k:v['full_annotated_support_covered'] for k,v in results.items()})
    print('RETROSPECTIVE_SOURCE_ONLY',output)

if __name__=='__main__':
    cli=argparse.ArgumentParser()
    cli.add_argument('mode', choices=('freeze','selection','evaluation'))
    args=cli.parse_args()
    if args.mode=='freeze':freeze()
    elif args.mode=='selection':selection()
    else:evaluate()
