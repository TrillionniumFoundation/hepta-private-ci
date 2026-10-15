#!/usr/bin/env python3
"""P0 V6 independent cold pretrained Encoder re-forward (research, DENY_ALL).

The second worker loads pinned original pretrained weights, encodes a predeclared,
label-blind source-disjoint subset, and checks Q24 features independently against
V5 source-paired archive. Not a publisher signature, device attestation, evaluation
of held labels, or authority to deploy. Real CLI has NO synthetic model fallback.
"""
from __future__ import annotations

import argparse
import math
import resource
import time
from pathlib import Path

from p0_multirc_semantic_material import Invalid, canonical, read, save, sha, validate
from p0_physical_replay_v5 import (MODEL_WIDTHS, independent_numeric_replay,
                                    _ensure_hash)
from p0_multirc_semantic_review import REVISIONS
from p0_question_only_head import matched_pairs

SCHEMA='hepta.p0.original-cold-pretrained-q24-replay.v1'
SELECTION='sha256-panel-source-pair-2-groups-per-split-v1'
SPLITS=('train','calibration','test')
PAIRS_PER_SPLIT=2
MAX_Q24_DELTA=2  # registered before physical forward, never tune from held outputs
Q24=1 << 24


def checked_probe(fit,blind):
    """Choose exactly 2 source-distinct question/candidate pairs per split.

    Selection uses immutable public case IDs, source group and panel ID, NEVER
    original answer labels, head probabilities or downstream score margins.
    """
    validate(fit,blind)
    paired=matched_pairs(fit,blind)
    panel=fit['metadata']['panel_id']
    out=[]
    for split in SPLITS:
        rows=paired[split]
        ranked=sorted(rows,key=lambda pair:(sha(f'{SELECTION}:{panel}:{split}:{pair[0]["case_id"]}'.encode()),pair[0]['case_id']))
        chosen=[];source_groups=set()
        for original,prior in ranked:
            if (original['source_group'] in source_groups or original['split']!=split
                    or prior['split']!=split or original['condition']!='original'
                    or prior['condition']!='no_evidence'):
                continue
            chosen.extend((original,prior))
            source_groups.add(original['source_group'])
            if len(source_groups)==PAIRS_PER_SPLIT:
                break
        if len(source_groups)!=PAIRS_PER_SPLIT:
            raise Invalid('not enough original independent source groups to probe')
        out.extend(chosen)
    if len(out)!=2*PAIRS_PER_SPLIT*len(SPLITS) or len({r['case_id'] for r in out})!=len(out):
        raise Invalid('missing source/group/question contrast in registered probe')
    if any('label' in r for r in out if r['split']=='test'):
        raise Invalid('a future human label crossed the blind test boundary')
    return out


