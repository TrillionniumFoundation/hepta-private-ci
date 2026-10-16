"""V7.8 original MultiRC labels bound to a genuine archived V6 frozen split Cell.

The data/label admission contract can be tested without a pretrained Encoder;
that does NOT qualify fake latent features as Granite. The real CLI separately
requires the exact original Encoder bytes and old warmup output parity.
"""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import zipfile
import random
import time
from torch.nn import functional as F

import torch

from bridge_split_cell_v77 import (SplitBridgeCell,FrozenNewTaskCache,
    digest_parameters,fit_new_task_head, require)
from bridge_v78_original_calibration import original_bytes, case_id, digest, V6_SHA

TRAIN_ROWS=3909
TUNE_ROWS=827
TRAIN_SOURCES=64
TUNE_SOURCES=16
OLD_BINDING_SOURCES=64
SCHEMA='hepta.bridge.v78.original-human-label-frozen-cell.shadow.v1'
SAMPLING_ARMS=('row_uniform','source_balanced')


def roster(original_v6):
    """Read all original human labels from bytes pinned to the real V6 ZIP.

    No caller-provided targets are accepted. Tuning rows are returned for
    descriptive scoring only, never passed to the fit function.
    """
    with zipfile.ZipFile(io.BytesIO(original_bytes(original_v6))) as z:
        human=json.loads(z.read('reader-v5-independent-audit/natural-cases.json'))
        original=json.loads(z.read('reader-v6-bridge/all-cases.json'))
        require(set(human)=={'train','tune'} and
                set(original)=={'reader_train','internal_tune','fresh_combinations',
                                'fresh_vocabulary','verifier_fit'},
                'registered original source partitions required')
        tr,tu,old=human['train'],human['tune'],original['reader_train']
        require((len(tr),len(tu),len(old))==(TRAIN_ROWS,TUNE_ROWS,128),
                'complete original source training and tune rows required')
        trainids=tuple(case_id(r) for r in tr)
        tuneids=tuple(case_id(r) for r in tu)
        olds=tuple(case_id(r) for r in old)
        require(len(set(trainids))==TRAIN_ROWS and len(set(tuneids))==TUNE_ROWS
                and not set(trainids)&set(tuneids),
                'registered unique complete original source/case IDs required')
        a={r['source_hash'] for r in tr}
        b={r['source_hash'] for r in tu}
        c={r['source_hash'] for r in old}
        require(len(a)==TRAIN_SOURCES and len(b)==TUNE_SOURCES and len(c)==OLD_BINDING_SOURCES
                and not a&b and not a&c and not b&c,
                'original source-group separation required')
        for part in (tr,tu):
            require(all(type(r['label']) is int and r['label'] in (0,1)
                        and r['source_split']=='train' for r in part),
                    'original public train-only human binary MultiRC labels required')
        parents={}
        for seed in (41,47,53):
            p=f'reader-v6-bridge/seed-{seed}/bridge/'
            m=json.loads(z.read(p+'warmup-model.json'))
            weight=z.read(p+'warmup.pt')
            require(m['seed']==seed and m['architecture']['arm']=='bridge' and
                    m['parameter_count']==42562 and
                    hashlib.sha256(weight).hexdigest()==m['file_sha256'],
                    'exact source-bound frozen historical V6 warmup required')
            parents[seed]=dict(blob_sha256=m['file_sha256'],
                training_parameter_sha256=m['training_parameter_sha256'])
        return dict(schema=SCHEMA,original_v6_sha256=V6_SHA,
            train=tr,tune=tu,old=old,parents=parents,
            train_case_ids=trainids,tune_case_ids=tuneids,
            train_source_hashes=tuple(r['source_hash'] for r in tr),
            tune_source_hashes=tuple(r['source_hash'] for r in tu),
            old_source_hashes=tuple(r['source_hash'] for r in old),
            train_label_sha256=digest([r['label'] for r in tr]),
            tune_label_sha256=digest([r['label'] for r in tu]),
            tune_used_to_select_model=False,production_authorized=False)


