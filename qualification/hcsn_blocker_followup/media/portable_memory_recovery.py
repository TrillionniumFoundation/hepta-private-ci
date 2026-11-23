"""Resume a source_replay.zip run from its original media/RGB with two bounded-memory stages."""
import argparse
import ctypes
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
import zipfile

import numpy as np


def sha(path):
    with Path(path).open('rb') as fh:
        return hashlib.file_digest(fh, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    os.replace(tmp,path)


def save_array(path, **arrays):
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.npz', delete=False) as f:
        np.savez_compressed(f,**arrays)
        temp=Path(f.name)
    os.replace(temp,path)


def trim():
    gc.collect()
    try: ctypes.CDLL(None).malloc_trim(0)
    except AttributeError: pass


def valid(folder, kind, row, identity):
    q=row['query_id']; proof=folder/f'{q}.{kind}.json'; data=folder/f'{q}.{kind}.npz'
    if not proof.is_file() or not data.is_file():return False
    meta=read(proof)
    return meta['binding']==identity[q] and meta['sha256']==sha(data)


def worker(stage, rows, root, folder, binding):
    import torch
    import vision_disk as original
    from qualification.hcsn_intervention_value.media import vision
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if stage=='transform':
        transform=vision.ResNet18_Weights.IMAGENET1K_V1.transforms()
    else:
        model,_,indices=vision.load_model(original.CHECKPOINT)
    with torch.inference_mode():
        for r in rows:
            q=r['query_id']
            if valid(folder,stage,r,binding):continue
            target=folder/f'{q}.{stage}.npz'
            if stage=='transform':
                z,raw=original.tensors(r,transform)
                assert z.dtype==torch.float32 and tuple(z.shape)==(6,3,224,224)
                save_array(target,z=z.numpy()); extra={'tensor_sha256':original.th(z)}
                del z
            else:
                if not valid(folder,'transform',r,binding):raise ValueError('unbound preprocessed tensor '+q)
                with np.load(folder/f'{q}.transform.npz',allow_pickle=False) as arrays:
                    z=torch.from_numpy(arrays['z'])
                logits=model(z);post=vision.cumulative_class_probability(logits,indices)
                save_array(target,probability=post.numpy())
                extra={'tensor_sha256':original.th(z),'logits_sha256':original.th(logits),'probability_sha256':original.th(post)}
                del z,logits,post
            write(folder/f'{q}.{stage}.json',dict(binding=binding[q],sha256=sha(target),**extra))
            trim()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True,help='destination created by portable_replay.py')
    p.add_argument('--kit',type=Path,required=True,help='unchanged published source_replay.zip')
    p.add_argument('--split',required=True,choices=('train','dev','test'))
    p.add_argument('--worker',choices=('transform','predict'),help=argparse.SUPPRESS)
    p.add_argument('--only',nargs='*',help=argparse.SUPPRESS)
    a=p.parse_args();project=a.workspace.resolve();root=project/'lab3/recordings'
    sys.path[:0]=[str(root),str(project/'trial')]
    roster=root/'roster'/(a.split+'.json');rows=read(roster)
    folder=root/'resume-cache'/a.split;folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.kit) as z:
        published=json.loads(z.read('hashes.json'))
        seal=json.loads(z.read('pinned/data_freeze.json'))
        original_roster=json.loads(z.read('pinned/roster/'+a.split+'.json'))
        source_registry=json.loads(z.read('pinned/sources.json'))
        assert hashlib.sha256(z.read('pinned/sources.json')).hexdigest()==seal['sources_sha256']==sha(root/'sources.json')
    for name in ('rgb_disk.py','vision_disk.py'):assert published['pinned/'+name]==sha(root/name)
    assert [{k:v for k,v in r.items() if k!='local_media'} for r in rows]==[{k:v for k,v in r.items() if k!='local_media'} for r in original_roster]
    frozen_original=sha(project/'trial/qualification/hcsn_intervention_value/media/vision.py')
    expected_weight='f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec'
    assert sha(project/'lab2/weights/resnet18.pth')==expected_weight
    if a.worker:
        ids=set(a.only) if a.only else None
        batch=[r for r in rows if ids is None or r['query_id'] in ids]
        worker(a.worker,batch,root,folder,read(folder/'binding.json'))
        return
    started=time.monotonic();utc=datetime.now(timezone.utc).isoformat()
    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',MALLOC_ARENA_MAX='1')
    actual={str(r['pageid']):r['original_sha256'] for r in source_registry}; seen=set();binding={};raw_rows={}
    for r in rows:
        q=r['query_id'];rgb=root/'rgb-cache'/a.split/(q+'.rgb');meta=read(rgb.with_suffix('.json'))
        if r['recording'] not in seen:
            assert sha(r['local_media'])==actual[r['recording']];seen.add(r['recording'])
        assert r['start_seconds']==meta['details']['start_seconds'] and q==meta['query_id']
        assert actual[r['recording']]==meta['source_sha256'] and sha(rgb)==meta['rgb_sha256']
        assert meta['original_selector_sha256']==frozen_original and meta['adapter_sha256']==sha(root/'rgb_disk.py')
        binding[q]={'rgb_sha256':meta['rgb_sha256'],'source_sha256':meta['source_sha256'],'weight_sha256':expected_weight,
                    'source_selector_sha256':frozen_original,'source_transform_and_inference_sha256':sha(root/'vision_disk.py'),
                    'resume_sha256':sha(__file__),'query_id':q}
        raw_rows[q]=meta
    write(folder/'binding.json',binding)
    attempts=[]
    def attempt(stage,ids):
        cmd=[sys.executable,str(Path(__file__).resolve()),'--workspace',str(project),'--kit',str(a.kit.resolve()),'--split',a.split,'--worker',stage,'--only',*ids]
        start=time.monotonic()
        with (folder/'jobs.log').open('a') as f:
            c=subprocess.Popen(cmd,env=env,stdout=f,stderr=subprocess.STDOUT)
            _,status,usage=os.wait4(c.pid,0);c.returncode=os.waitstatus_to_exitcode(status)
        attempts.append(dict(stage=stage,queries=ids,returncode=c.returncode,wall_seconds=time.monotonic()-start,user_cpu_seconds=usage.ru_utime,system_cpu_seconds=usage.ru_stime,max_rss_kib=usage.ru_maxrss))
        write(folder/'attempts.json',attempts)
        return c.returncode==0
    for stage in ('transform','predict'):
        missing=[r['query_id'] for r in rows if not valid(folder,stage,r,binding)]
        if missing and not attempt(stage,missing):
            for r in rows:
                if not valid(folder,stage,r,binding) and not attempt(stage,[r['query_id']]):
                    raise RuntimeError(f"{stage} failed on individual query {r['query_id']}; retained verified progress")
    values=[];notes=[]
    for r in rows:
        q=r['query_id'];pr=read(folder/f'{q}.predict.json')
        assert valid(folder,'predict',r,binding)
        with np.load(folder/f'{q}.predict.npz',allow_pickle=False) as z:values.append(z['probability'])
        notes.append(dict(query_id=q,source_sha256=binding[q]['source_sha256'],rgb_sha256=binding[q]['rgb_sha256'],
                          preprocessed_sha256=pr['tensor_sha256'],preprocessed_dtype='torch.float32',logits_sha256=pr['logits_sha256'],
                          probability_sha256=pr['probability_sha256'],**raw_rows[q]['details']))
    out=root/'semantic'/(a.split+'.npz')
    if out.exists():raise FileExistsError('complete output exists '+str(out))
    save_array(out,query_id=np.array([r['query_id'] for r in rows]),probability=np.stack(values))
    rec=dict(status='ok',split=a.split,queries=len(rows),output_sha256=sha(out),roster_sha256=sha(roster),weight_sha256=expected_weight,
             script_sha256=sha(__file__),original_vision_sha256=frozen_original,rgb_adapter_sha256=sha(root/'rgb_disk.py'),
             archived_adapter_sha256=sha(root/'vision_disk.py'),rows=notes,began_utc=utc,ended_utc=datetime.now(timezone.utc).isoformat(),
             wall_seconds=time.monotonic()-started,attempts=attempts)
    write(out.with_suffix('.receipt.json'),rec);print(a.split,len(rows),sha(out),rec['wall_seconds'],flush=True)
if __name__=='__main__':main()
