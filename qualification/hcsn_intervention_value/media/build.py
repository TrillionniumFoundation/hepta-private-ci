"""Materialize separated source-disjoint music shards from publisher media."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time

import numpy as np

if __package__:
    from .recording_features import extract, starts, duration_of, STEPS, DT
else:
    from recording_features import extract, starts, duration_of, STEPS, DT

HERE = Path(__file__).resolve().parent


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def save_json(path, data):
    path.parent.mkdir(exist_ok=True, parents=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def roster_for(source, original):
    rid = str(source['pageid'])
    return [dict(query_id=f'commons-{rid}-w{k+1:02d}', local_media=str(original.resolve()),
                 split=source['split'], group=source['group'], recording=rid, label=source['label'],
                 start_seconds=float(start), dt=[DT] * STEPS)
            for k, start in enumerate(starts(duration_of(original)))]


def job(args):
    src, row, feat_dir = args
    dest=feat_dir/(row['query_id']+'.npz')
    t=time.perf_counter()
    a=extract(src, row['start_seconds'])
    np.savez_compressed(dest, **a)
    return {'query_id':row['query_id'],'seconds':time.perf_counter()-t,'sha256':digest(dest)}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--root',type=Path,required=True)
    cli.add_argument('--split',required=True,choices=['gallery','train','dev','retain','test'])
    cli.add_argument('--jobs',type=int,default=2)
    cli.add_argument('--partial',action='store_true',help='cache available inputs before the entire split arrives')
    cli.add_argument('--roster-only',action='store_true')
    ns=cli.parse_args(); root=ns.root.resolve(); start=time.perf_counter()
    sources=[r for r in json.loads((HERE/'sources.json').read_text()) if r['split']==ns.split]
    rows=[];available=[];missing=[]
    for s in sources:
        p=root/'media-cache'/(str(s['pageid'])+Path(s['title']).suffix)
        if not p.exists():
            missing.append(s['pageid'])
            continue
        if p.stat().st_size != s['size'] or hashlib.sha1(p.read_bytes()).hexdigest()!=s['sha1']:
            raise ValueError(f"original publisher size/hash mismatch {s['pageid']}")
        rows.extend(roster_for(s,p))
        available.append({'pageid':s['pageid'],'size':p.stat().st_size,'sha256':digest(p)})
    if missing and not ns.partial:raise ValueError(f'missing originals {missing}')
    if not rows:return
    suffix='.partial' if missing else ''
    roster=root/'roster'/(ns.split+suffix+'.json')
    save_json(roster, rows)
    print(f'roster {roster} rows={len(rows)} held={missing}',flush=True)
    if ns.roster_only:return
    feat_dir=root/'window-cache'/ns.split;feat_dir.mkdir(exist_ok=True,parents=True)
    todo=[(r['local_media'],r,feat_dir) for r in rows if not (feat_dir/(r['query_id']+'.npz')).exists()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=ns.jobs) as pool:
        results=list(pool.map(job,todo))
    dest=root/'features';dest.mkdir(exist_ok=True)
    receipts=root/'receipts';receipts.mkdir(exist_ok=True)
    out=dest/(ns.split+suffix+'.npz')
    columns={}
    for r in rows:
        with np.load(feat_dir/(r['query_id']+'.npz'),allow_pickle=False) as z:
            for k in z.files:columns.setdefault(k,[]).append(z[k])
        for k in ('label','group','recording','query_id','dt','start_seconds','split'):
            columns.setdefault(k,[]).append(r[k])
    np.savez_compressed(out,**{k:np.asarray(v) for k,v in columns.items()})
    receipt={'split':ns.split,'rows':len(rows),'missing':missing,'media':available,
             'jobs':results,'wall_seconds':time.perf_counter()-start,'roster_sha256':digest(roster),
             'shard_sha256':digest(out),'sources_sha256':digest(HERE/'sources.json'),
             'build_sha256':digest(Path(__file__)), 'frontend_sha256':digest(HERE/'recording_features.py')}
    save_json(receipts/(ns.split+suffix+'.json'),receipt)
    print('shard',out,'wall',receipt['wall_seconds'],flush=True)
if __name__=='__main__':main()
