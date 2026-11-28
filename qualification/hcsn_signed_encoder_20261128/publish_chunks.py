"""Upload immutable archive fragments and verify their Git IDs before updating the private ref."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import time
from publish_evidence import BRANCH,PREFIX,gh

BLOCK=512*1024
def sha(data):return hashlib.sha256(data).hexdigest()
def hash_blob(data):return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def release(src,ledger,prefix):
    ledger.mkdir(exist_ok=True,parents=True)
    files={};manifest={}
    for p in sorted(src.glob("*")):
        if not p.is_file():continue
        content=p.read_bytes()
        if len(content)<=BLOCK:
            files[p.name]=content;continue
        chunks=[]
        for offset in range(0,len(content),BLOCK):
            part=content[offset:offset+BLOCK];name="pieces/"+p.name+".part%04d"%(offset//BLOCK)
            files[name]=part;chunks.append(dict(path=name,bytes=len(part),sha256=sha(part)))
        manifest[p.name]=dict(bytes=len(content),sha256=sha(content),parts=chunks)
    files["archive_index.json"]=(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode()
    def upload(item):
        name,content=item;oid=hash_blob(content);persist=ledger/(oid+".ok")
        if not persist.is_file():
            for trial in range(5):
                try:
                    rr=gh("POST","blobs",dict(content=base64.b64encode(content).decode(),encoding="base64"))
                    if rr["sha"]!=oid:raise ValueError("Git blob mismatch "+name)
                    persist.write_text(oid+"\n")
                    break
                except Exception as e:
                    if trial==4:raise
                    time.sleep(3*(trial+1))
        return dict(path=PREFIX+prefix+"/"+name,mode="100644",type="blob",sha=oid)
    entries=[]
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs=[pool.submit(upload,i) for i in files.items()]
        for future in as_completed(jobs):
            entries.append(future.result())
            if len(entries)%10==0:print("verified upload",len(entries),"/",len(jobs),flush=True)
    for retry in range(4):
        head=gh("GET","ref/heads/"+BRANCH)["object"]["sha"]
        orig=gh("GET","commits/"+head)["tree"]["sha"]
        tree=gh("POST","trees",dict(base_tree=orig,tree=entries))["sha"]
        if tree==orig:return head
        c=gh("POST","commits",dict(tree=tree,parents=[head],message="Archive complete original "+prefix+" bytes with per-fragment replay ledger"))["sha"]
        try:return gh("PATCH","refs/heads/"+BRANCH,dict(sha=c,force=False))["object"]["sha"]
        except ValueError:
            if retry==3:raise
            time.sleep(2)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("stage",type=Path);p.add_argument("ledger",type=Path);p.add_argument("--prefix",default="results")
    a=p.parse_args();print(release(a.stage,a.ledger,a.prefix),flush=True)