def validate_train_cache(cell,cache,source,*,seed):
    """Exact data/parent provenance; SHA is not an issuer signature or feature proof."""
    require(type(cell) is SplitBridgeCell and type(cache) is FrozenNewTaskCache
            and type(seed) is int and seed in (41,47,53),
            'registered frozen Cell/cache and original seed required')
    require(source['schema']==SCHEMA and source['original_v6_sha256']==V6_SHA,
            'original archived source identity required')
    expected=source['parents'][seed]['training_parameter_sha256']
    require(cell.original_sha256==expected and digest_parameters(cell.parent)==expected,
            'wrong seed original V6 immutable warmup checkpoint')
    cache.validate()
    require(cache.frozen_model_sha256==expected and cache.source_scope=='train'
            and cache.case_ids==source['train_case_ids']
            and cache.source_hashes==source['train_source_hashes']
            and cache.hidden.shape==(TRAIN_ROWS,97)
            and not set(cache.source_hashes)&set(source['old_source_hashes'])
            and not set(cache.source_hashes)&set(source['tune_source_hashes']),
            'full source-aligned true-label TRAIN cache, without old/tune overlap, required')
    return True


def _fit_source_balanced(cell,cache,labels,*,seed,updates,learning_rate,batch_size,max_train_cpu_ns):
    """Every update observes B distinct original paragraph groups, one row each.

    Matched parameter/optimizer/step budget to row-uniform V7.7. This is not
    equal empirical example exposure or equal compute; the cohort shift is the
    proposed treatment and recorded as such.
    """
    from bridge_split_cell_v77 import PARAMETERS_PER_CELL
    import math
    require(cell.candidate_fitted is False and type(seed) is int and
            type(updates) is int and 1<=updates<=5000 and
            type(learning_rate) is float and 0<learning_rate<=.1 and
            type(batch_size) is int and 1<=batch_size<=64 and
            type(max_train_cpu_ns) is int and max_train_cpu_ns>0,
            'registered source-group balanced candidate training budget required')
    cache.validate();cell.check_frozen()
    require(labels.dtype==torch.long and labels.shape==(len(cache.case_ids),),
            'complete original human task labels required')
    grouped={}
    for i,source in enumerate(cache.source_hashes):
        grouped.setdefault(source,[]).append(i)
    keys=sorted(grouped)
    require(len(keys)==64 and batch_size<=len(keys),
            'original 64-source train groups and distinct paragraph batches required')
    initial_parent=digest_parameters(cell.parent)
    params=list(cell.new_head.parameters())
    require(sum(v.numel() for v in params)==PARAMETERS_PER_CELL and
            not set(map(id,params))&set(map(id,cell.parent.parameters())),
            'strict 1700-scalar independent Cell-only optimizer required')
    rng=random.Random('hepta-v78/source-balanced/'+str(seed))
    cell.new_head.train()
    opt=torch.optim.Adam(params,lr=learning_rate,foreach=False)
    began=time.process_time_ns();wall=time.perf_counter_ns()
    used={source:0 for source in keys}
    steps=[]
    for step in range(updates):
        require(time.process_time_ns()-began<max_train_cpu_ns,
                'source-balanced complete update CPU budget exceeded')
        groups=rng.sample(keys,batch_size)
        selected=[rng.choice(grouped[g]) for g in groups]
        for g in groups: used[g]+=1
        idx=torch.tensor(selected,dtype=torch.long)
        opt.zero_grad(set_to_none=True)
        pred=cell.new_head(cache.hidden[idx],cache.original_logits[idx])
        loss=F.cross_entropy(pred,labels[idx]);require(bool(torch.isfinite(loss)),
               'source-balanced loss must remain finite')
        loss.backward()
        require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in params),
                'all six Cell parameter gradients required')
        opt.step()
        require(all(bool(torch.isfinite(v).all()) for v in params),'finite Head state required')
        steps.append(tuple(selected))
    cell.check_frozen()
    require(digest_parameters(cell.parent)==initial_parent,'old parent mutated by source sampler')
    optimizer_bytes=sum(int(t.numel()*t.element_size()) for obj in opt.state.values()
                        for t in obj.values() if isinstance(t,torch.Tensor))
    cell.new_head.eval().requires_grad_(False);cell.candidate_fitted=True
    with torch.no_grad():
        baseline=int((cache.original_logits.argmax(-1)==labels).sum())
        now=int((cell.new_head(cache.hidden,cache.original_logits).argmax(-1)==labels).sum())
    return dict(schema=SCHEMA,status='trained_candidate_only',sampler='distinct_orig_paragraphs_per_step',
        source_balanced=True,parent_sha256=initial_parent,
        new_head_sha256=digest_parameters(cell.new_head),new_head_parameter_count=PARAMETERS_PER_CELL,
        train_only_before_correct=baseline,train_only_after_correct=now,
        logical_optimizer_updates=updates,accepted_optimizer_updates=updates,
        optimizer_tensor_bytes=optimizer_bytes,
        train_row_count=len(labels),train_unique_source_groups=len(keys),
        actual_frozen_reader_calls_to_build_cache=cache.encoded_reader_calls,
        repeated_encoder_forwards_during_head_training=0,
        real_granite_features_not_authenticated_here=True,
        old_reader_training_updates=0,
        sample_schedule_sha256=digest(steps),
        total_candidate_exposures=updates*batch_size,
        source_exposure_min=min(used.values()),source_exposure_max=max(used.values()),
        training_cpu_ns=time.process_time_ns()-began,
        training_wall_ns=time.perf_counter_ns()-wall,
        generalization_established=False,model_selected=False,production_authorized=False)


