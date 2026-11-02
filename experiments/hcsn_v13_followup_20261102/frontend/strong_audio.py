"""Local-only official pretrained speech encoder; no task-quality promotion."""

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import time
from unittest.mock import patch

import numpy as np

WEIGHT_NAME = "wav2vec2_fairseq_base_ls960_asr_ls960.pth"
WEIGHT_SHA = "488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d"
WEIGHT_BYTES = 377664473
ROOT = Path(__file__).resolve().parents[3]
RUNTIME_FILES = ("torchaudio/pipelines/_wav2vec2/impl.py", "torchaudio/pipelines/_wav2vec2/utils.py",
                 "torchaudio/models/wav2vec2/model.py", "torchaudio/models/wav2vec2/components.py")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def checkpoint_guard(path):
    if path.name != WEIGHT_NAME or path.stat().st_size != WEIGHT_BYTES or sha(path) != WEIGHT_SHA:
        raise ValueError("Exact retained official checkpoint required; no fallback")


def prepare(args):
    checkpoint_guard(args.checkpoint)
    files = {str(Path(__file__).resolve()): sha(__file__), str(args.sample.resolve()): sha(args.sample)}
    files.update({str((args.runtime / item).resolve()): sha(args.runtime / item) for item in RUNTIME_FILES})
    write(args.plan, {"schema": "hcsn-v13-official-audio-forward-plan.v1", "source_and_input_sha256": files,
                     "checkpoint": str(args.checkpoint.resolve()), "checkpoint_sha256": WEIGHT_SHA,
                     "checkpoint_bytes": WEIGHT_BYTES, "runtime": str(args.runtime.resolve()),
                     "sample": str(args.sample.resolve()), "torch": "2.6.0+cpu", "torchaudio": "2.6.0+cpu",
                     "official_bundle": "WAV2VEC2_ASR_BASE_960H", "sample_rate": 16000,
                     "accepted_samples": 16000, "normalization": "none, as pinned official bundle",
                     "controls": ["future NaN suffix", "future finite suffix", "NaN inside accepted window",
                                  "short accepted window", "wrong local checkpoint bytes"],
                     "quality_scope": "Historical training waveform; actual pretrained ASR forward only. No emotion/binding fit, v6 recovery or independent confirmation."})


def accepted_prefix(wave):
    wave = np.asarray(wave)
    if wave.ndim != 1 or len(wave) < 16000:
        raise ValueError("A complete accepted one-second prefix is required")
    bounded = np.array(wave[:16000], dtype=np.float32, copy=True)
    if not np.isfinite(bounded).all():
        raise ValueError("Nonfinite accepted input")
    return bounded


class LocalSpeech:
    def __init__(self, checkpoint, runtime):
        checkpoint_guard(checkpoint)
        import torch
        import torchaudio
        from torchaudio.pipelines._wav2vec2 import utils
        if torch.__version__ != "2.6.0+cpu" or torchaudio.__version__ != "2.6.0+cpu":
            raise ValueError("Pinned Torch/TorchAudio CPU versions required")
        if not Path(torchaudio.__file__).resolve().is_relative_to(runtime.resolve()):
            raise ValueError("Unsealed runtime location")
        torch.set_num_threads(1)
        self.bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
        if self.bundle.sample_rate != 16000 or self.bundle._normalize_waveform:
            raise ValueError("Pinned official preprocessing contract differs")
        self.local_loads = 0

        def local_weights(url, **kwargs):
            if url != "https://download.pytorch.org/torchaudio/models/" + WEIGHT_NAME:
                raise ValueError("Unexpected checkpoint request")
            self.local_loads += 1
            return torch.load(checkpoint, map_location="cpu", weights_only=True)

        # The official factory performs its own strict state_dict load and
        # removes the unused fairseq auxiliary axes. Its network loader is
        # replaced by this verified local-file-only loader for this call.
        with patch.object(utils, "load_state_dict_from_url", side_effect=local_weights):
            self.model = self.bundle.get_model()
        if self.local_loads != 1:
            raise ValueError("Expected exactly one strict local checkpoint load")
        self.model.eval().requires_grad_(False)
        self.torch = torch

    def infer(self, wave):
        bounded = accepted_prefix(wave)
        with self.torch.inference_mode():
            layers, _ = self.model.extract_features(self.torch.from_numpy(bounded[None]))
            hidden = layers[-1][0]
            logits = self.model.aux(hidden)
            feature = self.torch.cat((hidden.mean(0), hidden.std(0, unbiased=False)))
        if hidden.shape != (49, 768) or logits.shape != (49, 29) or feature.shape != (1536,):
            raise ValueError("Official forward output dimensions differ")
        values = [item.numpy().copy() for item in (hidden, logits, feature)]
        if not all(np.isfinite(item).all() for item in values):
            raise ValueError("Nonfinite official encoder output")
        return values


