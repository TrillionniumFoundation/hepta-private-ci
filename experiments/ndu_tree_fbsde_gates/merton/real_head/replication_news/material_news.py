"""Pinned archival source adapter. Coordinator separates labels; no custody claim."""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
import time
import zipfile
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
PREFIX = 'hepta-public-study/'
PROTOCOL_SHA = '5578624257ef38a25c12a1dffa24d861a92de5cdd8fef193029c689f20e67a2c'
PINS = {
 'model-source.json': 'f90e80e2d83e6c67b5590675f4661b7056db75b3b3d63512888481385ad9db4d',
 'acquisition.json': '499a041579c39b24ff97453010899ac45e58befe64e1130ea86b1a4f9694a90c',
 'manifest.json': 'ad9312a0c981b27468d572a4f6c28d453e320c52dfd31261f9d7617d06639b4a',
 'execution/frozen-features/manifest.json': '6d6e01804fc086e5bcb8a1d4133789845d0b35c5ea1daca0c82fad6f4d4e5842',
 'dataset.jsonl': '50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c',
 'execution/frozen-features/features.safetensors': 'e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490',
}
ARRAYS = {'x_train','y_train','x_cal','y_cal','x_holdout','train_ids','cal_ids','holdout_ids','cal_hashes'}

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def encode(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def loads(raw: bytes | str):
    def pairs(items):
        d = {}
        for k,v in items:
            if k in d: raise ValueError('duplicate JSON field')
            d[k] = v
        return d
    def reject(v): raise ValueError('nonfinite JSON constant: '+v)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)

def spec() -> dict:
    raw = (ROOT/'protocol.json').read_bytes()
    if sha(raw) != PROTOCOL_SHA: raise ValueError('frozen protocol changed')
    return loads(raw)

def write(path: Path, value: object) -> None:
    with path.open('xb') as f: f.write(encode(value))

def tensor(raw: bytes) -> np.ndarray:
    if len(raw) < 8: raise ValueError('truncated safetensors')
    n = struct.unpack('<Q', raw[:8])[0]
    if n > 10000 or n+8 > len(raw): raise ValueError('invalid tensor header')
    header = loads(raw[8:8+n])
    if set(header) != {'features'}: raise ValueError('unexpected tensors')
    t = header['features']
    if t != {'dtype':'F32','shape':[128,384],'data_offsets':[0,196608]}:
        raise ValueError('wrong tensor shape/dtype/offsets')
    if len(raw) != 8+n+196608: raise ValueError('truncated or extra tensor bytes')
    a = np.frombuffer(raw[8+n:],dtype='<f4').reshape(128,384).copy()
    if not np.isfinite(a).all(): raise ValueError('nonfinite features')
    return a

def original(archive: Path):
    p = spec(); raw = archive.read_bytes()
    if sha(raw) != p['archive_sha256']: raise ValueError('wrong original archive')
    with zipfile.ZipFile(archive) as z:
        if len(z.namelist()) != len(set(z.namelist())): raise ValueError('duplicate ZIP entries')
        b = {k:z.read(PREFIX+k) for k in PINS}
    if any(sha(b[k]) != v for k,v in PINS.items()): raise ValueError('original member changed')
    rows = [loads(line) for line in b['dataset.jsonl'].splitlines()]
    fm = loads(b['execution/frozen-features/manifest.json'])
    x = tensor(b['execution/frozen-features/features.safetensors'])
    if len(rows) != 128 or len(fm['rows']) != 128 or fm['contains_labels'] is not False:
        raise ValueError('feature census changed')
    seen_ids,seen_texts = set(),set()
    for r,m in zip(rows,fm['rows']):
        if any(r[k] != m[k] for k in ('case_id','cell','group','observed_at','scope','split')):
            raise ValueError('feature-to-source row mismatch')
        if type(r['label']) is not int or not 0 <= r['label'] < 4: raise ValueError('invalid source label')
        h = sha(r['text'].encode())
        if r['case_id'] in seen_ids or h in seen_texts: raise ValueError('duplicate identity or text')
        seen_ids.add(r['case_id']); seen_texts.add(h)
    parts = {s:[i for i,r in enumerate(rows) if r['split']==s] for s in ('train','calibration','holdout')}
    if [len(v) for v in parts.values()] != [64,32,32]: raise ValueError('split census changed')
    return rows,x,parts

def prepare(archive: Path, output: Path):
    c,w = time.process_time_ns(),time.perf_counter_ns()
    rows,x,parts = original(archive)
    output.mkdir(parents=True,exist_ok=False)
    arrays = {}
    for source,dest in [('train','train'),('calibration','cal'),('holdout','holdout')]:
        idx = parts[source]
        arrays['x_'+dest] = x[idx]
        arrays[dest+'_ids'] = np.array([rows[i]['case_id'] for i in idx])
        if source != 'holdout': arrays['y_'+dest] = np.array([rows[i]['label'] for i in idx],dtype=np.int64)
    arrays['cal_hashes'] = np.array([sha(rows[i]['text'].encode()) for i in parts['calibration']])
    np.savez(output/'worker.npz', **arrays)
    write(output/'scorer-labels.json', {rows[i]['case_id']:rows[i]['label'] for i in parts['holdout']})
    write(output/'receipt.json', {'schema':'hepta.news-material.v1','protocol_sha256':PROTOCOL_SHA,
        'archive_sha256':spec()['archive_sha256'],'member_sha256':PINS,
        'worker_sha256':sha((output/'worker.npz').read_bytes()),
        'held_label_sha256':sha((output/'scorer-labels.json').read_bytes()),
        'counts':[64,32,32],'source_identity_only_not_story_independence':True,
        'cpu_ns':time.process_time_ns()-c,'wall_ns':time.perf_counter_ns()-w})

def packet(path: Path):
    receipt = loads((path.parent/'receipt.json').read_bytes())
    if receipt['protocol_sha256'] != PROTOCOL_SHA or receipt['worker_sha256'] != sha(path.read_bytes()):
        raise ValueError('worker or protocol binding changed')
    with np.load(path,allow_pickle=False) as n:
        if set(n.files) != ARRAYS: raise ValueError('unknown worker field or heldout-label leak')
        a = {k:n[k].copy() for k in n.files}
    all_ids = []
    for s,n in [('train',64),('cal',32),('holdout',32)]:
        if a['x_'+s].shape != (n,384) or not np.isfinite(a['x_'+s]).all(): raise ValueError('bad feature input')
        if a[s+'_ids'].shape != (n,): raise ValueError('bad identity shape')
        all_ids.extend(a[s+'_ids'].tolist())
        if s != 'holdout':
            y = a['y_'+s]
            if y.shape != (n,) or y.dtype.kind not in 'iu' or np.any((y<0)|(y>3)):
                raise ValueError('invalid permitted labels')
    if len(all_ids) != len(set(all_ids)): raise ValueError('train/calibration/holdout overlap')
    if a['cal_hashes'].shape != (32,) or len(set(a['cal_hashes'])) != 32: raise ValueError('invalid calibration blocks')
    return a,receipt

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();prepare(a.archive,a.output)
