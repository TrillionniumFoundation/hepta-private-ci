"""Causal decoded-observation CREMA-D events with native independent clocks.

``load_batch(root, split, indices)`` returns NumPy x[B,T,D], dt[B,T] in REAL
SECONDS, y[B], lengths[B], valid[B,T], y_sequence[B,T], and timestamps[B,T].
It never multiplies time by the older HCSN model's physical scale. Adapters own
that conversion and must gather the last valid event rather than padded output.
Default D=40: 16 features + 16 causal differences, modality one-hot (2), observed
modality flags (2), age since last observation in seconds (2), ever-observed (2).
An inactive/missing modality is not a measurement of silence. Known missing
acquisitions retain their schedule but expose neither values nor hidden deltas.
No model input contains total duration, actor, labels, or future observations.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import subprocess
import time
import traceback
from urllib.request import urlopen

import numpy as np


PACKAGE = Path(__file__).resolve().parent
SOURCE = PACKAGE.parent / "hcsn_real_av_v1" / "data"
SOURCE_SHA = "982367fca163d49022c02deadbaa2ccd07c9f1ec4203320a1302e89771add0b8"
COHORT_SHA = "ac896bfb2643f22234c9917794347e2aa443836122b5950541335fdc002e3874"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(f"Different existing evidence: {path}")
        return
    with path.open("xb") as stream:
        stream.write(data)


def append_json(path, value):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()


def save_npz(path, **arrays):
    with Path(path).open("xb") as stream:
        np.savez_compressed(stream, **arrays)


def cpu_seconds():
    rows = [resource.getrusage(kind) for kind in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)]
    return sum(row.ru_utime + row.ru_stime for row in rows)


def register_subset(destination, feature_dim=32):
    if feature_dim not in (32, 128):
        raise ValueError("Use 32 or 128 features per observed modality")
    manifest_path, plan_path = SOURCE / "MANIFEST.json", SOURCE / "COHORT_PLAN.json"
    if digest(manifest_path) != SOURCE_SHA or digest(plan_path) != COHORT_SHA:
        raise ValueError("Frozen upstream media allocation changed")
    source, plan = json.loads(manifest_path.read_text()), json.loads(plan_path.read_text())
    counts = {"train": 4, "validation": 2, "test": 2}
    actors = {split: plan["splits"][split][:count] for split, count in counts.items()}
    if sum(map(len, actors.values())) != len(set(sum(actors.values(), []))):
        raise ValueError("Actor leakage between splits")
    rows = [row for row in source["records"]
            if row["actor"] in actors[row["split"]] and row["sentence"] == "DFA"]
    if len(rows) != 48 or any(sum(r["actor"] == actor for r in rows) != 6
                             for actor in sum(actors.values(), [])):
        raise ValueError("Fixed balanced 24/12/12 subset is incomplete")
    result = dict(schema="hcsn-causal-async-av.v1", upstream_commit=source["commit"],
        source_manifest_sha256=SOURCE_SHA, source_cohort_sha256=COHORT_SHA,
        selection="Original cohort actor order, first 4/2/2 actors; DFA sentence; all six emotions",
        actors=actors, records=rows, raw_bytes=sum(row["bytes"] for row in rows),
        old_heldout_previously_observed=True, fresh_confirmation=False,
        license_database=source["license_database"], license_contents=source["license_contents"],
        license_sha256=digest(SOURCE / "CREMA_D_LICENSE.txt"),
        features=dict(per_modality=feature_dim, input_dim=feature_dim + 8,
            audio="Native-rate decoded mono PCM; 25ms Hann windows, 10ms hop, log mel",
            audio_timestamp="First decoded audio PTS + exclusive window END sample/native rate",
            video="Original decoded presentation timestamps; 16x16 grayscale spatial DCT",
            difference="Current minus last OBSERVED value of the same modality; first difference zero",
            resampling="No temporal interpolation, audio resampling, or full-clip time normalization",
            clock_validation="Audio packet PTS versus decoded sample clock; reject discrepancy >2ms",
            ties="Ascending timestamp, then audio (0) before video (1); tied dt is zero",
            missing="Known missing acquisition: observed flags zero, zero payload, past state unchanged",
            metadata_columns=["audio_event", "video_event", "audio_observed", "video_observed",
                              "audio_age_seconds", "video_age_seconds", "audio_seen", "video_seen"]),
        normalization="Source-uniform moments over TRAIN clips only, separately by modality; std floor .01",
        time_contract="dt is true seconds since the previous event, first measured from first media PTS; adapter handles model scale",
        scope="Causal features of decoded presentation observations, not measured codec/network latency or live sensor capture",
        missingness_observed_in_source=False, imposed_missingness_is_a_registered_intervention=True)
    write_json(destination, result)
    return result


def decode(path):
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams",
        "-show_frames", "-show_entries",
        "stream=codec_type,sample_rate,start_time:frame=media_type,best_effort_timestamp_time,nb_samples",
        "-of", "json", str(path)]))
    streams = {row["codec_type"]: row for row in probe["streams"]}
    if not {"audio", "video"}.issubset(streams):
        raise ValueError("Expected genuine paired audio/video")
    video_rows = [r for r in probe["frames"] if r.get("media_type") == "video"]
    audio_rows = [r for r in probe["frames"] if r.get("media_type") == "audio"]
    timestamps = np.array([float(r["best_effort_timestamp_time"]) for r in video_rows])
    rate = int(streams["audio"]["sample_rate"])
    start = float(audio_rows[0]["best_effort_timestamp_time"])
    prefix = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-i", str(path)]
    audio = np.frombuffer(subprocess.check_output(prefix + ["-map", "0:a:0", "-ac", "1",
        "-threads", "1", "-f", "f32le", "-"]), dtype="<f4").astype(np.float64)
    video = np.frombuffer(subprocess.check_output(prefix + ["-map", "0:v:0", "-an", "-vf",
        "scale=16:16:flags=area,format=gray", "-filter_threads", "1", "-threads", "1",
        "-vsync", "0", "-f", "rawvideo", "-"]), dtype=np.uint8).reshape(-1, 16, 16)
    samples = np.array([int(r["nb_samples"]) for r in audio_rows])
    packet_times = np.array([float(r["best_effort_timestamp_time"]) for r in audio_rows])
    discrepancy = float(np.max(np.abs(packet_times - start - np.r_[0, samples.cumsum()[:-1]] / rate)))
    if len(audio) != samples.sum() or discrepancy > 0.002:
        raise ValueError("Decoded audio sample clock disagrees with native packet timestamps")
    if len(video) != len(timestamps) or len(video) < 2 or np.any(np.diff(timestamps) <= 0):
        raise ValueError("Video frame/PTS mismatch or non-monotone native timestamps")
    return audio, video, timestamps, rate, start, dict(native_sample_rate=rate,
        audio_start_seconds=start, decoded_audio_samples=len(audio), video_frames=len(video),
        maximum_audio_clock_discrepancy_seconds=discrepancy,
        video_first_pts=float(timestamps[0]), video_last_pts=float(timestamps[-1]))


def audio_features(audio, rate, start, base_dim=16):
    window, hop = int(math.ceil(0.025 * rate)), int(round(0.010 * rate))
    if len(audio) < window:
        return np.empty((0, base_dim)), np.empty(0)
    frames = np.lib.stride_tricks.sliding_window_view(audio, window)[::hop]
    nfft = 1 << (window - 1).bit_length()
    power = np.abs(np.fft.rfft(frames * np.hanning(window), n=nfft)) ** 2
    frequency = np.fft.rfftfreq(nfft, 1 / rate)
    mel_max = 2595 * np.log10(1 + min(8000, rate / 2) / 700)
    edges = 700 * (10 ** (np.linspace(0, mel_max, base_dim + 2) / 2595) - 1)
    filters = np.maximum(0, np.minimum(
        (frequency[None] - edges[:-2, None]) / np.diff(edges)[:-1, None],
        (edges[2:, None] - frequency[None]) / np.diff(edges)[1:, None]))
    values = np.log(np.maximum(power @ filters.T, 1e-8))
    ends = start + (np.arange(len(values)) * hop + window) / rate
    return values, ends


def video_features(video, base_dim=16):
    side = math.isqrt(base_dim)
    if side * side != base_dim:
        raise ValueError("Video feature count must be square")
    matrix = np.cos(np.pi * np.arange(side)[:, None] * (np.arange(16) + 0.5) / 16)
    matrix *= np.sqrt(2 / 16)
    matrix[0] /= np.sqrt(2)
    return np.einsum("ki,nij,lj->nkl", matrix, video.astype(np.float64) / 255, matrix).reshape(-1, base_dim)


def merge_observations(audio_base, audio_times, video_base, video_times):
    base = np.concatenate((audio_base, video_base))
    times = np.concatenate((audio_times, video_times))
    modalities = np.r_[np.zeros(len(audio_times), dtype=np.uint8), np.ones(len(video_times), dtype=np.uint8)]
    order = np.lexsort((modalities, times))
    return dict(base=base[order], times=times[order], modality=modalities[order])


def event_inputs(base, times, modality, origin, normalization=None, observed=None):
    base, times, modality = np.asarray(base), np.asarray(times), np.asarray(modality)
    observed = np.ones(len(times), dtype=bool) if observed is None else np.asarray(observed, dtype=bool)
    if (base.ndim != 2 or len(base) != len(times) or observed.shape != times.shape
            or modality.shape != times.shape or not np.isin(modality, [0, 1]).all()
            or not np.isfinite(base).all() or not np.isfinite(times).all()
            or np.any(np.diff(times) < 0) or (len(times) and times[0] < origin)):
        raise ValueError("Invalid ordered observations")
    width = 2 * base.shape[1]
    x = np.zeros((len(times), width + 8), dtype=np.float32)
    previous, seen, last_time = np.zeros((2, base.shape[1])), np.zeros(2, dtype=bool), np.zeros(2)
    for index, (value, timestamp, kind, available) in enumerate(zip(base, times, modality, observed, strict=True)):
        x[index, width + kind] = 1
        if available:
            feature = np.r_[value, value - previous[kind] if seen[kind] else np.zeros_like(value)]
            if normalization is not None:
                feature = (feature - normalization["mean"][kind]) / normalization["scale"][kind]
            x[index, :width] = feature
            previous[kind], seen[kind], last_time[kind] = value, True, timestamp
            x[index, width + 2 + kind] = 1
        x[index, width + 4:width + 6] = np.where(seen, timestamp - last_time, 0)
        x[index, width + 6:width + 8] = seen
    return x, np.diff(np.r_[origin, times]).astype(np.float32)


def fit_normalization(clips):
    training = [clip for clip in clips if clip["split"] == "train"]
    if not training:
        raise ValueError("Training clips are required to fit normalization")
    means, second = [[], []], [[], []]
    for clip in training:
        x, _ = event_inputs(clip["base"], clip["times"], clip["modality"], clip["origin"])
        width = 2 * clip["base"].shape[1]
        for kind in (0, 1):
            values = x[clip["modality"] == kind, :width].astype(np.float64)
            means[kind].append(values.mean(0))
            second[kind].append((values ** 2).mean(0))
    mean = np.array([np.mean(rows, axis=0) for rows in means])
    variance = np.array([np.mean(rows, axis=0) for rows in second]) - mean ** 2
    return dict(mean=mean, scale=np.maximum(np.sqrt(np.maximum(variance, 0)), 0.01))


def prefix_audit(audio, video, timestamps, rate, start, base_dim):
    audio_base, audio_times = audio_features(audio, rate, start, base_dim)
    video_base = video_features(video, base_dim)
    cutoff = start + (min(audio_times[-1], timestamps[-1]) - start) * 0.5
    count = int(math.floor((cutoff - start) * rate))
    kept_video = timestamps <= cutoff
    original = merge_observations(audio_base, audio_times, video_base, timestamps)
    prefix = merge_observations(*audio_features(audio[:count], rate, start, base_dim),
                                video_features(video[kept_video], base_dim), timestamps[kept_video])
    changed_audio, changed_video = audio.copy(), video.copy()
    changed_audio[count:] = -changed_audio[count:] + 0.125
    changed_video[~kept_video] = 255 - changed_video[~kept_video]
    modified = merge_observations(*audio_features(changed_audio, rate, start, base_dim),
                                  video_features(changed_video, base_dim), timestamps)
    origin = min(start, timestamps[0])
    selected = original["times"] <= cutoff
    errors = []
    for candidate in (prefix, {key: value[selected] for key, value in modified.items()}):
        if not np.array_equal(original["times"][selected], candidate["times"]):
            raise AssertionError("Prefix observation times depend on the future")
        actual, actual_dt = event_inputs(**candidate, origin=origin)
        expected, expected_dt = event_inputs(**{key: value[selected] for key, value in original.items()}, origin=origin)
        errors.append(float(np.max(np.abs(actual - expected))))
        if not np.array_equal(actual_dt, expected_dt) or not np.allclose(actual, expected, atol=1e-6, rtol=0):
            raise AssertionError("Future observations changed the decoded prefix")
    return original, dict(cutoff_seconds=cutoff, prefix_events=int(selected.sum()),
                         truncate_max_abs_error=errors[0], perturb_future_max_abs_error=errors[1], passed=True)


def load_batch(root, split, indices=None, *, missing_modality=None):
    """Missing-modality intervention never exposes its payload or derived delta."""
    if split not in ("train", "validation", "test") or missing_modality not in (None, 0, 1):
        raise ValueError("Unknown split or missing modality")
    with np.load(Path(root) / f"{split}.npz", allow_pickle=False) as archive:
        data = {key: np.array(archive[key], copy=True) for key in archive.files}
    indices = np.arange(len(data["labels"])) if indices is None else np.asarray(indices, dtype=np.int64)
    if indices.ndim != 1 or not len(indices) or np.any(indices < 0) or np.any(indices >= len(data["labels"])):
        raise ValueError("A nonempty valid one-dimensional batch index is required")
    lengths = data["offsets"][indices + 1] - data["offsets"][indices]
    x = np.zeros((len(indices), int(lengths.max()), data["x"].shape[1]), dtype=np.float32)
    dt, timestamps = np.zeros(x.shape[:2], dtype=np.float32), np.zeros(x.shape[:2], dtype=np.float64)
    valid, targets = np.zeros(x.shape[:2], dtype=bool), np.full(x.shape[:2], -100, dtype=np.int64)
    for row, (index, length) in enumerate(zip(indices, lengths, strict=True)):
        begin, end = data["offsets"][index:index + 2]
        values = data["x"][begin:end]
        if missing_modality is not None:
            values, _ = event_inputs(data["base"][begin:end], data["times"][begin:end],
                data["modality"][begin:end], data["origins"][index],
                dict(mean=data["normalization_mean"], scale=data["normalization_scale"]),
                observed=data["modality"][begin:end] != missing_modality)
        x[row, :length], dt[row, :length] = values, data["dt"][begin:end]
        timestamps[row, :length], valid[row, :length] = data["times"][begin:end], True
        targets[row, length - 1] = data["labels"][index]
    return dict(x=x, dt=dt, dt_seconds=dt.copy(), y=data["labels"][indices], lengths=lengths,
                valid=valid, y_sequence=targets, timestamps=timestamps, clip_ids=data["clip_ids"][indices])


def prepare(manifest, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "RESULT.json").exists() or (output / "START.json").exists():
        raise FileExistsError("Use a new run namespace; failed and successful evidence must remain")
    started_cpu, started_wall = cpu_seconds(), time.perf_counter()
    write_json(output / "START.json", dict(manifest_sha256=digest(manifest),
        source_sha256=digest(__file__), wall_clock_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    plan = json.loads(Path(manifest).read_text())
    raw, features, data_dir = output / "raw", output / "clip_features", output / "data"
    for path in (raw, features, data_dir):
        path.mkdir(exist_ok=True)
    clips, checks = [], []
    try:
        for row in plan["records"]:
            path = raw / (row["clip"] + ".flv")
            began_cpu, began_wall = cpu_seconds(), time.perf_counter()
            if not path.exists():
                with urlopen(row["url"], timeout=45) as response:
                    payload = response.read(row["bytes"] + 1)
                if len(payload) != row["bytes"] or hashlib.sha256(payload).hexdigest() != row["sha256"]:
                    raise ValueError("Downloaded media failed its frozen LFS identity")
                with path.open("xb") as stream:
                    stream.write(payload)
            if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
                raise ValueError("Existing media failed its frozen LFS identity")
            audio, video, timestamps, rate, start, metadata = decode(path)
            observations, audit = prefix_audit(audio, video, timestamps, rate, start,
                                               plan["features"]["per_modality"] // 2)
            observations["base"] = observations["base"].astype(np.float32)
            origin = float(min(start, timestamps[0]))
            target = features / (row["clip"] + ".npz")
            save_npz(target, **observations, origin=np.array(origin))
            clips.append(dict(**observations, origin=origin, **row))
            checks.append(dict(clip=row["clip"], **audit))
            receipt = dict(clip=row["clip"], source_sha256=row["sha256"], source_bytes=row["bytes"],
                feature_sha256=digest(target), events=len(observations["times"]), **metadata,
                cpu_seconds=cpu_seconds() - began_cpu, wall_seconds=time.perf_counter() - began_wall,
                raw_deleted_after_verified_feature_write=True)
            append_json(output / "decode.jsonl", receipt)
            append_json(output / "prefix_checks.jsonl", checks[-1])
            path.unlink()
            print(json.dumps(dict(completed=len(clips), expected=48, clip=row["clip"], events=receipt["events"])), flush=True)
        normalization = fit_normalization(clips)
        write_json(data_dir / "NORMALIZATION.json", dict(
            mean=normalization["mean"].tolist(), scale=normalization["scale"].tolist(),
            training_clips=[clip["clip"] for clip in clips if clip["split"] == "train"],
            rule=plan["normalization"], nontraining_clips_used=False))
        split_reports = {}
        for split in ("train", "validation", "test"):
            selected = [clip for clip in clips if clip["split"] == split]
            inputs = [event_inputs(c["base"], c["times"], c["modality"], c["origin"], normalization) for c in selected]
            offsets = np.r_[0, np.cumsum([len(c["times"]) for c in selected])]
            target = data_dir / f"{split}.npz"
            save_npz(target, x=np.concatenate([i[0] for i in inputs]), dt=np.concatenate([i[1] for i in inputs]),
                base=np.concatenate([c["base"] for c in selected]), times=np.concatenate([c["times"] for c in selected]),
                modality=np.concatenate([c["modality"] for c in selected]), offsets=offsets,
                labels=np.array([c["label"] for c in selected]), origins=np.array([c["origin"] for c in selected]),
                clip_ids=np.array([c["clip"] for c in selected]), actors=np.array([c["actor"] for c in selected]),
                normalization_mean=normalization["mean"], normalization_scale=normalization["scale"])
            check = load_batch(data_dir, split)
            if not np.isfinite(check["x"]).all() or not np.all(check["dt"] >= 0):
                raise AssertionError("Serialized model inputs failed finite/time checks")
            split_reports[split] = dict(clips=len(selected), events=int(offsets[-1]),
                minimum_length=int(check["lengths"].min()), maximum_length=int(check["lengths"].max()),
                sha256=digest(target), bytes=target.stat().st_size)
        license_path = output / "LICENSE_CREMA_D.txt"
        with license_path.open("xb") as stream:
            stream.write((SOURCE / "CREMA_D_LICENSE.txt").read_bytes())
        report = dict(schema="hcsn-async-frontend-result.v1", completed=True, clips=len(clips),
            splits=split_reports, input_dim=plan["features"]["input_dim"], dt_unit="seconds",
            prefix_checks_passed=sum(c["passed"] for c in checks), prefix_checks=len(checks),
            maximum_prefix_error=max(max(c["truncate_max_abs_error"], c["perturb_future_max_abs_error"]) for c in checks),
            manifest_sha256=digest(manifest), source_sha256=digest(__file__),
            source_media_bytes=sum(c["bytes"] for c in clips), retained_raw_media_bytes=0,
            retained_npz_bytes=sum(p.stat().st_size for p in output.rglob("*.npz")),
            cpu_seconds_including_reaped_decoders=cpu_seconds() - started_cpu,
            wall_seconds=time.perf_counter() - started_wall,
            scope=plan["scope"], old_heldout_previously_observed=True, fresh_confirmation=False,
            ffmpeg=subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
            numpy_version=np.__version__, direct_energy_joules=None, gpu_used=False)
        if report["retained_npz_bytes"] > 5 * 1024 * 1024:
            raise RuntimeError("Prepared tensors exceed the registered 5MiB storage budget")
        write_json(output / "RESULT.json", report)
        return report
    except Exception as error:
        write_json(output / "FAILED.json", dict(error_type=type(error).__name__, error=str(error),
            completed_clips=len(clips), traceback=traceback.format_exc(),
            cpu_seconds=cpu_seconds() - started_cpu, wall_seconds=time.perf_counter() - started_wall))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "prepare"))
    parser.add_argument("--manifest", type=Path, default=PACKAGE / "data/async_manifest.json")
    parser.add_argument("--output", type=Path, default=PACKAGE / "results/async_frontend001")
    parser.add_argument("--feature-dim", type=int, default=32)
    args = parser.parse_args()
    result = register_subset(args.manifest, args.feature_dim) if args.action == "register" else prepare(args.manifest, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
