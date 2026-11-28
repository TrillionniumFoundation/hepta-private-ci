"""Read every newly exposed Git blob, SHA-1/SHA-256, NUL-test and term screen all bytes."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
R=Path.home()/".local/state/hepta-hcsn-1140569-audit"
P=R/"refs-namespace/delta/recovery_9de7/new_snapshot"
sys.path.insert(0,str(R))
import screen
ids=set(gzip.decompress((P/"new_blob_ids.txt.gz").read_bytes()).splitlines())
assert len(ids)==696
db=sqlite3.connect(P/"latest_marker.sqlite")
db.execute("create table if not exists files(oid text primary key,size integer,digest text,nul integer,flags integer)")
def read(oid):
    for attempt in range(3):
        try:
            with tempfile.TemporaryFile() as f:
                subprocess.run(["gh","api","-H","Accept: application/vnd.github.raw+json","/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/"+oid.decode()],stdout=f,stderr=subprocess.PIPE,check=True,timeout=40)
                size=f.tell();f.seek(0);flags=0;nul=0;carry=b""
                git=hashlib.sha1(b"blob "+str(size).encode()+b"\0");sha=hashlib.sha256()
                while val:=f.read(131072):
                    git.update(val);sha.update(val);nul|=int(b"\0" in val);chunk=carry+val.lower()
                    for i,pat in enumerate(screen.REGEX):
                        if not (flags&(1<<i)) and pat.search(chunk):flags|=1<<i
                    carry=chunk[-512:]
                if git.hexdigest()!=oid.decode():raise ValueError("raw content mismatch")
                return oid.decode(),size,sha.hexdigest(),nul,flags
        except (subprocess.SubprocessError,OSError,ValueError):
            if attempt==2:raise
            time.sleep(1+2*attempt)
already={o.encode() for o, in db.execute("select oid from files")}
with ThreadPoolExecutor(max_workers=5) as pool:
    work={pool.submit(read,oid):oid for oid in sorted(ids-already)}
    for i,job in enumerate(as_completed(work),1):
        try:row=job.result()
        except Exception as exc:
            print("failed",work[job].decode(),str(type(exc)),flush=True);continue
        with db:db.execute("insert into files values(?,?,?,?,?)",row)
        if i%80==0:print(i,flush=True)
rows=list(db.execute("select * from files order by oid"));assert {r[0].encode() for r in rows}==ids
text="".join("\t".join(map(str,r))+"\n" for r in rows).encode()
(P/"latest_marker_rows.tsv.gz").write_bytes(gzip.compress(text,mtime=0))
report=dict(utc=datetime.now(timezone.utc).isoformat(),objects=len(rows),bytes=sum(r[1] for r in rows),
            nul_positive=sum(r[3] for r in rows),row_sha256=hashlib.sha256(text).hexdigest(),
            markers={name:sum(bool(r[4]&(1<<i)) for r in rows) for i,name in enumerate(screen.MARKS)})
(P/"latest_marker_report.json").write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report),flush=True)