def fit_original_human_task(cell,cache,original,*,seed,updates=420,
                            learning_rate=0.04,batch_size=16,max_train_cpu_ns=60_000_000_000,
                            sampling_arm="row_uniform"):
    """Fit exactly one 1,700-param Head from actual original human labels ONLY.

    This function is a provenance-bound learning primitive, NOT a validation of
    the Encoder or cache origin; only the physically gated runner can claim
    actual pretrained feature execution.
    """
    require(sampling_arm in SAMPLING_ARMS,"only predeclared equal-update sampler arms allowed")
    source=roster(original)
    validate_train_cache(cell,cache,source,seed=seed)
    labels=torch.tensor([r['label'] for r in source['train']],dtype=torch.long)
    require(digest(labels.tolist())==source['train_label_sha256'],
            'human target label ordering/bytes changed')
    if sampling_arm=='row_uniform':
        receipt=fit_new_task_head(cell,cache,labels,updates=updates,seed=seed,
            learning_rate=float(learning_rate),batch_size=batch_size,
            max_train_cpu_ns=max_train_cpu_ns)
    else:
        receipt=_fit_source_balanced(cell,cache,labels,seed=seed,updates=updates,
            learning_rate=float(learning_rate),batch_size=batch_size,
            max_train_cpu_ns=max_train_cpu_ns)
    require(cell.parent.training is False and
            digest_parameters(cell.parent)==source['parents'][seed]['training_parameter_sha256'],
            'original old route changed by true-label Head fitting')
    return dict(schema=SCHEMA,scope='actual_archived_multirc_human_labels_train_only',
        sampling_arm=sampling_arm,physically_shared_frozen_reader=True,
        source_archive_sha256=V6_SHA,seed=seed,original_v6_parent=cell.original_sha256,
        natural_train_case_roster_sha256=digest(list(source['train_case_ids'])),
        natural_train_label_sha256=source['train_label_sha256'],
        train_source_groups=TRAIN_SOURCES,train_candidates=TRAIN_ROWS,
        tune_candidates_opened_for_model_selection=0,
        source_disjoint_future_window_verified=False,
        parent_original_weight_updates=0,parent_original_digests_unchanged=True,
        hidden_feature_origin_is_not_certified_by_this_function=True,
        real_granite_tokenbank_numeric_parity_claimed=False,
        real_new_task_generalization_claimed=False,
        production_authorized=False,model_selected=False,
        fitting=receipt)


def score_preexposed_tune(cell,source,hidden,old_logits,*,case_ids,source_hashes):
    """Descriptive old and new output scoring, never call during fitting.

    Only the REAL runner can assert those hidden features came from Granite.
    """
    from bridge_v78_original_calibration import scores
    require(cell.candidate_fitted and tuple(case_ids)==source['tune_case_ids']
            and tuple(source_hashes)==source['tune_source_hashes'],
            'complete exact prior-exposed natural tune source identity required')
    require(type(hidden) is torch.Tensor and hidden.shape==(TUNE_ROWS,97)
            and hidden.dtype==torch.float32 and
            type(old_logits) is torch.Tensor and old_logits.shape==(TUNE_ROWS,2)
            and old_logits.dtype==torch.float32 and
            torch.isfinite(hidden).all() and torch.isfinite(old_logits).all(),
            'correct finite original 97D data and 2 original logits required')
    with torch.no_grad():
        new_logits=cell.new_head(hidden,old_logits)
        old=old_logits.argmax(-1).tolist()
        updated=new_logits.argmax(-1).tolist()
    labels=[r['label'] for r in source['tune']]
    return dict(schema=SCHEMA,cohort='old_training_source_exposed_internal_tune_only',
        old_frozen=scores(labels,old,source['tune']),
        new_head=scores(labels,updated,source['tune']),
        always_positive=scores(labels,[1]*TUNE_ROWS,source['tune']),
        future_source_disjoint_verified=False,model_selected=False,
        production_authorized=False)