def review_cold_vectors(fit,blind,report,model,replay_dir,selected,actual_vectors,
                        actual_tokens,actual_digests,actual_physical):
    """Independent Q24-value comparison after *real* cold frozen model invocation.

    The verifier takes measured arrays for isolated unit tests. The executable CLI
    below ALWAYS calls the original pinned E1 pretrained loader directly.
    """
    import numpy as np
    from safetensors.numpy import load_file

    if canonical(selected)!=canonical(checked_probe(fit,blind)):
        raise Invalid('cold probe selector deviates from registered original source and splits')
    if model not in MODEL_WIDTHS or type(report) is not dict:
        raise Invalid('unregistered trained-model replay subject')
    if (report.get('model')!=model or report.get('model_revision')!=REVISIONS[model]
            or report.get('authority')!='DENY_ALL'
            or report.get('production_promotion_permitted') is not False
            or report.get('actual_pretrained_local_weights_claimed') is not True):
        raise Invalid('unqualified physical model or wrong original revision')
    # Independent numeric Head replay must pass first, using *original* artifacts.
    independent_numeric_replay(replay_dir,fit,blind,report,model=model)
    original=load_file(str(Path(replay_dir)/'features.safetensors'))
    expected_matrix=original.get('features_q24_fp32')
    full_ids=[r['case_id'] for r in fit['cases']+blind['cases']]
    if not isinstance(expected_matrix,np.ndarray) or expected_matrix.shape!=(len(full_ids),MODEL_WIDTHS[model]):
        raise Invalid('inconsistent frozen original materialized feature matrix')
    expected_by_id={cid:expected_matrix[i] for i,cid in enumerate(full_ids)}
    ids=[r['case_id'] for r in selected]
    if (len(ids)!=len(set(ids)) or type(actual_vectors) is not dict or
            type(actual_tokens) is not dict or type(actual_digests) is not dict or
            set(actual_vectors)!=set(ids) or set(actual_tokens)!=set(ids) or set(actual_digests)!=set(ids)):
        raise Invalid('missing/synthetic/duplicated cold pretrained forward samples')
    profile=report.get('complete_source_profiles')
    if type(profile) is not dict or profile.get('physical_encoder_api_requests')!=len(full_ids):
        raise Invalid('original physical model-forward census is unavailable')
    original_tokens=profile.get('physical_token_counts_by_case')
    if type(original_tokens) is not dict or set(original_tokens)!=set(full_ids):
        raise Invalid('unsealed per-input original physical token counts')
    if type(actual_physical) is not dict or actual_physical.get('local_model_api_requests')!=len(ids):
        raise Invalid('cold provider call census does not match submitted cases')
    if type(actual_physical.get('physical_transformer_forward_count_attested')) is not bool or actual_physical.get('physical_transformer_forward_count_attested') is not False:
        raise Invalid('cannot invent a physical forward count or independent worker signature')
    cold_load=actual_physical.get('load_ms')
    if type(cold_load) not in (float,int) or not math.isfinite(cold_load) or cold_load<=0:
        raise Invalid('no paid original pretrained cold model load')
    durations=actual_physical.get('encode_ms_by_case')
    if type(durations) is not dict or set(durations)!=set(ids):
        raise Invalid('cold CPU feature-forward durations incomplete')
    if model=='mmbert_small':
        if (actual_physical.get('mmbert_all_serialized_weights_byte_verified') is not True or
            actual_physical.get('mmbert_whole_pretrained_checkpoint_sha256')!=profile.get('source_checkpoint_sha256') or
            _ensure_hash(profile.get('source_checkpoint_sha256')) != profile.get('source_checkpoint_sha256')):
            raise Invalid('mmBERT cold run lacks original full-source tensor proof')
    rows=[];maximum=0;exact=0
    for r in selected:
        cid=r['case_id']
        n=actual_tokens[cid]
        if type(n) is not int or not 1<=n<=512 or n!=original_tokens[cid]:
            raise Invalid('source-scoped actual tokenizer count differs from original')
        if (type(actual_digests[cid]) is not str or len(actual_digests[cid])!=64 or
                any(v not in '0123456789abcdef' for v in actual_digests[cid])):
            raise Invalid('missing actual pinned-model output feature hash')
        d=durations[cid]
        if type(d) not in (int,float) or not math.isfinite(d) or d<=0:
            raise Invalid('no measured cold Encoder work')
        array=np.asarray(actual_vectors[cid],dtype=np.float64)
        if array.shape!=(MODEL_WIDTHS[model],) or not bool(np.isfinite(array).all()) or bool((np.abs(array)>8).any()):
            raise Invalid('invalid new cold pretrained latent geometry or values')
        # Both parties quantize via registered original Q24; never evaluate labels.
        new_q=np.rint(array*Q24)
        stored_q=np.rint(expected_by_id[cid].astype(np.float64)*Q24)
        max_q=int(np.max(np.abs(new_q-stored_q)))
        if max_q>MAX_Q24_DELTA:
            raise Invalid('cold pretrained Encoder re-forward disagrees with the original physically archived features')
        maximum=max(maximum,max_q); exact+=int(max_q==0)
        rows.append({'case_id':cid,'source_group':r['source_group'],
                     'source_split':r['split'],'condition':r['condition'],
                     'token_count':n,'max_difference_q24_units':max_q,
                     'observed_encoder_ms':float(d)})
    if len(rows)!=2*PAIRS_PER_SPLIT*len(SPLITS):
        raise Invalid('incomplete cold physical probe study')
    return {'schema':SCHEMA,'model':model,'revision':REVISIONS[model],
            'selection_protocol':SELECTION,'cold_probed_case_count':len(rows),
            'source_distinct_pairs_per_split':PAIRS_PER_SPLIT,
            'actual_original_checkpoint_loader_invoked_in_second_process':True,
            'actual_original_model_source_independently_signed':False,
            'physical_gpu_worker_attestation':False,
            'original_training_reexecuted':False,'original_human_held_labels_accessed':False,
            'max_q24_disagreement':maximum,'exact_feature_match_cases':exact,
            'registered_max_q24_difference':MAX_Q24_DELTA,
            'cold_model_load_ms':float(cold_load),
            'cold_feature_forward_ms':sum(float(durations[k]) for k in ids),
            'cold_probe_rows':rows,'model_selected':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def real_cold_run(fit,blind,report,model,replay_dir,compact_checkout,gemma_checkout,gemma_manifest):
    if model not in MODEL_WIDTHS:
        raise Invalid('only original three frozen pretrained Stem owners are admitted')
    selected=checked_probe(fit,blind)
    # NEVER replace this loader with a generated stub or backend alias in a hosted run.
    from e1_public_triplet_real_cpu import encode_pretrained
    begin=time.perf_counter_ns();cpu=time.process_time_ns()
    values,tokens,digests,physical=encode_pretrained(selected,model,
              compact_checkout,gemma_checkout,gemma_manifest)
    receipt=review_cold_vectors(fit,blind,report,model,replay_dir,
                                selected,values,tokens,digests,physical)
    receipt.update({'cold_total_process_wall_ms':(time.perf_counter_ns()-begin)/1e6,
                    'cold_total_process_cpu_ms':(time.process_time_ns()-cpu)/1e6,
                    'cold_process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024})
    if receipt['cold_feature_forward_ms']>receipt['cold_total_process_wall_ms']+5:
        raise Invalid('fabricated or inconsistent cold elapsed work')
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('fit','blind','granite-97m-r2','mmbert-small','embeddinggemma-2-text','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--replay-root',type=Path,required=True)
    p.add_argument('--compact-checkout',type=Path,required=True)
    p.add_argument('--gemma-checkout',type=Path,required=True)
    p.add_argument('--gemma-manifest',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('cold pretrained-result must be create-only')
    fit,blind=read(a.fit),read(a.blind)
    validate(fit,blind)
    out={}
    # All three real models required; a partially succeeded physical run is blocked.
    for model in MODEL_WIDTHS:
        filename={'granite_97m_r2':a.granite_97m_r2,'mmbert_small':a.mmbert_small,
                  'embeddinggemma_2_text':a.embeddinggemma_2_text}[model]
        receipt=real_cold_run(fit,blind,read(filename),model,
                a.replay_root/f'{model}.replay',a.compact_checkout,
                a.gemma_checkout,a.gemma_manifest)
        out[model]=receipt
    save(a.output,{'schema':'hepta.p0.three-real-cold-encoder-replay.v1',
                   'models':out,'new_original_human_labels_accessed':False,
                   'source_model_origin_independently_signed':False,
                   'model_selection_permitted':False,'production_promotion_permitted':False,
                   'authority':'DENY_ALL'})

if __name__=='__main__':main()
