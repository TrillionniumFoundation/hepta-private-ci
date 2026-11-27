"""Read and hash the complete payload of each selected Git blob; index topic markers."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time

MARKS = {
    'hcsn': 'hcsn|hepta[ _-]*continuous[ _-]*spik|hepta[ _-]*连续脉冲',
    'paper': 'he[ _–—-]*(?:(?:and|&)[ _-]*)?xiong|rollover risk and credit risk|rollover[ _-]*(?:loss|risk)',
    'boundary': 'free[ _-]*boundar|smooth[ _-]*past|自由边界|光滑粘贴|光滑贴合',
    'hit': 'first[ _-]*(?:passage|hitt?ing)|brownian bridge|首达|首次穿越',
    'neural': 'spiking|neuron|神经元|脉冲网络',
    'kinetic': 'refractory|regenerati(?:ve|on)|renewal|不应期|复位',
    'editing': 'weight[ _-]*edit|model[ _-]*edit|knowledge[ _-]*edit|forward[ _-]*projection|权重编辑|前向投影',
    'multimodal': 'multi[ _-]*modal|omni[ _-]*modal|全模态|多模态|image[ _-]*(?:text|caption)|audio[ _-]*visual',
    'speed': 'time[ _-]*to[ _-]*(?:quality|target)|wall[ _-]*(?:time|clock)|同质量|端到端时间',
}
# One regex per predicate. Lower-case normalized chunks maintain UTF-8 Chinese markers.
REGEX = [re.compile(v.encode()) for v in MARKS.values()]
ENV = {**os.environ, 'GIT_NO_LAZY_FETCH':'1', 'GIT_TERMINAL_PROMPT':'0'}
def run(cmd, **kw):
    return subprocess.run(cmd,env=ENV,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kw)
def command(repo):
    return ['git','--git-dir='+str(repo)]
def have(repo):
    raw=run(command(repo)+['cat-file','--batch-check=%(objectname) %(objecttype)','--batch-all-objects']).stdout
    return {line[:40] for line in raw.splitlines() if line.endswith(b' blob')}
def inspect(repo,ids,db):
    unit=1024*128
    with subprocess.Popen(command(repo)+['cat-file','--batch'],env=ENV,stdin=subprocess.PIPE,stdout=subprocess.PIPE) as stream:
        for oid,tier,path in ids:
            stream.stdin.write(oid+b'\n')
            stream.stdin.flush()
            head=stream.stdout.readline().split()
            if len(head)!=3 or head[1]!=b'blob' or head[0]!=oid:
                raise ValueError((oid,head))
            length=int(head[2])
            git_hash=hashlib.sha1(b'blob '+head[2]+b'\0')
            need=length
            hits=0
            binary=False
            carry=b''
            while need:
                raw=stream.stdout.read(min(unit,need))
                if not raw:raise IOError('truncated Git record')
                git_hash.update(raw)
                need-=len(raw)
                binary=b'\0' in raw or binary
                chunk=carry+raw.lower()
                for i,pattern in enumerate(REGEX):
                    if not hits&(1<<i) and pattern.search(chunk):
                        hits|=1<<i
                carry=chunk[-512:]
            if stream.stdout.read(1)!=b'\n' or git_hash.hexdigest().encode()!=oid:
                raise IOError('Git blob integrity')
            db.execute('insert into files values(?,?,?,?,?,?)',(oid.decode(),tier,path,length,binary,hits))
        stream.stdin.close()
    db.commit()
def fetch_scan(remote,ids,db,work):
    # Each pack is disposable after all Git object IDs in it have verified.
    with tempfile.TemporaryDirectory(dir=work) as d:
        repo=Path(d)
        run(['git','init','--bare','--quiet',d])
        base=command(repo)
        run(base+['remote','add','origin',remote])
        run(base+['-c','fetch.negotiationAlgorithm=noop','-c','fetch.writeCommitGraph=false',
                  '-c','gc.auto=0','fetch','--filter=blob:none','--no-tags','--no-recurse-submodules',
                  '--no-write-fetch-head','--stdin','origin'],input=b'\n'.join(r[0] for r in ids)+b'\n')
        inspect(repo,ids,db)
def main(a):
    a.work.mkdir(exist_ok=True,parents=True)
    db=sqlite3.connect(a.work/'screen.sqlite')
    db.execute('create table if not exists files(oid text primary key,tier integer,path text,size integer,binary integer,flags integer)')
    done={oid.encode() for oid, in db.execute('select oid from files')}
    rows=[]
    for row in a.files.read_bytes().splitlines():
        oid,tier,path=row.split(b'\t',2)
        if oid not in done:
            rows.append((oid,int(tier),path.decode('utf8','replace')))
    rows.sort(key=lambda r:(-r[1],r[0]))
    present=have(a.repo)
    existing=[r for r in rows if r[0] in present]
    needed=[r for r in rows if r[0] not in present]
    for off in range(0,len(existing),300):
        inspect(a.repo,existing[off:off+300],db)
    remote=run(command(a.repo)+['remote','get-url','origin']).stdout.decode().strip()
    print('existing',len(existing),'remaining',len(needed),'resume',len(done),flush=True)
    for off in range(0,len(needed),a.batch):
        selected=needed[off:off+a.batch]
        for attempt in range(4):
            try:
                fetch_scan(remote,selected,db,a.work)
                break
            except (OSError,subprocess.CalledProcessError) as error:
                db.rollback()
                if attempt==3:raise
                print('retry',off,attempt+1,type(error).__name__,flush=True)
                time.sleep(3*(attempt+1))
        if off%(a.batch*10)==0:
            print('verified',*db.execute('select count(*),sum(size) from files').fetchone(),'wall',round(time.time()),flush=True)
    counts=Counter()
    totals=Counter()
    a.out.mkdir(exist_ok=True,parents=True)
    with gzip.open(a.out/'screen.tsv.gz','wt',encoding='utf8') as f:
        f.write('oid\tprimary\tpath\tbytes\tbinary\tflags\n')
        for oid,tier,path,size,binary,flags in db.execute('select * from files order by oid'):
            f.write(f'{oid}\t{tier}\t{path}\t{size}\t{binary}\t{flags}\n')
            totals['objects']+=1;totals['bytes']+=size;totals['binary']+=binary;totals['primary']+=tier
            for i,label in enumerate(MARKS):
                counts[label]+=bool(flags&(1<<i))
    (a.out/'screen.json').write_text(json.dumps(dict(markers=MARKS,counts=counts,total=totals),ensure_ascii=False,indent=2)+'\n')
    print('complete',dict(totals),dict(counts),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('repo','work','files','out'):
        p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--batch',type=int,default=384)
    main(p.parse_args())
