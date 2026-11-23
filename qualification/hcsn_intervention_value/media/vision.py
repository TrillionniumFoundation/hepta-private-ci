"""Frozen ImageNet ResNet18 recognition from six causally available camera frames."""

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import os
import re
import resource
import subprocess
import sys
import time

import numpy as np
from PIL import Image
import torch
import torchvision
from torchvision.models import ResNet18_Weights, resnet18


WEIGHT_SHA = "f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec"
LABELS = (("grand piano", "upright"), ("acoustic guitar", "electric guitar"))
_FRAME = re.compile(rb"\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:.*?\bs:(\d+)x(\d+)")
_BASE = re.compile(rb"config in time_base:\s*(\d+)/(\d+)")


def digest(path):
    with Path(path).open("rb") as fh:
        return hashlib.file_digest(fh,"sha256").hexdigest()


def load_model(path):
    if digest(path)!=WEIGHT_SHA:
        raise ValueError("ImageNet V1 weight digest mismatch")
    w=ResNet18_Weights.IMAGENET1K_V1
    categories=w.meta["categories"]
    idx=[[categories.index(label) for label in group] for group in LABELS]
    if idx!=[[579,881],[402,546]]:
        raise ValueError("unexpected ImageNet label ordering")
    model=resnet18(weights=None)
    model.load_state_dict(torch.load(path,map_location="cpu",weights_only=True),strict=True)
    return model.eval(),w.transforms(),idx


def _info(stderr):
    bases=set(_BASE.findall(stderr))
    if len(bases)!=1:
        raise ValueError("ambiguous or missing decoded frame clock")
    numerator,denominator=next(iter(bases))
    clock=Fraction(int(numerator),int(denominator))
    rows=[tuple(map(int,match)) for match in _FRAME.findall(stderr)]
    if (not rows or any(n!=i or w<1 or h<1 for i,(n,_,w,h) in enumerate(rows))
            or any(a[1]>b[1] for a,b in zip(rows,rows[1:]))):
        raise ValueError("invalid frame sequence")
    return clock,rows


def select_indices(pts, boundaries):
    # PTS and cutoffs use exact rationals. A frame whose timestamp equals its
    # decision endpoint is deliberately left for the next decision.
    from bisect import bisect_left
    idx=[bisect_left(pts,t)-1 for t in boundaries]
    if min(idx)<0:
        raise ValueError("at least one prefix has no preceding frame")
    return idx


def source_meta(path):
    p=subprocess.run(["ffprobe","-v","error","-show_entries","format=start_time,duration",
                      "-of","json",str(path)],check=True,capture_output=True)
    fmt=json.loads(p.stdout)["format"]
    return Fraction(fmt["start_time"]),Fraction(fmt["duration"])


def decode_prefixes(path,start,source_info):
    origin,duration=source_info
    start=Fraction(str(start))
    ends=[origin+start+Fraction(12,25)*t for t in range(1,7)]
    if start<0 or ends[-1]>origin+duration+Fraction(1,1000):
        raise ValueError("registered segment outside original recording")
    seek=max(Fraction(0), start-2)
    while True:
        # Seek relative to original container start; -copyts retains absolute PTS
        # for matching. Both passes perform identical decoder seeking/discard.
        length=start+Fraction(29,10)-seek
        cmd=["ffmpeg","-hide_banner","-nostdin","-v","info","-threads","1","-copyts",
             "-ss",f"{float(seek):.6f}","-t",f"{float(length):.6f}","-i",str(path),
             "-map","0:v:0","-an","-filter_threads","1"]
        probe=subprocess.run(cmd+["-vf","showinfo=checksum=0","-fps_mode","passthrough",
                                 "-f","null","-"],capture_output=True,check=True)
        clock,rows=_info(probe.stderr)
        pts=[clock*r[1] for r in rows]
        if pts[0]<ends[0] or seek==0:
            break
        seek=max(Fraction(0),start-2*(start-seek))
    selected=select_indices(pts,ends)
    unique=sorted(set(selected))
    expression="+".join(f"eq(n\\,{n})" for n in unique)
    filtered=f"select={expression},format=rgb24,showinfo=checksum=0"
    proc=subprocess.run(cmd+["-vf",filtered,"-fps_mode","passthrough","-c:v","rawvideo",
                             "-threads:v","1","-f","rawvideo","-"],capture_output=True,check=True)
    check,kept=_info(proc.stderr)
    if len(kept)!=len(unique) or [check*r[1] for r in kept]!=[pts[i] for i in unique]:
        raise ValueError("selected-frame identities changed between decoding passes")
    images={}
    offset=0
    for ix,(_,_,w,h) in zip(unique,kept):
        size=w*h*3
        frame=proc.stdout[offset:offset+size]
        if len(frame)!=size:
            raise ValueError("incomplete RGB frame")
        images[ix]=Image.frombytes("RGB",(w,h),frame)
        offset+=size
    if offset!=len(proc.stdout):
        raise ValueError("raw decoded frame count does not match selected PTS")
    return [images[i] for i in selected],{
        "start_seconds":float(start),"absolute_endpoint_seconds":[float(t) for t in ends],
        "chosen_pts_seconds":[float(pts[i]) for i in selected],
        "chosen_pts_ticks":[rows[i][1] for i in selected],"time_base":str(clock),
        "decoded_dimensions":[list(images[i].size) for i in selected]}


