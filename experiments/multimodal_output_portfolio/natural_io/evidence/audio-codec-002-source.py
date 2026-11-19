#!/usr/bin/env python3
"""Pinned, frozen DAC reconstruction of the first two seconds of recorded audio."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import traceback
import warnings
import wave


CODE_REVISION = "c7cfc5d2647e26471dc394f95846a0830e7bec34"
CODE_ARCHIVE = f"https://github.com/descriptinc/descript-audio-codec/archive/{CODE_REVISION}.zip"
CODE_ARCHIVE_SHA256 = "a8fa0e7ba90aaf6b53405f4a541ee6dee18aaef932cf110651b4fb2bc6833963"
WEIGHT_URL = "https://github.com/descriptinc/descript-audio-codec/releases/download/0.0.5/weights_16khz.pth"
WEIGHT_SHA256 = "95ab7176b67137d4d4c6c54b8d6ef3cea797faec228cb03ad084badcad570b4d"
WEIGHT_BYTES = 296820733
INPUT_SHA256 = "e81fc702ce828c0711c4bfd2133619b0e58aba17cf4685d7a5aa9b90ebada384"
LICENSE_SHA256 = "5d7a5f644313f30aad5ef032669ada67efdacefecb2c7d7b875683698bd70e87"
SOURCE_HASHES = {
    "dac/model/dac.py": "412c6bb1fddfd01a96e4f73df6934a5cdcbc9c6ee50e2b462433917dbceb7300",
    "dac/nn/quantize.py": "e2dc61f32f6123aa48a0aeb934a0d9a41ea29a5eae8db28119c791885c9f1b07",
    "dac/utils/__init__.py": "ac4e097f5db5f730bdd944bfd7ddf66761e776ba22d14d5ad7e3d6bd902addf5",
}
SAMPLE_RATE = 16000
CLIP_SAMPLES = 32000


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def memory_snapshot():
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    peak *= 1024 if sys.platform.startswith("linux") else 1
    status = Path("/proc/self/status")
    current = None
    if status.exists():
        line = next(row for row in status.read_text().splitlines() if row.startswith("VmRSS:"))
        current = int(line.split()[1]) * 1024
    return {"process_peak_rss_bytes": peak, "process_current_rss_bytes": current}


def write_pcm(path, data, sample_rate):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(data)


def execute(args, receipt):
    receipt["stage"] = "runtime_imports"
    import dac
    import numpy as np
    import torch
    import torchaudio

    expected = {"numpy": "1.26.4", "torch": "2.5.1+cpu", "torchaudio": "2.5.1+cpu",
                "descript-audio-codec": "1.0.0", "descript-audiotools": "0.7.2"}
    actual = {name: importlib.metadata.version(name) for name in expected}
    if actual != expected or torch.version.cuda is not None or torch.cuda.is_available():
        raise RuntimeError(f"pinned CPU runtime mismatch: {actual}")
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    receipt["runtime"] = {"python": sys.version, "executable": sys.executable,
                          "platform": platform.platform(), "versions": actual,
                          "device": "cpu", "cuda_build": torch.version.cuda,
                          "cpu_count": os.cpu_count(), "torch_threads": torch.get_num_threads(),
                          "memory_after_imports": memory_snapshot()}
    check = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    receipt["pip_check"] = {"exit_code": check.returncode, "stdout": check.stdout, "stderr": check.stderr}
    check.check_returncode()
    (args.output_directory / "pip-freeze.txt").write_text(
        subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))

    receipt["stage"] = "source_and_weights"
    distribution = importlib.metadata.distribution("descript-audio-codec")
    direct = json.loads(distribution.read_text("direct_url.json"))
    if (direct["url"] != CODE_ARCHIVE or
            direct["archive_info"]["hashes"]["sha256"] != CODE_ARCHIVE_SHA256):
        raise RuntimeError("installed DAC archive provenance differs from the pinned commit")
    package_root = Path(dac.__file__).resolve().parent.parent
    installed_hashes = {name: digest(package_root / name) for name in SOURCE_HASHES}
    if installed_hashes != SOURCE_HASHES:
        raise RuntimeError("installed DAC model/quantizer/download source differs from the pin")
    if args.weights.stat().st_size != WEIGHT_BYTES or digest(args.weights) != WEIGHT_SHA256:
        raise RuntimeError("16 kHz release weights do not match the pinned size and SHA256")
    if digest(args.upstream_license) != LICENSE_SHA256:
        raise RuntimeError("upstream MIT license bytes do not match the pinned source")
    (args.output_directory / "LICENSE-MIT-Descript.txt").write_bytes(args.upstream_license.read_bytes())
    receipt["model_provenance"] = {
        "repository": "https://github.com/descriptinc/descript-audio-codec",
        "code_revision": CODE_REVISION, "code_archive_sha256": CODE_ARCHIVE_SHA256,
        "installed_source_sha256": installed_hashes, "weights_url": WEIGHT_URL,
        "weights_release": "0.0.5", "weights_asset_id": 115688008,
        "weights_bytes": WEIGHT_BYTES, "weights_sha256": WEIGHT_SHA256,
        "license": "MIT", "license_sha256": LICENSE_SHA256,
        "license_source": f"https://github.com/descriptinc/descript-audio-codec/blob/{CODE_REVISION}/LICENSE",
        "weight_license_statement": f"https://github.com/descriptinc/descript-audio-codec/blob/{CODE_REVISION}/README.md",
        "weight_license_statement_excerpt": "Weights are released as part of this repo under MIT license.",
        "paper": "https://arxiv.org/abs/2306.06546"}

    receipt["stage"] = "fixed_input_prefix"
    source = args.input_directory / "recorded-audio-16khz.wav"
    if digest(source) != INPUT_SHA256:
        raise RuntimeError("input audio differs from the recorded ingestion receipt")
    with wave.open(str(source), "rb") as stream:
        header = {"sample_rate": stream.getframerate(), "channels": stream.getnchannels(),
                  "sample_width_bytes": stream.getsampwidth(), "frames": stream.getnframes()}
        if (header["sample_rate"], header["channels"], header["sample_width_bytes"]) != (16000, 1, 2):
            raise ValueError("expected the recorded 16 kHz mono PCM16 derivative")
        pcm = stream.readframes(CLIP_SAMPLES)
    if len(pcm) != 2 * CLIP_SAMPLES:
        raise ValueError("input is shorter than the fixed two-second prefix")
    original = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    if not np.isfinite(original).all() or original.std() == 0:
        raise ValueError("input prefix is not finite nonconstant audio")
    write_pcm(args.output_directory / "input-first-two-seconds.wav", pcm, SAMPLE_RATE)
    attribution = json.loads((args.input_directory / "ATTRIBUTION.json").read_text())
    attribution["changes"] += ["fixed first 32000 samples of the 16 kHz mono derivative retained",
                               "frozen pretrained DAC encoding, integer-code dequantization and decoding",
                               "decoded audio rounded to PCM16 for the listening derivative"]
    (args.output_directory / "ATTRIBUTION.json").write_text(json.dumps(attribution, indent=2) + "\n")
    receipt["input"] = {"path": str(source), "sha256": INPUT_SHA256, "header": header,
                        "prefix_start_sample": 0, "prefix_samples": CLIP_SAMPLES,
                        "prefix_seconds": 2.0, "selection": "fixed prefix before reconstruction; no quality-based selection",
                        "shape": [1, 1, CLIP_SAMPLES], "dtype": "float32", "all_finite": True,
                        "rms": float(np.sqrt(np.mean(original.astype(np.float64) ** 2))),
                        "attribution": attribution}

    phases = receipt["phases"] = []

    def timed(name, operation):
        receipt["stage"] = name
        start, cpu = time.perf_counter(), time.process_time()
        value = operation()
        phases.append({"stage": name, "wall_seconds": time.perf_counter() - start,
                       "process_cpu_seconds": time.process_time() - cpu, **memory_snapshot()})
        return value

    model = timed("load_pretrained_model", lambda: dac.DAC.load(str(args.weights), strict=True))
    model = model.to("cpu").eval().requires_grad_(False)
    if model.sample_rate != SAMPLE_RATE or any(p.device.type != "cpu" for p in model.parameters()):
        raise RuntimeError("loaded model is not the requested CPU 16 kHz codec")
    receipt["scope"]["pretrained_codec_loaded"] = True
    receipt["model"] = {"sample_rate": model.sample_rate, "hop_length": int(model.hop_length),
                        "encoder_rates": model.encoder_rates, "decoder_rates": model.decoder_rates,
                        "n_codebooks": model.n_codebooks, "codebook_size": model.codebook_size,
                        "latent_dim": model.latent_dim, "parameters": sum(p.numel() for p in model.parameters()),
                        "parameter_bytes": sum(p.numel() * p.element_size() for p in model.parameters()),
                        "training": model.training, "all_parameters_frozen": not any(p.requires_grad for p in model.parameters()),
                        "state_dict_load_strict": True}
    with torch.inference_mode():
        x = torch.from_numpy(original.copy()).reshape(1, 1, CLIP_SAMPLES)
        # The 16 kHz decoder has an odd stride: its padded transposed-convolution
        # path loses eight samples. One fixed zero hop supplies boundary context.
        guard_samples = int(model.hop_length)
        x_padded = torch.nn.functional.pad(model.preprocess(x, SAMPLE_RATE), (0, guard_samples))
        z, codes, latents, _, _ = timed("encode_and_quantize", lambda: model.encode(x_padded))
        receipt["scope"]["neural_encoding_completed"] = True
        z_codes, _, returned_codes = timed("reconstruct_latent_from_integer_codes", lambda: model.quantizer.from_codes(codes))
        code_latent_error = float(torch.max(torch.abs(z_codes - z)))
        if not torch.equal(codes, returned_codes) or code_latent_error > 1e-5:
            raise AssertionError("integer-code roundtrip differs from the quantized encoding")
        decoded = timed("decode_from_integer_code_latent", lambda: model.decode(z_codes))
        receipt["scope"]["neural_decoding_completed"] = True
        receipt["decoded_shape_before_length_check"] = list(decoded.shape)
        if decoded.shape[-1] < CLIP_SAMPLES:
            raise AssertionError("decoded waveform is shorter than the input")
        reconstructed = decoded[0, 0, :CLIP_SAMPLES].numpy().copy()
        arrays = {"discrete_codes": codes.numpy(), "quantized_latent": z_codes.numpy(),
                  "reconstructed_audio": reconstructed.reshape(1, 1, -1)}
        receipt["tensors"] = {name: {"shape": list(array.shape), "dtype": str(array.dtype),
                                    "all_finite": bool(np.isfinite(array).all()),
                                    "min": float(array.min()), "max": float(array.max())}
                              for name, array in arrays.items()}
        if not all(row["all_finite"] for row in receipt["tensors"].values()):
            raise AssertionError("nonfinite codec output")
        if int(codes.min()) < 0 or int(codes.max()) >= model.codebook_size:
            raise AssertionError("discrete code index exceeds the codebook")
        receipt["codec_path"] = {"padded_input_shape": list(x_padded.shape),
                                 "untrimmed_output_shape": list(decoded.shape),
                                 "fixed_right_zero_guard_samples": guard_samples,
                                 "retained_samples": CLIP_SAMPLES,
                                 "quantized_latent_max_abs_code_roundtrip_error": code_latent_error,
                                 "decoder_input": "latent reconstructed solely from integer codes and frozen codebooks",
                                 "projected_encoder_latent_shape": list(latents.shape)}
        np.save(args.output_directory / "discrete-codes.npy", codes.numpy(), allow_pickle=False)
        np.save(args.output_directory / "reconstructed-float32.npy", reconstructed, allow_pickle=False)

    error = reconstructed.astype(np.float64) - original.astype(np.float64)
    mse, signal_power = float(np.mean(error ** 2)), float(np.mean(original.astype(np.float64) ** 2))
    receipt["reconstruction_metrics"] = {
        "alignment": "same sample indices after one fixed right zero hop and truncation; no shift or gain fitting",
        "sample_count": CLIP_SAMPLES, "mse": mse, "rmse": math.sqrt(mse),
        "signal_power": signal_power, "snr_db": 10 * math.log10(signal_power / mse) if mse > 0 else None,
        "snr_definition": "10 log10(mean(input^2) / mean((output-input)^2))",
        "exact_reconstruction": mse == 0, "perceptual_or_task_quality_established": False}
    clipped = np.clip(reconstructed, -1, 1)
    export_pcm = np.rint(clipped * 32767).astype("<i2").tobytes()
    write_pcm(args.output_directory / "dac-reconstructed-first-two-seconds.wav", export_pcm, SAMPLE_RATE)
    receipt["export"] = {"sample_rate": SAMPLE_RATE, "channels": 1, "sample_width_bytes": 2,
                         "sample_count": CLIP_SAMPLES, "clipped_samples": int(np.sum(clipped != reconstructed)),
                         "metrics_use_float_output_before_PCM16_rounding": True}
    receipt["artifacts"] = {path.name: {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}
                            for path in sorted(args.output_directory.iterdir()) if path.is_file()}
    receipt["status"] = "completed_frozen_pretrained_codec_reconstruction_only"
    receipt["scope"]["pretrained_codec_reconstruction"] = True
    receipt["stage"] = "complete"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-directory", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--upstream-license", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.receipt.exists() or args.output_directory.exists():
        parser.error("use new receipt and output paths; prior attempts are preserved")
    if not 1 <= args.threads <= 8:
        parser.error("threads must be between 1 and 8")
    args.output_directory.mkdir(parents=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    start, cpu = time.perf_counter(), time.process_time()
    receipt = {"schema": "hepta.natural-audio-pretrained-codec-smoke.v1", "status": "running",
               "started_at_utc": datetime.now(timezone.utc).isoformat(),
               "script_sha256": digest(__file__), "command": sys.argv,
               "initial_memory": memory_snapshot(),
               "scope": {"real_recorded_audio": True, "pretrained_codec_reconstruction": False,
                         "pretrained_codec_loaded": False, "neural_encoding_completed": False,
                         "neural_decoding_completed": False,
                         "target_blind_generation": False, "ndu_controller_invoked": False,
                         "training_performed": False, "generalization_established": False,
                         "natural_foundation_model_blocker_closed": False,
                         "formal_v3_source_or_protocol_changed": False}}
    status = 0
    with warnings.catch_warnings(record=True) as observed_warnings:
        warnings.simplefilter("always")
        try:
            execute(args, receipt)
        except Exception:
            receipt.update(status="failed", traceback=traceback.format_exc())
            status = 1
        warning_counts = {}
        for row in observed_warnings:
            key = (row.category.__name__, str(row.message), row.filename, row.lineno)
            warning_counts[key] = warning_counts.get(key, 0) + 1
        receipt["warnings"] = [{"category": key[0], "message": key[1], "filename": key[2],
                                "line": key[3], "count": count}
                               for key, count in warning_counts.items()]
    receipt.update(completed_at_utc=datetime.now(timezone.utc).isoformat(),
                   total_wall_seconds=time.perf_counter() - start,
                   total_process_cpu_seconds=time.process_time() - cpu, final_memory=memory_snapshot(),
                   memory_scope="whole-process RSS/high-water mark; includes imports, weights and native tensor allocations",
                   timing_scope="one local CPU run, no warmup/repeats; excludes dependency installation and prior weight download")
    with args.receipt.open("x") as output:
        json.dump(receipt, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    (args.output_directory / "audio-codec-receipt.json").write_text(args.receipt.read_text())
    print(json.dumps({"status": receipt["status"], "stage": receipt["stage"],
                      "receipt": str(args.receipt), "wall_seconds": receipt["total_wall_seconds"]}), flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
