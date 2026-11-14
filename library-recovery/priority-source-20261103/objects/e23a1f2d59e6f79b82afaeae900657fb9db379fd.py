"""P3 paired four-modality *instance* retrieval diagnostics, not product proof.

Class-level retrieval can score 100% with color/frequency label shortcuts while
failing to recover WHICH image/audio/video/text belongs to an exact sample.
This evaluator requires unique sample IDs, entity/scene isolation across splits,
noncollapsed embeddings, and reports all 12 directional instance-level top-1
retrievals. The source datasets / real-world encoders cannot be authenticated
from embedding arrays and this evaluator NEVER grants a production admission.
"""
from __future__ import annotations
import hashlib
import itertools
from collections import defaultdict
import math
import numpy as np

MODALITIES=('text','image','audio','video')
SPLITS=('train','validation','holdout')


def inspect(samples:list[dict],min_holdout=4,noise_sigma=0.0,seed=2405):
    if not isinstance(samples,list) or not samples:
        raise ValueError('missing embedding records')
    if not isinstance(min_holdout,int) or min_holdout<2:
        raise ValueError('invalid minimum holdout')
    if not isinstance(noise_sigma,(int,float)) or not 0<=noise_sigma<=1 or not math.isfinite(noise_sigma):
        raise ValueError('invalid noise scale')
    issues=[]
    seen=set()
    per_split=defaultdict(list)
    dimension=None
    by_entity=defaultdict(set)
    by_scene=defaultdict(set)
    signatures=defaultdict(list)
    for i,r in enumerate(samples):
        if not isinstance(r,dict):issues.append(f'row {i}: not mapping');continue
        sid=r.get('sample_id');split=r.get('split')
        if not isinstance(sid,str) or not sid or sid in seen:
            issues.append(f'row {i}: empty/duplicate instance ID');continue
        seen.add(sid)
        if split not in SPLITS:
            issues.append(f'{sid}: unknown split');continue
        for key,registry in [('entity_id',by_entity),('scene_id',by_scene)]:
            x=r.get(key)
            if not isinstance(x,str) or not x:
                issues.append(f'{sid}: missing {key}')
            else:registry[x].add(split)
        embeddings=r.get('embeddings')
        if not isinstance(embeddings,dict) or set(embeddings)!=set(MODALITIES):
            issues.append(f'{sid}: 4 modalities required');continue
        clean={}
        for mod in MODALITIES:
            try:v=np.asarray(embeddings[mod],dtype=float)
            except (TypeError,ValueError):
                issues.append(f'{sid}/{mod}: invalid embedding');continue
            if v.ndim!=1 or v.size<2 or v.size>32768 or not np.all(np.isfinite(v)):
                issues.append(f'{sid}/{mod}: invalid shape/finite');continue
            norm=np.linalg.norm(v)
            if not np.isfinite(norm) or norm<1e-10:
                issues.append(f'{sid}/{mod}: zero/overflow embedding');continue
            if dimension is None:dimension=v.size
            if v.size!=dimension:
                issues.append(f'{sid}/{mod}: dimension mismatch');continue
            v=v/norm
            clean[mod]=v
            # Duplicated exact embeddings of distinct IDs imply feature collapse
            # or a split leak; do not score forced argmax ties as retrieval success.
            sig=hashlib.sha256(v.tobytes()).hexdigest()
            signatures[mod,sig].append((split,sid))
        if len(clean)==4:
            per_split[split].append({'sample_id':sid,'embeddings':clean})
    for name,registry in [('entity',by_entity),('scene',by_scene)]:
        for tag,splits in registry.items():
            if len(splits)>1:issues.append(f'cross-split {name} reuse: {tag}')
    for (mod,sig),ids in signatures.items():
        if len(ids)>1:
            suffix='cross-split ' if len({split for split,_ in ids})>1 else ''
            issues.append(f'{suffix}embedding collision {mod}: {len(ids)} instances')
    holdout=per_split['holdout']
    if len(holdout)<min_holdout:
        issues.append(f'only {len(holdout)} holdout instances < {min_holdout}')
    all_directed=[]
    if not issues:
        rng=np.random.default_rng(seed)
        n=len(holdout)
        for src,dst in itertools.permutations(MODALITIES,2):
            query=np.stack([r['embeddings'][src] for r in holdout]);
            target=np.stack([r['embeddings'][dst] for r in holdout]);
            if noise_sigma:
                query=query+rng.normal(0,noise_sigma,query.shape)
                query/=np.linalg.norm(query,axis=1,keepdims=True)
            sims=query@target.T
            winners=np.argmax(sims,axis=1)
            ties=np.sum(np.abs(sims-np.max(sims,axis=1,keepdims=True))<1e-10,axis=1)
            exact=(winners==np.arange(n)) & (ties==1)
            all_directed.append({'from':src,'to':dst,'holdout_count':n,
                                 'top1_instance_accuracy':float(np.mean(exact)),
                                 'ambiguous_top1_tie_count':int(np.sum(ties!=1))})
    return {'structurally_evaluable':not issues,
            'issues':issues,'n_holdout':len(holdout),
            'pair_directions':all_directed,
            'all_directed_instance_top1_at_least_90pct':bool(all_directed) and all(
                 row['top1_instance_accuracy']>=.9 for row in all_directed),
            'noise_sigma_embedding_level':noise_sigma,
            'strict_input_byte_provenance_verified':False,
            'true_natural_encoder_grounded':False,
            'production_evidence_accepted':False}
