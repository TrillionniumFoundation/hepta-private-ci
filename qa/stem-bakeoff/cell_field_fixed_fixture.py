"""Pinned original classes and shared synthetic fixtures; never dataset loading."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parent
ORIGINALS=('cell_field_control.py','cell_field_state.py','cell_learning_models.py','cell_learning_metrics.py')


def verify_original_sources():
    raw=(ROOT/'cell_field_fixed_sources.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!='3e654d6e2f4149134945121e25a515afe39a9e6b1eb20d4a856ce031107466e4':
        raise ValueError('pinned source contract changed')
    contract=json.loads(raw)
    if (set(contract)!={'schema','source_commit','source_tree','scope','files'}
            or contract['schema']!=1
            or contract['source_commit']!='c69e4e7ab55456e75476be4ca9a3bcaeaea1934c'
            or contract['source_tree']!='67a83f5bace75465fd1dc775292b70cf491f2c6b'
            or set(contract['files'])!=set(ORIGINALS)):
        raise ValueError('exact original source contract required')
    for filename,item in contract['files'].items():
        content=(ROOT/filename).read_bytes()
        if (set(item)!={'sha256','git_blob_sha1','bytes'} or len(content)!=item['bytes']
                or hashlib.sha256(content).hexdigest()!=item['sha256']
                or hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()!=item['git_blob_sha1']):
            raise ValueError('original source mismatch: '+filename)
    return contract


verify_original_sources()
from cell_learning_models import NumpyCellHead
from cell_field_state import CellTrainingState
from cell_field_control import build_reference
for filename in ORIGINALS:
    if Path(sys.modules[filename[:-3]].__file__).resolve()!=(ROOT/filename).resolve():
        raise RuntimeError('unverified preloaded module: '+filename)


def build_synthetic_references(modes=('linear','gated')):
    if modes not in (('linear',),('linear','gated')):raise ValueError('fixed synthetic modes only')
    refs={};rng=np.random.default_rng(4801)
    x=rng.normal(size=(12,8));y=np.tile(np.arange(4),3)
    old=rng.normal(size=(12,8));oy=np.roll(y,1)
    for mode in modes:
        state=CellTrainingState(NumpyCellHead(8,4,mode),bindings={'fixture':'synthetic-only'})
        state.step_count=3
        for name in state.names:
            state.m[name][:]=rng.normal(0,.003,state.m[name].shape);state.v[name][:]=.02
        refs[mode]=build_reference(state,x,y,((x,y),(old,oy)),horizon=3)
    return refs
