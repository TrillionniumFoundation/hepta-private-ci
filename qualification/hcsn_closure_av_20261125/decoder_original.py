"""Acquire exact paired CREMA-D media and prepare an offline AV benchmark.

The selected database and derived tensor cache retain ODbL/DbCL attribution.
No model result is read by acquisition, cohort selection or normalization.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import time
import urllib.request

import numpy as np
from scipy.fft import dctn


UPSTREAM = "https://github.com/CheyneyComputerScience/CREMA-D.git"
COMMIT = "1658cd342dff90010aa843eaeebd53610a08b1dc"
SENTENCES = ("DFA", "IOM", "ITH", "IWL")
EMOTIONS = ("ANG", "DIS", "FEA", "HAP", "NEU", "SAD")
COHORT_SALT = "hcsn-real-av-cohort-v1:"
STEPS = 32


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(f"Refusing to overwrite different evidence: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def register(cache, output):
    upstream = cache / "upstream"
    if not upstream.exists():
        subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none",
                        "--no-checkout", UPSTREAM, str(upstream)], check=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream,
                                     text=True).strip()
    if actual != COMMIT:
        subprocess.run(["git", "fetch", "--depth", "1", "origin", COMMIT],
                       cwd=upstream, check=True)
    listing = subprocess.check_output(["git", "ls-tree", "-r", COMMIT, "VideoFlash"],
                                      cwd=upstream, text=True)
    entries = {}
    for row in listing.splitlines():
        metadata, path = row.split("\t", 1)
        entries[Path(path).stem] = (path, metadata.split()[2])
    actors = sorted({name.split("_")[0] for name in entries})
    eligible = [actor for actor in actors if all(
        f"{actor}_{sentence}_{emotion}_XX" in entries
        for sentence in SENTENCES for emotion in EMOTIONS)]
    order = sorted(eligible, key=lambda actor: hashlib.sha256(
        (COHORT_SALT + actor).encode()).hexdigest())
    if len(order) < 30:
        raise ValueError("The frozen complete-actor cohort is unavailable")
    splits = dict(train=order[:20], validation=order[20:25], test=order[25:30])
    plan = dict(schema="hcsn-real-av-cohort-v1", upstream=UPSTREAM, commit=COMMIT,
                selection_salt=COHORT_SALT, eligible_actors=eligible,
                sentences=list(SENTENCES), emotions=list(EMOTIONS), level="XX",
                splits=splits, expected_clips=720,
                selection_uses="official filename availability only; no model outcomes")
    write_json(output / "COHORT_PLAN.json", plan)
    paths = [entries[f"{actor}_{sentence}_{emotion}_XX"][0]
             for group in splits.values() for actor in group
             for sentence in SENTENCES for emotion in EMOTIONS]
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
    git = ["git", "-c", "filter.lfs.required=false", "-c", "filter.lfs.smudge=",
           "-c", "filter.lfs.process="]
    subprocess.run(git + ["sparse-checkout", "set", "--no-cone", "--stdin"],
                   input="\n".join("/" + p for p in paths + ["LICENSE.txt"]) + "\n",
                   cwd=upstream, text=True, env=env, check=True)
    subprocess.run(git + ["reset", "--hard", COMMIT], cwd=upstream, env=env, check=True)
    records = []
    for split, group in splits.items():
        for actor in group:
            for sentence in SENTENCES:
                for label, emotion in enumerate(EMOTIONS):
                    clip = f"{actor}_{sentence}_{emotion}_XX"
                    path, blob = entries[clip]
                    pointer = (upstream / path).read_text()
                    fields = dict(line.split(" ", 1) for line in pointer.splitlines())
                    if fields.get("version") != "https://git-lfs.github.com/spec/v1":
                        raise ValueError(f"Expected an official LFS pointer: {path}")
                    records.append(dict(clip=clip, actor=actor, sentence=sentence,
                        emotion=emotion, label=label, split=split, git_path=path,
                        pointer_blob_sha1=blob, sha256=fields["oid"].split(":")[1],
                        bytes=int(fields["size"]), url="https://media.githubusercontent.com/media/"
                        f"CheyneyComputerScience/CREMA-D/{COMMIT}/{path}"))
    (output / "CREMA_D_LICENSE.txt").write_bytes((upstream / "LICENSE.txt").read_bytes())
    write_json(output / "MANIFEST.json", dict(schema="hcsn-real-av-media-v1",
        cohort_plan_sha256=digest(output / "COHORT_PLAN.json"), commit=COMMIT,
        license_database="ODbL-1.0", license_contents="DbCL-1.0", records=records,
        total_bytes=sum(row["bytes"] for row in records)))
    print(json.dumps(dict(clips=len(records), bytes=sum(r["bytes"] for r in records))))


def acquire(cache, output, workers):
    records = json.loads((output / "MANIFEST.json").read_text())["records"]
    directory = cache / "media"
    directory.mkdir(parents=True, exist_ok=True)

    def fetch(row):
        path = directory / (row["clip"] + ".flv")
        if path.exists():
            if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
                raise ValueError(f"Existing media failed integrity: {path}")
            return dict(clip=row["clip"], verified=True, source="existing")
        temporary = path.with_suffix(".partial")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(row["url"], timeout=60) as response:
                    with temporary.open("wb") as stream:
                        while chunk := response.read(1048576):
                            stream.write(chunk)
                if temporary.stat().st_size != row["bytes"] or digest(temporary) != row["sha256"]:
                    raise ValueError(f"Downloaded media failed integrity: {row['clip']}")
                temporary.replace(path)
                return dict(clip=row["clip"], verified=True, attempts=attempt + 1)
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(0.5)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = []
        for index, result in enumerate(pool.map(fetch, records), 1):
            results.append(result)
            if index % 60 == 0:
                print(json.dumps(dict(acquired=index, expected=len(records))), flush=True)
    write_json(output / "ACQUISITION.json", dict(manifest_sha256=digest(output / "MANIFEST.json"),
        records=results, all_verified=True, bytes=sum(row["bytes"] for row in records)))


def _interpolate(values, times, targets):
    return np.stack([np.interp(targets, times, values[:, i])
                     for i in range(values.shape[1])], axis=1)


def decode(path):
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams",
        "-show_frames", "-show_entries", "stream=index,codec_type,start_time:frame=media_type,best_effort_timestamp_time",
        "-of", "json", str(path)]))
    streams = {s["codec_type"]: s for s in probe["streams"]}
    if not {"audio", "video"}.issubset(streams):
        raise ValueError("A selected clip is not genuine paired audio/video")
    timestamps = np.array([float(f["best_effort_timestamp_time"]) for f in probe["frames"]
                           if f.get("media_type") == "video"], dtype=np.float64)
    prefix = ["ffmpeg", "-v", "error", "-threads", "1", "-i", str(path)]
    audio = np.frombuffer(subprocess.check_output(prefix + ["-map", "0:a:0", "-ac", "1",
        "-ar", "16000", "-threads", "1", "-f", "f32le", "-"]), dtype="<f4").astype(np.float64)
    video = np.frombuffer(subprocess.check_output(prefix + ["-map", "0:v:0", "-an",
        "-vf", "scale=16:16:flags=area,format=gray", "-filter_threads", "1", "-threads", "1",
        "-vsync", "0", "-f", "rawvideo", "-"]), dtype=np.uint8).reshape(-1, 16, 16)
    if len(video) != len(timestamps) or len(timestamps) < 2 or not np.all(np.diff(timestamps) > 0):
        raise ValueError("Decoded frames and original frame timestamps do not align")
    audio_start = float(streams["audio"].get("start_time", 0))
    start = max(audio_start, timestamps[0])
    end = min(audio_start + len(audio) / 16000,
              timestamps[-1] + float(np.median(np.diff(timestamps))))
    if end <= start + 0.1:
        raise ValueError("No usable common audiovisual interval")
    targets = start + (np.arange(STEPS) + 0.5) * (end - start) / STEPS
    frames = np.lib.stride_tricks.sliding_window_view(audio, 400)[::160]
    power = np.abs(np.fft.rfft(frames * np.hanning(400), n=512)) ** 2
    frequency = np.fft.rfftfreq(512, 1 / 16000)
    mel_max = 2595 * np.log10(1 + 8000 / 700)
    edges = 700 * (10 ** (np.linspace(0, mel_max, 66) / 2595) - 1)
    filters = np.maximum(0, np.minimum(
        (frequency[None, :] - edges[:-2, None]) / np.diff(edges)[:-1, None],
        (edges[2:, None] - frequency[None, :]) / np.diff(edges)[1:, None]))
    mel = np.log(np.maximum(power @ filters.T, 1e-8))
    mel_times = audio_start + (np.arange(len(mel)) * 160 + 199.5) / 16000
    audio_features = _interpolate(mel, mel_times, targets)
    spatial = dctn(video.astype(np.float64) / 255, axes=(-2, -1), norm="ortho")[:, :8, :8]
    video_features = _interpolate(spatial.reshape(len(video), 64), timestamps, targets)
    features = [np.concatenate((v, np.diff(v, axis=0, prepend=v[:1])), axis=1)
                for v in (audio_features, video_features)]
    return features, dict(audio_samples=len(audio), video_frames=len(video),
        common_start_seconds=start, common_end_seconds=end, duration_seconds=end - start,
        first_video_timestamp=float(timestamps[0]), last_video_timestamp=float(timestamps[-1]),
        audio_start_seconds=audio_start)


def prepare(cache, output):
    started = datetime.now(timezone.utc).isoformat()
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    children_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    records = json.loads((output / "MANIFEST.json").read_text())["records"]
    if (output / "DATASET.json").exists():
        raise FileExistsError("Feature cache already sealed; use its checksum verifier")
    encoded, receipts = [], []
    for index, row in enumerate(records, 1):
        media = cache / "media" / (row["clip"] + ".flv")
        if digest(media) != row["sha256"]:
            raise ValueError("Media identity changed before decode")
        features, metadata = decode(media)
        encoded.append(features)
        receipts.append(dict(clip=row["clip"], **metadata))
        if index % 60 == 0:
            print(json.dumps(dict(decoded=index, expected=len(records))), flush=True)
    array = np.asarray(encoded, dtype=np.float64)
    train_indices = np.array([i for i, row in enumerate(records) if row["split"] == "train"])
    mean = array[train_indices].mean(axis=(0, 2), keepdims=True)
    scale = np.maximum(array[train_indices].std(axis=(0, 2), keepdims=True), 1e-5)
    normalized = ((array - mean) / scale).astype(np.float32)
    if not np.isfinite(normalized).all():
        raise FloatingPointError("Nonfinite preprocessed features")
    np.savez_compressed(output / "normalization.npz", mean=mean, scale=scale)
    split_rows = {}
    for split in ("train", "validation", "test"):
        indices = [i for i, row in enumerate(records) if row["split"] == split]
        rows = [records[i] for i in indices]
        durations = np.array([receipts[i]["duration_seconds"] for i in indices], dtype=np.float32)
        path = output / (split + ".npz")
        np.savez_compressed(path, audio=normalized[indices, 0], video=normalized[indices, 1],
            dt=np.repeat((10 * durations / STEPS)[:, None], STEPS, axis=1),
            y=np.array([r["label"] for r in rows], dtype=np.int64),
            actor=np.array([r["actor"] for r in rows]), clip=np.array([r["clip"] for r in rows]))
        split_rows[split] = dict(path=path.name, sha256=digest(path), examples=len(rows),
                                actors=sorted({r["actor"] for r in rows}))
    write_json(output / "DECODE.json", dict(records=receipts,
        ffmpeg=subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]))
    write_json(output / "DATASET.json", dict(schema="hcsn-real-av-tensors-v1", splits=split_rows,
        manifest_sha256=digest(output / "MANIFEST.json"), decoder_sha256=digest(__file__),
        normalization_sha256=digest(output / "normalization.npz"),
        decode_receipt_sha256=digest(output / "DECODE.json"), shape_per_modality=[STEPS, 128],
        normalization="training actors only; distinct moments for audio and video",
        time_scale="model dt = 10 * elapsed seconds; HCSN physical scale 0.1 restores seconds",
        frontend_scope="fixed low-level features with full-clip resampling; offline encoder",
        actual_total_media_bytes=sum(r["bytes"] for r in records),
        targets="acted filename emotion and same-recording audiovisual match"))
    children_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    parent_cpu = time.process_time() - cpu_start
    child_cpu = ((children_end.ru_utime + children_end.ru_stime) -
                 (children_start.ru_utime + children_start.ru_stime))
    write_json(output / "PREPARATION_COST.json", dict(started_utc=started,
        finished_utc=datetime.now(timezone.utc).isoformat(),
        scope="Feature preparation only; includes ffmpeg subprocess CPU; excludes media download and interpreter imports",
        python_cpu_seconds=parent_cpu, decoder_cpu_seconds=child_cpu,
        total_cpu_seconds=parent_cpu + child_cpu, wall_seconds=time.perf_counter()-wall_start,
        python_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        maximum_decoder_rss_bytes=children_end.ru_maxrss * 1024,
        python=platform.python_version(), numpy=version("numpy"), scipy=version("scipy"),
        dataset_sha256=digest(output / "DATASET.json"), measured_energy_joules=None))
    print(json.dumps(split_rows, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "acquire", "prepare"))
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.command == "register":
        register(args.cache, args.output)
    elif args.command == "acquire":
        acquire(args.cache, args.output, args.workers)
    else:
        prepare(args.cache, args.output)


if __name__ == "__main__":
    main()
