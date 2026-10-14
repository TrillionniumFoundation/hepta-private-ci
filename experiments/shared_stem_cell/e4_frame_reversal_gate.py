#!/usr/bin/env python3
"""Real frame-BYTES reversal check, not real video model or NDU verification.

Requires the local approved frame files; self-reported order hashes alone never
prove a reversal. This does not decode video or authenticate the video owner.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA='hepta.e4-frame-order-pairs.v1'
MAX_FILE=4*1024*1024
MAX_PAIRS=1000
SPLITS=('test','future1','future2','future3')
class Invalid(ValueError):pass

def digest(s):
    if type(s) is not str or len(s)!=64 or s=='0'*64 or any(c not in '0123456789abcdef' for c in s):
        raise Invalid('invalid nonzero SHA256')
    return s

def stable(s):
    if type(s) is not str or not 1<=len(s)<=128 or not all(c.isascii() and (c.isalnum() or c in '._:-') for c in s):
        raise Invalid('invalid stable ID')
    return s

def _pairs(pairs):
    out={}
    for key,value in pairs:
        if key in out:raise Invalid('duplicate JSON field')
        out[key]=value
    return out

def read(path):
    raw=Path(path).read_bytes()
    if not 0<len(raw)<=8*1024*1024:raise Invalid('invalid manifest byte budget')
    return json.loads(raw,object_pairs_hook=_pairs,parse_constant=lambda _:(_ for _ in ()).throw(Invalid('nonfinite JSON'))),hashlib.sha256(raw).hexdigest()

def frame_hash(root,relative):
    if type(relative) is not str or '\\' in relative or not relative or len(relative)>200:
        raise Invalid('unsafe frame name')
    rel=Path(relative)
    if rel.is_absolute() or '..' in rel.parts or rel.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):
        raise Invalid('unsafe frame path')
    pos=root
    for part in rel.parts:
        pos=pos/part
        if pos.is_symlink():raise Invalid('symlink in frame path')
    if not pos.is_file() or not pos.resolve().is_relative_to(root.resolve()):
        raise Invalid('frame outside approved root')
    if not 0<pos.stat().st_size<=MAX_FILE:raise Invalid('invalid frame byte size')
    with pos.open('rb') as file:
        raw=file.read(MAX_FILE+1)
    if len(raw)>MAX_FILE:raise Invalid('frame enlarged during read')
    return hashlib.sha256(raw).hexdigest()

def probability(p):
    if type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1:
        raise Invalid('invalid probability')
    return float(p)

def review(manifest,root):
    if type(manifest) is not dict or manifest.get('schema')!=SCHEMA or manifest.get('authority')!='DENY_ALL' or manifest.get('production_promotion_permitted') is not False:
        raise Invalid('unregistered or authorized E4 manifest')
    if root.is_symlink() or not root.is_dir():raise Invalid('unsafe approved frame root')
    scope=stable(manifest.get('scope'))
    for key in ('plan_sha256','source_sha256','temporal_model_sha256','frame_preprocessor_sha256'):
        digest(manifest.get(key))
    pairs=manifest.get('pairs')
    if type(pairs) is not list or not 1<=len(pairs)<=MAX_PAIRS:raise Invalid('missing bounded pairs')
    groups=set();ids=set();windows={key:[] for key in SPLITS};paired=[]
    for item in pairs:
        if type(item) is not dict or set(item)!= {'pair_id','scope','source_group','split','observed_at','source_video_sha256','question_sha256','forward','reversed','labels','predictions'}:
            raise Invalid('missing pair fields')
        ident=stable(item['pair_id']);group=stable(item['source_group']);split=item['split']
        if ident in ids or group in groups or item['scope']!=scope or split not in SPLITS:
            raise Invalid('duplicate or cross-scope pair')
        ids.add(ident);groups.add(group)
        ts=item['observed_at']
        if type(ts) not in (int,float) or not math.isfinite(ts) or ts<=0:
            raise Invalid('invalid source time')
        windows[split].append(float(ts))
        digest(item['source_video_sha256']);digest(item['question_sha256'])
        sides=[]
        for tag in ('forward','reversed'):
            f=item[tag]
            if type(f) is not dict or set(f) != {'files','frame_sha256s'}:
                raise Invalid('missing source frame identities')
            names=f['files'];sha=f['frame_sha256s']
            if type(names) is not list or type(sha) is not list or not 3<=len(names)<=32 or len(names)!=len(sha):
                raise Invalid('invalid sampled frame count')
            if len(set(names))!=len(names):raise Invalid('duplicate source frame')
            observed=[]
            for path,expected in zip(names,sha):
                digest(expected)
                actual=frame_hash(root,path)
                if actual!=expected:raise Invalid('frame bytes differ from declared digest')
                observed.append(actual)
            sides.append(observed)
        forward,reversed_=sides
        if len(set(forward))!=len(forward) or reversed_!=forward[::-1]:
            raise Invalid('not exactly reversed sampled frame bytes')
        labels=item['labels'];preds=item['predictions']
        if type(labels) is not dict or set(labels)!={'forward','reversed'} or (labels['forward'],labels['reversed']) not in ((0,1),(1,0)):
            raise Invalid('counterfactual labels are not opposite binary tasks')
        if type(preds) is not dict or set(preds)!={'order_invariant','frozen_temporal','learned_temporal'}:
            raise Invalid('missing matched temporal controls')
        scored={}
        for arm,v in preds.items():
            if type(v) is not dict or set(v)!={'forward','reversed','prelabel_sealed'} or v['prelabel_sealed'] is not True:
                raise Invalid('missing prelabel seal claim')
            a=probability(v['forward']);b=probability(v['reversed'])
            if arm=='order_invariant' and abs(a-b)>1e-6:
                raise Invalid('order-insensitive baseline changes under frame reversal')
            scored[arm]={'both_correct':(a>=.5)==bool(labels['forward']) and (b>=.5)==bool(labels['reversed']),
                         'correct_predictions':int((a>=.5)==bool(labels['forward']))+int((b>=.5)==bool(labels['reversed']))}
        paired.append((split,scored))
    for old,new in zip(SPLITS,SPLITS[1:]):
        if windows[old] and windows[new] and max(windows[old])>=min(windows[new]):
            raise Invalid('future source times overlap')
    report={}
    for split in SPLITS:
        subset=[x for s,x in paired if s==split]
        if not subset:continue
        report[split]={'pairs':len(subset),'order_reversal_verified_from_local_frame_bytes':True,
                       'arms':{arm:{'both_correct_pairs':sum(int(x[arm]['both_correct']) for x in subset),
                                    'correct_orientations':sum(x[arm]['correct_predictions'] for x in subset)}
                               for arm in ('order_invariant','frozen_temporal','learned_temporal')}}
    return {'schema':'hepta.e4-frame-reversal-audit.v1','source_pairs':len(paired),
            'split_metrics':report,'source_frame_bytes_checked':True,
            'original_video_decode_or_origin_authenticated':False,
            'prelabel_prediction_seals_independently_authenticated':False,
            'model_weights_or_temporal_forwards_verified':False,
            'external_labels_or_future_ndu_verified':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--frames-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();doc,sha=read(a.manifest);result=review(doc,a.frames_root);result['manifest_sha256']=sha
    with a.output.open('x',encoding='utf8') as f:json.dump(result,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
