"""Use the old, true-training record for parent selection; recover missing independent fits."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def hash_file(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def main(a):
    a.target.mkdir(exist_ok=True,parents=True)
    for name in ('law4.npz','data.npz','data.json','vocabulary.json'):
        dst=a.target/name
        if not dst.exists():
            try:
                dst.symlink_to((a.old/name).resolve())
            except FileExistsError:
                pass
    here=Path(__file__).parent
    tag=f'{a.arm}-{a.seed}'
    out=a.target/'runs'/tag
    out.mkdir(exist_ok=True,parents=True)
    record=out/'selected.json'
    if record.exists():
        return
    if (a.old/'runs'/tag/'done.json').is_file():
        location=a.old/'runs'/tag
        mode='existing'
    else:
        location=out
        mode='recovered-from-original-source'
        subprocess.run([sys.executable,str(here/'source_train.py'),'fit',a.arm,str(a.seed)],
                       check=True,env=dict(os.environ,FULLSTACK_DATA=str(a.target.resolve())))
    history=json.loads((location/'history.json').read_text())
    done=json.loads((location/'done.json').read_text())
    best=min((r for r in history if r['cpu']<=300),key=lambda r:(r['nll'],r['cpu']))
    assert best['state'] and hash_file(location/best['state'])==best['sha']
    selected=out/'selected.pt'
    if mode=='existing':
        selected.symlink_to((location/best['state']).resolve())
        for name in ('history.json','done.json'):
            (out/name).write_bytes((location/name).read_bytes())
    else:
        (location/best['state']).replace(selected)
        for file in out.glob('s[0-9]*.pt'):
            file.unlink()
    record.write_text(json.dumps({'arch':a.arm,'seed':a.seed,'selection':best,'source':mode,
        'source_history_sha':hash_file(out/'history.json'),'parent_source_s':done['setup_s']+done['elapsed']['wall'],
        'parameters':done['parameters'],'sha':hash_file(selected)},indent=1)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('old',type=Path);p.add_argument('target',type=Path);p.add_argument('arm');p.add_argument('seed',type=int)
    main(p.parse_args())
