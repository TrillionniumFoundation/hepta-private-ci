"""Verify pinned works, source partitions and causal descriptor archives."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
COUNTS={'gallery':1,'train':3,'dev':2,'retain':2,'test':3}


def check_manifest(rows):
    if len(rows)!=22:raise ValueError('expected 22 independent recording files')
    for key in ['pageid','sha1','page_permanent']:
        if len({r[key] for r in rows})!=len(rows):raise ValueError(f'duplicate {key}')
    for key in ['group','uploader']:
        fold={}
        for r in rows:
            if fold.setdefault(r[key],r['split'])!=r['split']:
                raise ValueError(f'{key} crosses a partition {r[key]}')
    expected=Counter({(s,label):n for s,n in COUNTS.items() for label in (0,1)})
    if Counter((r['split'],r['label']) for r in rows)!=expected:
        raise ValueError('instrument/split recording counts disagree')
    for r in rows:
        if r['instrument']!=('piano','guitar')[r['label']] or not r['metadata'].get('LicenseShortName'):
            raise ValueError(f'incomplete publisher label/attribution {r["pageid"]}')


def check_shard(rows,root,split):
    expected={str(r['pageid']):r for r in rows if r['split']==split}
    path=root/'features'/(split+'.npz')
    receipt=json.loads((root/'receipts'/(split+'.json')).read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest()!=receipt['shard_sha256']:
        raise ValueError('shard differs from decode receipt')
    roster=json.loads((root/'roster'/(split+'.json')).read_text())
    with np.load(path,allow_pickle=False) as z:
        n=len(roster)
        assert n==4*len(expected)==len(set(z['query_id'].tolist()))
        assert z['query_id'].tolist()==[r['query_id'] for r in roster]
        assert set(z['split'])=={split} and set(z['recording'])==set(expected)
        assert z['dt'].shape==(n,6) and np.array_equal(z['dt'],np.full((n,6),.48))
        for rid,ref in expected.items():
            mask=z['recording']==rid
            assert mask.sum()==4 and set(z['group'][mask])=={ref['group']}
            assert set(z['label'][mask])=={ref['label']}
            assert np.diff(z['start_seconds'][mask]).min()>2.88
        for k,f in [('audio',52),('visual',76)]:
            b=z[k+'_block']; c=z[k]
            assert b.shape==c.shape==(n,6,f) and np.all(np.isfinite(b))
            assert np.array_equal(c,b.cumsum(1)/np.arange(1,7)[None,:,None])
    return {'split':split,'rows':n,'recordings':len(expected),'sha256':receipt['shard_sha256']}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--root',type=Path)
    cli.add_argument('--split',action='append',choices=COUNTS)
    ns=cli.parse_args()
    rows=json.loads((HERE/'sources.json').read_text());check_manifest(rows)
    print(json.dumps({'recordings':len(rows),'producers':len({r['group'] for r in rows}),
           'uploaders':len({r['uploader'] for r in rows}),'split_recordings_per_class':COUNTS}))
    if ns.root:
        for s in ns.split or ['gallery','train','dev','retain']:
            print(json.dumps(check_shard(rows,ns.root,s)))
if __name__=='__main__':main()
