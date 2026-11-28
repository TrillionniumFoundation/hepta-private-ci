"""Recover original large payloads by their exact Git IDs, preserving raw-content verification."""
from collections import defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
r=Path(__file__).resolve().parent
roster=json.loads(gzip.decompress((r/"local_roster.json.gz").read_bytes()))
want=defaultdict(set)
for oid,(size,name) in roster.items():want[size].add(oid)
names={v[1] for v in roster.values()};out=r/"native_rows.tsv";old=out.read_text().splitlines() if out.exists() else []
done={line.split("\t")[0] for line in old}
rx=[re.compile(s.encode()) for s in ("hcsn|hepta[ _-]*continuous[ _-]*spik|hepta[ _-]*连续脉冲","he[ _–—-]*(?:(?:and|&)[ _-]*)?xiong|rollover risk and credit risk|rollover[ _-]*(?:loss|risk)","free[ _-]*boundar|smooth[ _-]*past|自由边界|光滑粘贴|光滑贴合","first[ _-]*(?:passage|hitt?ing)|brownian bridge|首达|首次穿越","spiking|neuron|神经元|脉冲网络","refractory|regenerati(?:ve|on)|renewal|不应期|复位","weight[ _-]*edit|model[ _-]*edit|knowledge[ _-]*edit|forward[ _-]*projection|权重编辑|前向投影","multi[ _-]*modal|omni[ _-]*modal|全模态|多模态|image[ _-]*(?:text|caption)|audio[ _-]*visual","time[ _-]*to[ _-]*(?:quality|target)|wall[ _-]*(?:time|clock)|同质量|端到端时间")]
visited=set()
def scan(p,s):
    if (s.st_dev,s.st_ino) in visited:return
    visited.add((s.st_dev,s.st_ino));size=s.st_size
    if not want[size]-done:return
    data=p.read_bytes();oid=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
    if oid not in want[size] or oid in done:return
    low=data.lower();flags=sum((1<<i) for i,rgx in enumerate(rx) if rgx.search(low));sha=hashlib.sha256(data).hexdigest()
    with out.open("a") as f:f.write("\t".join(map(str,[oid,len(data),sha,int(b"\0" in data),flags]))+"\n")
    done.add(oid)
roots=[Path.home()/".local/share/hepta-research",Path.home()/".local/state",Path("/tmp")]+[p for p in Path.home().iterdir() if p.is_dir() and re.search(r'hepta|hcsn|research|experiment',p.name,re.I)]
for root in roots:
    for path,dirs,files in os.walk(root):
        dirs[:]=[d for d in dirs if d not in {".git","node_modules","__pycache__","objects","target","packs","venv","cache"} and not d.endswith(".git")]
        if str(r)==path or "site-packages" in path:dirs.clear();continue
        for name in files:
            p=Path(path)/name
            try:
                s=p.stat()
                if s.st_size in want and (name in names or (s.st_size>=50000 and any(x in path.lower() for x in ("hepta","hcsn","mosi","weightcode","lsm","crema")))):scan(p,s)
            except (OSError,ValueError):pass
print("verified",len(done),"bytes",sum(roster[oid][0] for oid in done),flush=True)
