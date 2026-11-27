"""Verify every remaining branch-head blob, indexing readable files and streamed artifact packaging."""
import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
from screen import REGEX,MARKS,ENV,command,run

FORMATS={b'\x1f\x8b':'gzip',b'PK\x03\x04':'zip',b'\xfd7zXZ':'xz',b'\x28\xb5\x2f\xfd':'zstd',
         b'\x93NUMPY':'numpy',b'\x89PNG':'png',b'\xff\xd8\xff':'jpeg',b'%PDF':'pdf',b'PAR1':'parquet',
         b'\x89HDF':'hdf',b'\x7fELF':'elf',b'Rar!':'rar',b'BZh':'bzip2',b'GIF8':'gif'}
def flags(chunk,prior=0):
    for i,pattern in enumerate(REGEX):
        if not prior&(1<<i) and pattern.search(chunk):prior|=1<<i
    return prior
def inspect(repo,rows,db):
    with subprocess.Popen(command(repo)+['cat-file','--batch'],env=ENV,stdin=subprocess.PIPE,stdout=subprocess.PIPE) as p:
        for sha,path in rows:
            p.stdin.write(sha+b'\n');p.stdin.flush()
            head=p.stdout.readline().split()
            assert len(head)==3 and head[0]==sha and head[1]==b'blob'
            left=size=int(head[2]);h=hashlib.sha1(b'blob '+head[2]+b'\0')
            source=b'';prev=b'';e=path.lower().split('.')[-1];kind='empty';matched=0;decoded=None;limited=False;inner=b''
            while left:
                chunk=p.stdout.read(min(131072,left))
                if not chunk:raise RuntimeError('truncated payload')
                if left==size:
                    kind=next((s for magic,s in FORMATS.items() if chunk.startswith(magic)),None)
                    if not kind:
                        lo=chunk[:8192];non=sum(v<9 or v in (11,12) or 13<v<32 for v in lo)
                        kind='binary' if b'\0' in lo or non>max(1,len(lo)//100) else 'text'
                    if kind=='text' and e in {'b64','base64'}:kind='encoded_text'
                left-=len(chunk);h.update(chunk)
                if kind=='text':
                    z=prev+chunk.lower();matched=flags(z,matched);prev=z[-512:]
                elif kind=='gzip' and size<=4*1024*1024:
                    source+=chunk
            assert p.stdout.read(1)==b'\n' and h.hexdigest().encode()==sha
            if source:
                try:
                    with gzip.GzipFile(fileobj=io.BytesIO(source)) as f:
                        inner=f.read(4*1024*1024+1);limited=len(inner)>4*1024*1024
                    if b'\0' not in inner[:8192]:
                        decoded='text';matched=flags(inner[:4*1024*1024].lower())
                    else:decoded='binary'
                except (OSError,EOFError):decoded='invalid_gzip'
            db.execute('insert into entries values(?,?,?,?,?,?,?)',(sha.decode(),path,size,kind,decoded,limited,matched))
        p.stdin.close()
    db.commit()

def collect(a):
    a.work.mkdir(exist_ok=True,parents=True);a.out.mkdir(exist_ok=True,parents=True)
    db=sqlite3.connect(a.work/'remaining.sqlite')
    db.execute('create table if not exists entries(oid text primary key,path text,size integer,kind text,inner text,limited integer,flags integer)')
    skip={row.split(b'\t',1)[0] for row in a.known.read_bytes().splitlines()}
    done={oid.encode() for oid, in db.execute('select oid from entries')}
    entries=[]
    for line in a.all.read_bytes().splitlines():
        sha,name=line.split(b'\t',1);p=name.decode('utf8','replace')
        if sha not in skip and sha not in done:entries.append((sha,p))
    # Narrative human-readable output is handled first, with the same Git verification as every later artifact.
    ext={'log','patch','stdout','stderr','lock','snap','v','sv','diff','s','lua','ipynb','ini','conf','xml','out','adoc'}
    entries.sort(key=lambda r:(0 if r[1].lower().split('.')[-1] in ext else 1,r[0]))
    remote=run(command(a.repo)+['remote','get-url','origin']).stdout.decode().strip()
    for off in range(0,len(entries),a.batch):
        batch=entries[off:off+a.batch]
        for attempt in range(4):
            try:
                with tempfile.TemporaryDirectory(dir=a.work) as d:
                    repo=Path(d);run(['git','init','--bare','--quiet',d]);base=command(repo);run(base+['remote','add','origin',remote])
                    run(base+['-c','fetch.negotiationAlgorithm=noop','-c','fetch.writeCommitGraph=false','-c','gc.auto=0',
                              'fetch','--filter=blob:none','--no-tags','--no-write-fetch-head','--no-recurse-submodules','--stdin','origin'],
                        input=b'\n'.join(x[0] for x in batch)+b'\n')
                    inspect(repo,batch,db)
                break
            except (OSError,subprocess.CalledProcessError):
                db.rollback()
                if attempt>=3:raise
                time.sleep(3*(attempt+1))
        if off%(a.batch*15)==0:
            print('verified',*db.execute('select count(*),sum(size) from entries').fetchone(),round(time.time()),flush=True)
    types=Counter();bytes_by=Counter();dec=Counter();size=0;nn=0;lim=0
    with gzip.open(a.out/'other.tsv.gz','wt',encoding='utf8') as out:
        out.write('oid\tpath\tbytes\tformat\tinner\tinner_truncated\tflags\n')
        for oid,path,n,k,i,limited,fl in db.execute('select * from entries order by oid'):
            out.write(f'{oid}\t{path}\t{n}\t{k}\t{i or ""}\t{limited}\t{fl}\n')
            size+=n;nn+=1;types[k]+=1;bytes_by[k]+=n;lim+=limited
            if i:dec[i]+=1
    obj=dict(objects=nn,bytes=size,kinds=types,by_type_bytes=bytes_by,gzip_examined=dec,gzip_examination_truncated=lim,
             markers=list(MARKS),scope='Every selected raw Git blob is authenticated against its own ID. Readable text is indexed. Gzip <=4MiB gets up to 4MiB of decoded semantic inspection. Large weights or embedded archive tensors are not treated as reviewed source.')
    (a.out/'other.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    print(obj,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for field in ('repo','all','known','work','out'):p.add_argument('--'+field,type=Path,required=True)
    p.add_argument('--batch',type=int,default=40)
    collect(p.parse_args())
