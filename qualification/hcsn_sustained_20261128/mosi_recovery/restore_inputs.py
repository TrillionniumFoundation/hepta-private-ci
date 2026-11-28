"""Restore published MOSI inputs and check normalized tensors against the original frozen seal."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

TASK=Path(__file__).resolve().parent
REV='4f80d069218e5416be0f51323a9db46b461d07dd'
GITPATH='qualification/hcsn_mosi_three_stream_20261127'
SEAL_SHA='75ec41f336ab20aded67a94ac8c435861fe7fc1e2fc4276e8a5ceb5d4b31d256'
URL='https://huggingface.co/datasets/tamb2203579/CMU-MOSI/resolve/092c41f8843df675ab8a169e41419e74e6ae05da/Processed/aligned_50.pkl'
RAW_SHA='d3994fd25681f9c7ad6e9c6596a6fe9b4beb85ff7d478ba978b124139002e5f9'

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def original(path):
    out=TASK/'source'/path;out.parent.mkdir(exist_ok=True)
    if not out.exists():
        endpoint=f'repos/TrillionniumFoundation/hepta-private-ci/contents/{GITPATH}/{path}?ref={REV}'
        payload=json.loads(subprocess.check_output(['gh','api',endpoint]))
        data=base64.b64decode(''.join(payload['content'].split()),validate=True)
        if len(data)!=payload['size']:raise ValueError('GitHub content length')
        tmp=out.with_suffix(out.suffix+'.tmp');tmp.write_bytes(data);tmp.replace(out)
    return out

def acquire():
    sf=original('SEAL.json')
    if sha(sf)!=SEAL_SHA:raise ValueError('seal identity')
    seal=json.loads(sf.read_text())
    for name,digest in {**seal['code'],'data.json':seal['data_manifest_sha256'],'law.npz':seal['law_sha256'],'law_check.json':seal['kernel_parity']}.items():
        if sha(original(name))!=digest:raise ValueError('pinned source '+name)
    raw=TASK/'aligned_50.pkl'
    if not raw.exists():
        tmp=raw.with_suffix('.part')
        with urllib.request.urlopen(URL,timeout=90) as src,tmp.open('wb') as dst:
            while data:=src.read(2**20):dst.write(data)
        if sha(tmp)!=RAW_SHA:raise ValueError('raw MMSA checksum')
        tmp.replace(raw)
    if sha(raw)!=RAW_SHA:raise ValueError('existing MMSA checksum')
    src=TASK/'source';dest=TASK/'reconstructed';dest.mkdir(exist_ok=True)
    # Distribution NumPy 1.x exposes the implementation under np.core; original
    # script imports np._core (the same module's current NumPy 2.x name).
    # Use a real 2.x interpreter for reproducibility if it is available.
    import numpy as np
    env={**os.environ,'PYTHONOPTIMIZE':'','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
    run=subprocess.run([sys.executable,str(src/'prepare.py'),str(raw),str(src/'official_folds.py'),str(dest)],
                       env=env,capture_output=True,text=True)
    if run.returncode:raise RuntimeError(run.stderr[-1400:])
    manifest=json.loads((src/'data.json').read_text())
    checks={s:{'actual':sha(dest/(s+'.npz')),'expected':info['sha256']} for s,info in manifest['splits'].items()}
    if any(c['actual']!=c['expected'] for c in checks.values()):raise ValueError('tensor SHA mismatch '+repr(checks))
    receipt={'raw_source':URL,'raw_bytes':raw.stat().st_size,'raw_sha256':RAW_SHA,'original_seal_sha256':SEAL_SHA,
             'original_code_and_manifest_verified':True,'restored_split_sha256':checks,'numpy':np.__version__,
             'python':sys.version,'actual_cold_source_clips':manifest['splits']['test']['cases'],
             'actual_cold_source_videos':len(manifest['splits']['test']['videos']),
             'observed_scores':False,'note':'Normalized tensors authenticated independently of missing trained weight bytes.'}
    (TASK/'input_recovery.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt),flush=True)

if __name__=='__main__':acquire()
