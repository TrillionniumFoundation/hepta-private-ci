"""Frozen official speech model receiving only the accepted one-second PCM."""

import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import resource
import subprocess
import time

import numpy as np
from scipy.signal import resample_poly
import torch
import torchaudio


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SENTENCES = ("DFA", "IOM")
EMOTIONS = ("ANG", "DIS", "FEA", "HAP", "NEU", "SAD")
CHECKPOINT_SHA256 = "488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d"
FEATURE_WIDTH = 1652


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False); stream.write("\n")


def source_guard():
    frozen = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    publication = json.loads((HERE / "SOURCE_PUBLICATION.json").read_text())
    if publication["source_freeze_sha256"] != sha(HERE / "SOURCE_FREEZE.json"):
        raise ValueError("Published source-freeze identity differs")
    if not re.fullmatch(r"[0-9a-f]{40}", publication["source_commit"]):
        raise ValueError("Remote source commit is required")
    if any(sha(ROOT / p) != value for p, value in frozen["source"].items()):
        raise ValueError("Source changed after publication freeze")
    if any(sha(importlib.import_module(name).__file__) != value
           for name, value in frozen["runtime_source_sha256"].items()):
        raise ValueError("Official encoder implementation changed")
    return frozen


def target_guard(records, split):
    if len({row["clip"] for row in records}) != len(records):
        raise ValueError("Clip identities must be unique")
    targets = []
    for row in records:
        fields = row["clip"].split("_")
        if (len(fields) != 4 or fields[0] != str(row["actor"]) or fields[1] != row["sentence"]
                or fields[2] != row["emotion"] or fields[3] != "XX"
                or row["sentence"] not in SENTENCES or row["emotion"] not in EMOTIONS
                or row["split"] != split or row["sentence_target"] != SENTENCES.index(row["sentence"])):
            raise ValueError("Clip/sentence binary target mismatch; emotion labels are not sentence targets")
        targets.append(row["sentence_target"])
    if set(targets) != {0, 1}:
        raise ValueError("Both sentence classes must be present")
    actors = sorted({str(row["actor"]) for row in records})
    if any(sum(str(row["actor"]) == actor for row in records) != 12 for actor in actors):
        raise ValueError("Each actor must provide both sentences and six emotions")
    return np.asarray(targets, dtype=np.int64)


def accepted_pcm(wave, timestamps, audio_start, sample_rate):
    timestamps = np.asarray(timestamps, dtype=np.float64)
    if len(timestamps) < 2 or not np.all(np.diff(timestamps) > 0):
        raise ValueError("Strictly increasing video timestamps required")
    origin = max(float(audio_start), float(timestamps[0]))
    if timestamps[-1] < origin + 1.0:
        raise ValueError("Incomplete synchronized physical prefix")
    lo = int(np.ceil((origin - audio_start) * sample_rate - 1e-7))
    hi = int(np.floor((origin + 1.0 - audio_start) * sample_rate + 1e-7))
    if lo < 0 or hi > len(wave) or not sample_rate - 1 <= hi - lo <= sample_rate:
        raise ValueError("Incomplete native audio prefix")
    # Crop FIRST. Resampling the full recording could use future PCM through
    # the finite resampling filter. Both padding and all model context stay
    # inside the already accepted window.
    bounded = np.asarray(wave[lo:hi], dtype=np.float64)
    divisor = math.gcd(sample_rate, 16000)
    resampled = resample_poly(bounded, 16000 // divisor, sample_rate // divisor, padtype="constant")
    if not 15998 <= len(resampled) <= 16000:
        raise ValueError("Unexpected resampled one-second length")
    output = np.pad(resampled, (0, 16000 - len(resampled))).astype(np.float32)
    if not np.isfinite(output).all():
        raise ValueError("Nonfinite accepted PCM")
    detail = dict(origin=origin, accepted_end=origin+1., audio_start=float(audio_start),
                  native_sample_rate=int(sample_rate), native_lo=lo, native_hi=hi,
                  native_samples=hi-lo, resampled_before_padding=len(resampled),
                  padded_samples=16000-len(resampled), accepted_samples=16000,
                  waveform_sha256=hashlib.sha256(output.tobytes()).hexdigest(),
                  full_recording_normalization=False, future_pcm_used=False)
    return output, detail


def decode_prefix(path):
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_frames",
        "-show_entries", "stream=codec_type,start_time,sample_rate:frame=media_type,best_effort_timestamp_time",
        "-of", "json", str(path)]))
    timestamps = [float(r["best_effort_timestamp_time"]) for r in probe["frames"] if r.get("media_type") == "video"]
    audio = next(r for r in probe["streams"] if r["codec_type"] == "audio")
    wave = np.frombuffer(subprocess.check_output(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "1",
        "-i", str(path), "-map", "0:a:0", "-ac", "1", "-threads", "1", "-f", "f32le", "-"]), dtype="<f4")
    return accepted_pcm(wave, timestamps, float(audio.get("start_time", 0)), int(audio["sample_rate"]))


