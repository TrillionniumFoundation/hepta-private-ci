"""Index every tree currently available from verified historical roots; retain all missing frontiers."""
from datetime import datetime,timezone
from pathlib import Path
import gzip
import sqlite3
import subprocess
import hashlib
import os
import json
import sys
root=Path.home()/".local/state/hepta-hcsn-1140569-audit"
q=root/"historical-closure-9de7";p=root/"refs-namespace/delta/recovery_9de7/new_snapshot";repo=q/"objects.git"
out=q/sys.argv[1];out.mkdir(exist_ok=True)
env={**os.environ,"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_TERMINAL_PROMPT":"0"}
base=["git","--git-dir",str(repo)]
raw=gzip.decompress((p/"advertisement.tsv.gz").read_bytes()).decode().splitlines()
refs={k:v for v,k in (s.split("\t",1) for s in raw) if k.startswith("refs/")}
refs.update({k[:-3]:v for k,v in list(refs.items()) if k.endswith("^{}")});tips={v for k,v in refs.items() if not k.endswith("^{}")}
def ordered(s):return "".join(v+"\n" for v in sorted(s)).encode()
def digest(s):return hashlib.sha256(s).hexdigest()
with (out/"rev-list.stdout").open("wb") as stdout,(out/"rev-list.stderr").open("wb") as stderr:
    result=subprocess.run(base+["rev-list","--objects","--no-object-names","--missing=print","--stdin"],input=ordered(tips),stdout=stdout,stderr=stderr,env=env)
conn=sqlite3.connect("file:"+str(q/"verified.sqlite")+"?mode=ro",uri=True)
conn.execute("begin")
roots={v for v, in conn.execute("select distinct root from commits")};commits={v for v, in conn.execute("select oid from commits")};parents={v for line, in conn.execute("select parents from commits") for v in line.split()};frontier=(parents|tips)-commits;conn.close()
listing=subprocess.check_output(base+["cat-file","--batch-all-objects","--batch-check=%(objectname) %(objecttype)"],env=env,stderr=subprocess.DEVNULL)
local={r[:40].decode() for r in listing.splitlines() if r.endswith(b" tree")}
seen=set();missing=set();blobs=set();links=set();todo=list(roots)
cat=subprocess.Popen(base+["cat-file","--batch"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env)
while todo:
    oid=todo.pop()
    if oid in seen or oid in missing:continue
    if oid not in local:missing.add(oid);continue
    cat.stdin.write((oid+"\n").encode());cat.stdin.flush();h=cat.stdout.readline().split()
    if len(h)!=3 or h[0].decode()!=oid or h[1]!=b"tree":raise ValueError(oid)
    raw=cat.stdout.read(int(h[2]));assert cat.stdout.read(1)==b"\n" and hashlib.sha1(b"tree "+h[2]+b"\0"+raw).hexdigest()==oid
    seen.add(oid);i=0
    while i<len(raw):
        k=raw.index(b" ",i);j=raw.index(b"\0",k);child=raw[j+1:j+21].hex();mode=raw[i:k];i=j+21
        if mode==b"40000":todo.append(child)
        elif mode==b"160000":links.add(child)
        else:blobs.add(child)
cat.stdin.close();assert cat.wait()==0
current=set(gzip.decompress((p/"all_ids.txt.gz").read_bytes()).decode().splitlines())
z=blobs-current
assert current<=blobs
sets={"historical_tree_frontier":missing,"known_historical_only":z,"known_historical_blob_union":blobs,"known_historical_roots":roots,"verified_historical_trees":seen,"missing_parent_or_tip":frontier}
details={}
for name,values in sets.items():
    v=ordered(values);(out/(name+".txt.gz")).write_bytes(gzip.compress(v,mtime=0));details[name]=dict(count=len(values),sha256=digest(v))
d=dict(utc=datetime.now(timezone.utc).isoformat(),advertisement_sha256=digest(gzip.decompress((p/"advertisement.tsv.gz").read_bytes())),tip_commits=len(tips),raw_reachable_commits=len(commits),gitlinks=len(links),current_tip_blobs=len(current),sets=details,
       git_rev_list_exit=result.returncode,git_rev_list_stdout_sha256=digest((out/"rev-list.stdout").read_bytes()),git_rev_list_lines=sum(1 for _ in (out/"rev-list.stdout").open("rb")),git_rev_list_stderr=(out/"rev-list.stderr").read_text(errors="replace")[-350:],
       complete=not missing and not frontier)
(out/"result.json").write_text(json.dumps(d,indent=2)+"\n");print(json.dumps(d),flush=True)
