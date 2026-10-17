"""Independent, label-late ScienceQA E3 V7 interventional outcome reviewer.

No import of the producer, model, trainer or optimizer. Binds immutable original
prediction artifact, source cohort and labels, verifies the deterministic
cross-image permutation, computes paired scores and three preregistered tests.
Research-only, DENY_ALL, no human visual-necessity or future-window claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from math import comb, fsum

SCHEMA='hepta.stem.scienceqa-physical-image-intervention.v7'
ARMS=('correct_image','other_group_image','black_image','text_only')
SOURCE_SHA='a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202'
FIT_SHA='e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e'
HELD_SHA='b15cb81cbce3ff500ec58bb7da59c92801170bbce3b7995d689342505161f6d3'
ORIGINAL_SHA='e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7'
HEAD='2dc43da7d9bf343acc871219ddce44d0e14d8911'

class ReviewError(ValueError):
    pass

def need(ok, reason):
    if not ok: raise ReviewError(reason)

def canonical(value):
    return (json.dumps(value,sort_keys=True,ensure_ascii=True,
                       separators=(',',':'),allow_nan=False)+'\n').encode()

def sha(value):
    return hashlib.sha256(value).hexdigest()

def no_dup(pairs):
    out={}
    for key,val in pairs:
        need(key not in out,'duplicate JSON key')
        out[key]=val
    return out

def parse(raw):
    try:
        doc=json.loads(raw,object_pairs_hook=no_dup,
            parse_constant=lambda x: (_ for _ in ()).throw(ReviewError('nonfinite '+x)))
        need(type(doc) is dict,'JSON document required')
        canonical(doc)  # Reject JSON exponent overflow as well as explicit NaN.
        return doc
    except (ValueError, OverflowError, UnicodeError, TypeError) as exc:
        raise ReviewError('invalid, duplicate or nonfinite original JSON') from exc

def verify_prelabel_seal(seal_path, producer_path, producer_bytes):
    """Reject changed producer bytes after the pre-label SHA was written.

    The seal is same-owner historical data, not an issuer signature, ACL or
    independent host attestation. The reviewer independently rehashes bytes.
    """
    import re
    import stat
    seal_path = Path(seal_path)
    producer_path = Path(producer_path)
    need(not seal_path.is_symlink() and seal_path.is_file() and
         seal_path.stat().st_size <= 512 and seal_path.stat().st_size > 0 and
         stat.S_ISREG(seal_path.stat().st_mode) and seal_path.stat().st_nlink == 1,
         'unsafe or missing original pre-label seal')
    try:
        raw = seal_path.read_bytes().decode('ascii', 'strict').strip()
    except UnicodeError as error:
        raise ReviewError('invalid pre-label seal encoding') from error
    items = raw.split('  ', 1)
    need(len(items) == 2 and re.fullmatch(r'[0-9a-f]{64}', items[0]) is not None and
         items[1] == str(producer_path) and
         items[0] == sha(producer_bytes),
         'producer changed or source not bound to original pre-label digest')
    return items[0]

def top1(values):
    need(type(values) is list and len(values)==4 and
         all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in values) and
         abs(fsum(values)-1) < 1e-6,'noncanonical model probabilities')
    return max(range(4),key=lambda k:(values[k],-k))

def exact_p(gained,lost):
    n=gained+lost
    need(type(gained) is int and type(lost) is int and 0<=n<=64,
         'invalid paired counts')
    return min(1.,2*sum(comb(n,k) for k in range(min(gained,lost)+1))/2**n) if n else 1.

def review(candidate, sources, held, original):
    need(type(candidate) is dict and candidate.get('schema')==SCHEMA and
         candidate.get('authority')=='DENY_ALL' and candidate.get('production_authorized') is False and
         candidate.get('source_sha256')==SOURCE_SHA and candidate.get('fit_labels_sha256')==FIT_SHA and
         candidate.get('original_prediction_sha256')==ORIGINAL_SHA and
         candidate.get('original_model_code_commit')==HEAD,
         'unsigned or incompatible producer result')
    need(candidate.get('model_text_repo')=='ibm-granite/granite-embedding-97m-multilingual-r2' and
         candidate.get('model_text_revision')=='835ad14087e140460703cf0fae09f97d469d65c2' and
         candidate.get('model_vision_repo')=='facebook/dinov2-small' and
         candidate.get('model_vision_revision')=='ed25f3a31f01632728cabb09d1542f84ab7b0056' and
         candidate.get('same_head_parameters_in_all_image_arms') is True and
         candidate.get('actual_frozen_pretrained_model_executed') is True and
         candidate.get('actual_image_mask_dino_forward_executed') is True and
         candidate.get('other_group_image_source_was_physically_encoded') is True and
         candidate.get('test_labels_loaded_by_producer') is False and
         candidate.get('model_promoted') is False and
         candidate.get('independent_human_necessity_adjudication') is False,
         'unqualified experimental controls')
    for k in ('training_steps_original','training_steps_independent_check'):
        need(type(candidate.get(k)) is int and candidate[k]==80,'unregistered training steps')
    for k in ('text_forward_batches_original','vision_forward_batches_original'):
        need(type(candidate.get(k)) is int and candidate[k]>0,'physical Encoder work missing')
    need(type(candidate.get('vision_forward_batches_black_mask')) is int and
         candidate['vision_forward_batches_black_mask']==1 and
         type(candidate.get('vision_forward_batches_other_image_extra')) is int and
         candidate['vision_forward_batches_other_image_extra']==0,
         'misdeclared original/masked/mispaired visual model work')
    need(type(candidate.get('history_max_probability_delta')) in (float,int) and
         0<=candidate['history_max_probability_delta']<=.002 and
         type(candidate.get('independent_refit_max_probability_delta')) in (float,int) and
         0<=candidate['independent_refit_max_probability_delta']<=1e-5,
         'historical or independent training parity mismatch')
    for key in ('original_trained_bridge_sha256','original_trained_gate_sha256',
                'black_image_png_sha256'):
        need(type(candidate.get(key)) is str and len(candidate[key])==64 and
             all(c in '0123456789abcdef' for c in candidate[key]),'missing real material ID')
    historical=parse(original['sealed-source-bound-predictions.json'])
    need(sha(original['sealed-source-bound-predictions.json'])==ORIGINAL_SHA and
         historical['source_sha256']==SOURCE_SHA,
         'original E3 archived predictions modified')
    fit=historical['fit']
    # Cross-host matrix kernels can produce different serialized FP32 values.
    # Require actual paired historical OUTPUT parity, not falsely claim that
    # a regenerated checkpoint must be byte-for-byte equal on every host.
    need(candidate.get('historical_bridge_sha256')==fit['organ_fitted_bridge_sha256'] and
         candidate.get('historical_gate_sha256')==fit['gate_sha256'] and
         candidate.get('historical_bridge_byte_parity') is (
             candidate['original_trained_bridge_sha256']==fit['organ_fitted_bridge_sha256']) and
         candidate.get('historical_gate_byte_parity') is (
             candidate['original_trained_gate_sha256']==fit['gate_sha256']),
         'historical checkpoint byte-parity description forged')
    need(len(sources)==192 and len({x['id'] for x in sources})==192,
         'original publisher cohort incomplete')
    held_sources={r['id']:r for r in sources if r['split']=='test'}
    fit_sources={r['id'] for r in sources if r['split']!='test'}
    need(len(held_sources)==64 and len(fit_sources)==128 and
         len({r['group'] for r in held_sources.values()})==64,
         'original test media groups incomplete')
    label_map={r['id']:r['label'] for r in held}
    need(len(held)==64 and len(label_map)==64 and set(label_map)==set(held_sources) and
         all(type(y) is int and 0<=y<4 for y in label_map.values()),
         'independent label owner missing or changed')
    previous={r['id']:r for r in historical['predictions']}
    need(len(previous)==64 and set(previous)==set(label_map),'retrospective E3 cases drifted')
    ids=sorted(held_sources)
    mapping={rid:ids[(i+1)%len(ids)] for i,rid in enumerate(ids)}
    rows=candidate.get('per_case_predictions')
    need(type(rows) is list and len(rows)==64,'intervention case cardinality')
    byid={}
    correct={arm:{} for arm in ARMS};nll={arm:[] for arm in ARMS}
    for row in rows:
        need(type(row) is dict and set(row)=={
             'id','group','split','source_input_sha256','other_group_image_from_id',
             'other_group_image_source_group','arms'},'unregistered original intervention row')
        rid=row['id'];src=held_sources.get(rid)
        need(src is not None and rid not in byid and row['split']=='test' and
             row['group']==src['group'] and row['source_input_sha256']==sha(canonical(src)) and
             row['other_group_image_from_id']==mapping[rid] and
             row['other_group_image_source_group']==held_sources[mapping[rid]]['group'] and
             src['group']!=row['other_group_image_source_group'],
             'different-image intervention source ID is not predeclared derangement')
        need(type(row['arms']) is dict and set(row['arms'])==set(ARMS),
             'changed original intervention arms')
        original_row=previous[rid]
        need(original_row['group']==src['group'] and
             original_row['source_input_sha256']==sha(canonical(src)),
             'original physical source binding changed')
        for name in ARMS:
            vals=row['arms'][name]
            guess=top1(vals)
            correct[name][rid]=int(guess==label_map[rid])
            nll[name].append(-math.log(max(vals[label_map[rid]],1e-12)))
        for name,ref in (('correct_image','train_gate'),('text_only','text_only')):
            obs=row['arms'][name];orig=original_row['arms'][ref]
            need(max(abs(a-b) for a,b in zip(obs,orig))<=.002 and
                 top1(obs)==top1(orig),'historical actual pretrained baseline drift')
        byid[rid]=row
    need(set(byid)==set(label_map),'duplicate, missing or substituted TEST case')
    scores={name:{'cases':64,'correct':sum(correct[name].values()),
                  'accuracy':sum(correct[name].values())/64,
                  'nll':fsum(nll[name])/64} for name in ARMS}
    need(scores['text_only']['correct']==17 and scores['correct_image']['correct']==24,
         'genuine original retrospective baseline score changed')
    contrasts={}
    base=correct['correct_image']
    for name in ('other_group_image','black_image','text_only'):
        ctrl=correct[name]
        retained=sum(base[r] and ctrl[r] for r in base)
        gained=sum(base[r] and not ctrl[r] for r in base)
        lost=sum(not base[r] and ctrl[r] for r in base)
        p=exact_p(gained,lost)
        contrasts[name]={'correct_only_vs_intervention':gained,
                         'intervention_only_vs_correct':lost,
                         'both_correct':retained,'both_wrong':64-retained-gained-lost,
                         'paired_correctness_delta':(gained-lost)/64,
                         'mcnemar_unadjusted_exact_p':p,
                         'bonferroni_three_predeclared_p':min(1.,3*p)}
    return {'schema':'hepta.stem.scienceqa-image-intervention-independent-review.v7',
            'source_sha256':SOURCE_SHA,'original_prediction_sha256':ORIGINAL_SHA,
            'producer_payload_sha256':sha(canonical(candidate)),
            'replayed_original_historical_case_count':64,
            'independently_checked_all_case_ids':True,
            'independently_joined_publisher_test_labels':True,
            'arms':scores,'predeclared_contrasts':contrasts,
            'independent_human_visual_necessity_adjudicated':False,
            'future_window_generalization_attested':False,
            'complete_lifecycle_cost_parity_attested':False,
            'promotion_authorized':False,'authority':'DENY_ALL'}

def main():
    from e3_scienceqa_contract import read_jsonl, validate_source,validate_labels
    from scienceqa_independent_rejudge_v5 import read_archive
    p=argparse.ArgumentParser()
    for key in ('sources','source-sha256','heldout-labels','heldout-labels-sha256',
                'original-archive','producer','producer-seal','output'):
        p.add_argument('--'+key,required=True)
    a=p.parse_args()
    need(a.source_sha256==SOURCE_SHA and a.heldout_labels_sha256==HELD_SHA,
         'unregistered independent original source and labels')
    source=read_jsonl(Path(a.sources),SOURCE_SHA)
    validate_source(source)
    labels=read_jsonl(Path(a.heldout_labels),HELD_SHA)
    validate_labels(source,labels,{'test'})
    producer=Path(a.producer)
    need(producer.is_file() and not producer.is_symlink() and
         0<producer.stat().st_size<=200_000,'missing or oversize source-free producer seal')
    producer_bytes = producer.read_bytes()
    verify_prelabel_seal(Path(a.producer_seal), producer, producer_bytes)
    result=review(parse(producer_bytes),source,labels,read_archive(Path(a.original_archive)))
    target=Path(a.output)
    need(not target.exists() and not target.is_symlink(),'create-only independent review')
    with target.open('xb') as handle:
        handle.write(canonical(result));handle.flush();os.fsync(handle.fileno())
    print('E3 V7 ORIGINAL PHYSICAL IMAGE INTERVENTION REVIEWED / DENY_ALL')

if __name__=='__main__':
    main()
