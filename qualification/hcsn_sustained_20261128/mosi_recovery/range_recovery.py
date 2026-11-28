"""Resume the one pinned 367 MB public MOSI resource using four verified HTTP ranges."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

BASE=Path(__file__).resolve().parent
from restore_inputs import RAW_SHA,URL,sha

SIZE=367257274
CHUNK=16*1024**2


def fetch(bounds):
    start,end=bounds
    p=BASE/'parts'/f'{start}-{end}.range'
    if p.is_file() and p.stat().st_size==end-start+1:return p
    err=None
    for i in range(4):
        try:
            req=urllib.request.Request(URL,headers={'Range':f'bytes={start}-{end}'})
            with urllib.request.urlopen(req,timeout=90) as src:
                if src.status!=206 or src.headers.get('Content-Range')!=f'bytes {start}-{end}/{SIZE}':raise ValueError('unverified HTTP range')
                temp=p.with_suffix('.tmp')
                with temp.open('wb') as dest:shutil.copyfileobj(src,dest,1024**2)
            if temp.stat().st_size!=end-start+1:raise ValueError('short range')
            temp.replace(p);print('verified range',start,end,flush=True);return p
        except (OSError,ValueError) as e:err=e;time.sleep(2**i)
    raise RuntimeError(f'failed bounded range {start},{end}: {err}')


def main():
    raw=BASE/'aligned_50.pkl'
    if not raw.exists():
        part=BASE/'aligned_50.part'
        limit=part.stat().st_size if part.exists() else 0
        if not 0<=limit<=SIZE:raise ValueError('prior prefix size')
        (BASE/'parts').mkdir(exist_ok=True)
        spans=[(j,min(j+CHUNK,SIZE)-1) for j in range(limit,SIZE,CHUNK)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:paths=list(pool.map(fetch,spans))
        tmp=BASE/'aligned_50.verified'
        with tmp.open('wb') as out:
            if limit:
                if part.stat().st_size!=limit:raise ValueError('source prefix is still being written')
                with part.open('rb') as f:shutil.copyfileobj(f,out,1024**2)
            for path in paths:
                with path.open('rb') as f:shutil.copyfileobj(f,out,1024**2)
        if tmp.stat().st_size!=SIZE or sha(tmp)!=RAW_SHA:raise ValueError('full immutable MMSA hash mismatch')
        receipt={'size':SIZE,'sha256':RAW_SHA,'initial_prefix_bytes':limit,'http_range_requests':spans,'source':URL}
        (BASE/'source_transfer.json').write_text(json.dumps(receipt,indent=2)+'\n')
        tmp.replace(raw)
        # Delete only this task's now redundant verified partials after publishing the full object.
        if limit:part.unlink()
        for path in paths:path.unlink()
    subprocess.run([sys.executable,str(BASE/'restore_inputs.py')],check=True)


if __name__=='__main__':main()
