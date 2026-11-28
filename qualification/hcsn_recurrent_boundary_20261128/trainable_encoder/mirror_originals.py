"""Save each original rung to an independent disk even if GitHub transport is offline."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
import fcntl


def hashes(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def persist(sealer,stage,out,rung):
    target=out/(rung+".json")
    if target.exists():return True
    files=sealer.inventory(stage,rung)
    if files is None:return False
    # All members have been checked by the source inventory against native checkpoint receipts.
    out.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=out,prefix="archive-",suffix=".part",delete=False) as obj:
        tmp=Path(obj.name)
    try:
        with tarfile.open(tmp,"w:gz",compresslevel=2) as tar:
            for member in sorted(files):tar.add(stage/member,arcname=member,recursive=False)
        partdir=out/rung;partdir.mkdir(exist_ok=True)
        pieces=[]
        with tmp.open("rb") as stream:
            while data:=stream.read(240000):
                name=f"archive.part{len(pieces):04}"
                part=partdir/(name+".tmp");part.write_bytes(data)
                final=partdir/name;part.replace(final)
                pieces.append(dict(path=name,bytes=len(data),sha256=hashes(final)))
        with tarfile.open(tmp,"r:gz") as tar:
            for mem in tar:
                if hashlib.file_digest(tar.extractfile(mem),"sha256").hexdigest()!=hashes(stage/mem.name):
                    raise ValueError("independent archive discrepancy")
        manifest=dict(rung=rung,utc=time.time(),native_files=len(files),
                      archive_bytes=tmp.stat().st_size,archive_sha256=hashes(tmp),parts=pieces,
                      raw_receipt_sha=hashes(stage/("released-"+rung+".json")))
        t=target.with_suffix(".tmp");t.write_text(json.dumps(manifest,indent=2)+"\n");t.replace(target)
        print("verified original archive",rung,manifest["native_files"],manifest["archive_bytes"],manifest["archive_sha256"],flush=True)
        return True
    finally:tmp.unlink(missing_ok=True)


def main(provider,stage,out):
    spec=importlib.util.spec_from_file_location("native_provider",provider)
    s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
    stage.mkdir(exist_ok=True,parents=True);out.mkdir(exist_ok=True,parents=True)
    with (out/"mirror.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        rungs=(*s.RUNG,"terminal")
        while True:
            for rung in rungs:
                if not (out/(rung+".json")).exists():
                    try:persist(s,stage,out,rung)
                    except (OSError,RuntimeError,TimeoutError) as ex:
                        print("source transport",rung,type(ex).__name__,str(ex)[:240],flush=True)
                    break
            else:return
            time.sleep(20)
if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("provider",type=Path);a.add_argument("stage",type=Path);a.add_argument("out",type=Path)
    p=a.parse_args();main(p.provider,p.stage,p.out)
