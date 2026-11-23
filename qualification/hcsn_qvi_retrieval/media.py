"""Causal frozen two-modality frontend for actor-disjoint RAVDESS retrieval.

Decode source-timestamped media from the 2018 public release. Audio is free.
The paid observation unlocks the visual prefix, scored against independent
opposite-take references. Dataset construction never measures task accuracy.
"""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import resource
import subprocess
import time

import numpy as np

if __package__:
    from .acquire_media import MANIFEST, file_names
else:
    from acquire_media import MANIFEST, file_names


def run(argv):
    return subprocess.run(argv, capture_output=True, check=True).stdout


def modality_features(path, steps, seconds, subframes):
    probe = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-of", "json",
                            str(path)]))["streams"]
    audio_stream = next(s for s in probe if s["codec_type"] == "audio")
    video_stream = next(s for s in probe if s["codec_type"] == "video")
    rate = int(audio_stream["sample_rate"])
    frequency = np.fft.rfftfreq(round(rate * seconds / subframes), 1 / rate)
    audio_start = float(audio_stream.get("start_time", 0))
    video_start = float(video_stream.get("start_time", 0))
    origin = max(audio_start, video_start)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-i", str(path)]
    # Native sample rate avoids a resampling filter's temporal support.
    audio = np.frombuffer(run(cmd + ["-map", "0:a:0", "-ac", "1", "-f", "f32le", "-"]),
                          dtype="<f4").astype(np.float64)
    # A fixed face-center crop; only spatial reduction, no temporal interpolation.
    vf = "crop=iw*0.50:ih*0.42:iw*0.25:ih*0.38,scale=24:16:flags=area,format=gray"
    pixels = run(cmd + ["-map", "0:v:0", "-vf", vf, "-fps_mode", "passthrough",
                        "-filter_threads", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    frames = np.frombuffer(pixels, dtype=np.uint8).reshape(-1, 16, 24).astype(np.float64) / 255
    entries = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "frame=best_effort_timestamp_time",
                              "-of", "json", str(path)]))["frames"]
    pts = np.array([float(row["best_effort_timestamp_time"]) for row in entries])
    if len(pts) != len(frames) or np.any(np.diff(pts) <= 0):
        raise ValueError(f"unaligned timestamps in {path.name}")
    duration = float(video_stream["duration"]) + video_start - origin
    dt = seconds / subframes
    nframe = round(rate*dt)
    stop = origin + steps*seconds
    if min(duration, len(audio)/rate + audio_start - origin) + 1e-6 < steps*seconds:
        raise ValueError(f"short recording {path.name} before cut-off {stop}")
    boundaries = [(80,320), (320,800), (800,1600), (1600,3200), (3200,6400)]
    band_masks = [(frequency >= a) & (frequency < b) for a,b in boundaries]
    window = np.hanning(nframe)
    visual, acoustic = [], []
    origin_frames = np.searchsorted(pts, origin, side="right")
    if not origin_frames:
        raise ValueError(f"missing initial video frame {path.name}")
    initial = frames[origin_frames-1]
    for i in range(steps*subframes):
        tick = origin + (i+1)*dt
        end = round((tick-audio_start)*rate)
        block = audio[end-nframe:end]
        spec = np.abs(np.fft.rfft(block*window)) / window.sum()
        bands = np.array([np.linalg.norm(spec[mask]) for mask in band_masks])
        audio_energy = np.sqrt(np.mean(block**2))
        acoustic.append(np.clip((np.log10(1e-6+np.r_[audio_energy,bands])+5)/4,0,1))
        # At tick exactly, only frames with decoded timestamp strictly earlier are available.
        available = np.searchsorted(pts, tick-1e-9, side="right")
        if not available:
            raise ValueError(f"missing causal visual prefix {path.name}")
        current = frames[available-1]
        diff = current-initial
        grid = diff.reshape(4,4,6,4)
        signed = grid.mean(axis=(1,3)).ravel()
        absolute = np.abs(grid).mean(axis=(1,3)).ravel()
        visual.append(np.clip(4*np.r_[signed,absolute],-1,1))
    return np.stack(acoustic), np.stack(visual)


def match_scores(query, candidates, steps, subframes):
    """Each score at t uses only subframes observed by t on both recordings."""
    errors = np.stack([np.square(query-reference).mean(axis=1)
                       for reference in candidates],axis=1)
    numerator = np.cumsum(errors, axis=0)[subframes-1::subframes]
    return -np.sqrt(numerator / (np.arange(1,steps+1)*subframes)[:,None])


