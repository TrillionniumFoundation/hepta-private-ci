"""Fixed-window, actor-disjoint CREMA-D audio/video/text consistency data.

Preparation is offline and decodes whole source files. Each emitted feature uses
only its declared prefix. These fixed features are not pretrained encoders.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import resource
import subprocess
import time

import numpy as np
from scipy.fft import dctn


SCHEMA = "hcsn-four-stage.avt.v1"
UPSTREAM_COMMIT = "1658cd342dff90010aa843eaeebd53610a08b1dc"
SENTENCES = ("DFA", "IOM")
EMOTIONS = ("ANG", "DIS", "FEA", "HAP", "NEU", "SAD")
TRANSCRIPTS = ("Don't forget a jacket", "I'm on my way to the meeting")
TOKEN_PATTERN = r"[a-z]+(?:'[a-z]+)?"
TOKENS = tuple(tuple(re.findall(TOKEN_PATTERN, s.lower())) for s in TRANSCRIPTS)
VOCAB = ("<pad>",) + tuple(sorted(set(itertools.chain.from_iterable(TOKENS))))
TOKEN_IDS = tuple(tuple(VOCAB.index(token) for token in row) for row in TOKENS)
MAX_TEXT_TOKENS = max(map(len, TOKEN_IDS))
SAMPLE_RATE = 16000
WINDOW_SECONDS = 0.5
CUTOFFS = np.array([0.5, 1.0], dtype=np.float64)
MODALITY_SLICES = {
    "audio": [0, 64], "video": [64, 128],
    "text": [128, 128 + len(VOCAB)],
    "observed": [128 + len(VOCAB), 131 + len(VOCAB)],
}
INPUT_DIM = MODALITY_SLICES["observed"][1]
MODEL_ARRAYS = ("x", "dt")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def save_json(path, value):
    """Create immutable JSON, accepting only an identical existing artifact."""
    path = Path(path)
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"Different artifact already exists: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def cpu_seconds():
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + children.ru_utime + children.ru_stime


def combination_rows():
    return [dict(audio=a, video=v, text=t, y=int(a == v == t),
                 weight=3 if a == v == t else 1)
            for a, v, t in itertools.product(range(2), repeat=3)]


def information_bounds():
    """Exact weighted Bayes accuracy from observable sentence identities."""
    rows = combination_rows()
    total = sum(row["weight"] for row in rows)
    result = {}
    for size in range(4):
        for visible in itertools.combinations(("audio", "video", "text"), size):
            groups = {}
            for row in rows:
                key = tuple(row[name] for name in visible)
                counts = groups.setdefault(key, [0, 0])
                counts[row["y"]] += row["weight"]
            correct = sum(max(counts) for counts in groups.values())
            result["+".join(visible) or "none"] = dict(
                correct_weight=correct, total_weight=total, accuracy=correct / total)
            if size == 1 and any(c[0] != c[1] for c in groups.values()):
                raise AssertionError("A single modality leaks the consistency label")
    if result["audio+video"]["correct_weight"] != 10:
        raise AssertionError("The weighted two-modality oracle changed")
    return result


def read_cohort(path):
    cohort = json.loads(Path(path).read_text())
    if cohort.get("upstream_sha", cohort.get("commit")) != UPSTREAM_COMMIT:
        raise ValueError("Cohort does not identify the pinned CREMA-D source")
    splits = cohort.get("splits")
    if set(splits or {}) != {"train", "validation", "test"}:
        raise ValueError("Expected the three actor-level cohort splits")
    actors = [actor for group in splits.values() for actor in group]
    if len(actors) != len(set(actors)) or any(not group for group in splits.values()):
        raise ValueError("Actor splits must be nonempty and disjoint")
    seen, records = set(), []
    for source in cohort["records"]:
        row = {name: source[name] for name in
               ("actor", "sentence", "emotion", "split", "clip", "sha256", "bytes")}
        expected = f"{row['actor']}_{row['sentence']}_{row['emotion']}_XX"
        if (not re.fullmatch(r"[0-9]{4}", row["actor"])
                or row["sentence"] not in SENTENCES or row["emotion"] not in EMOTIONS
                or row["split"] not in splits or row["actor"] not in splits[row["split"]]
                or row["clip"] != expected or expected in seen
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                or not isinstance(row["bytes"], int) or row["bytes"] <= 0):
            raise ValueError(f"Invalid or duplicate cohort record: {expected}")
        seen.add(expected)
        records.append(row)
    expected = {f"{actor}_{sentence}_{emotion}_XX" for actor in actors
                for sentence in SENTENCES for emotion in EMOTIONS}
    if seen != expected:
        raise ValueError("Each actor must have both sentences in all six emotions")
    return splits, sorted(records, key=lambda row: (row["split"], row["clip"]))


def protocol_contract(cohort_path, splits, records):
    return dict(
        schema=SCHEMA, source_sha256=digest(__file__), cohort_sha256=digest(cohort_path),
        upstream_commit=UPSTREAM_COMMIT, actor_splits=splits, media_records=records,
        source_url="https://github.com/CheyneyComputerScience/CREMA-D",
        license_database="ODbL-1.0", license_contents="DbCL-1.0",
        baseline_public_commit="1dc975504276d9f7af3b28f0f7b1c2a79ef66d8d",
        windows=dict(seconds=WINDOW_SECONDS, cutoffs_seconds=CUTOFFS.tolist(),
                     origin="max(audio stream start, first video timestamp)",
                     video="last original frame at or before cutoff",
                     audio="native preceding half-second cropped before window-local resampling to 8000 samples"),
        features=dict(audio="32 log-mel means followed by 32 standard deviations",
                      video="top-left 8x8 orthonormal DCT of a 16x16 grayscale frame",
                      text="mean token one-hot; a linear projection is a learned mean embedding",
                      normalization="none in preparation; any fitted normalization uses train only",
                      pretrained=False),
        transcripts=list(TRANSCRIPTS), vocabulary=list(VOCAB), token_ids=TOKEN_IDS,
        modality_slices=MODALITY_SLICES, input_dim=INPUT_DIM,
        model_arrays=MODEL_ARRAYS, text_available="before the first AV window",
        episode_definition=combination_rows(), information_bounds=information_bounds(),
        inference="weighted accuracy; cluster uncertainty by actor, retaining emotion groups",
        holdout="test preparation requires a saved candidate-freeze artifact; no test-based selection",
        scope="Two-sentence acted AV/text consistency; not open-domain or foundation-model validation",
        causality="Features use fixed accepted prefixes; whole-file decoding remains offline preparation",
        cost="Whole-file decode and extraction CPU included; CPU is not joules; prior acquisition separate")


def freeze_plan(cohort_path, out):
    splits, records = read_cohort(cohort_path)
    contract = protocol_contract(cohort_path, splits, records)
    plan_path = Path(out) / "PLAN.json"
    if plan_path.exists():
        old = json.loads(plan_path.read_text())
        if old["contract"] != json.loads(json.dumps(contract)):
            raise ValueError("Resume would change the frozen AV data contract")
    else:
        save_json(plan_path, dict(frozen_utc=datetime.now(timezone.utc).isoformat(),
                                  contract=contract))
    return records


def audio_features(window):
    if window.shape != (8000,) or not np.isfinite(window).all():
        raise ValueError("A complete finite half-second audio window is required")
    frames = np.lib.stride_tricks.sliding_window_view(window, 400)[::160]
    power = np.abs(np.fft.rfft(frames * np.hanning(400), n=512)) ** 2
    frequencies = np.fft.rfftfreq(512, 1 / SAMPLE_RATE)
    mel_max = 2595 * np.log10(1 + 8000 / 700)
    edges = 700 * (10 ** (np.linspace(0, mel_max, 34) / 2595) - 1)
    filters = np.maximum(0, np.minimum(
        (frequencies[None, :] - edges[:-2, None]) / np.diff(edges)[:-1, None],
        (edges[2:, None] - frequencies[None, :]) / np.diff(edges)[1:, None]))
    mel = np.log(np.maximum(power @ filters.T, 1e-8))
    return np.concatenate((mel.mean(0), mel.std(0))).astype(np.float32)


def fixed_window_features(wave, pixels, timestamps, audio_start, sample_rate=SAMPLE_RATE):
    """Pure prefix extraction, separately testable without a media decoder."""
    timestamps = np.asarray(timestamps, dtype=np.float64)
    if not isinstance(sample_rate, int) or sample_rate <= 0 or sample_rate % 2:
        raise ValueError("An even positive integer native sample rate is required")
    if (len(timestamps) != len(pixels) or len(timestamps) < 2
            or not np.isfinite(timestamps).all() or not np.isfinite(audio_start)
            or not np.all(np.diff(timestamps) > 0)):
        raise ValueError("Original frame timestamps must be finite and strictly increasing")
    origin = max(float(audio_start), float(timestamps[0]))
    cutoffs = origin + CUTOFFS
    if timestamps[-1] < cutoffs[-1]:
        raise ValueError("Recording does not cover the fixed one-second protocol")
    audio, video, selected = [], [], []
    for cutoff in cutoffs:
        # Sample k covers [k/sr,(k+1)/sr); never include a partial future sample.
        hi = int(np.floor((cutoff - audio_start) * sample_rate + 1e-7))
        lo = hi - sample_rate // 2
        if lo < 0 or hi > len(wave):
            raise ValueError("Recording lacks a required complete audio prefix window")
        window = wave[lo:hi]
        if sample_rate != SAMPLE_RATE:
            # Whole-file resampling would let its FIR use the next window.
            # Crop first, then transform only accepted samples with zero edges.
            from scipy.signal import resample_poly
            common = math.gcd(sample_rate, SAMPLE_RATE)
            window = resample_poly(window, SAMPLE_RATE // common,
                                   sample_rate // common, padtype="constant")
        audio.append(audio_features(window))
        index = int(np.searchsorted(timestamps, cutoff, side="right") - 1)
        frame = np.asarray(pixels[index], dtype=np.float64) / 255.0
        if frame.shape != (16, 16):
            raise ValueError("Expected 16x16 grayscale frames")
        video.append(dctn(frame, axes=(-2, -1), norm="ortho")[:8, :8].reshape(64))
        selected.append(float(timestamps[index] - origin))
    return dict(audio=np.asarray(audio, dtype=np.float32),
                video=np.asarray(video, dtype=np.float32),
                dt=np.full(2, WINDOW_SECONDS, dtype=np.float32)), dict(
                    media_origin_seconds=origin, selected_video_times=selected,
                    audio_samples_used_per_window=8000,
                    native_audio_sample_rate=sample_rate,
                    native_audio_samples_used_per_window=sample_rate // 2,
                    source_audio_samples=len(wave), source_video_frames=len(pixels))


def decode_features(path):
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_frames", "-show_entries",
        "stream=codec_type,start_time,sample_rate:frame=media_type,best_effort_timestamp_time",
        "-of", "json", str(path)]))
    timestamps = np.array([float(frame["best_effort_timestamp_time"])
        for frame in probe["frames"] if frame.get("media_type") == "video"])
    audio_stream = next(row for row in probe["streams"] if row["codec_type"] == "audio")
    audio_start = float(audio_stream.get("start_time", 0))
    sample_rate = int(audio_stream["sample_rate"])
    prefix = ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "1", "-i", str(path)]
    wave = np.frombuffer(subprocess.check_output(prefix + ["-map", "0:a:0", "-ac", "1",
        "-threads", "1", "-f", "f32le", "-"]), dtype="<f4")
    pixels = np.frombuffer(subprocess.check_output(prefix + ["-map", "0:v:0", "-an",
        "-vf", "scale=16:16:flags=area,format=gray", "-filter_threads", "1",
        "-threads", "1", "-vsync", "0", "-f", "rawvideo", "-"]), dtype=np.uint8)
    return fixed_window_features(wave, pixels.reshape(-1, 16, 16), timestamps,
                                 audio_start, sample_rate)


def text_arrays(sentence):
    ids = np.zeros(MAX_TEXT_TOKENS, dtype=np.int64)
    ids[:len(TOKEN_IDS[sentence])] = TOKEN_IDS[sentence]
    mask = ids != 0
    bag = np.bincount(ids[mask], minlength=len(VOCAB)).astype(np.float32)
    return ids, mask, bag / mask.sum()


def assemble_episodes(records, features):
    """Metadata stays in separate arrays; only x and dt are model inputs."""
    lookup = {(r["actor"], r["emotion"], r["sentence"]): r["clip"] for r in records}
    groups = sorted({(r["actor"], r["emotion"]) for r in records})
    samples = []
    for actor, emotion in groups:
        clips = [lookup[(actor, emotion, sentence)] for sentence in SENTENCES]
        for combo in combination_rows():
            x = np.zeros((2, INPUT_DIM), dtype=np.float32)
            x[:, slice(*MODALITY_SLICES["audio"])] = features[clips[combo["audio"]]]["audio"]
            x[:, slice(*MODALITY_SLICES["video"])] = features[clips[combo["video"]]]["video"]
            ids, token_mask, bag = text_arrays(combo["text"])
            x[:, slice(*MODALITY_SLICES["text"])] = bag
            x[:, slice(*MODALITY_SLICES["observed"])] = 1.0
            samples.append(dict(x=x, dt=np.full(2, WINDOW_SECONDS, dtype=np.float32),
                y=combo["y"], sample_weight=combo["weight"],
                sample_id=f"{actor}:{emotion}:a{combo['audio']}v{combo['video']}t{combo['text']}",
                actor=actor, emotion=emotion, text_token_ids=ids, text_token_mask=token_mask,
                sentence_indices=[combo[k] for k in ("audio", "video", "text")]))
    arrays = {key: np.asarray([s[key] for s in samples]) for key in samples[0]}
    arrays["y"] = arrays["y"].astype(np.int64)
    arrays["sample_weight"] = arrays["sample_weight"].astype(np.float32)
    if not np.isfinite(arrays["x"]).all():
        raise ValueError("Nonfinite emitted feature")
    return arrays


def mask_modalities(x, hidden):
    """Remove both content and availability flags; preserve shape and clocks."""
    result = np.array(x, copy=True)
    for name in hidden:
        if name not in ("audio", "video", "text"):
            raise ValueError(f"Unknown modality: {name}")
        result[..., slice(*MODALITY_SLICES[name])] = 0
        flag = MODALITY_SLICES["observed"][0] + ("audio", "video", "text").index(name)
        result[..., flag] = 0
    return result


def prepare(media_root, cohort_path, out, selected_splits, candidate_freeze=None):
    started_wall, started_cpu = time.perf_counter(), cpu_seconds()
    out, media_root = Path(out), Path(media_root)
    if "test" in selected_splits and candidate_freeze is None:
        raise ValueError("Save and pass --candidate-freeze before preparing confirmation data")
    freeze_sha = None
    if candidate_freeze is not None:
        if not isinstance(json.loads(Path(candidate_freeze).read_text()), dict):
            raise ValueError("Candidate-freeze artifact must be a JSON object")
        freeze_sha = digest(candidate_freeze)
    records = freeze_plan(cohort_path, out)  # Must precede extraction or labels.
    selected_records = [r for r in records if r["split"] in selected_splits]
    cache = out / "clip_features"
    cache.mkdir(exist_ok=True)
    features, receipts = {}, []
    for row in selected_records:
        raw = media_root / (row["clip"] + ".flv")
        if raw.stat().st_size != row["bytes"] or digest(raw) != row["sha256"]:
            raise ValueError(f"Raw media identity mismatch: {row['clip']}")
        target, receipt_path = cache / (row["clip"] + ".npz"), cache / (row["clip"] + ".json")
        if target.exists() and receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            if receipt["sha256"] != digest(target) or receipt["raw_sha256"] != row["sha256"]:
                raise ValueError("Frozen feature cache identity mismatch")
        elif target.exists() or receipt_path.exists():
            raise FileExistsError("Incomplete cache entry retained; inspect it before retrying")
        else:
            wall, cpu = time.perf_counter(), cpu_seconds()
            values, detail = decode_features(raw)
            with target.open("xb") as stream:
                np.savez_compressed(stream, **values)
            receipt = dict(clip=row["clip"], raw_sha256=row["sha256"], sha256=digest(target),
                wall_seconds=time.perf_counter() - wall, cpu_seconds=cpu_seconds() - cpu,
                extraction=detail, source_sha256=digest(__file__), energy_joules=None)
            save_json(receipt_path, receipt)
        with np.load(target, allow_pickle=False) as data:
            features[row["clip"]] = {key: data[key] for key in ("audio", "video")}
        receipts.append(receipt)
    for split in selected_splits:
        destination, metadata_path = out / f"{split}.npz", out / f"{split}.json"
        if destination.exists() and metadata_path.exists():
            if json.loads(metadata_path.read_text())["sha256"] != digest(destination):
                raise ValueError("Existing split failed integrity")
            continue
        if destination.exists() or metadata_path.exists():
            raise FileExistsError("Incomplete split retained; do not silently overwrite")
        rows = [r for r in selected_records if r["split"] == split]
        arrays = assemble_episodes(rows, features)
        with destination.open("xb") as stream:
            np.savez_compressed(stream, **arrays)
        save_json(metadata_path, dict(schema=SCHEMA, split=split, sha256=digest(destination),
            plan_sha256=digest(out / "PLAN.json"), candidate_freeze_sha256=freeze_sha,
            episodes=len(arrays["y"]), total_sample_weight=float(arrays["sample_weight"].sum()),
            actors=sorted(set(arrays["actor"].tolist())), modality_slices=MODALITY_SLICES,
            model_arrays=MODEL_ARRAYS, information_bounds=information_bounds(),
            raw_sources=[dict(clip=r["clip"], sha256=r["sha256"], bytes=r["bytes"]) for r in rows],
            clip_receipts=[r for r in receipts if r["clip"] in {row["clip"] for row in rows}]))
    attempts = out / "preparation_receipts"
    attempts.mkdir(exist_ok=True)
    number = len(list(attempts.glob("attempt*.json"))) + 1
    save_json(attempts / f"attempt{number:03d}.json", dict(
        schema=SCHEMA, selected_splits=selected_splits, candidate_freeze_sha256=freeze_sha,
        wall_seconds=time.perf_counter() - started_wall, cpu_seconds=cpu_seconds() - started_cpu,
        peak_self_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        peak_child_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        energy_joules=None, cost_scope="prepare body plus waited ffmpeg children; interpreter imports excluded",
        prior_acquisition_cost="unobserved in this execution; not zero",
        plan_sha256=digest(out / "PLAN.json")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--cohort-path", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--splits", "--split", nargs="+", choices=("train", "validation", "test"),
                        default=["train", "validation"])
    parser.add_argument("--candidate-freeze", type=Path)
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    if len(set(args.splits)) != len(args.splits):
        parser.error("Duplicate split names are not allowed")
    if args.freeze_only:
        freeze_plan(args.cohort_path, args.out)
    else:
        prepare(args.media_root, args.cohort_path, args.out, args.splits, args.candidate_freeze)


if __name__ == "__main__":
    main()
