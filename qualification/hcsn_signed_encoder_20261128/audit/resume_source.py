"""Read missing frozen source objects through bounded Git packs and recover defective batches."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

root = Path.home() / '.local/state/hepta-hcsn-1140569-audit'
out = root / 'source-recovery-9de7'
out.mkdir(exist_ok=True)
lock=(out/'run.lock').open('a')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
sys.path.insert(0,str(root))
import screen

roster = {}
for row in (root/'results/files.tsv').read_bytes().splitlines():
    oid,tier,path = row.split(b'\t',2)
    roster[oid]=(int(tier),path.decode('utf8','replace'))
assert len(roster)==158089
original=sqlite3.connect(f'file:{root}/scan-work/screen.sqlite?mode=ro',uri=True)
previous={oid.encode() for oid, in original.execute('select oid from files')}
assert previous <= roster.keys()
db=sqlite3.connect(out/'recovered.sqlite')
schema='create table if not exists files(oid text primary key,tier integer,path text,size integer,binary integer,flags integer)'
db.execute(schema)
db.execute('create table if not exists errors(oid text primary key, reason text)')
done={oid.encode() for oid, in db.execute('select oid from files')}
assert done.isdisjoint(previous)
need=roster.keys()-done-previous
git_env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GIT_NO_LAZY_FETCH':'1'}
url='https://github.com/TrillionniumFoundation/hepta-private-ci.git'
def local_inspect(repo,oids):
    mem=sqlite3.connect(':memory:');mem.execute(schema)
    screen.inspect(repo,[(oid,*roster[oid]) for oid in oids],mem)
    return mem.execute('select * from files').fetchall()
def read_pack(oids):
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        git=['git','-C',tmp]
        subprocess.run(git+['init','-q','--bare'],check=True,capture_output=True,env=git_env)
        subprocess.run(git+['-c','gc.auto=0','-c','fetch.negotiationAlgorithm=noop','-c','fetch.writeCommitGraph=false','fetch','--quiet','--filter=blob:none','--no-tags','--no-recurse-submodules','--no-write-fetch-head','--stdin',url],input=b'\n'.join(oids)+b'\n',check=True,capture_output=True,env=git_env,timeout=100)
        return local_inspect(Path(tmp),oids)
def one_raw(oid):
    val=subprocess.run(['gh','api','-H','Accept: application/vnd.github.raw+json','/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/'+oid.decode()],check=True,capture_output=True,env=git_env,timeout=75).stdout
    n=len(val)
    assert hashlib.sha1(b'blob '+str(n).encode()+b'\0'+val).hexdigest().encode()==oid
    flags=sum((1<<i) for i,regex in enumerate(screen.REGEX) if regex.search(val.lower()))
    return (oid.decode(),*roster[oid],n,int(b'\0' in val),flags)
def fetch(oids):
    try:
        return read_pack(oids),[]
    except (subprocess.SubprocessError,OSError):
        if len(oids)>12:
            third=(len(oids)+2)//3
            results=[fetch(oids[i:i+third]) for i in range(0,len(oids),third)]
            return sum((rows for rows,errors in results),[]),sum((errors for rows,errors in results),[])
        rows=[];errors=[]
        for o in oids:
            try:rows.append(one_raw(o))
            except (OSError,subprocess.SubprocessError) as err:errors.append((o.decode(),str(type(err).__name__)))
        return rows,errors
def save(rows,errors):
    with db:
        db.executemany('insert into files values(?,?,?,?,?,?)',rows)
        db.executemany('delete from errors where oid=?',[(r[0],) for r in rows])
        db.executemany('insert or replace into errors values(?,?)',errors)
def progress():
    new,nb=db.execute('select count(*),coalesce(sum(size),0) from files').fetchone()
    orig,ob=original.execute('select count(*),sum(size) from files').fetchone()
    rep={'utc':datetime.now(timezone.utc).isoformat(),'target':len(roster),'original_verified':orig,'new_verified':new,'verified':orig+new,'unverified':len(roster)-orig-new,'bytes':ob+nb,'errors':db.execute('select count(*) from errors').fetchone()[0]}
    p=out/'progress.tmp';p.write_text(json.dumps(rep,indent=2)+'\n');p.replace(out/'progress.json')
    print(json.dumps(rep),flush=True)
progress()
# All candidate databases refer to this same repository; verify Git identity before accepting local bytes.
for repo in [root/'frozen.git',root/'refs-namespace/pr-objects.git',Path.home()/'hepta-branch-audit-20261113-ab5b.git']:
    if not (repo/'objects').is_dir():continue
    keep=sorted(screen.have(repo) & need)
    for i in range(0,len(keep),384):
        save(local_inspect(repo,keep[i:i+384]),[])
    need-=set(keep)
print('network pending',len(need),flush=True)
items=sorted(need,key=lambda o:(-roster[o][0],o));chunks=[items[i:i+384] for i in range(0,len(items),384)]
with ThreadPoolExecutor(max_workers=4) as pool:
    jobs=[pool.submit(fetch,c) for c in chunks]
    for f in as_completed(jobs):
        rows,errors=f.result();save(rows,errors);progress()
progress()
assert len(roster)==len(previous)+db.execute('select count(*) from files').fetchone()[0]
