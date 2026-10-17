"""Separate source-bound V26 historical pixel-intervention reviewer.

No pretrained model, fitting routine or publisher labels enter the producer's
conditional inference. This reviewer reopens publisher TEST labels after both
immutable prediction journals have been sealed, and reports aggregates only.
Historical, unblinded task cohort; not prospective scientific admission.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from math import fsum, log, comb
from pathlib import Path
import json
import io

from v26_real_pixel_lesion import (ARCHIVE_SHA, SOURCE_SHA, HELD_SHA, SCHEMA, DENY,
                                    THRESHOLD, Invalid, strict_archive, digest, canonical,
                                    validate_source_set, validate_probs, top1, safe_new, route_from_text, PRED_SHA)


def exact_mcnemar(a,b):
    n=a+b
    return 1.0 if n==0 else min(1.,2*sum(comb(n,j) for j in range(min(a,b)+1)) / (2**n))


def score_arm(rows, labels):
    y={r['id']:r for r in rows}
    if set(y)!=set(labels) or len(rows)!=64:
        raise Invalid('incomplete original source/label cases in candidate arm')
    count=0; br=[]; nll=[]; truths={}
    for rid, row in y.items():
        val=validate_probs(row['probabilities']);label=labels[rid]
        ok=top1(val)==label
        truths[rid]=ok;count+=int(ok)
        br.append(fsum((v-float(i==label))**2 for i,v in enumerate(val))/4)
        nll.append(-log(max(val[label],1e-12)))
    return {'correct':count,'total':len(y),'accuracy':count/len(y),'brier_4class':fsum(br)/len(br),
            'nll':fsum(nll)/len(nll)}, truths


def review(sources, labels, sealed, pred, archived):
    held=validate_source_set(sources,archived)
    label_map={r['id']:r['label'] for r in labels}
    if (len(labels)!=64 or set(label_map)!={r['id'] for r in held} or
        any(type(r['label']) is not int or not 0<=r['label']<4 or r['split']!='test' or
            r['group']!=archived[r['id']]['group'] for r in labels)):
        raise Invalid('publisher label rows invalid/incomplete')
    if (sealed.get('schema')!=SCHEMA or pred.get('schema')!=SCHEMA+'.sealed-interventions'
        or sealed.get('source_sha256')!=SOURCE_SHA or pred.get('source_sha256')!=SOURCE_SHA
        or sealed.get('route_threshold')!=THRESHOLD or sealed.get('visual_route_arm')!='bridge_image_only' or sealed.get('selected_test_count')!=21
        or sealed.get('original_held_label_sha256')!=HELD_SHA
        or sealed.get('production_authorized') is not False or pred.get('production_authorized') is not False
        or pred.get('frozen_conditional_sha256')!=digest(canonical(sealed))
        or sealed.get('unselected_test_pixels_never_loaded_before_seal') is not True
        or pred.get('identical_fit_weights_across_all_arms') is not True
        or sealed.get('authority_posture')!=DENY or pred.get('authority_posture')!=DENY
        or pred.get('original_archive_sha256')!=ARCHIVE_SHA
        or pred.get('true_independent_future_windows')!=0):
        raise Invalid('unsealed or non-fail-closed research evidence')
    # Validate actual ORIGINAL/BLACK/SWAPPED byte identities independently.
    transformations=pred.get('transform_bindings')
    if type(transformations) is not list or len(transformations)!=21:
        raise Invalid('missing all true pixel-intervention hashes')
    if {r.get('id') for r in transformations} != {r['id'] for r in sealed['predictions'] if r['selected']}:
        raise Invalid('pixel transformation roster not bound to conditional route')
    for slot in ('text_reference','full_reference','full_gate_diagnostic','conditional','black_pixels','shuffled_real_pixels'):
        rows=pred.get(slot)
        if not isinstance(rows,list) or len(rows)!=64:
            raise Invalid('missing one full model arm')
        seen=set()
        for row in rows:
            if set(row)!={'id','group','source_input_sha256','selected','probabilities'}:
                raise Invalid('changed predicted case schema')
            rid=row['id']
            if rid in seen or rid not in archived or type(row['selected']) is not bool or row['group']!=archived[rid]['group']:
                raise Invalid('wrong or duplicated original case identity')
            if row['source_input_sha256']!=archived[rid]['source_input_sha256']:
                raise Invalid('source image/text cannot be swapped in metadata')
            seen.add(rid);validate_probs(row['probabilities'])
    if pred.get('conditional')!=sealed.get('predictions'):
        raise Invalid('retroactively changed frozen conditional decisions')
    sel={r['id'] for r in pred['conditional'] if r['selected']}
    if len(sel)!=21 or sel!=route_from_text(archived):
        raise Invalid('precommitted 21 selected source IDs drifted')
    ref={r['id']:r['probabilities'] for r in pred['text_reference']}
    full={r['id']:r['probabilities'] for r in pred['full_reference']}
    cond={r['id']:r['probabilities'] for r in pred['conditional']}
    if any(cond[i]!=ref[i] for i in ref if i not in sel):
        raise Invalid('unselected source used a test image')
    if any(top1(full[i])!=top1(archived[i]['arms']['bridge_image_only']) for i in full):
        raise Invalid('original full model top-1 no longer matches historical outputs')
    if any(top1(ref[i])!=top1(archived[i]['arms']['text_only']) for i in ref):
        raise Invalid('original text top-1 no longer matches historical outputs')
    cost=pred.get('test_image_cost',{})
    for name,n,k in [('conditional',21,3),('full',64,8),('black',21,3),('shuffled',21,3)]:
        row=cost.get(name,{})
        if row.get('image_count')!=n or row.get('physical_dino_batches')!=k or type(row.get('wall_ns')) is not int or row['wall_ns']<=0:
            raise Invalid('fabricated source-bound image-forward accounting')
    # No uncertainty claims from correlated historical cases.
    results={};correct={}
    for arm in ('text_reference','full_reference','full_gate_diagnostic','conditional','black_pixels','shuffled_real_pixels'):
        results[arm],correct[arm]=score_arm(pred[arm],label_map)
    base=correct['text_reference']
    for arm in ('full_reference','full_gate_diagnostic','conditional','black_pixels','shuffled_real_pixels'):
        cur=correct[arm]
        gained=sum(not base[i] and cur[i] for i in base)
        harmed=sum(base[i] and not cur[i] for i in base)
        results[arm].update({'historical_rescues_vs_text':gained,'historical_harms_vs_text':harmed,
                             'historical_paired_mcnemar_unadjusted_p':exact_mcnemar(gained,harmed),
                             'changed_class_vs_full':sum(top1(next(x for x in pred[arm] if x['id']==rid)['probabilities'])!=top1(full[rid]) for rid in full)})
    if (results['text_reference']['correct']!=17 or results['full_reference']['correct']!=21 or results['full_gate_diagnostic']['correct']!=24 or
        results['conditional']['correct']!=17 or results['conditional']['historical_rescues_vs_text']!=5 or
        results['conditional']['historical_harms_vs_text']!=5):
        raise Invalid('V25 physically re-executed model historical parity failed')
    return {'schema':SCHEMA+'.independently-reviewed','decision':'HISTORICAL_PIXEL_LESION_ONLY_HOLD_NO_GO',
            'source_sha256':SOURCE_SHA,'original_prediction_sha256':PRED_SHA,
            'real_pixel_interventions_executed':True,'original_publisher_labels_reopened_after_seal':True,
            'publisher_label_sha256':HELD_SHA,'original_historical_test_cases':64,
            'precommitted_selected_test_images':21,
            'physical_conditional_dino_batches':cost['conditional']['physical_dino_batches'],
            'physical_full_test_dino_batches':cost['full']['physical_dino_batches'],
            'conditional_test_image_wall_ns':cost['conditional']['wall_ns'],
            'full_test_image_wall_ns':cost['full']['wall_ns'],
            'physical_traincal_visual_batches':sealed['training_image_cost']['physical_dino_batches'],
            'original_model_parity_max_abs':pred['max_abs_compatibility_drift_vs_archived_original'],
            'paired_original_scores':results,
            'original_externally_human_adjudicated_modality_necessity':False,
            'source_custody_independent':False,'true_prospective_window_count':0,
            'matched_total_lifecycle_cpu_rss_gpu_energy':False,
            'production_authorized':False,'scientific_promotion_authorized':False,
            'stem_winner_verified':False,'authority_posture':DENY}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--held-labels',type=Path,required=True)
    ap.add_argument('--archive',type=Path,required=True)
    ap.add_argument('--model-output',type=Path,required=True)
    ap.add_argument('--images',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if digest(a.source.read_bytes())!=SOURCE_SHA or digest(a.held_labels.read_bytes())!=HELD_SHA:
        raise Invalid('original source/held labels changed; cannot score')
    _,archived=strict_archive(a.archive)
    from e3_scienceqa_contract import read_jsonl,validate_source,validate_labels
    sources=read_jsonl(a.source,SOURCE_SHA);validate_source(sources)
    labels=read_jsonl(a.held_labels,HELD_SHA);validate_labels(sources,labels,{'test'})
    sealed_file=a.model_output/'sealed-conditional-before-full-images.json'
    second_file=a.model_output/'sealed-interventions-before-labels.json'
    if sealed_file.is_symlink() or second_file.is_symlink():raise Invalid('unsafe source journals')
    sealed=json.loads(sealed_file.read_bytes());pred=json.loads(second_file.read_bytes())
    from PIL import Image
    from e3_scienceqa_contract import read_pinned
    donors=[]
    held=validate_source_set(sources,archived)
    by_id={r['id']:r for r in held}
    for meta in pred.get('transform_bindings',[]):
        r=by_id.get(meta.get('id'))
        donor=by_id.get(meta.get('donor_id'))
        if r is None or donor is None or donor['id']==r['id'] or donor['group']==r['group'] or donor['image']!=meta.get('donor_image_sha256') or r['image']!=meta.get('source_image_sha256'):
            raise Invalid('forged shuffled pixel input identity')
        raw=read_pinned(a.images/r['image'],r['image'],maximum=8*1024*1024)
        swap=read_pinned(a.images/donor['image'],donor['image'],maximum=8*1024*1024)
        with Image.open(io.BytesIO(raw)) as image:
            image.load();mask=Image.new('RGB',image.size,(0,0,0));buff=io.BytesIO();mask.save(buff,format='PNG')
        if digest(buff.getvalue())!=meta.get('masked_input_sha256') or digest(swap)!=meta.get('donor_image_sha256') or r['image']==donor['image']:
            raise Invalid('forged black/shuffled original pixel bytes')
        donors.append(donor['id'])
    if len(donors)!=21:raise Invalid('missing transformed-image physical reference')
    safe_new(a.output,review(sources,labels,sealed,pred,archived))

if __name__=='__main__': main()
