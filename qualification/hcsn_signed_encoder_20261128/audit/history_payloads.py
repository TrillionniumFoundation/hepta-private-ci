"""Read, hash and flag historical-only contents, using verified local copies before bounded Git packs."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
R=Path.home()/".local/state/hepta-hcsn-1140569-audit"
H=R/"historical-closure-9de7";sys.path.insert(0,str(R));import screen
repo=H/"objects.git";path=Path(sys.argv[1]);workers=int(sys.argv[2]);label=sys.argv[3]
stage=H/"payloads"/label;stage.mkdir(exist_ok=True,parents=True)
target=set(gzip.decompress(path.read_bytes()).decode().splitlines())
db=sqlite3.connect(stage/"results.sqlite");db.execute("create table if not exists files(oid text primary key,size integer,sha text,nul integer,flags integer)")
done={x for x, in db.execute("select oid from files")};missing=sorted(target-done)
env={**os.environ,"GIT_NO_LAZY_FETCH":"1","GIT_TERMINAL_PROMPT":"0"}
def cat(repo,ids):
    ret=[]
    process=subprocess.Popen(["git","--git-dir",str(repo),"cat-file","--batch"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env)
    try:
        for oid in ids:
            process.stdin.write((oid+"\n").encode());process.stdin.flush();h=process.stdout.readline().split()
            if len(h)!=3:continue
            assert h[0].decode()==oid and h[1]==b"blob"
            size=int(h[2]);left=size;g=hashlib.sha1(b"blob "+h[2]+b"\0");s=hashlib.sha256();nul=False;flags=0;carry=b""
            while left:
                b=process.stdout.read(min(left,131072));assert b;left-=len(b);g.update(b);s.update(b);nul|=b"\0" in b
                if not nul:
                    chunk=carry+b.lower();carry=chunk[-512:]
                    for i,p in enumerate(screen.REGEX):
                        if not (flags&(1<<i)) and p.search(chunk):flags|=1<<i
            assert process.stdout.read(1)==b"\n" and g.hexdigest()==oid;ret.append((oid,size,s.hexdigest(),int(nul),-1 if nul else flags))
    finally:process.stdin.close();process.wait()
    return ret
def save(rows):
    with db:db.executemany("insert or ignore into files values(?,?,?,?,?)",rows)
def status():
    n,amt=db.execute("select count(*),coalesce(sum(size),0) from files").fetchone()
    s=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),target=len(target),verified=n,bytes=amt,missing=len(target)-n,roster_ledger=path.name)
    (stage/"progress.json").write_text(json.dumps(s,indent=2)+"\n");print(s,flush=True)
for i in range(0,len(missing),512):
    save(cat(repo,missing[i:i+512]))
    if i%8192==0:status()
status()
if workers==0:sys.exit(0)
missing=sorted(target-{x for x, in db.execute("select oid from files")})
def fetch(ids):
    with tempfile.TemporaryDirectory(dir=stage) as path:
        git=["git","-C",path];subprocess.run(git+["init","--bare","-q"],env=env,check=True)
        args=git+["-c","gc.auto=0","-c","fetch.negotiationAlgorithm=noop","fetch","--quiet","--filter=blob:none","--no-tags","--no-write-fetch-head","--stdin","https://github.com/TrillionniumFoundation/hepta-private-ci.git"]
        subprocess.run(args,input="".join(o+"\n" for o in ids).encode(),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,check=True)
        return cat(path,ids)
with ThreadPoolExecutor(max_workers=workers) as pool:
    tasks={pool.submit(fetch,missing[i:i+128]):missing[i:i+128] for i in range(0,len(missing),128)}
    for i,f in enumerate(as_completed(tasks),1):
        try:save(f.result())
        except (OSError,subprocess.SubprocessError):pass
        if i%12==0:status()
status()
