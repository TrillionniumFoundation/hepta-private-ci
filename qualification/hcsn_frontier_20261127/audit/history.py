"""Stream each history tree once, recording every referenced blob and representative path."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

PRIMARY=set('py pyi rs hia c cc cpp h hpp cu cuh jl ipynb ts tsx js mjs jsx sh bash md tex txt rst toml yml yaml go proto swift java kt kts html r ps1 sql bzl bazel'.split())
STRUCTURED=PRIMARY|set('zsh csv tsv json jsonl'.split())


def main(repo, paths, out, head):
    out.mkdir(exist_ok=True,parents=True)
    db=sqlite3.connect(out/'objects.sqlite')
    db.execute('pragma journal_mode=wal')
    db.execute('pragma synchronous=normal');db.execute('pragma cache_size=-18000')
    db.execute('create table if not exists blobs(oid blob primary key,path text,tier integer) without rowid')
    db.execute('create table if not exists state(slot integer primary key,last_tree integer,total_files integer,links integer)')
    old=db.execute('select last_tree,total_files,links from state').fetchone() or (0,0,0)
    skip,refs,links=old;trees=commits=0;begin=time.monotonic()
    cmd=['git','--git-dir='+str(repo),'cat-file','--batch']
    pending=[]
    with subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,env={**os.environ,'GIT_NO_LAZY_FETCH':'1'}) as p, gzip.open(paths,'rb') as rows:
        for line in rows:
            if b' ' not in line:
                commits+=1;continue
            oid,path=line.rstrip(b'\n').split(b' ',1);trees+=1
            if trees<=skip:continue
            p.stdin.write(oid+b'\n');p.stdin.flush()
            hdr=p.stdout.readline().split();assert hdr[0]==oid and hdr[1]==b'tree'
            data=p.stdout.read(int(hdr[2]));assert p.stdout.read(1)==b'\n'
            assert hashlib.sha1(b'tree '+hdr[2]+b'\0'+data).hexdigest().encode()==oid
            k=0
            while k<len(data):
                a=data.index(b' ',k);b=data.index(b'\0',a);mode=data[k:a];name=data[a+1:b];blob=data[b+1:b+21];k=b+21
                if mode==b'40000':continue
                if mode==b'160000':links+=1;continue
                filename=name.decode('utf-8','replace');ext=filename.lower().rsplit('.',1)[-1] if '.' in filename else ''
                full=(path+b'/'+name if path else name).decode('utf-8','replace')
                pending.append((blob,full,2 if ext in PRIMARY else int(ext in STRUCTURED)));refs+=1
            if len(pending)>=20000 or trees%10000==0:
                db.executemany('insert into blobs values(?,?,?) on conflict(oid) do update set tier=max(tier,excluded.tier) where excluded.tier>tier',pending)
                pending.clear();db.execute('insert or replace into state values(1,?,?,?)',(trees,refs,links));db.commit()
                if trees%10000==0:print('trees',trees,'entries',refs,'seconds',round(time.monotonic()-begin,1),flush=True)
        p.stdin.close()
    db.executemany('insert into blobs values(?,?,?) on conflict(oid) do update set tier=max(tier,excluded.tier) where excluded.tier>tier',pending)
    db.execute('insert or replace into state values(1,?,?,?)',(trees,refs,links));db.commit()
    db.execute('create temp table head(oid blob primary key) without rowid')
    with head.open('rb') as f:db.executemany('insert into head values(?)',((bytes.fromhex(row[:40].decode()),) for row in f))
    total=db.execute('select count(*) from blobs').fetchone()[0];nhead=db.execute('select count(*) from head').fetchone()[0]
    assert db.execute('select count(*) from head where not exists(select 1 from blobs where head.oid=blobs.oid)').fetchone()[0]==0
    delta_count=nt=0
    with (out/'additional.tsv').open('w') as a,(out/'additional-text.tsv').open('w') as t:
        for h,p,tier in db.execute('select lower(hex(oid)),path,tier from blobs where not exists(select 1 from head where head.oid=blobs.oid) order by oid'):
            assert '\n' not in p and '\t' not in p
            a.write(f'{h}\t{p}\n');delta_count+=1
            if tier:t.write(f'{h}\t{int(tier==2)}\t{p}\n');nt+=1
    info=dict(history_commits=commits,unique_trees=trees,file_entries=refs,gitlink_entries=links,
              unique_blobs=total,initial_tip_blobs=nhead,historical_additional=delta_count,historical_text=nt)
    (out/'summary.json').write_text(json.dumps(info,indent=2)+'\n');print(info,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('repo','paths','out','head'):p.add_argument('--'+k,type=Path,required=True)
    args=p.parse_args();main(args.repo,args.paths,args.out,args.head)
