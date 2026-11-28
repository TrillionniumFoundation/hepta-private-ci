"""Build content-addressed evidence for all interleaved endpoints, aliasing byte-identical originals."""
import argparse
from pathlib import Path
import gzip
import hashlib
import json

def digest(b):return hashlib.sha256(b).hexdigest()
def prepare(original,timing,out):
    out.mkdir(exist_ok=True,parents=True)
    previous=json.loads((original/"original_manifest.json").read_text())
    catalog={entry["sha256"]:{"original_archive":piece,"member":name} for piece,m in previous.items()
             for name,entry in m["members"].items()}
    schedule=json.loads((timing/"seal.json").read_text());terminal=json.loads((timing/"terminal.json").read_text())
    assert digest((timing/"seal.json").read_bytes())==terminal["seal_sha256"]
    manifest={}
    for cell,rows in schedule.items():
        for label,row in rows.items():
            held=cell+"/"+label+"-held.npz"
            for name,sha in [(cell+"/"+row["weight"],row["weight_sha"]),(cell+"/"+row["dev"],row["dev_sha"]),
                             (held,terminal["metrics"][cell+"/"+label]["held_sha256"])]:
                b=(timing/name).read_bytes()
                if digest(b)!=sha:raise ValueError(name)
                if sha not in catalog:
                    packed=gzip.compress(b,compresslevel=4,mtime=0);fname=sha+".gz";(out/fname).write_bytes(packed)
                    catalog[sha]={"supplementary_archive":fname,"compressed_sha256":digest(packed)}
                manifest[name]=dict(sha256=sha,bytes=len(b),storage=catalog[sha])
    (out/"timing_manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n")
    print("logical files",len(manifest),"new content objects",sum(1 for x in out.glob("*.gz")),"staged bytes",sum(p.stat().st_size for p in out.iterdir()))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("original","timing","out"):p.add_argument(name,type=Path)
    a=p.parse_args();prepare(a.original,a.timing,a.out)
