"""Export observed original windows and preserve all eligibility decisions in a separate receipt."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import resource
import tempfile
import time

import numpy as np

if __package__:
    from . import build
else:
    import build

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--coverage',type=Path,required=True)
    parser.add_argument('--split',required=True)
    parser.add_argument('--output-root',type=Path)
    ns=parser.parse_args();t=time.perf_counter()
    root=ns.root.resolve();outroot=(ns.output_root or root).resolve()
    rosterfile=root/'roster'/(ns.split+'.json')
    roster=json.loads(rosterfile.read_text())
    coverage=json.loads(ns.coverage.read_text())
    assert build.digest(rosterfile)==coverage['roster_sha256']
    assert build.digest(HERE/'coverage.py')==coverage['auditor_sha256']
    states=coverage['queries'];assert len(roster)==len(states)==len({r['query_id'] for r in roster})
    originals={str(r['pageid']):r for r in json.loads((HERE/'sources.json').read_text()) if r['split']==ns.split}
    frontend=build.digest(HERE/'recording_features.py')
    handles={};valid=[];todo=[];all_ids=[]
    tmp_cache=outroot/'complete-cache'/ns.split;tmp_cache.mkdir(exist_ok=True,parents=True)
    for r,state in zip(roster,states):
        rid=r['recording'];p=Path(r['local_media'])
        assert rid==state['recording'] and r['query_id']==state['query_id']
        assert int(rid)==originals[rid]['pageid'] and r['start_seconds']==state['start_seconds']
        if rid not in handles:
            if hashlib.sha1(p.read_bytes()).hexdigest()!=originals[rid]['sha1'] or p.stat().st_size!=originals[rid]['size']:
                raise ValueError(f'publisher original mismatch {p}')
            handles[rid]=build.digest(p)
        all_ids.append(r['query_id'])
        if state['missing_original_samples']==0:
            valid.append(r)
            signature={'input_sha256':handles[rid],'frontend_sha256':frontend,'start_seconds':r['start_seconds']}
            todo.append((r['local_media'],r,tmp_cache,signature))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        decodes=list(pool.map(build.job,todo))
    columns={}
    for r in valid:
        with np.load(tmp_cache/(r['query_id']+'.npz'),allow_pickle=False) as z:
            for k in z.files:columns.setdefault(k,[]).append(z[k])
        for k in ('label','group','recording','query_id','dt','start_seconds','split'):
            columns.setdefault(k,[]).append(r[k])
    folder=outroot/'features';folder.mkdir(exist_ok=True)
    output=folder/(ns.split+'.complete.npz')
    with tempfile.NamedTemporaryFile(dir=folder,suffix='.npz',delete=False) as f:
        np.savez_compressed(f,**{k:np.asarray(v) for k,v in columns.items()})
        temp=Path(f.name)
    os.replace(temp,output)
    receipt={'split':ns.split,'predeclared_rows':len(roster),'available_rows':len(valid),
             'state':'incomplete original roster',
             'sha256':build.digest(output),'shard_sha256':build.digest(output),
             'coverage_sha256':build.digest(ns.coverage),'roster_sha256':build.digest(rosterfile),
             'source_manifest_sha256':build.digest(HERE/'sources.json'),'frontend_sha256':frontend,
             'exporter_sha256':build.digest(Path(__file__)),'builder_sha256':build.digest(HERE/'build.py'),
             'source_sha256':handles,'all_original_query_ids':all_ids,
             'complete_query_ids':[r['query_id'] for r in valid],
             'case_evidence':states,'individual_decodes':decodes,
             'elapsed_seconds':time.perf_counter()-t,'original_intervals_preserved':True,
             'imputation':False,'scores_computed':False}
    build.save_json(outroot/'receipts'/(ns.split+'.complete.json'),receipt)
    print('complete cases',len(valid),'of',len(roster),'shard',receipt['sha256'],flush=True)


if __name__=='__main__':main()
