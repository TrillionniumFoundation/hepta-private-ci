"""Recover the official RAVDESS audio-video corpus and exactly mirror the CREMA-D front end."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import zipfile

import numpy as np

LABEL={5:0,7:1,6:2,3:3,1:4,4:5}
SOURCE="https://zenodo.org/api/records/1188976"


def digest(path,algorithm="sha256"):
    with path.open("rb") as f:return hashlib.file_digest(f,algorithm).hexdigest()


def write(path,obj):
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj,indent=2)+"\n")
    tmp.replace(path)


def fetch(entry,target):
    info=target.with_suffix(".identity.json")
    if target.exists() and info.exists():
        stored=json.loads(info.read_text())
        if stored["bytes"]==target.stat().st_size and digest(target)==stored["sha256"]:return stored
    temp=target.with_suffix(".part")
    expected=entry["checksum"].removeprefix("md5:")
    for attempt in range(8):
        start=temp.stat().st_size if temp.exists() else 0
        if start==entry["bytes"]:
            actual=digest(temp,"md5")
            if actual==expected:
                rec=dict(bytes=start,md5=actual,sha256=digest(temp),official_url=entry["url"])
                temp.replace(target);write(info,rec);return rec
            temp.replace(target.with_suffix(".failed-md5"))
            continue
        req=Request(entry["url"],headers={"User-Agent":"Hepta academic audiovisual evaluation","Accept-Encoding":"identity"})
        if start:req.add_header("Range",f"bytes={start}-")
        try:
            with urlopen(req,timeout=90) as stream:
                status=stream.status
                if status==200:start=0
                if status==206 and not stream.getheader("Content-Range","").startswith(f"bytes {start}-"):
                    raise OSError("unmatched partial response")
                with temp.open("ab" if start else "wb") as f:
                    while chunk:=stream.read(1024*1024):f.write(chunk)
                if temp.stat().st_size>entry["bytes"]:raise ValueError("oversize archive")
        except (OSError,TimeoutError,HTTPError) as err:
            seconds=int(err.headers.get("Retry-After","0")) if isinstance(err,HTTPError) and err.headers.get("Retry-After","0").isdigit() else 0
            print(target.name,"retry",attempt+1,type(err).__name__,flush=True)
            time.sleep(max(seconds,min(40,2**attempt)))
    raise RuntimeError("exhausted transfer attempts "+str(target))


def extract_data(payload,decoder):
    # Source MP4s may store their sample index after the media. A seekable
    # per-process temporary file handles both ordinary and fast-start layouts.
    with tempfile.NamedTemporaryFile(suffix=".mp4") as media:
        media.write(payload);media.flush()
        first=[str(decoder),"-nostdin","-loglevel","error","-threads","1","-filter_threads","1","-i",media.name]
        def decode(args):
            return subprocess.run(first+args+["pipe:1"],stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,check=True,timeout=80).stdout
        pix=np.frombuffer(decode(["-map","0:v:0","-vf","scale=28:28:flags=area","-pix_fmt","gray","-f","rawvideo"]),np.uint8).reshape(-1,28,28)
        wave=np.frombuffer(decode(["-map","0:a:0","-ac","1","-ar","8000","-f","s16le"]),"<i2")
    if len(pix)<12 or len(wave)<1024:raise ValueError("invalid clip")
    selected=pix[np.minimum(len(pix)-1,((np.arange(12)+.5)*len(pix)/12).astype(int))]
    audio=wave.astype(np.float32)/32768
    win=np.lib.stride_tricks.sliding_window_view(audio,256)[::80]
    power=np.abs(np.fft.rfft(win*np.hanning(256),axis=-1))**2
    band=.5*(power[:,1:129:2]+power[:,2:129:2])
    feat=np.stack([np.log1p(t).mean(0) for t in np.array_split(band,12)]).astype(np.float32)
    return selected,feat,len(pix),len(wave)


def prepare(root,decoder):
    root.mkdir(parents=True,exist_ok=True)
    roster=root/"release.json"
    if not roster.exists():
        with urlopen(SOURCE,timeout=45) as f:v=json.load(f)
        write(roster,{r["key"]:dict(bytes=r["size"],checksum=r["checksum"],url=r["links"]["self"])
                      for r in v["files"] if r["key"].startswith("Video_Speech_Actor_")})
    identity=json.loads(roster.read_text())
    if len(identity)!=24:raise ValueError("actor roster")
    def actor(name):
        actor_id=int(name[-6:-4]);out=root/f"actor-{actor_id:02}.npz"
        if out.is_file():
            m=json.loads(out.with_suffix(".json").read_text())
            if digest(out)==m["processed_sha256"]:return m
            raise ValueError("processed actor differs")
        archive=root/name
        admission=fetch(identity[name],archive)
        clip_ids=[];vids=[];sounds=[];labels=[];proof=[]
        with zipfile.ZipFile(archive) as z:
            for member in sorted(z.namelist()):
                base=Path(member).name.lower()
                if not re.fullmatch(r"01-01-(?:01|03|04|05|06|07)-\d\d-\d\d-\d\d-\d\d\.mp4",base):continue
                fields=list(map(int,base[:-4].split("-")))
                if fields[-1]!=actor_id:raise ValueError(member)
                payload=z.read(member)
                video,audio,frames,samples=extract_data(payload,decoder)
                labels.append(LABEL[fields[2]]);clip_ids.append(base[:-4]);vids.append(video);sounds.append(audio)
                proof.append(dict(id=base[:-4],member=member,crc32=f"{z.getinfo(member).CRC:08x}",
                         source_sha256=hashlib.sha256(payload).hexdigest(),frames=frames,samples=samples,
                         video_sha256=hashlib.sha256(video.tobytes()).hexdigest(),audio_sha256=hashlib.sha256(audio.tobytes()).hexdigest()))
        if len(clip_ids)!=44:raise ValueError((actor_id,len(clip_ids)))
        tmp=out.with_suffix(".tmp")
        with tmp.open("wb") as f:np.savez_compressed(f,ids=np.array(clip_ids),video=vids,audio=sounds,y=labels)
        tmp.replace(out)
        rec=dict(actor=actor_id,count=len(clip_ids),archive=admission,clips=proof,processed_sha256=digest(out))
        write(out.with_suffix(".json"),rec)
        print("actor",actor_id,len(clip_ids),admission["bytes"],rec["processed_sha256"],flush=True)
        return rec
    with ThreadPoolExecutor(max_workers=2) as pool:actors=list(pool.map(actor,sorted(identity)))
    sets=[np.load(root/f"actor-{r['actor']:02}.npz") for r in actors]
    try:
        data={k:np.concatenate([d[k] for d in sets]) for k in ("ids","video","audio","y")}
    finally:
        for d in sets:d.close()
    if len(set(data["ids"]))!=1056 or not np.isfinite(data["audio"]).all():raise ValueError("cohort")
    path=root/"external.npz";tmp=path.with_suffix(".tmp")
    with tmp.open("wb") as f:np.savez_compressed(f,**data)
    tmp.replace(path)
    write(root/"prepared.json",dict(cohort="RAVDESS six shared CREMA emotions",actors=[r["actor"] for r in actors],clips=len(data["ids"]),
         counts=np.bincount(data["y"]).tolist(),official_archives_bytes=sum(r["archive"]["bytes"] for r in actors),
         prepared_sha256=digest(path),ffmpeg_sha256=digest(decoder),release_table_sha256=digest(roster),
         script_sha256=digest(Path(__file__)),actor_receipts={str(r["actor"]):digest(root/f"actor-{r['actor']:02}.json") for r in actors}))
    print("prepared",digest(path),flush=True)


if __name__=="__main__":prepare(Path(sys.argv[1]),Path(sys.argv[2]))
