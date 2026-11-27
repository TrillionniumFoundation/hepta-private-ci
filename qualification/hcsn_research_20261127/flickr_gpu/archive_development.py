"""Archive immutable development snapshots alongside the single running experiment."""
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import time
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent
PRIMARY=ROOT/'panel_gpu'
ARCHIVE=ROOT/'development_archive'
ARCHIVE.mkdir(exist_ok=True)
lock=(ARCHIVE/'capture.lock').open('a')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
objects=ARCHIVE/'objects'
objects.mkdir(exist_ok=True)
ARMS=('hcsn','smooth','lif','mean','dense')
SEEDS=(17011,24203,39827)
BUDGETS=(20,120,420,720,1020,1320,1620,1920,2220,2520)

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def write_once(path,raw):
    if path.exists():
        assert path.read_bytes()==raw
    else:
        temp=path.with_name(path.name+'.part');temp.write_bytes(raw);temp.replace(path)

def record(arm,seed,stage):
    name=f'{arm}-{seed}'
    source=(ROOT/'caption_external20' if stage==20 else PRIMARY)/name
    fit=source/'fit.json';selected=source/'selected.pt'
    if not fit.exists() or not selected.exists():return False
    before=fit.read_bytes()
    data=json.loads(before)
    current=data['checkpoints'][-1]['nominal_s']
    if current<stage:return False
    if current>stage:raise RuntimeError(f'Missed real selected file for {name} at {stage}')
    if selected.stat().st_mtime_ns>fit.stat().st_mtime_ns and stage!=20:return False
    sh=digest(selected);dst=objects/(sh+'.pt')
    if not dst.exists():
        tmp=dst.with_name(dst.name+'.part');shutil.copyfile(selected,tmp)
        if digest(tmp)!=sh or fit.read_bytes()!=before:
            tmp.unlink();return False
        tmp.replace(dst)
    elif digest(dst)!=sh:raise RuntimeError('Archived selected bytes changed')
    if fit.read_bytes()!=before or digest(selected)!=sh:return False
    root=ARCHIVE/f'{stage:04d}'
    root.mkdir(exist_ok=True)
    receipt={'arm':arm,'seed':seed,'budget':stage,'selected_sha256':sh,'fit_sha256':hashlib.sha256(before).hexdigest(),'fit':data}
    write_once(root/(name+'.json'),json.dumps(receipt,sort_keys=True).encode())
    return True

deadline=time.monotonic()+46000
for stage in BUDGETS:
    path=ARCHIVE/f'{stage:04d}'
    names=[f'{arm}-{seed}' for arm in ARMS for seed in SEEDS]
    while not all((path/(n+'.json')).is_file() for n in names):
        if time.monotonic()>deadline:raise TimeoutError('Scientific panel stopped before the declared limit')
        for arm in ARMS:
            for seed in SEEDS:
                if not (path/(f'{arm}-{seed}.json')).exists():record(arm,seed,stage)
        if not all((path/(n+'.json')).is_file() for n in names):time.sleep(7)
    seals={n:digest(path/(n+'.json')) for n in names}
    if not (path/'stage_seal.json').exists():
        write_once(path/'stage_seal.json',json.dumps({'budget':stage,'captured_at':datetime.now(timezone.utc).isoformat(),'receipts':seals},sort_keys=True).encode())
    else:assert json.loads((path/'stage_seal.json').read_text())['receipts']==seals
    print('sealed development budget',stage,len(seals),flush=True)
