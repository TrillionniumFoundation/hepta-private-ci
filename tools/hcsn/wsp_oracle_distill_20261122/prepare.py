"""Materialize the source snapshot and the 170 original model/graph/feature pins."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

REVISION='def96748960a30eaf917bd43a368cfddddfd547f'
ROOT=Path(__file__).resolve().parent
PREFIX='tools/hcsn/wsp_20261122_next/'
PIN='adca7eed0c7dc63a5d884fc44f8e8431d7dae56eb44d0566d522eb8dae405d10'
SOURCE_FILES=['PROTOCOL_FROZEN.json','study_io.py','vendor/data_contract.py','vendor/own_context.py',
    'vendor/public_sampling.py','vendor/value_graph.py','semantic/checked_replay.py','semantic/joint_deploy.py',
    'semantic/joint_task.py','semantic/legacy_task.py','semantic/planning.py','semantic/run_head_edit.py',
    'evidence/run/selection_attempt001/output/WORLDS_FROZEN.json','evidence/run/confirmation_attempt001/output/WORLDS_FROZEN.json']

def write_checked(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=data:
            raise ValueError(f'conflicting existing file {path}')
        return
    with path.open('xb') as out:
        out.write(data)

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('evidence_zip',type=Path)
    ap.add_argument('repository',type=Path,help='local git repository containing PR 6956 revision')
    args=ap.parse_args()
    for rel in SOURCE_FILES:
        data=subprocess.check_output(['git','-C',str(args.repository),'show',f'{REVISION}:{PREFIX}{rel}'])
        write_checked(ROOT/'pinned'/rel,data)
    raw=(ROOT/'pinned/PROTOCOL_FROZEN.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==PIN
    p=json.loads(raw)
    with zipfile.ZipFile(args.evidence_zip) as archive:
        selected=[v for v in p['input_pins'] if v['path'].startswith(('models/','graphs/','hidden/'))]
        assert len(selected)==170
        for v in selected:
            rel=v['path']
            data=archive.read('evidence/value/input_bundle/'+rel)
            if len(data)!=v['bytes'] or hashlib.sha256(data).hexdigest()!=v['sha256']:
                raise ValueError('identity mismatch: '+rel)
            write_checked(ROOT/'inputs'/rel,data)
