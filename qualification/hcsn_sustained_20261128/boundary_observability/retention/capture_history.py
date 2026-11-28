"""Capture immutable checkpoints from the original sustained CREMA-D experiment."""
import hashlib
import json
import os
import re
import time
from pathlib import Path

RUN = Path('/home/qq/.local/share/hepta-research/hcsn-sustained-1140569/run')
SNAP = RUN.parent.parent / 'hcsn-9de7-sustained-history'
ARMS = ('literal','smooth','lif','sdpa')
SEEDS = (137,311,557)
TAGS = {'update16','update128','time20','time240','time1000','time3150'}
SOURCE = '69e8cf12bcfcd414175250405ac08286901457377d76c1ad28f08d33a775dbc1'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def capture():
    if digest(RUN.parent/'study.py') != SOURCE:
        raise ValueError('unexpected source identity')
    objects = SNAP/'objects'
    objects.mkdir(parents=True,exist_ok=True,mode=0o700)
    rows, complete = {}, True
    seal_path = RUN/'seal.json'
    seal = json.loads(seal_path.read_text()) if seal_path.exists() else None
    for arm in ARMS:
        for seed in SEEDS:
            cell = f'{arm}-{seed}'
            entries = json.loads((RUN/cell/'progress.json').read_text())
            if (entries['arm'],entries['seed']) != (arm,seed):
                raise ValueError('progress identity mismatch')
            history = entries['history']
            if not TAGS.issubset({k for h in history for k in h['tags']}):
                complete = False
            byname = {}
            for rec in history:
                name,sha = rec['file'],rec['sha256']
                if not re.fullmatch(r'step[0-9]+\.pt',name) or not re.fullmatch('[0-9a-f]{64}',sha):
                    raise ValueError('unexpected checkpoint identifier')
                src, dst = RUN/cell/name, objects/(sha+'.pt')
                if not dst.exists():
                    if digest(src) != sha:
                        raise ValueError('changed original checkpoint')
                    os.link(src,dst)
                if not os.path.samefile(src,dst):
                    raise ValueError('snapshot does not point to original checkpoint')
                byname[name]=sha
                rows[cell+'/'+name]={'sha256':sha,'bytes':src.stat().st_size, 'history':rec}
            if seal:
                cfg=seal[cell]
                for selected in (cfg['best'],*cfg['gates'].values()):
                    if selected and byname.get(selected['file'])!=selected['sha256']:
                        raise ValueError('selection absent from original history')
    result = {'source_sha256':SOURCE,'source_machine_sha256':digest(Path('/etc/machine-id')),
              'condition_count':len(ARMS)*len(SEEDS),'weights':rows,'complete':bool(complete and seal),
              'original_seal':seal,'cold_arrays_acquired':False}
    print(json.dumps(result,sort_keys=True,allow_nan=False))


if __name__=='__main__':
    os.umask(0o077)
    capture()
