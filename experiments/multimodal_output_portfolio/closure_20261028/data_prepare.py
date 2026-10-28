"""Stream frozen sources, retain compact event arrays and actual-media features."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import zipfile

import numpy as np
import torch

from ..unified_20261028.natural_data import RemoteZip
from .data_sources import digest, save
from .semantic_backbones import SemanticBackbones

DEVELOPMENT_ROLES = ("generator_train", "observer_train", "development")


def decode(path):
    def ffmpeg(extra):
        process = subprocess.run(["ffmpeg","-v","error","-threads","1","-i",str(path),*extra],
                                 capture_output=True)
        if process.returncode:
            raise RuntimeError(process.stderr.decode(errors="replace")[:1000])
        return process.stdout
    frames = np.frombuffer(ffmpeg(["-vf","fps=8,scale=112:112:flags=area","-f","rawvideo",
                                   "-pix_fmt","rgb24","pipe:1"]),np.uint8).reshape(-1,112,112,3)
    audio = np.frombuffer(ffmpeg(["-vn","-ac","1","-ar","16000","-f","f32le","pipe:1"]),"<f4")
    return frames,audio


def prepare(root, roles, holdout_freeze):
    plan = json.loads((root/"SOURCE_PROTOCOL.json").read_text())
    copy = dict(plan)
    expected = copy.pop("protocol_sha256")
    if digest(copy) != expected:
        raise ValueError("Frozen source protocol changed")
    if any(role not in DEVELOPMENT_ROLES for role in roles):
        if holdout_freeze is None or not holdout_freeze.is_file():
            raise ValueError("Held-out media requires an explicit prior observer/policy freeze")
    torch.set_num_threads(2)
    backbone = SemanticBackbones(root/"pretrained")
    archives = {}
    remotes = {}
    selected = [row for row in plan["selected"] if row["role"] in roles]
    started=time.monotonic()
    done=0
    for source in selected:
        role,source_id = source["role"],source["source_id"]
        destination = root/"prepared"/role/source_id
        metadata_path = destination/"RECEIPT.json"
        if metadata_path.exists():
            existing=json.loads(metadata_path.read_text())
            if existing["source_protocol_sha256"]!=expected:
                raise ValueError("Existing prepared source belongs to another protocol")
            for name,pin in existing["retained_files"].items():
                if digest((destination/name).read_bytes())!=pin:
                    raise ValueError("Existing prepared artifact changed")
            done+=1
            continue
        destination.mkdir(parents=True,exist_ok=True)
        split=source["official_split"]
        if split not in archives:
            remote = RemoteZip(plan["archive"][split]["url"])
            if remote.generation!=plan["archive"][split]["generation"] or remote.etag!=plan["archive"][split]["etag"]:
                raise ValueError("Official source archive identity changed")
            remotes[split]=remote
            archives[split]=zipfile.ZipFile(remote)
        raw=root/("pending-"+source_id+".mp4")
        payload=archives[split].read(source["member"])
        if len(payload)!=source["source_bytes"]:
            raise ValueError("Original source byte length changed")
        source_sha=digest(payload)
        raw.write_bytes(payload)
        del payload
        try:
            frames,audio=decode(raw)
            clips=[]
            for event_index,event in enumerate(source["events"][:source["retained_event_count"]]):
                first=int(round(event["window_start_seconds"]*8))
                window=frames[first:first+32]
                wave=audio[first*2000:first*2000+64000]
                if window.shape!=(32,112,112,3) or wave.shape!=(64000,):
                    raise ValueError(f"Short frozen event: {source_id}:{event_index}")
                clips.append((window,wave,event))
            feature_video=[];feature_audio=[];features_cpu=0.
            if role != "generator_train":
                for offset in range(0,len(clips),2):
                    group=clips[offset:offset+2]
                    video=np.stack([x[0][8:24] for x in group])
                    waveform=np.stack([x[1][16000:48000] for x in group])
                    v,a,receipt=backbone.features(video,waveform)
                    feature_video.append(v);feature_audio.append(a)
                    features_cpu+=receipt["cpu_seconds"]
                feature_path=destination/"FEATURES.npz"
                np.savez_compressed(feature_path,video=np.concatenate(feature_video),
                                    audio=np.concatenate(feature_audio))
            if role != "observer_train":
                window,wave,event=clips[0]
                np.savez_compressed(destination/"EVENT.npz",
                    context_video=window[np.r_[0:8,24:32]],context_audio=wave[np.r_[0:16000,48000:64000]],
                    target_video=window[8:24],target_audio=wave[16000:48000],target_image=window[16])
            rows=[]
            for event_index,(_,_,event) in enumerate(clips):
                rows.append({"event_id":f"{source_id}-closure-{event_index}","source_id":source_id,
                             "source_sha256":source_sha,"role":role,**event})
            retained={p.name:digest(p.read_bytes()) for p in destination.iterdir() if p.is_file()}
            save(metadata_path,{"schema":"hepta.closure.prepared-source.v1",
                "source_protocol_sha256":expected,"source_id":source_id,"role":role,
                "original_source_sha256":source_sha,"original_source_bytes":source["source_bytes"],
                "original_url":plan["archive"][split]["url"],"original_member":source["member"],
                "events":rows,"retained_files":retained,"feature_cpu_seconds":features_cpu,
                "source_code_sha256":digest(Path(__file__).read_bytes()),
                "backbone_source_sha256":digest((Path(__file__).parent/"semantic_backbones.py").read_bytes()),
                "heldout_freeze_sha256":digest(holdout_freeze.read_bytes()) if holdout_freeze else None})
        finally:
            # This code owns only the newly downloaded member. The official source
            # hash and archive/member identity make it recoverable after completion.
            raw.unlink(missing_ok=True)
        done+=1
        if done%8==0 or done==len(selected):
            print(json.dumps({"prepared":done,"total":len(selected),"last_source":source_id,
                              "last_role":role,"elapsed_wall_seconds":time.monotonic()-started}),flush=True)
    receipt={"schema":"hepta.closure.preparation-pass.v1","source_protocol_sha256":expected,
             "roles":roles,"sources_completed":done,"wall_seconds":time.monotonic()-started,
             "range_receipts":{k:v.receipts for k,v in remotes.items()},
             "new_qualification_metrics":0,"observer_metrics":0}
    name="PREPARATION_"+"_".join(roles)+"_"+str(time.time_ns())+".json"
    save(root/name,receipt)
    return receipt


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--assets",type=Path,required=True)
    parser.add_argument("--roles",nargs="+",default=list(DEVELOPMENT_ROLES))
    parser.add_argument("--holdout-freeze",type=Path)
    args=parser.parse_args()
    prepare(args.assets,args.roles,args.holdout_freeze)
