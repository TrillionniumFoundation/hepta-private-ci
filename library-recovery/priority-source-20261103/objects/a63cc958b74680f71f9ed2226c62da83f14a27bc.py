"""P3 input pairing and leakage checks for four-modality real-data protocols.

Caller must verify actual licensed media bytes, source chain-of-custody,
annotations and existence separately. A digest-only record is never proof
that real text/images/audio/video are present or correctly aligned.
"""
import math
import re
from collections import defaultdict

SHA256=re.compile(r'^[0-9a-f]{64}$')
SPLITS=('train','validation','holdout')
MODALITIES=('text','image','audio','video')


def check_pairs(records):
    failures=[]
    seen_ids=set()
    entity_splits=defaultdict(set)
    scene_splits=defaultdict(set)
    asset_splits=defaultdict(set)
    for index,r in enumerate(records):
        required=('sample_id','entity_id','scene_id','split','t_start_sec','t_end_sec',
                  'asset_sha256','provenance')
        missing=[x for x in required if x not in r]
        if missing:
            failures.append(f'row {index}: missing {missing}')
            continue
        sid=r['sample_id']
        if not isinstance(sid,str) or not sid:
            failures.append(f'row {index}: missing sample id')
        elif sid in seen_ids:
            failures.append(f'row {index}: duplicate sample id {sid}')
        seen_ids.add(sid)
        if r['split'] not in SPLITS:
            failures.append(f'row {index}: invalid split')
        else:
            entity_splits[r['entity_id']].add(r['split'])
            scene_splits[r['scene_id']].add(r['split'])
        a,b=r['t_start_sec'],r['t_end_sec']
        if not (isinstance(a,(int,float)) and isinstance(b,(int,float))
                and math.isfinite(a) and math.isfinite(b) and 0<=a<b):
            failures.append(f'row {index}: invalid timestamp window')
        if not r['provenance'] or not isinstance(r['provenance'],str):
            failures.append(f'row {index}: missing source provenance')
        assets=r['asset_sha256']
        if not isinstance(assets,dict):
            failures.append(f'row {index}: assets not a dict')
            continue
        for mod in MODALITIES:
            digest=assets.get(mod)
            if not isinstance(digest,str) or not SHA256.fullmatch(digest):
                failures.append(f'row {index}: missing valid {mod} digest')
            elif r['split'] in SPLITS:
                asset_splits[digest].add(r['split'])
    for typ,groups in (('entity',entity_splits),('scene',scene_splits),
                       ('media_digest',asset_splits)):
        for identity,splits in groups.items():
            if len(splits)>1:
                failures.append(f'{typ} leaks across splits: {identity}')
    return {'metadata_valid':len(failures)==0,'failures':failures,
            'real_media_verified':False,'four_modality_alignment_proven':False,
            'production_evidence_accepted':False}
