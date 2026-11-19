"""Source-bound NDU-Merton scientific *non-promotion* gate.

This is an independent arithmetic check over archived ORIGINAL prediction bytes,
not a model trainer, a signed evaluator, a new task family, or production authority.
It deliberately refuses to infer source-family independence from record IDs.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from fractions import Fraction
from hashlib import sha256
from itertools import combinations
import json
import math
from pathlib import Path
import zipfile

ARCHIVE_SHA256 = '195dfb9e5bedaf5cee7fe8b2994a10f7ebaaf9ecca2a3a94bb77b0185a4337a7'
TRIAL_SHA256 = 'c78cfe148e6d9544450836202f4da0f9bc5d93f980c96362238945b20a67898f'
MODEL = 'jhu-clsp/mmBERT-small'
MODEL_REVISION = 'abc32620dd4f6ab06f5fbe905dc25f310618e09f'
ARMS = ('fixed8', 'ndu_discrete')
SCHEMA = 'hepta.ndu-merton.source-science-gate.v1'


def stable(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value: object) -> str:
    return sha256(stable(value)).hexdigest()


def loads(data: bytes):
    def unique_pairs(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError('duplicate JSON key')
            result[k] = v
        return result
    return json.loads(data, object_pairs_hook=unique_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def ensure(value, message):
    if not value:
        raise ValueError(message)


def zip_read(z: zipfile.ZipFile, name: str):
    ensure(name in z.namelist(), 'missing original member: ' + name)
    return loads(z.read(name))


def label_source(z: zipfile.ZipFile):
    # This is an ORIGINAL DATA label re-read. The producer's score summaries
    # and declared accuracy never become the sole truth source.
    records = [loads(line.encode()) for line in
               z.read('hepta-public-study/dataset.jsonl').decode().splitlines()]
    ensure(len(records) == 128, 'original source census changed')
    ids = [r['case_id'] for r in records]
    ensure(len(ids) == len(set(ids)), 'original source identifiers repeated')
    splits = {s: [r for r in records if r['split'] == s] for s in ('train', 'calibration', 'holdout')}
    ensure([len(splits[s]) for s in splits] == [64, 32, 32], 'original split changed')
    for r in records:
        ensure(type(r['label']) is int and 0 <= r['label'] <= 3, 'original labels invalid')
        ensure(r['group'] == r['case_id'], 'unexpected group semantics')
    return {r['case_id']: r['label'] for r in splits['holdout']}


def argmax4(probabilities):
    ensure(type(probabilities) is list and len(probabilities) == 4,
           'invalid original output dimensions')
    ensure(all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1
               for p in probabilities), 'invalid original probabilities')
    ensure(abs(sum(probabilities)-1.0) < 1e-9, 'unnormalized probabilities')
    return max(range(4), key=lambda i: probabilities[i])


def archived_no_go(source_zip: str | Path, study_zip: str | Path) -> dict:
    source_bytes = Path(source_zip).read_bytes()
    ensure(sha256(source_bytes).hexdigest() == ARCHIVE_SHA256,
           'original public feature source SHA changed')
    ensure(sha256(Path(study_zip).read_bytes()).hexdigest() == TRIAL_SHA256,
           'original completed-trial ZIP SHA changed')
    with zipfile.ZipFile(source_zip) as source, zipfile.ZipFile(study_zip) as evidence:
        for z in (source, evidence):
            names=z.namelist()
            ensure(len(names)==len(set(names)), 'duplicate ZIP member names')
        ensure(source.testzip() is None and evidence.testzip() is None, 'archive CRC failure')
        source_lock = zip_read(source,'hepta-public-study/model-source.json')
        ensure(source_lock['model_id'] == MODEL and
               source_lock['revision'] == MODEL_REVISION, 'wrong pretrained lineage')
        labels = label_source(source)
        original_labels = zip_read(evidence,'news-material/scorer-labels.json')
        ensure(labels == original_labels, 'label-owner mismatch to original dataset')
        protocol = zip_read(evidence, 'news-final-normal/protocol.json')
        ensure(protocol['model_id'] == MODEL and
               protocol['model_revision'] == MODEL_REVISION and
               protocol['archive_sha256'] == ARCHIVE_SHA256,
               'experiment origin or model drift')
        ensure(protocol['archive_previously_scored_by_other_research'] is True and
               protocol['record_ids_are_not_validated_independent_story_families'] is True and
               protocol['prospective_or_new_calendar_window'] is False,
               'historical negative provenance disappeared')
        ensure(protocol['arms'][:3] == ['zero','train_majority','fixed8'] and
               'ndu_discrete' in protocol['arms'], 'registered arm census drift')
        raw = []
        for mode in ('normal','optimized'):
            sealed = zip_read(evidence, f'news-final-{mode}/sealed.json')
            ensure(sealed['archive_sha256'] == ARCHIVE_SHA256 and
                   sealed['heldout_labels_loaded'] is False and
                   sealed['posture'] == 'RESEARCH_ONLY_DENY_ALL',
                   'blind seal/origin/authority failure')
            observed = {(r['repeat'],r['arm']):r for r in sealed['rows']}
            ensure(len(observed) == len(sealed['rows']) == 27, 'incomplete original sealed matrix')
            for repeat in range(3):
                arm_rows = {}
                for arm in ARMS:
                    path=f'news-final-{mode}/{repeat}-{arm}.json'
                    row=zip_read(evidence,path)
                    ensure(row == observed[(repeat,arm)], 'sealed original row differs')
                    ensure(row['arm']==arm and row['repeat']==repeat and
                           type(row['actual_steps']) is int and row['actual_steps']>0,
                           'invalid arm or executed-work receipt')
                    ensure(row['selected_steps'] == 8, 'original selected checkpoint drift')
                    ensure(type(row['cpu_ns']) is int and row['cpu_ns'] > 0 and
                           type(row['wall_ns']) is int and row['wall_ns'] > 0,
                           'original clock receipt absent')
                    phases=row['phases']
                    ensure(isinstance(phases,dict) and
                           all(type(p['cpu_ns']) is int and p['cpu_ns'] >= 0 for p in phases.values()),
                           'original phase costs absent')
                    ensure(sum(p['cpu_ns'] for p in phases.values()) <= row['cpu_ns'],
                           'phase timing exceeds total CPU')
                    ids=row['holdout_ids']
                    ensure(len(ids)==32 and len(set(ids))==32 and set(ids)==set(labels),
                           'source-holdout dropout or inflation')
                    prob=row['probabilities']
                    ensure(len(prob)==len(ids),'source probabilities missing')
                    pred={case:argmax4(pr) for case,pr in zip(ids,prob)}
                    arm_rows[arm]=(row,pred)
                f,pf=arm_rows['fixed8'];n,pn=arm_rows['ndu_discrete']
                ensure(f['holdout_ids']==n['holdout_ids'], 'unequal original Reader inputs')
                ensure(f['actual_steps']==8 and n['actual_steps']==128,
                       'original full pilot cost overwritten')
                correct={arm:sum(pred[i]==labels[i] for i in labels)
                         for arm,(_,pred) in arm_rows.items()}
                wins=sum(pn[i]==labels[i] and pf[i]!=labels[i] for i in labels)
                losses=sum(pn[i]!=labels[i] and pf[i]==labels[i] for i in labels)
                ensure(correct['fixed8']==correct['ndu_discrete']==26 and wins==0 and losses==0,
                       'observed archival negative result changed')
                # Strict prediction probability equality is stronger than same accuracy.
                ensure(n['probabilities'] == f['probabilities'],
                       'fixed8/NDU exact output vectors differ')
                saved=f['cpu_ns']; cost=n['cpu_ns']
                ensure(cost>saved,'observed original control was not costlier')
                raw.append({'interpreter':mode,'repeat':repeat,'unique_sources':32,
                            'fixed8_correct':correct['fixed8'],
                            'ndu_correct':correct['ndu_discrete'],
                            'paired_wins':wins,'paired_losses':losses,
                            'fixed8_actual_steps':f['actual_steps'],
                            'ndu_actual_steps':n['actual_steps'],
                            'fixed8_cpu_ns':saved,'ndu_cpu_ns':cost,
                            'ndu_incremental_cpu_ns':cost-saved})
    # This is SAME DATA repeated 3x in 2 modes, NOT 192 independent outcomes.
    return {'schema':SCHEMA+'.retrospective',
            'source_sha256':ARCHIVE_SHA256,
            'trial_zip_sha256':TRIAL_SHA256,
            'model_id':MODEL,'model_revision':MODEL_REVISION,
            'historical_unique_cases':32,
            'verified_independent_source_families':0,
            'true_prospective_windows':0,
            'studies_replayed':len(raw),
            'source_first_original_label_reopen':True,
            'same_final_probabilities_all_repeats':True,
            'paired_ndu_wins':0,'paired_ndu_losses':0,
            'observed_cached_input_dominance':True,
            'complete_online_service_cost_verified':False,
            'causal_ndu_superiority_established':False,
            'production_accepted':False,
            'posture':'RESEARCH_ONLY_DENY_ALL',
            'observations':raw}


def sign_test_one_sided(wins:int,losses:int) -> Fraction:
    ensure(type(wins) is int and type(losses) is int and wins>=0 and losses>=0,
           'invalid exact paired sign-test counts')
    n=wins+losses
    return Fraction(sum(math.comb(n,k) for k in range(wins,n+1)),2**n) if n else Fraction(1)


def holm_one_sided(pvalues):
    ensure(pvalues and all(isinstance(p,Fraction) and 0<=p<=1 for p in pvalues),
           'invalid registered family-comparison p-values')
    order=sorted(range(len(pvalues)),key=lambda i:pvalues[i])
    output=[Fraction(1)]*len(pvalues); running=Fraction(0)
    for rank,i in enumerate(order):
        running=max(running,min(Fraction(1),pvalues[i]*(len(pvalues)-rank)))
        output[i]=running
    return tuple(output)


def prospective_structure(packet:dict) -> dict:
    """Strictly structural gate. Never issues independent signed authorization.

    Does NOT accept caller-provided `independent=true` as an attestation.
    Positive mock fixtures establish numerical mechanics only.
    """
    ensure(type(packet) is dict and packet.get('schema')==SCHEMA+'.input',
           'unknown prospective source schema')
    ensure(packet.get('objective')=='full_task_exact_accuracy',
           'immutable external task objective unavailable')
    ensure(packet.get('posture')=='RESEARCH_ONLY_DENY_ALL' and
           packet.get('production_accepted') is False,
           'production authority must remain external')
    controls=packet.get('controls')
    ensure(controls==['fixed8','neutral','ndu_discrete'],
           'missing cheap/same-information comparators')
    sources=packet.get('source_inventory'); labels=packet.get('held_labels')
    ensure(isinstance(sources,list) and sources and isinstance(labels,dict),
           'complete original inventory and post-seal labels required')
    ids=[x['case_id'] for x in sources]
    ensure(len(ids)==len(set(ids))==len(labels) and set(ids)==set(labels),
           'source/label missing, duplicated or invented')
    grouped=defaultdict(list); windows=set()
    for item in sources:
        ensure(set(item)=={'case_id','source_family','window','source_digest'},
               'unexpected source inventory field or embedded label')
        ensure(isinstance(item.get('source_family'),str) and item['source_family'],
               'source family cannot be inferred from a candidate row')
        ensure(isinstance(item.get('window'),str) and item['window'],
               'unbound future observation window')
        ensure(isinstance(item.get('source_digest'),str) and
               len(item['source_digest'])==64 and
               all(c in '0123456789abcdef' for c in item['source_digest']),
               'missing original source digest')
        grouped[item['source_family']].append(item['case_id']); windows.add(item['window'])
    ensure(all(type(y) is int and y in (0,1) for y in labels.values()),
           'binary whole-task outcomes only')
    seal=packet.get('blind_prediction_seal')
    ensure(isinstance(seal,dict) and seal.get('schema')=='hepta.prospective.blind.v1',
           'sealed predictions required')
    predictions=seal.get('rows')
    ensure(isinstance(predictions,list) and len(predictions)==len(ids),
           'incomplete predicted arm census')
    ensure(seal.get('digest')==digest(predictions),
           'blind prediction content digest mismatch')
    ensure(seal.get('labels_present') is False and seal.get('score_present') is False,
           'label or score seen before sealing')
    pred={}
    for r in predictions:
        ensure(type(r) is dict and set(r)=={'case_id','arms'},
               'prediction seal contains unregistered data or labels')
        i=r.get('case_id')
        ensure(i in labels and i not in pred,'duplicate or foreign prediction')
        ensure(type(r.get('arms')) is dict and set(r['arms'])==set(controls),
               'missing registered prediction arm')
        ensure(all(type(v) is int and v in (0,1) for v in r['arms'].values()),
               'invalid task prediction')
        pred[i]=r['arms']
    ensure(set(pred)==set(labels),'unpaired task census')
    # Bounded, typed actual work. Missing data remain unknown, not free.
    invoices=packet.get('invoices'); totals={}; known=True
    ensure(isinstance(invoices,dict) and set(invoices)==set(controls),
           'missing any comparator lifecycle invoice')
    cost_fields=('model_material','encoder','training','pilot','inference',
                 'verifier','policy_compile','policy_load','migration')
    for arm, inv in invoices.items():
        ensure(isinstance(inv,dict) and set(inv)==set(cost_fields),
               'unregistered or omitted lifecycle phase')
        vals=list(inv.values())
        ensure(all(v is None or (type(v) is int and v>=0) for v in vals),
               'invalid phase cost')
        if any(v is None for v in vals): known=False;totals[arm]=None
        else:totals[arm]=sum(vals)
    # Report all source-family paired contrasts. No fake n=row counts.
    comps=[]; raw_p=[]
    for comparator in controls[:2]:
        deltas={family:sum(int(pred[i]['ndu_discrete']==labels[i])-
                                  int(pred[i][comparator]==labels[i])
                                  for i in family_ids)
                for family,family_ids in grouped.items()}
        wins=sum(v>0 for v in deltas.values());loss=sum(v<0 for v in deltas.values());ties=sum(v==0 for v in deltas.values())
        p=sign_test_one_sided(wins,loss);raw_p.append(p)
        comps.append({'comparator':comparator,'source_family_wins':wins,
                      'source_family_losses':loss,'source_family_ties':ties,
                      'paired_correct_delta':sum(deltas.values()),
                      'exact_one_sided_sign_p':str(p),
                      'cost_delta_ns':totals['ndu_discrete']-totals[comparator]
                      if known else None})
    for x, adj in zip(comps,holm_one_sided(raw_p)):
        x['holm_adjusted_p']=str(adj)
    protocol=packet.get('protocol')
    ensure(isinstance(protocol,dict) and
           protocol.get('source_manifest_digest') == digest(sources) and
           protocol.get('candidate_frozen_before_evaluation') is True and
           all(isinstance(protocol.get(k),str) and
               len(protocol[k])==64 and
               all(c in '0123456789abcdef' for c in protocol[k])
               for k in ('shared_encoder_digest','fixed_reader_digest','fixed_tokenizer_digest')),
           'unfrozen or unbound source/model/reader protocol')
    # An in-chat/source-only gate cannot authenticate independent source,
    # assessor, temporal custody, or hardware signatures. It may NOT issue an
    # acceptance bit from a caller-controlled boolean or arbitrary key.
    conditions=[
        'external_source_family_independence_not_authenticated',
        'independent_evaluator_and_time_window_custody_not_authenticated',
        'full_cost_independent_observer_not_authenticated' if not known else
        'full_cost_source_only_not_independently_authenticated',
    ]
    if len(grouped)<20:conditions.append('fewer_than_20_independent_source_family_candidates')
    if len(windows)<3:conditions.append('fewer_than_3_distinct_time_windows')
    if any(Fraction(x['holm_adjusted_p']) > Fraction(1,20) or
           x['paired_correct_delta']<=0 for x in comps):
        conditions.append('no_positive_multiplicity_corrected_paired_task_evidence')
    if known and any(x['cost_delta_ns']>=0 for x in comps):
        conditions.append('candidate_not_cheaper_than_all_controls')
    return {'schema':SCHEMA+'.structural-review','case_count':len(ids),
            'declared_source_family_count':len(grouped),
            'declared_time_window_count':len(windows),
            'cost_complete':known,'cost_ns':totals,
            'comparisons':comps,'blockers':conditions,
            'independently_verified_new_source_efficacy':False,
            'model_promotion_qualified':False,
            'production_accepted':False,
            'posture':'RESEARCH_ONLY_DENY_ALL'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--public-archive',type=Path)
    ap.add_argument('--original-trial-archive',type=Path)
    ap.add_argument('--prospective-packet',type=Path)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if a.public_archive and a.original_trial_archive and not a.prospective_packet:
        out=archived_no_go(a.public_archive,a.original_trial_archive)
    elif a.prospective_packet and not(a.public_archive or a.original_trial_archive):
        out=prospective_structure(loads(a.prospective_packet.read_bytes()))
    else:ap.error('supply original archive pair OR one prospective packet')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:
        json.dump(out,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps({k:out.get(k) for k in ('schema','historical_unique_cases',
         'studies_replayed','declared_source_family_count','posture')},sort_keys=True))

if __name__=='__main__':
    main()
