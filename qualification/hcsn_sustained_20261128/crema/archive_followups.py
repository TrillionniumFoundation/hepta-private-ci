"""Make reproducible archive parts of the two completed auxiliary panels, including all weights."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile


def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def prepare(base, kind, destination):
    destination.mkdir(exist_ok=True,parents=True)
    ready=destination/"manifest.json"
    if ready.exists():return
    result=json.loads((base/"terminal.json").read_text())
    if kind=="whole_corpus":
        seal=base/"development_seal.json";verified=json.loads((base/"verification.json").read_text())
        assert verified["verified"] and verified["candidates"]==45 and sha(base/"terminal.json")==verified["terminal_sha256"]
        assert sha(seal)==result["seal_sha256"]
        fits=json.loads(seal.read_text())["fits"]
        names=["terminal.json","development_seal.json","verification.json"]
        for key,rr in fits.items():
            names.append(key+"/fits.json")
            for r in rr:
                path=base/key/r["weights"]
                if sha(path)!=r["sha256"]:raise ValueError(str(path))
                names+= [key+"/"+r["weights"],f"{key}/dev-{r['epoch']}.npz",f"{key}/cold-{r['epoch']}.npz"]
    else:
        seal=base/"fits.json";assert sha(seal)==result["fit_seal_sha256"]
        fits=json.loads(seal.read_text());names=["fits.json","terminal.json"]
        for seed,arms in fits.items():
            names.extend((seed+"-dev.npz",seed+"-cold.npz"))
            for r in arms.values():
                if sha(base/r["weights"])!=r["sha256"]:raise ValueError(r["weights"])
                names.append(r["weights"])
    names=sorted(set(names))
    if not all(re.fullmatch(r"[.A-Za-z0-9/_-]+",n) and ".." not in n for n in names):raise ValueError("file list")
    brief={n:{"bytes":(base/n).stat().st_size,"sha256":sha(base/n)} for n in names}
    raw=destination/"panel.tar.gz.tmp"
    with raw.open("wb") as output, gzip.GzipFile(fileobj=output,mode="wb",filename="",compresslevel=1,mtime=0) as gz:
        with tarfile.open(fileobj=gz,mode="w|") as archive:
            for n in names:
                member=tarfile.TarInfo(n);member.size=brief[n]["bytes"];member.mtime=0;member.mode=0o600
                with (base/n).open("rb") as f:archive.addfile(member,f)
    compressed_sha=sha(raw);parts=[]
    with raw.open("rb") as stream:
        while data:=stream.read(2*1024*1024):
            n=f"panel.tar.gz.part{len(parts):03}";(destination/n).write_bytes(data)
            parts.append(dict(name=n,bytes=len(data),sha256=sha(destination/n)))
    # Reopen the compressed archive; require the exact allowlist and SHA for every tar member.
    with tarfile.open(raw,mode="r|gz") as archive:
        verified={}
        for member in archive:
            if not member.isfile():raise ValueError(member.name)
            with archive.extractfile(member) as f:verified[member.name]=hashlib.file_digest(f,"sha256").hexdigest()
    if verified!={n:v["sha256"] for n,v in brief.items()}:raise ValueError("archive membership")
    manifest=dict(kind=kind,terminal_sha256=sha(base/"terminal.json"),file_count=len(names),files=brief,
                  archive_sha256=compressed_sha,archive_bytes=raw.stat().st_size,parts=parts)
    ready.write_text(json.dumps(manifest,indent=2)+"\n");raw.unlink()
    print(kind,len(names),len(parts),compressed_sha,flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("base",type=Path)
    a=p.parse_args()
    for kind,folder in (("whole_corpus","whole_edit"),("null_space","null_edit")):
        prepare(a.base/folder,kind,a.base/"followup_archives"/kind)
