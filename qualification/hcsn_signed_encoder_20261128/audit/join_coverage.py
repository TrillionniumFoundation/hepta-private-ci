"""Check the exact OID union for frozen heads, PRs and tags against verified per-object receipts."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
R=Path(sys.argv[1]);S=R/"refs-namespace";P=S/"delta/recovery_9de7/new_snapshot";OUT=Path(sys.argv[2])
OUT.mkdir(exist_ok=True,parents=True)
data={};stats={}
def add(bucket,items):
    n=size=0
    for oid,length,flags,binary,sha in items:
        if oid in data and data[oid][0]!=length:raise ValueError(oid)
        data[oid]=length,flags,binary,sha,bucket;n+=1;size+=length
    stats[bucket]={"objects":n,"bytes":size}
def screen(db):
    conn=sqlite3.connect("file:"+str(db)+"?mode=ro",uri=True)
    for oid,size,binary,flags in conn.execute("select oid,size,binary,flags from files"):yield oid,size,flags,binary,""
def rows(path):
    for line in gzip.decompress(path.read_bytes()).decode().splitlines():yield line.split("\t")
def oidset(path):return {r.split(b"\t",1)[0].decode() for r in path.read_bytes().splitlines()}
originals=[]
for bucket,db in [("original-source",R/"scan-work/screen.sqlite"),("recovered-source",R/"source-recovery-9de7/recovered.sqlite"),("additional-text",R/"broad-text/work/screen.sqlite"),("tags-only-text",R/"tags/unique-work/screen.sqlite")]:
    a=list(screen(db));originals.append({r[0] for r in a});add(bucket,a)
assert originals[0].isdisjoint(originals[1])
assert originals[0]|originals[1]==oidset(R/"results/files.tsv")
for host in ["ai395","x230"]:
    add(host+"-binary",((r[0],int(r[2]),-1,-1,r[3]) for r in rows(P/(host+"-binary-verified.tsv.gz"))))
initial=oidset(R/"results/all_blobs.tsv")|oidset(R/"tags/tag_all_unique_input.tsv")
assert set(data)==initial and len(initial)==212288 and sum(x["objects"] for x in stats.values())==len(initial)
add("second-source",screen(S/"delta/source/work/screen.sqlite"))
add("second-other",((r[0],int(r[2]),-1,-1,r[3]) for r in rows(S/"delta/recovery_9de7/verified_objects.tsv.gz")))
second=oidset(S/"public_heads_tags/all_blobs.tsv")|oidset(S/"pull/all_blobs.tsv")
assert set(data)==initial|second
latest=set(gzip.decompress((P/"all_ids.txt.gz").read_bytes()).decode().splitlines())
receipt=json.loads((P/"tree_receipt.json").read_text());gethash=lambda b:hashlib.sha256(b).hexdigest()
assert len(latest)==231450 and gethash("".join(o+"\n" for o in sorted(latest)).encode())==receipt["blob_ids_sha256"]
latest_detail=list(rows(P/"latest_marker_rows.tsv.gz"))
assert {r[0] for r in latest_detail}==latest-second
add("latest-delta",((r[0],int(r[1]),int(r[4]),int(r[3]),r[2]) for r in latest_detail))
assert set(data)>=latest
current={o:data[o] for o in latest};names=["hcsn","paper","boundary","hit","neural","kinetic","editing","multimodal","speed"]
ledger=("oid\tbytes\tmarker_flags\tnul\tcontent_sha256\tsource\n"+"".join(o+"\t"+"\t".join(map(str,current[o]))+"\n" for o in sorted(current))).encode()
packed=gzip.compress(ledger,mtime=0)
(OUT/"verified_objects.tsv.gz").write_bytes(packed)
raw=(P/"advertisement.tsv.gz").read_bytes();(OUT/"advertisement.tsv.gz").write_bytes(raw)
counts=Counter();sizes=Counter()
for length,flags,nul,sha,bucket in current.values():counts[bucket]+=1;sizes[bucket]+=length
meta=dict(reference_capture_utc=json.loads((P/"comparison.json").read_text())["finished_utc"],refs=receipt["refs"],advertisement_sha256=gethash(gzip.decompress(raw)),
targets=receipt["verifiable_commit_targets"],root_trees=receipt["roots"],trees=receipt["trees"],gitlinks=receipt["gitlinks"],
all_verified_blobs=len(current),total_verified_bytes=sum(v[0] for v in current.values()),oid_set_sha256=receipt["blob_ids_sha256"],
marker_screened_objects=sum(v[1]>=0 for v in current.values()),marker_screened_bytes=sum(v[0] for v in current.values() if v[1]>=0),
markers={name:sum(v[1]>=0 and bool(v[1]&(1<<i)) for v in current.values()) for i,name in enumerate(names)},
objects_with_independent_sha256=sum(bool(v[3]) for v in current.values()),raw_receipt_sources=stats,
included_by_source={k:dict(objects=v,bytes=sizes[k]) for k,v in counts.items()},
evidence_ledger_sha256=gethash(ledger),evidence_archive_sha256=gethash(packed),
read_scope="Git blob identity and full payload lengths from the exact fixed tip trees. Source-like objects were marker screened. Compressed payloads were checked as their outer Git objects. Negative marker_flags or nul denote that the original evidence did not record that column.")
(OUT/"coverage.json").write_text(json.dumps(meta,sort_keys=True,indent=2)+"\n")
print(json.dumps(meta,sort_keys=True),flush=True)