class FrozenSpeech:
    def __init__(self, checkpoint=None):
        if torch.__version__ != "2.6.0+cpu" or torchaudio.__version__ != "2.6.0+cpu":
            raise ValueError("Pinned Torch/TorchAudio2.6.0 CPU runtime required")
        record = json.loads((HERE / "CHECKPOINT.json").read_text())
        path = Path(checkpoint or record["path"])
        if path.name != "wav2vec2_fairseq_base_ls960_asr_ls960.pth" or sha(path) != CHECKPOINT_SHA256:
            raise ValueError("Official checkpoint identity mismatch")
        self.bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
        if self.bundle.sample_rate != 16000 or self.bundle._normalize_waveform:
            raise ValueError("Unexpected official bundle input contract")
        self.labels = self.bundle.get_labels()
        self.model = self.bundle.get_model(dl_kwargs={"model_dir": str(path.parent), "weights_only": True})
        self.model.eval().requires_grad_(False)
        self.checkpoint = path

    def infer(self, window):
        window = np.asarray(window, dtype=np.float32)
        if window.shape != (16000,) or not np.isfinite(window).all():
            raise ValueError("Exactly16000 finite accepted samples required")
        with torch.inference_mode():
            layers, _ = self.model.extract_features(torch.from_numpy(window[None]))
            hidden = layers[-1][0]
            logits = self.model.aux(hidden)
            if hidden.shape != (49, 768) or logits.shape != (49, 29):
                raise ValueError("Unexpected official encoder output dimensions")
            bins = torch.tensor_split(logits, 4, dim=0)
            feature = torch.cat((hidden.mean(0), hidden.std(0, unbiased=False),
                                 *[part.mean(0) for part in bins])).numpy()
        if feature.shape != (FEATURE_WIDTH,) or not np.isfinite(feature).all():
            raise ValueError("Invalid frozen speech descriptor")
        indices = torch.unique_consecutive(logits.argmax(-1)).tolist()
        transcript = "".join(self.labels[i] for i in indices if i).replace("|", " ")
        return feature.astype(np.float32), logits.numpy().astype(np.float32), transcript


def prepare(manifest, media_root, out, split, checkpoint=None):
    source_guard()
    if split != "train":
        from .study import candidate_guard, validation_manifest_guard
        candidate_guard()
        validation_manifest_guard(manifest)
    elif sha(manifest) != sha(HERE / "TRAIN_COHORT.json"):
        raise ValueError("Only the frozen train-only manifest may be extracted")
    manifest_bytes = Path(manifest).read_bytes()
    records = json.loads(manifest_bytes)["records"]
    records = sorted(records, key=lambda r: r["clip"])
    labels = target_guard(records, split)
    if split == "train" and (len(records) != 288 or len({r["actor"] for r in records}) != 24):
        raise ValueError("Original288 train clips/24 actors required")
    out.mkdir(parents=True, exist_ok=False)
    with (out / "COHORT.json").open("xb") as stream:
        stream.write(manifest_bytes)
    clock, cpu = time.perf_counter(), time.process_time()
    model = FrozenSpeech(checkpoint)
    values, logits, details = [], [], []
    for index, row in enumerate(records):
        path = Path(media_root) / (row["clip"] + ".flv")
        if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("Pinned raw media identity differs")
        window, detail = decode_prefix(path)
        feature, ctc, transcript = model.infer(window)
        values.append(feature); logits.append(ctc)
        details.append(dict(clip=row["clip"], raw_sha256=row["sha256"], prefix=detail,
                            feature_sha256=hashlib.sha256(feature.tobytes()).hexdigest(),
                            ctc_sha256=hashlib.sha256(ctc.tobytes()).hexdigest(), greedy_ctc=transcript))
        if (index + 1) % 24 == 0:
            print(json.dumps(dict(prepared=index+1, clips=len(records), split=split)), flush=True)
    target = out / "features.npz"
    with target.open("xb") as stream:
        np.savez_compressed(stream, features=np.asarray(values), ctc_logits=np.asarray(logits),
                            clip=np.asarray([r["clip"] for r in records]), actor=np.asarray([r["actor"] for r in records]), label=labels)
    write(out / "IDENTITY.json", dict(schema="hcsn.audio.frozen-prefix-features.v1", split=split,
        features_sha256=sha(target), manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(), checkpoint_sha256=CHECKPOINT_SHA256,
        source_sha256=sha(__file__), clips=len(records), details=details,
        body_cpu_seconds=time.process_time()-cpu, body_wall_seconds=time.perf_counter()-clock,
        body_cpu_excludes_decoder_children=True, observation_seconds=1., gpu=None, energy_joules=None))


if __name__ == "__main__":
    torch.set_num_threads(1)
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True); parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True); parser.add_argument("--split", choices=("train", "validation"), required=True)
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args(); prepare(args.manifest, args.media_root, args.out, args.split, args.checkpoint)
