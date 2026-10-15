"""Unprivileged E5 sparse two-wave CAS: content-addressed safetensors, fail-closed.

Real CPU Torch SGD on *synthetic* Q24 input/labels. Not production Worker,
filesystem power-loss certification, distributed CAS, WAL or FinalUse.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid
from safetensors.torch import load as safe_load, save as safe_save
import torch

from e5_continual_sparse_checkpoint import (
    Invalid, config, fresh, wave, schedule, SHAPES, state_hash, freeze,
)
from e5_crash_atomic_store import (
    ZERO, FAILPOINTS, _lock, _immutable, _read, _dirsync, _inject, canonical,
    parse, sha, hexdigest, stable,
)

SCHEMA = 'hepta.e5.two-wave-delta-cas.v1'
HEAD_SCHEMA = 'hepta.e5.two-wave-delta-cas-head.v1'
MAX_DELTA = 128 * 1024 * 1024
MAX_MANIFEST = 8192


def _validate_identity(cfg: dict, epoch: int) -> dict:
    if type(cfg) is not dict or set(cfg) != {'cells','active','seed','scope','fence','source'}:
        raise Invalid('unregistered sparse Cell config')
    approved = config(cfg['cells'], cfg['active'], cfg['seed'], cfg['scope'], cfg['fence'], cfg['source'])
    if type(epoch) is not int or epoch < 1:
        raise Invalid('missing positive authority epoch')
    return approved


def _delta(state, cfg, wave_number):
    selected = schedule(cfg, wave_number)
    idx = selected.tolist()
    if len(set(idx)) != cfg['active']:
        raise Invalid('not exactly independently selected active Cells')
    tensors = {'idx': selected.contiguous().to(dtype=torch.int64),
               'steps': state['steps'].index_select(0, selected).contiguous()}
    for name in SHAPES:
        tensors['w.'+name] = state['weights'][name].index_select(0,selected).contiguous()
        tensors['m.'+name] = torch.stack([state['momentum'][int(i)][name]
            for i in idx]).contiguous()
    data = safe_save(tensors, metadata={'schema': SCHEMA, 'authority': 'DENY_ALL'})
    if not 0 < len(data) <= MAX_DELTA:
        raise Invalid('delta exceeds bounded safetensors byte budget')
    return data


def _apply_delta(state, cfg, number, data):
    if not 0 < len(data) <= MAX_DELTA:
        raise Invalid('delta size mismatch')
    try:
        blob=safe_load(data)
    except Exception as exc:
        raise Invalid('bad safetensors bytes') from exc
    if set(blob) != ({'idx','steps'} | {'w.'+n for n in SHAPES} | {'m.'+n for n in SHAPES}):
        raise Invalid('incomplete sparse state')
    expected=schedule(cfg,number)
    idx=blob['idx'];steps=blob['steps']
    if (idx.dtype!=torch.int64 or idx.shape!=expected.shape or
        not torch.equal(idx,expected) or steps.dtype!=torch.int64 or steps.shape!=expected.shape):
        raise Invalid('wrong Cell indices or optimizer steps')
    expected_steps=state['steps'].index_select(0,idx)+3
    if not torch.equal(steps,expected_steps):
        raise Invalid('reordered/duplicated/missing sparse SGD progress')
    for name,shape in SHAPES.items():
        w,m=blob['w.'+name],blob['m.'+name]
        if (w.shape!=(cfg['active'],*shape) or m.shape!=w.shape or
            w.dtype!=torch.float32 or m.dtype!=torch.float32 or
            not bool(torch.isfinite(w).all()) or not bool(torch.isfinite(m).all())):
            raise Invalid('bad per-Cell value or momentum')
    with torch.no_grad():
        state['steps'].index_copy_(0,idx,steps)
        for name in SHAPES:
            state['weights'][name].index_copy_(0,idx,blob['w.'+name])
        for j,k in enumerate(idx.tolist()):
            state['momentum'].setdefault(k,{})
            for name in SHAPES:state['momentum'][k][name]=blob['m.'+name][j].clone()
    state['generation']=number
    return state


def _manifest(root, digest):
    hexdigest(digest)
    payload=_read(root/'commits'/(digest+'.json'),MAX_MANIFEST)
    if sha(payload)!=digest:
        raise Invalid('commit manifest SHA mismatch')
    record=parse(payload)
    fields={'schema','wave','parent','blob_sha256','blob_bytes','state_sha256',
            'config','epoch','authority','production_promotion_permitted'}
    if type(record) is not dict or set(record)!=fields or record['schema']!=SCHEMA:
        raise Invalid('wrong complete manifest schema')
    cfg=_validate_identity(record['config'],record['epoch'])
    if (record['authority']!='DENY_ALL' or record['production_promotion_permitted'] is not False or
        type(record['wave']) is not int or record['wave'] not in (1,2) or
        type(record['blob_bytes']) is not int or not 0<record['blob_bytes']<=MAX_DELTA):
        raise Invalid('unrecognized manifest or false authority')
    hexdigest(record['parent'],allow_zero=True)
    hexdigest(record['blob_sha256']);hexdigest(record['state_sha256'])
    if (record['wave']==1 and record['parent']!=ZERO or
        record['wave']==2 and record['parent']==ZERO):
        raise Invalid('broken parent chain')
    return record


def _tip(root):
    head=root/'HEAD.json'
    if not head.exists():
        if head.is_symlink() or any((root/'commits').glob('*.json')):
            raise Invalid('selected HEAD missing or moved')
        return ZERO, None
    obj=parse(_read(head,1024))
    if type(obj) is not dict or set(obj)!={'schema','manifest_sha256'} or obj['schema']!=HEAD_SCHEMA:
        raise Invalid('changed or torn HEAD')
    digest=hexdigest(obj['manifest_sha256'])
    return digest,_manifest(root,digest)


def _read_chain(root, expected, cfg, epoch):
    tip,most_recent=_tip(root)
    if expected is not None and tip!=expected:
        raise Invalid('stale exact-parent compare-and-swap expected HEAD')
    if tip==ZERO:return tip,None,None
    sequence=[];record=most_recent
    for _ in range(2):
        if record['config']!=cfg or record['epoch']!=epoch:
            raise Invalid('revoked Scope/Generation/fence/model or source drift')
        sequence.append(record)
        if record['wave']==1:break
        record=_manifest(root,record['parent'])
    sequence.reverse()
    if [r['wave'] for r in sequence]!=list(range(1,len(sequence)+1)):
        raise Invalid('missing chronological commit chain')
    state=fresh(cfg)
    for r in sequence:
        raw=_read(root/'objects'/(r['blob_sha256']+'.safetensors'),MAX_DELTA)
        if len(raw)!=r['blob_bytes'] or sha(raw)!=r['blob_sha256']:
            raise Invalid('selected immutable delta changed')
        state=_apply_delta(state,cfg,r['wave'],raw)
        if state_hash(state)!=r['state_sha256']:
            raise Invalid('replayed sparse weights and momentum differ from exact saved state')
    return tip,most_recent,state


def commit(root, cfg, epoch, expected_tip, next_state, crash=None):
    cfg=_validate_identity(cfg,epoch)
    hexdigest(expected_tip,allow_zero=True)
    if crash is not None and crash not in FAILPOINTS:
        raise Invalid('unknown crash point')
    root=Path(root)
    tick=time.perf_counter_ns()
    with _lock(root):
        tip,current,previous=_read_chain(root,expected_tip,cfg,epoch)
        number=1 if current is None else current['wave']+1
        if number not in (1,2) or next_state['generation']!=number:
            raise Invalid('nonadvancing checkpoint generation')
        # Prove checkpoint is exactly a legitimate next wave from the recovered parent,
        # not merely a forged syntactically valid source report.
        proof=previous if previous is not None else fresh(cfg)
        wave(proof,cfg,number)
        if state_hash(proof)!=state_hash(next_state):
            raise Invalid('checkpoint lacks reproducible scoped training lineage')
        raw=_delta(next_state,cfg,number)
        body_sha=sha(raw)
        manifest={'schema':SCHEMA,'wave':number,'parent':tip,
                  'blob_sha256':body_sha,'blob_bytes':len(raw),'state_sha256':state_hash(next_state),
                  'config':cfg,'epoch':epoch,'authority':'DENY_ALL','production_promotion_permitted':False}
        manifest_raw=canonical(manifest);manifest_sha=sha(manifest_raw)
        _immutable(root/'objects',body_sha+'.safetensors',raw,'blob',crash)
        _immutable(root/'commits',manifest_sha+'.json',manifest_raw,'manifest',crash)
        # Only HEAD.json confers local visibility. Unreferenced immutable files are orphans.
        temporary=root/('.head-'+uuid.uuid4().hex)
        content=canonical({'schema':HEAD_SCHEMA,'manifest_sha256':manifest_sha})
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            cut=len(content)//2
            os.write(fd,content[:cut]);_inject(crash,'head_partial')
            os.write(fd,content[cut:]);os.fsync(fd);_inject(crash,'head_fsynced')
        finally:os.close(fd)
        os.replace(temporary,root/'HEAD.json');_inject(crash,'head_replaced')
        _dirsync(root);_inject(crash,'head_dirsynced')
    return {'schema':SCHEMA+'.commit-receipt','wave':number,'manifest_sha256':manifest_sha,
            'snapshot_bytes':len(raw),'full_head_fp32_bytes':cfg['cells']*9744*4,
            'wall_ms':(time.perf_counter_ns()-tick)/1e6,
            'worker_physical_evidence_authenticated':False,'production_promotion_permitted':False,
            'powerloss_or_wal_verified':False,'authority':'DENY_ALL'}


def restore(root,cfg,epoch):
    cfg=_validate_identity(cfg,epoch)
    begin=time.perf_counter_ns()
    with _lock(root):
        tip,record,state=_read_chain(root,None,cfg,epoch)
    if record is None:raise Invalid('no published checkpoint')
    return state,{'schema':SCHEMA+'.replay','manifest_sha256':tip,'wave':record['wave'],
                  'complete_head_parameters':cfg['cells']*9744,
                  'reconstruction_ms':(time.perf_counter_ns()-begin)/1e6,
                  'production_promotion_permitted':False,'native_worker_or_NDU_verified':False,
                  'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--store',type=Path,required=True)
    p.add_argument('--action',choices=('first','second','verify'),required=True)
    p.add_argument('--cells',type=int,choices=(64,256,1024,4096),default=64)
    p.add_argument('--active',type=int,default=8)
    p.add_argument('--seed',type=int,default=20261014)
    p.add_argument('--scope',default='e5.shadow')
    p.add_argument('--fence',default='a'*64)
    p.add_argument('--source',default='b'*64)
    p.add_argument('--epoch',type=int,default=1)
    p.add_argument('--crash',choices=FAILPOINTS)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    cfg=config(args.cells,args.active,args.seed,args.scope,args.fence,args.source)
    begin=time.perf_counter_ns()
    if args.action=='first':
        state=fresh(cfg);wave(state,cfg,1)
        receipt=commit(args.store,cfg,args.epoch,ZERO,state,args.crash)
    elif args.action=='second':
        state,prior=restore(args.store,cfg,args.epoch)
        if prior['wave']!=1:raise Invalid('already committed second wave')
        wave(state,cfg,2)
        receipt=commit(args.store,cfg,args.epoch,prior['manifest_sha256'],state,args.crash)
    else:
        state,receipt=restore(args.store,cfg,args.epoch)
        direct=fresh(cfg)
        for wave_number in range(1,receipt['wave']+1):wave(direct,cfg,wave_number)
        if state_hash(state)!=state_hash(direct):raise Invalid('checkpoint not identical to uninterrupted wave history')
        receipt['full_bank_replayed_bit_exact']=True
    receipt['whole_invocation_ms']=(time.perf_counter_ns()-begin)/1e6
    if args.output.exists():raise FileExistsError('create-only receipt')
    args.output.write_bytes(canonical(receipt)+b'\n')

if __name__=='__main__':main()
