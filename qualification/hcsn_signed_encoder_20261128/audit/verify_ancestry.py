"""Verify raw commits and every parent edge behind the fixed latest reference advertisement."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from collections import deque
import gzip
import hashlib
import json
import os
import sqlite3
import subprocess
import time
import zlib

root=Path.home()/".local/state/hepta-hcsn-1140569-audit"
prior=root/"refs-namespace/delta/recovery_9de7/new_snapshot"
out=root/"historical-closure-9de7";out.mkdir(exist_ok=True)
repo=out/"objects.git";subprocess.run(["git","init","--bare","--quiet",str(repo)],check=True)
older=root/"reachable-history/history.git"
alt=[older/"objects",prior/"gitobjects.git/objects",Path.home()/"hepta-branch-audit-20261113-ab5b.git/objects"]
(repo/"objects/info/alternates").write_text("".join(str(p.resolve())+"\n" for p in alt if p.is_dir()))
env={**os.environ,"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_TERMINAL_PROMPT":"0"}
git=["git","--git-dir",str(repo)]
def raw_id(kind,v):return hashlib.sha1(kind+b" "+str(len(v)).encode()+b"\0"+v).hexdigest()
def utc():return datetime.now(timezone.utc).isoformat()
def try_api(oid):
    url="repos/TrillionniumFoundation/hepta-private-ci/git/commits/"+oid
    rec=json.loads(subprocess.check_output(["gh","api",url],timeout=40,stderr=subprocess.PIPE))
    if rec["sha"]!=oid:raise ValueError(oid)
    verification=rec["verification"]
    if verification["payload"] and verification["signature"]:
        head,body=verification["payload"].encode().split(b"\n\n",1)
        sig=verification["signature"].rstrip("\n").encode().replace(b"\n",b"\n ")
        for sighead in [b"gpgsig ",b"gpgsig-sha256 "]:
            for extra in [b"",b"\n "]:
                v=head+b"\n"+sighead+sig+extra+b"\n\n"+body
                if raw_id(b"commit",v)==oid:return v
    head=("tree "+rec["tree"]["sha"]+"\n"+"".join("parent "+x["sha"]+"\n" for x in rec["parents"])).encode()
    def who(key):
        x=rec[key];stamp=int(datetime.fromisoformat(x["date"].replace("Z","+00:00")).timestamp())
        return f"{key} {x['name']} <{x['email']}> {stamp} ".encode()
    A=who("author");C=who("committer")
    common=[b"+0000",b"-0500",b"-0400",b"+0800",b"-0700",b"-0800",b"+0100",b"-0600",b"+0530",b"+0900",b"+0200",b"+0300",b"-0000"]
    zones=common+[(sign+str(hour).zfill(2)+str(minute).zfill(2)).encode() for sign in "+-" for hour in range(15) for minute in (0,15,30,45)]
    zones=list(dict.fromkeys(zones));pairs=[(z,z) for z in zones]+[(a,b) for a in zones for b in zones if a!=b]
    msg=rec["message"].encode()
    for extra in (b"\n",b"",b"\n\n"):
        for a,c in pairs:
            v=head+A+a+b"\n"+C+c+b"\n\n"+msg+extra
            if raw_id(b"commit",v)==oid:return v
    raise ValueError("cannot reconstruct "+oid)
def store_object(oid,val):
    assert raw_id(b"commit",val)==oid
    obj=repo/"objects"/oid[:2]/oid[2:];obj.parent.mkdir(exist_ok=True)
    payload=b"commit "+str(len(val)).encode()+b"\0"+val;tmp=obj.with_suffix(".partial");tmp.write_bytes(zlib.compress(payload));tmp.replace(obj)
def parents(val):
    h,_,msg=val.partition(b"\n\n");lines=h.splitlines()
    return lines[0].split()[1].decode(),[x[7:].decode() for x in lines if x.startswith(b"parent ")],msg.split(b"\n",1)[0].decode("utf8","replace")
refs={k:v for v,k in (s.split("\t",1) for s in gzip.decompress((prior/"advertisement.tsv.gz").read_bytes()).decode().splitlines()) if k.startswith("refs/")}
refs.update({n[:-3]:v for n,v in list(refs.items()) if n.endswith("^{}")})
tips={v for n,v in refs.items() if not n.endswith("^{}")}
db=sqlite3.connect(out/"verified.sqlite")
db.execute("create table if not exists commits(oid text primary key,root text,parents text,subject text)")
cur={p.split()[0].decode() for p in subprocess.check_output(git+["cat-file","--batch-all-objects","--batch-check=%(objectname) %(objecttype)"],env=env,stderr=subprocess.DEVNULL).splitlines() if p.endswith(b" commit")}
known={o for o, in db.execute("select oid from commits")}
waiting=set(tips-known)
for ps, in db.execute("select parents from commits"):waiting.update(k for k in ps.split() if k not in known)
def take(oid,val):
    assert raw_id(b"commit",val)==oid;tr,ps,title=parents(val)
    db.execute("insert into commits values(?,?,?,?)",(oid,tr," ".join(ps),title));known.add(oid)
    waiting.update(p for p in ps if p not in known)
def status():
    d=dict(utc=utc(),tips=len(tips),verified_raw_commits=len(known),missing_frontier=len(waiting))
    (out/"progress.json").write_text(json.dumps(d,indent=2)+"\n");(out/"frontier.txt").write_text("".join(k+"\n" for k in sorted(waiting)));print(d,flush=True)
round_id=0
while waiting:
    with subprocess.Popen(git+["cat-file","--batch"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env) as cat:
        local=deque(sorted(cur&waiting))
        while local:
            oid=local.popleft()
            if oid in known:continue
            cat.stdin.write((oid+"\n").encode());cat.stdin.flush();h=cat.stdout.readline().split();assert len(h)==3
            val=cat.stdout.read(int(h[2]));assert cat.stdout.read(1)==b"\n"
            par=parents(val)[1];waiting.discard(oid);take(oid,val);local.extend(k for k in par if k in cur and k not in known)
        cat.stdin.close()
    db.commit();status()
    if not waiting:break
    round_id+=1;needed=sorted(waiting);failures={}
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs={pool.submit(try_api,k):k for k in needed}
        for j in as_completed(jobs):
            oid=jobs[j]
            try:val=j.result()
            except Exception as ex:
                failures[oid]=str(ex)[:180];continue
            store_object(oid,val);cur.add(oid);waiting.discard(oid);take(oid,val)
            if len(known)%100==0:db.commit();status()
    db.commit();status()
    if len(failures)==len(needed):raise RuntimeError("all API reconstructions unavailable: "+str(list(failures.items())[:3]))
walk=subprocess.check_output(git+["rev-list","--stdin"],input=("".join(o+"\n" for o in sorted(tips))).encode(),env=env).decode().splitlines()
assert set(walk)==known
ordered=lambda x:"".join(o+"\n" for o in sorted(x)).encode()
report={"utc":utc(),"tips":len(tips),"raw_commits":len(known),"git_rev_list":len(walk),"oid_sha256":hashlib.sha256(ordered(walk)).hexdigest(),"unique_root_trees":db.execute("select count(distinct root) from commits").fetchone()[0],"parent_edges":sum(len(p.split()) for p, in db.execute("select parents from commits")),"missing_parents":0}
(out/"summary.json").write_text(json.dumps(report,indent=2)+"\n");print(report,flush=True)
