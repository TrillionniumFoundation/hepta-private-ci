"""Preserve registered score and weight bytes. Run on the authorized CPU evidence relay."""
import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
from concurrent.futures import ThreadPoolExecutor

REPO="TrillionniumFoundation/hepta-private-ci"
BRANCH="research/hcsn-six-layer-signed-drift-9de7"
PREFIX="qualification/hcsn_signed_encoder_20261128/"

def digest(data):return hashlib.sha256(data).hexdigest()
def gh(method,endpoint,payload=None):
    args=["gh","api","-X",method,"repos/"+REPO+"/git/"+endpoint]
    if payload is not None:args+=["--input","-"]
    res=subprocess.run(args,input=None if payload is None else json.dumps(payload).encode(),
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=300)
    if res.returncode:raise ValueError(res.stderr.decode()[-600:])
    return json.loads(res.stdout)
def bundle(output,files):
    with output.open("wb") as raw,gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0,compresslevel=4) as gz,tarfile.open(mode="w",fileobj=gz) as tar:
        for name,data in sorted(files.items()):
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644
            tar.addfile(info,io.BytesIO(data))
def prepare(root,out):
    out.mkdir(exist_ok=True,parents=True)
    run=root/"run"
    def js(p):return json.loads(p.read_bytes())
    term=js(run/"terminal.json");seal=js(run/"seal.json")
    assert digest((run/"seal.json").read_bytes())==term["seal_sha256"]
    manifest={}
    for cell,labels in seal.items():
        parts={}
        for label,row in labels.items():
            m=term["metrics"][cell+"/"+label]
            for fname,sha in [(cell+"/"+row["weight"],row["weight_sha"]),
                              (cell+"/"+row["development_scores"],row["development_sha"]),
                              (m["held_file"],m["held_sha"])]:
                data=(run/fname).read_bytes()
                if digest(data)!=sha:raise ValueError(fname)
                parts[fname]=data
            info=cell+"/"+str(Path(row["weight"]).parent/(label+".json"))
            parts[info]=(run/info).read_bytes()
        dev=cell+"/development.json";parts[dev]=(run/dev).read_bytes()
        arc=out/(cell+".tar.gz");bundle(arc,parts)
        manifest[arc.name]=dict(bytes=arc.stat().st_size,sha256=digest(arc.read_bytes()),
                                members={p:dict(bytes=len(d),sha256=digest(d)) for p,d in parts.items()})
    assert len(manifest)==12
    for name in ("run/seal.json","run/recipe.json","run/terminal.json","kernel_validation.json"):
        data=(root/name).read_bytes();(out/Path(name).name).write_bytes(data)
    (out/"original_manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n")
def publish(out,prefix):
    paths=sorted(p for p in out.glob("*") if p.is_file())
    if not paths:raise ValueError("empty publication")
    def upload(p):
        data=p.read_bytes()
        want=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
        returned=gh("POST","blobs",{"encoding":"base64","content":base64.b64encode(data).decode()})["sha"]
        if want!=returned:raise ValueError(p.name)
        return {"path":PREFIX+prefix+"/"+p.name,"mode":"100644","type":"blob","sha":want}
    with ThreadPoolExecutor(max_workers=3) as workers:entries=list(workers.map(upload,paths))
    ref=gh("GET","ref/heads/"+BRANCH)["object"]["sha"]
    base=gh("GET","commits/"+ref)["tree"]["sha"]
    tree=gh("POST","trees",{"base_tree":base,"tree":entries})["sha"]
    if tree==base:return ref
    commit=gh("POST","commits",{"tree":tree,"parents":[ref],"message":"Preserve verified original "+prefix+" evidence for signed drift study"})["sha"]
    return gh("PATCH","refs/heads/"+BRANCH,{"sha":commit,"force":False})["object"]["sha"]
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("stage",type=Path);p.add_argument("--prepare-from",type=Path);p.add_argument("--prefix",default="results")
    a=p.parse_args()
    if a.prepare_from:prepare(a.prepare_from,a.stage)
    print(publish(a.stage,a.prefix),flush=True)
