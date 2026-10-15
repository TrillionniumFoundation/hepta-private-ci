"""Physical, exact-output Stem feature fan-out over frozen Reader evidence tasks.

Experimental ONLY: no real owner-signed authorizer, no selection/production grant.
A host-supplied per-use callback is a research hook, NEVER a capability issuer.
All comparisons keep the original input, frozen Reader and full task roster.
"""
from __future__ import annotations

import hashlib
import math
import time
from collections import OrderedDict

import torch

from reader_support_causal import OBS, CONDITIONS, _good, condition_texts, digest, hex64, validate_plan

SCHEMA = 'hepta.reader.shared-feature-fanout.v1'
CONTEXT_SCHEMA = 'hepta.reader.fanout-context-claim.v1'


def context_claim(*, principal, scope, generation, authority_epoch, stem_sha256,
                  tokenizer_sha256, source_use_revision):
    context = dict(schema=CONTEXT_SCHEMA, principal=principal, scope=scope,
                   generation=generation, authority_epoch=authority_epoch,
                   stem_sha256=stem_sha256, tokenizer_sha256=tokenizer_sha256,
                   source_use_revision=source_use_revision)
    validate_context(context)
    return context


def validate_context(context):
    if (not isinstance(context,dict) or set(context) != {
            'schema','principal','scope','generation','authority_epoch','stem_sha256',
            'tokenizer_sha256','source_use_revision'}
        or context['schema']!=CONTEXT_SCHEMA
        or any(not isinstance(context[k],str) or not context[k]
               or len(context[k].encode('utf-8'))>128 for k in
               ('principal','scope','source_use_revision'))
        or any(type(context[k]) is not int or not 0<=context[k]<=2**63-1
               for k in ('generation','authority_epoch'))
        or not hex64(context['stem_sha256']) or not hex64(context['tokenizer_sha256'])):
        raise ValueError('complete bounded source/Stem/epoch identity required')
    return True


def checked_prior(plan, observations, reader_sha256):
    validate_plan(plan)
    if (not isinstance(observations,dict) or observations.get('schema')!=OBS
        or observations.get('observation_id') != digest({k:v for k,v in observations.items()
                                                          if k != 'observation_id'})
        or observations.get('plan_id')!=plan['plan_id']
        or observations.get('model_sha256')!=plan['model_sha256']
        or observations.get('panel_sha256')!=plan['panel_sha256']
        or observations.get('reader_weights_sha256')!=reader_sha256
        or observations.get('condition_order')!=list(CONDITIONS)
        or observations.get('original_prediction_replay_verified') is not True
        or observations.get('production_authorized') is not False
        or observations.get('authority')!='DENY_ALL'
        or not isinstance(observations.get('rows'),list)
        or len(observations['rows'])!=len(plan['rows'])):
        raise ValueError('original nonauthorizing frozen full-task receipt required')
    n=len(plan['rows'])
    if (type(observations.get('physical_encoder_calls')) is not int
        or observations['physical_encoder_calls']!=4*n
        or type(observations.get('physical_reader_calls')) is not int
        or observations['physical_reader_calls']!=4*n
        or type(observations.get('physical_query_calls')) is not int
        or observations['physical_query_calls']!=n):
        raise ValueError('unmatched original no-share physical work inventory')
    for source, prior in zip(plan['rows'],observations['rows'],strict=True):
        if (not isinstance(prior,dict)
            or prior.get('task_id')!=source['task_id']
            or prior.get('source_group')!=source['source_group']
            or prior.get('original_input_sha256')!=hashlib.sha256(source['evidence'].encode()).hexdigest()
            or not isinstance(prior.get('observations'),dict)
            or set(prior['observations'])!=set(CONDITIONS)):
            raise ValueError('original full task and condition census drift')
        for cond,text in condition_texts(source).items():
            point=prior['observations'][cond]
            if (not isinstance(point,dict) or set(point)!={'logits','probability','evidence_sha256'}
                or point['evidence_sha256']!=hashlib.sha256(text.encode()).hexdigest()
                or not isinstance(point['logits'],list) or len(point['logits'])!=2
                or any(type(x) not in (float,int) or not math.isfinite(x) for x in point['logits'])):
                raise ValueError('untrusted reference logits/content identity')
    return True


def _tensor_sha(value):
    if not _good(value) or value.ndim != 2:
        raise ValueError('cached feature tensor has invalid geometry')
    return hashlib.sha256(value.detach().contiguous().numpy().tobytes()).hexdigest()