def run(args):
    plan = json.loads(args.plan.read_text())
    for name, digest in plan["source_and_input_sha256"].items():
        if sha(name) != digest:
            raise ValueError("Frozen source/input identity differs: " + name)
    args.out.mkdir(parents=True, exist_ok=False)
    began = time.process_time()
    with np.load(plan["sample"], allow_pickle=False) as sample:
        wave = sample["waveform"].copy()
        if int(sample["sample_rate"]) != 16000 or float(sample["prefix_seconds"]) != 1.:
            raise ValueError("Expected actual retained one-second 16kHz waveform")
        recording = str(sample["recording_id"])
        raw_sha = str(sample["source_sha256"])
    model = LocalSpeech(Path(plan["checkpoint"]), Path(plan["runtime"]))
    baseline = model.infer(wave)
    controls = []
    for label, suffix in (("future_NaN", np.full(999, np.nan, dtype=np.float32)),
                          ("future_finite", np.linspace(-100., 100., 999, dtype=np.float32))):
        actual = model.infer(np.r_[wave, suffix])
        passed = all(np.array_equal(a, b) for a, b in zip(baseline, actual))
        controls.append({"name": label, "actual_pretrained_forward": True, "bitwise_equal": passed})
        if not passed:
            raise ValueError("Unaccepted future payload affected pretrained forward")
    for label, invalid in (("inside_NaN", np.r_[np.nan, wave[1:]]), ("short", wave[:-1])):
        try:
            model.infer(invalid)
        except ValueError:
            controls.append({"name": label, "rejected_before_forward": True})
        else:
            raise ValueError("Invalid accepted prefix was not rejected")
    wrong = args.out / WEIGHT_NAME
    wrong.write_bytes(b"wrong checkpoint")
    try:
        checkpoint_guard(wrong)
    except ValueError:
        controls.append({"name": "wrong_checkpoint", "rejected_before_loading": True})
    else:
        raise ValueError("Wrong checkpoint admitted")
    wrong.unlink()
    with (args.out / "FORWARD.npz").open("xb") as stream:
        np.savez_compressed(stream, hidden=baseline[0], ctc_logits=baseline[1], feature=baseline[2])
    write(args.out / "RESULT.json", {"schema": "hcsn-v13-real-pretrained-audio-forward.v1", "status": "PASS",
          "plan_sha256": sha(args.plan), "recording": recording, "original_media_sha256": raw_sha,
          "checkpoint_sha256": WEIGHT_SHA, "sample_npz_sha256": sha(plan["sample"]),
          "accepted_waveform_sha256": hashlib.sha256(wave.tobytes()).hexdigest(),
          "output_sha256": sha(args.out / "FORWARD.npz"), "actual_pretrained_forwards": 3,
          "network_requests": 0, "local_checkpoint_loads": model.local_loads,
          "torch": model.torch.__version__, "torchaudio": importlib.import_module("torchaudio").__version__,
          "controls": controls, "process_body_cpu_seconds": time.process_time() - began,
          "scope": plan["quality_scope"], "strong_audio_reference_qualified": False,
          "device_energy_joules": None, "complete_process_family_memory_bytes": None})
    print(json.dumps({"status": "PASS", "actual_pretrained_forwards": 3, "controls": len(controls)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    (prepare if args.mode == "prepare" else run)(args)
