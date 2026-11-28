"""Join all historical-only original bytes, run missing cohorts and repair failed pack transfers."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import gzip,hashlib,json,os,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path
R=Path.home()/".local/state/hepta-hcsn-1140569-audit";H=R/"historical-closure-9de7";sys.path.insert(0,str(R));import screen
F=H/"actual-historical-content";F.mkdir(exist_ok=True)
def ids(p):return set(gzip.decompress(p.read_bytes()).decode().splitlines())
def ordered(values):return "".join(s+"\n" for s in sorted(values)).encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def job_running(script,label):
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():continue
        try:a=(p/"cmdline").read_bytes().split(b"\0")
        except OSError:continue
        if str(script).encode() in a[:5] and label.encode() in a:return True
    return False
while not (H/"complete_tree_index.json").is_file():time.sleep(25)
meta=json.loads((H/"complete_tree_index.json").read_text());assert meta["complete"]
full=ids(H/meta["directory"]/"known_historical_only.txt.gz")
first=ids(H/"index-at-1514z/known_historical_only.txt.gz");assert first<=full
rest=full-first;roster=F/"additional_history.txt.gz";roster.write_bytes(gzip.compress(ordered(rest),mtime=0))
worker=H/"history_payloads.py"
if rest:subprocess.run([sys.executable,"-u",str(worker),str(roster),"2","additional-final"],check=True)
while job_running(worker,"index-at-1514z"):time.sleep(30)
db=sqlite3.connect(F/"recovered.sqlite");db.execute("create table if not exists files(oid text primary key,size integer,sha text,nul integer,flags integer)")
for q in (H/"payloads").glob("*/results.sqlite"):
    with sqlite3.connect("file:"+str(q)+"?mode=ro",uri=True) as src:
        with db:db.executemany("insert or ignore into files values(?,?,?,?,?)",src.execute("select * from files"))
covered={o for o, in db.execute("select oid from files")};assert covered<=full
missing=sorted(full-covered)
def scan(oid,s,f):
    g=hashlib.sha1(b"blob "+str(s).encode()+b"\0");h=hashlib.sha256();nul=False;carry=b"";flags=0
    while raw:=f.read(131072):
        g.update(raw);h.update(raw);nul|=b"\0" in raw
        if not nul:
            c=carry+raw.lower();carry=c[-512:]
            for i,rg in enumerate(screen.REGEX):
                if not flags&(1<<i) and rg.search(c):flags|=1<<i
    if g.hexdigest()!=oid:raise ValueError(oid)
    return oid,s,h.hexdigest(),int(nul),-1 if nul else flags
def raw(oid):
    with tempfile.TemporaryFile() as f:
        q=subprocess.run(["gh","api","-H","Accept: application/vnd.github.raw+json","repos/TrillionniumFoundation/hepta-private-ci/git/blobs/"+oid],stdout=f,stderr=subprocess.PIPE,timeout=360)
        if q.returncode:raise IOError(q.stderr.decode(errors="replace")[-160:])
        n=f.tell();f.seek(0);return scan(oid,n,f)
def status():
    n,b=db.execute("select count(*),coalesce(sum(size),0) from files").fetchone();v={"utc":datetime.now(timezone.utc).isoformat(),"target":len(full),"verified":n,"bytes":b,"missing":len(full)-n}
    (F/"progress.json").write_text(json.dumps(v,indent=2)+"\n");print(v,flush=True)
status()
while missing:
    failures=[]
    with ThreadPoolExecutor(max_workers=5) as p:
        jobs={p.submit(raw,o):o for o in missing}
        for i,f in enumerate(as_completed(jobs),1):
            try:
                row=f.result()
                with db:db.execute("insert or ignore into files values(?,?,?,?,?)",row)
            except (OSError,ValueError,subprocess.SubprocessError):failures.append(jobs[f])
            if i%100==0:status()
    (F/"missing.txt").write_bytes(ordered(failures));status()
    if len(failures)==len(missing):time.sleep(35)
    missing=sorted(failures)
rows=db.execute("select * from files order by oid").fetchall();assert {r[0] for r in rows}==full
payload="".join("\t".join(map(str,r))+"\n" for r in rows).encode();(F/"verified.tsv.gz").write_bytes(gzip.compress(payload,mtime=0))
tip=json.loads((H/"tip-evidence/coverage.json").read_text())
result={"utc":datetime.now(timezone.utc).isoformat(),"advertisement_sha256":meta["advertisement_sha256"],"fully_reachable_commits":meta["raw_reachable_commits"],"historical_only":len(full),"historical_only_bytes":sum(v[1] for v in rows),"historical_ledger_sha256":sha(payload),"tip_blobs":tip["all_verified_blobs"],"tip_bytes":tip["total_verified_bytes"],"all_history_blob_union":len(full)+tip["all_verified_blobs"],"all_history_bytes":sum(v[1] for v in rows)+tip["total_verified_bytes"],"missing":0}
(F/"terminal.json").write_text(json.dumps(result,indent=2)+"\n");print(result,flush=True)