def cumulative_class_probability(logits,indices):
    if logits.shape!=(6,1000) or not torch.isfinite(logits).all():
        raise ValueError("expected 6 finite 1000-class outputs")
    z=torch.stack([torch.logsumexp(logits[:,list(group)],dim=1) for group in indices],dim=-1)
    p=z.double().softmax(-1)
    return p.cumsum(0)/torch.arange(1,7,dtype=torch.float64)[:,None]


def run(args,receipt):
    raw=json.loads(args.roster.read_text())
    rows=raw[args.split] if isinstance(raw,dict) else raw
    ids=[str(r["query_id"]) for r in rows]
    if (not rows or len(set(ids))!=len(ids) or any(r.get("split",args.split)!=args.split for r in rows)
            or any("local_media" not in r for r in rows)):
        raise ValueError("malformed or mixed split roster")
    args.out.parent.mkdir(parents=True,exist_ok=True)
    if args.out.exists():
        raise FileExistsError(args.out)
    receipt.update(roster_sha256=digest(args.roster),queries=len(rows),dtype="torch.float32",
                   torch=torch.__version__,torchvision=torchvision.__version__,
                   weight_sha256=digest(args.weights),
                   ffmpeg=subprocess.check_output(["ffmpeg","-version"],text=True).splitlines()[0],
                   model="torchvision.models.resnet18, ResNet18_Weights.IMAGENET1K_V1",
                   label_names=LABELS,weight_url=ResNet18_Weights.IMAGENET1K_V1.url)
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    started=time.monotonic()
    model,transform,idx=load_model(args.weights)
    receipt.update(label_indices=idx,official_preprocessing=str(transform),
                   model_load_wall_seconds=time.monotonic()-started)
    results=[]
    known={}
    with torch.inference_mode():
        for row in rows:
            path=Path(row["local_media"])
            if str(path) not in known:
                known[str(path)]=(source_meta(path),digest(path))
            meta,sha=known[str(path)]
            ts=time.monotonic()
            imgs,details=decode_prefixes(path,row["start_seconds"],meta)
            z=torch.stack([transform(im) for im in imgs])
            decode=time.monotonic()-ts
            forward=time.monotonic()
            out=cumulative_class_probability(model(z),idx).numpy()
            elapsed=time.monotonic()-forward
            results.append(out)
            receipt["rows"].append(dict(query_id=row["query_id"],source_sha256=sha,
                    decode_preprocess_wall_s=decode,forward_wall_s=elapsed,**details))
    tmp=args.out.with_suffix(args.out.suffix+".partial")
    with tmp.open("xb") as f:
        np.savez_compressed(f,query_id=np.array(ids),probability=np.stack(results))
    os.replace(tmp,args.out)
    receipt.update(output_sha256=digest(args.out),status="ok",inference_frames=6*len(results))


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("roster",type=Path)
    cli.add_argument("split",choices=("train","dev","retain","gallery","test"))
    cli.add_argument("out",type=Path)
    cli.add_argument("--weights",type=Path,required=True)
    cli.add_argument("--threads",type=int,default=1)
    args=cli.parse_args()
    if not 1<=args.threads<=8:
        raise ValueError("expected 1–8 CPU threads")
    out=args.out.with_suffix(".receipt.json")
    if out.exists():
        raise FileExistsError(out)
    receipt={"status":"started","split":args.split,"started_at":time.time(),"rows":[]}
    start=time.monotonic();cpu=time.process_time()
    out.parent.mkdir(parents=True,exist_ok=True)
    try:
        run(args,receipt)
    except Exception as exc:
        receipt.update(status="failed",error=repr(exc))
        raise
    finally:
        ch=resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt.update(wall_seconds=time.monotonic()-start,cpu_seconds=time.process_time()-cpu,
                       child_cpu_seconds=ch.ru_utime+ch.ru_stime,self_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       child_peak_rss_kib=ch.ru_maxrss,energy_joules=None,script_sha256=digest(Path(__file__)))
        with out.open("x") as f:
            json.dump(receipt,f,ensure_ascii=False,allow_nan=False)
            f.write("\n")


if __name__=="__main__":
    main()