def run_shared_fanout(plan, observations, *, encoder, question_encoder, reader,
                      reader_sha256, context, final_use_callback, max_cache_bytes=32*1024*1024,
                      tolerance=1e-5):
    """Return descriptive physical cost and deterministic original-logit parity.

    Each unique permitted (context, source, condition, exact input) has at most
    one cached immutable feature. A per-use host callback MUST run even on hits.
    No callback result is represented as an independently authenticated grant.
    """
    checked_prior(plan,observations,reader_sha256)
    validate_context(context)
    if (context['stem_sha256'] != plan['model_sha256']
        or not callable(encoder) or not callable(question_encoder) or not callable(reader)
        or not callable(final_use_callback)
        or type(max_cache_bytes) is not int or not 0<=max_cache_bytes<=256*1024*1024
        or type(tolerance) not in (int,float) or not math.isfinite(tolerance)
        or not 0<=tolerance<=1e-4):
        raise ValueError('full exact shared Encoder budget and host-use checks required')
    if isinstance(reader,torch.nn.Module):
        if reader.training or any(p.dtype!=torch.float32 or p.device.type!='cpu'
                                   or not torch.isfinite(p).all().item() for p in reader.parameters()):
            raise ValueError('frozen finite CPU Reader required')
    cache=OrderedDict()
    cached_bytes=0; physical_encoder=0; uses=0; hits=0; evictions=0; reader_calls=0
    query_calls=0; peak_cached_bytes=0; max_diff=0.0
    cost=dict(enc_ns=0,read_ns=0,query_ns=0,use_ns=0,hash_ns=0)
    distinct_keys=set();start=time.perf_counter_ns()
    for source,prior in zip(plan['rows'],observations['rows'],strict=True):
        qstart=time.perf_counter_ns()
        query_text=(source['question']+'\nCandidate answer: '+source['answer']+
                    '\nIs this candidate correct?')
        with torch.inference_mode():q=question_encoder(query_text)
        cost['query_ns']+=time.perf_counter_ns()-qstart
        query_calls+=1
        if not _good(q) or q.ndim!=1 or not 1<=len(q)<=4096:
            raise ValueError('shared Reader question feature invalid')
        for cond,text in condition_texts(source).items():
            source_digest=hashlib.sha256(text.encode()).hexdigest()
            key=digest(dict(context=context,source_group=source['source_group'],
                            condition=cond,source_sha256=source_digest))
            distinct_keys.add(key)
            use_start=time.perf_counter_ns()
            # Per-use validation is required on hits and misses, before return.
            # This callback is NOT an independent issuer or signed FinalUse proof.
            if final_use_callback(source['task_id'],source['source_group'],cond,key,context) is not True:
                raise ValueError('host did not admit this logical feature borrow')
            uses+=1
            cost['use_ns']+=time.perf_counter_ns()-use_start
            if key in cache:
                feature,original_bytes,original_sha=cache.pop(key)
                cache[key]=(feature,original_bytes,original_sha)
                hits+=1
            else:
                t=time.perf_counter_ns()
                with torch.inference_mode(): feature=encoder(text)
                cost['enc_ns']+=time.perf_counter_ns()-t
                physical_encoder+=1
                if (not _good(feature) or feature.ndim!=2
                    or not 1<=feature.shape[0]<=512 or feature.shape[1]!=len(q)):
                    raise ValueError('physical shared Encoder produced invalid token features')
                t=time.perf_counter_ns()
                original_sha=_tensor_sha(feature)
                cost['hash_ns']+=time.perf_counter_ns()-t
                original_bytes=feature.untyped_storage().nbytes()
                if original_bytes<=max_cache_bytes:
                    while cache and cached_bytes+original_bytes>max_cache_bytes:
                        _,removed=cache.popitem(last=False)
                        cached_bytes-=removed[1]
                        evictions+=1
                    cache[key]=(feature,original_bytes,original_sha)
                    cached_bytes+=original_bytes
                    peak_cached_bytes=max(peak_cached_bytes,cached_bytes)
            t=time.perf_counter_ns()
            with torch.inference_mode():out=reader(feature,q)
            cost['read_ns']+=time.perf_counter_ns()-t
            reader_calls+=1
            if not _good(out,(2,)):
                raise ValueError('shared-feature Reader output must be finite')
            t=time.perf_counter_ns()
            if _tensor_sha(feature)!=original_sha:
                raise ValueError('Reader mutated shared cached token features')
            cost['hash_ns']+=time.perf_counter_ns()-t
            logits=[float(x) for x in out]
            claimed=prior['observations'][cond]['logits']
            delta=max(abs(x-y) for x,y in zip(logits,claimed,strict=True))
            if delta>tolerance:
                raise ValueError('shared feature forward diverges from independently computed no-share logits')
            max_diff=max(max_diff,delta)
    n=len(plan['rows'])
    if (uses != 4*n or reader_calls != 4*n or query_calls!=n or hits+physical_encoder != 4*n
        or physical_encoder<len(distinct_keys)
        or cached_bytes>max_cache_bytes or peak_cached_bytes>max_cache_bytes):
        raise ValueError('shared tensor use/physical execution accounting invalid')
    result=dict(schema=SCHEMA,plan_id=plan['plan_id'],base_observation_id=observations['observation_id'],
        model_sha256=plan['model_sha256'],reader_weights_sha256=reader_sha256,
        execution_context_digest=digest(context),
        logical_feature_borrows=uses,per_use_callback_calls=uses,
        physical_encoder_calls=physical_encoder,distinct_source_bound_keys=len(distinct_keys),
        cache_hits=hits,cache_evictions=evictions,cache_max_bytes=max_cache_bytes,
        peak_cached_feature_bytes=peak_cached_bytes,physical_reader_calls=reader_calls,
        physical_query_calls=query_calls,
        reference_uncached_encoder_calls=4*n,
        descriptor_encoder_forward_reduction=(4*n-physical_encoder)/(4*n),
        max_abs_logit_difference=max_diff,
        measured_single_pass_wall_ns=max(1,time.perf_counter_ns()-start),
        component_wall_ns=cost,
        cache_independently_authorized=False,
        runtime_final_use_authenticated=False,
        real_pretrained_model_origin_authenticated=False,
        prospective_task_success_verified=False,
        model_learning_improvement_verified=False,
        full_lifecycle_cost_verified=False,
        production_authorized=False,authority='DENY_ALL')
    result['report_id']=digest(result)
    return result
