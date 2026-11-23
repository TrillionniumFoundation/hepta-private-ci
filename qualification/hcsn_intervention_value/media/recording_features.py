"""Decode independent, non-overlapping real music excerpts, preserving causal prefixes."""
import argparse
import json
from pathlib import Path
import subprocess
import numpy as np


STEPS = 6
DT = .48
SUB = 12
SUB_DT = DT / SUB


def run(args):
    return subprocess.run(args, check=True, capture_output=True).stdout


def make_frames(path, start):
    # Decode from a common physical timestamp; PCM and video are not time-warped.
    # For variable-frame clips obtain presentation timestamps and choose the newest
    # frame strictly before each subframe endpoint. Never interpolate across time.
    seek = max(0.,start-.20)
    end = start+STEPS*DT+.1
    duration = end-seek
    probe=json.loads(run(["ffprobe","-v","error","-show_streams","-of","json",str(path)]))
    a = next(x for x in probe["streams"] if x["codec_type"]=="audio")
    rate=int(a["sample_rate"])
    args=["ffmpeg","-hide_banner","-nostdin","-v","error","-threads","1","-ss",f"{seek:.6f}",
          "-i",str(path),"-t",f"{duration:.6f}"]
    pcm=np.frombuffer(run(args+["-map","0:a:0","-ac","1","-f","f32le","-"]),dtype="<f4").astype("float64")
    # Use exact decoded frame timestamps from showinfo in the SAME spatial-only
    # decode. ffmpeg -ss rebases presentation timestamps to the seek origin.
    vargs=args.copy()
    vargs[vargs.index("error")]="info"
    proc=subprocess.run(vargs+["-map","0:v:0","-vf","scale=24:16:flags=area,format=rgb24,showinfo",
                        "-filter_threads","1","-fps_mode","passthrough","-f","rawvideo","-"],
                        check=True,capture_output=True)
    import re
    stamps=[float(x) for x in re.findall(rb"\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:\s*([-+.\deE]+)",proc.stderr)]
    frames=np.frombuffer(proc.stdout,dtype="u1").reshape(-1,16,24,3).astype("float64")/255
    # showinfo can include one look-ahead frame that the output duration drops.
    if len(stamps) not in (len(frames),len(frames)+1,len(frames)+2):
        raise ValueError(f"video clock/decoded-size mismatch {len(stamps)}, {len(frames)}")
    pts=np.asarray(stamps[:len(frames)])
    if len(pts)<2 or (np.diff(pts)<0).any():
        raise ValueError("invalid video clock")
    offset=start-seek
    return pcm, rate, frames, pts, offset


def extract(path, start):
    pcm,rate,frames,pts,offset=make_frames(path,start)
    n=round(rate*SUB_DT)
    window=np.hanning(n)
    freqs=np.fft.rfftfreq(n,1/rate)
    bounds=np.geomspace(65.,min(8000.,rate/2),25)
    bands=[(freqs>=lo)&(freqs<hi) for lo,hi in zip(bounds[:-1],bounds[1:])]
    audio,visual=[],[]
    prev_audio=None; prev_image=None
    for idx in range(STEPS*SUB):
        end=offset+(idx+1)*SUB_DT
        hi=round(end*rate)
        wave=pcm[hi-n:hi]
        if len(wave)!=n:
            raise ValueError("truncated physical audio block")
        power=np.square(np.abs(np.fft.rfft(wave*window))/window.sum())
        energy=np.array([power[mask].sum() for mask in bands])
        logs=np.log1p(10000*np.sqrt(energy))
        chroma=energy/max(energy.sum(),1e-10)
        centroid=np.sum(freqs*power)/max(power.sum(),1e-12)/8000
        zcr=np.mean(np.signbit(wave[1:])!=np.signbit(wave[:-1]))
        flux=0. if prev_audio is None else np.linalg.norm(chroma-prev_audio)
        audio.append(np.r_[logs,np.sqrt(chroma),np.sqrt(np.mean(wave**2)),centroid,zcr,flux])
        prev_audio=chroma
        j=np.searchsorted(pts,end-1e-9,side="right")-1
        if j<0:raise ValueError("no causal video frame")
        image=frames[j]
        gray=image@np.array([.299,.587,.114])
        # 4 x 4 regional colour (48); 4 x 4 spatial edge (16);
        # 2 x 4 inter-frame absolute motion (8); RGB variances + global contrast (4).
        color=image.reshape(4,4,4,6,3).mean((1,3)).ravel()
        dx=np.abs(np.diff(gray,axis=1,prepend=gray[:,:1]))
        dy=np.abs(np.diff(gray,axis=0,prepend=gray[:1,:]))
        edge=(dx+dy).reshape(4,4,4,6).mean((1,3)).ravel()
        motion=np.zeros_like(gray) if prev_image is None else np.abs(gray-prev_image)
        v=np.r_[color,edge,motion.reshape(2,8,4,6).mean((1,3)).ravel(),image.std((0,1)),gray.std()]
        visual.append(v); prev_image=gray
    def summarize(items):
        blocks=np.array(items).reshape(STEPS,SUB,-1).mean(axis=1)
        return blocks,blocks.cumsum(0)/np.arange(1,STEPS+1)[:,None]
    ab,ac=summarize(audio); vb,vc=summarize(visual)
    if ab.shape!=(6,52) or vb.shape!=(6,76) or not np.isfinite(ab).all() or not np.isfinite(vb).all():
        raise ValueError("invalid finite output shapes")
    return dict(audio=ac,visual=vc,audio_block=ab,visual_block=vb)


def duration_of(path):
    d=json.loads(run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type","-of","json",str(path)]))
    if {"audio","video"} - {x["codec_type"] for x in d["streams"]}:
        raise ValueError("requires original audiovisual recording")
    return float(d["format"]["duration"])


def starts(length):
    # Deterministic uniform coverage. Four nonoverlapping windows per recording, avoiding
    # the first and final 5% of a production. No audiovisual outcomes used.
    lo=length*.05; hi=length*.95-STEPS*DT
    count=min(4,int((hi-lo+STEPS*DT)//(STEPS*DT+.2)))
    if count<4:raise ValueError("fewer than four disjoint physical windows")
    return np.linspace(lo,hi,count).round(5)


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("recording",type=Path); cli.add_argument("out",type=Path)
    args=cli.parse_args()
    times=starts(duration_of(args.recording))
    rows=[extract(args.recording,t) for t in times]
    np.savez_compressed(args.out,**{k:np.stack([r[k] for r in rows]) for k in rows[0]},start_seconds=times)