def check_arrays(arrays, selected_splits, erratum):
    n,steps,width = arrays["x"].shape
    expected = sum(erratum["expected_queries"][s] for s in selected_splits)
    if (n,steps,width) != (expected,6,8):
        raise ValueError("unexpected number of queries, prefixes, or free features")
    for name in ("scores","read_scores"):
        if arrays[name].shape != (n,steps,2):
            raise ValueError("candidate layout mismatch")
    for name in ("x","scores","read_scores","dt"):
        if not np.isfinite(arrays[name]).all():
            raise ValueError("nonfinite frontend output")
    groups = [set(arrays["group"][arrays["split"]==s]) for s in selected_splits]
    if list(map(len,groups)) != list(map(len,selected_splits.values())) or len(set.union(*groups)) != sum(map(len,groups)):
        raise ValueError("actor split overlap or incomplete splits")
    for group in np.unique(arrays["group"]):
        positions = np.bincount(arrays["target"][arrays["group"]==group], minlength=2)
        if len(positions)!=2 or positions[0]!=positions[1] or not positions[0]:
            raise ValueError("unbalanced target positions")


def build(cache, manifest, selected_splits, wait_limit):
    steps = manifest["clock"]["steps"]
    seconds = manifest["clock"]["seconds_per_step"]
    subframes = manifest["clock"]["subframes_per_step"]
    erratum = manifest["source_integrity_erratum"]
    exclude = {tuple(pair) for pair in erratum["excluded_actor_emotion"]}
    sources = {}
    wait_time = 0.0
    rows = {k:[] for k in ("x","scores","read_scores","target","group","split","dt","query_id","gallery_id")}
    for split, actors in selected_splits.items():
        for actor in actors:
            clips = {}
            for name in file_names(actor,manifest):
                path = cache/name
                started = time.monotonic()
                while not path.is_file():
                    if time.monotonic() - started + wait_time >= wait_limit:
                        raise FileNotFoundError(path)
                    time.sleep(2)
                wait_time += time.monotonic() - started
                sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
                if (actor, int(name.split("-")[2])) not in exclude:
                    clips[name] = modality_features(path,steps,seconds,subframes)
            for emo in manifest["emotion_ids"]:
                if (actor, emo) in exclude:
                    continue
                for rep in manifest["repetition_ids"]:
                    key = f"hepta-qvi-ravdess-v1/{actor}/{emo}/{rep}".encode()
                    order = [1,2] if hashlib.sha256(key).digest()[0]%2==0 else [2,1]
                    names = [f"01-01-{emo:02d}-01-{sid:02d}-{3-rep:02d}-{actor:02d}.mp4" for sid in order]
                    for statement in manifest["statement_ids"]:
                        query = f"01-01-{emo:02d}-01-{statement:02d}-{rep:02d}-{actor:02d}.mp4"
                        if query in names:
                            raise ValueError("retrieval query present in gallery")
                        a,v = clips[query]
                        free = match_scores(a,[clips[n][0] for n in names],steps,subframes)
                        paid_video = match_scores(v,[clips[n][1] for n in names],steps,subframes)
                        free_mean = a.reshape(steps,subframes,-1).mean(axis=1)
                        clock = np.arange(1,steps+1)/steps
                        gap = np.abs(free[:,0]-free[:,1])
                        rows["x"].append(np.column_stack([free_mean,gap,clock]))
                        rows["scores"].append(free)
                        rows["read_scores"].append(0.5*(free+paid_video))
                        rows["target"].append(order.index(statement))
                        rows["group"].append(f"ravdess-actor-{actor:02d}")
                        rows["split"].append(split)
                        rows["dt"].append(np.full(steps,seconds))
                        rows["query_id"].append(query)
                        rows["gallery_id"].append(names)
            print(f"decoded actor {actor:02d}",flush=True)
    arrays = {name:np.asarray(value) for name,value in rows.items()}
    check_arrays(arrays, selected_splits, erratum)
    return arrays, sources, wait_time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache",type=Path)
    parser.add_argument("out",type=Path)
    parser.add_argument("--split",choices=("train","dev","retain","test"),required=True)
    parser.add_argument("--wait-seconds",type=float,default=0.,
                        help="Maximum acquisition wait while the verified cache is being filled")
    args=parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    started=time.monotonic()
    manifest=json.loads(MANIFEST.read_text())
    selected = {args.split:manifest["splits"][args.split]}
    arrays, sources, waited = build(args.cache,manifest,selected,args.wait_seconds)
    np.savez_compressed(args.out,**arrays)
    children=resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt={"implementation":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "python":platform.python_version(),"numpy":np.__version__,
             "ffmpeg":run(["ffmpeg","-version"]).decode().splitlines()[0],
             "output_sha256":hashlib.sha256(args.out.read_bytes()).hexdigest(),
             "wall_seconds":time.monotonic()-started,
             "acquisition_wait_seconds":waited,"source_sha256":sources,
             "split":args.split,
             "parent_and_decoder_cpu_seconds":time.process_time()+children.ru_utime+children.ru_stime,
             "shapes":{k:list(v.shape) for k,v in arrays.items()},
             "scope":"Includes pinned-file reads, decoding and feature assembly. Separate acquisition process."}
    args.out.with_suffix(".receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt),flush=True)


if __name__=="__main__":
    main()
