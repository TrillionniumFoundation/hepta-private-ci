"""Recover missing tree objects of previously verified historical roots; verify the Git encoding."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import gzip,json,hashlib,subprocess,sys,zlib,os
root=Path.home()/".local/state/hepta-hcsn-1140569-audit/historical-closure-9de7"
repo=root/"objects.git";front=Path(sys.argv[1]);dest=root/"historical-tree-recovery";dest.mkdir(exist_ok=True)
wanted=set(gzip.decompress(front.read_bytes()).decode().splitlines())
def get(oid):
    p=repo/"objects"/oid[:2]/oid[2:]
    if p.is_file():return
    a=subprocess.run(["gh","api","repos/TrillionniumFoundation/hepta-private-ci/git/trees/"+oid],capture_output=True,timeout=60,check=True)
    result=json.loads(a.stdout)
    if result.get("truncated"):raise ValueError("truncated")
    children=sorted(result["tree"],key=lambda v:v["path"].encode()+ (b"/" if v["type"]=="tree" else b""))
    payload=b"".join(v["mode"].lstrip("0").encode()+b" "+v["path"].encode()+b"\0"+bytes.fromhex(v["sha"]) for v in children)
    obj=b"tree "+str(len(payload)).encode()+b"\0"+payload
    if hashlib.sha1(obj).hexdigest()!=oid:raise ValueError("tree ID mismatch")
    p.parent.mkdir(exist_ok=True);temp=p.with_suffix(".verified-tmp");temp.write_bytes(zlib.compress(obj));temp.replace(p)
ok=[];errors={}
with ThreadPoolExecutor(max_workers=5) as pool:
    jobs={pool.submit(get,o):o for o in sorted(wanted)}
    for i,j in enumerate(as_completed(jobs),1):
        try:j.result();ok.append(jobs[j])
        except Exception as e:errors[jobs[j]]=str(type(e).__name__)
        if i%100==0:print(i,len(ok),len(errors),flush=True)
out={"roster_sha256":hashlib.sha256(gzip.decompress(front.read_bytes())).hexdigest(),"verified":len(ok),"failures":errors}
(dest/(front.parent.name+".json")).write_text(json.dumps(out,sort_keys=True,indent=2)+"\n");print(out["verified"],"errors",len(errors),flush=True)
