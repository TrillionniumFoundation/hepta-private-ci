#!/usr/bin/env python3
"""Audit preserved attempts and probe the pinned codec's boundary on zero input."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time
import warnings
import wave

import numpy as np
import torch
import dac


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--input-directory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        parser.error("verification receipts are immutable; choose a new path")
    started = time.perf_counter()
    evidence = Path(__file__).resolve().parent
    source = evidence.parent / "audio_codec_smoke.py"
    spec = importlib.util.spec_from_file_location("codec_interface", source)
    interface = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(interface)
    attempts = {}
    receipts = {}
    for number in ("001", "002", "003"):
        receipt_path = evidence / f"audio-codec-{number}.json"
        receipt = receipts[number] = json.loads(receipt_path.read_text())
        snapshot = evidence / f"audio-codec-{number}-source.py"
        assert digest(snapshot) == receipt["script_sha256"]
        attempts[number] = {"receipt_sha256": digest(receipt_path),
                            "script_sha256": digest(snapshot), "status": receipt["status"]}
        for row in receipt.get("artifacts", {}).values():
            artifact = Path(row["path"])
            assert artifact.stat().st_size == row["bytes"]
            assert digest(artifact) == row["sha256"]
    assert receipts["001"]["status"] == "failed"
    assert digest(source) == receipts["003"]["script_sha256"]
    assert receipts["003"]["loading"]["torch_load_weights_only"] is True
    assert not any("weights_only=False" in row["message"] for row in receipts["003"]["warnings"])

    parity = {}
    for name, row in receipts["002"]["artifacts"].items():
        parity[name] = row["sha256"] == receipts["003"]["artifacts"][name]["sha256"]
    assert all(parity.values()), parity
    with wave.open(str(args.input_directory / "recorded-audio-16khz.wav"), "rb") as stream:
        original = np.frombuffer(stream.readframes(32000), dtype="<i2").astype(np.float64) / 32768
    reconstructed = np.load(args.run_root / "reconstruction-003" / "reconstructed-float32.npy",
                            allow_pickle=False).astype(np.float64)
    codes = np.load(args.run_root / "reconstruction-003" / "discrete-codes.npy", allow_pickle=False)
    assert reconstructed.shape == (32000,) and np.isfinite(reconstructed).all()
    assert codes.shape == (1, 12, 101) and codes.dtype == np.int64
    assert 0 <= codes.min() <= codes.max() < 1024
    mse = float(np.dot(reconstructed - original, reconstructed - original) / len(original))
    signal_power = float(np.dot(original, original) / len(original))
    snr = 10 * math.log10(signal_power / mse)
    metrics = receipts["003"]["reconstruction_metrics"]
    assert math.isclose(mse, metrics["mse"], rel_tol=1e-12)
    assert math.isclose(snr, metrics["snr_db"], rel_tol=1e-12)
    wav_headers = {}
    for name in ("input-first-two-seconds.wav", "dac-reconstructed-first-two-seconds.wav"):
        with wave.open(str(args.run_root / "reconstruction-003" / name), "rb") as stream:
            header = [stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes()]
        assert header == [1, 2, 16000, 32000]
        wav_headers[name] = header

    weights = args.run_root / "weights-16khz-0.0.5.pth"
    assert digest(weights) == interface.WEIGHT_SHA256
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    probe_started = time.perf_counter()
    with warnings.catch_warnings(record=True) as seen, torch.inference_mode():
        warnings.simplefilter("always")
        model, loading = interface.load_pinned_codec(weights, dac, torch)
        model = model.eval().requires_grad_(False)
        zero_input = torch.zeros(1, 1, 32000)
        upstream_preprocessed_shape = list(model.preprocess(zero_input, 16000).shape)
        output = model(zero_input, sample_rate=16000)
        raw_shape = list(output["audio"].shape)
        code_shape = list(output["codes"].shape)
        assert raw_shape == [1, 1, 31992] and code_shape == [1, 12, 100]
        assert torch.isfinite(output["audio"]).all()
        length = code_shape[-1]
        length_formula = []
        for layer in model.decoder.modules():
            if isinstance(layer, torch.nn.ConvTranspose1d):
                before = length
                stride, padding = layer.stride[0], layer.padding[0]
                kernel, dilation, extra = layer.kernel_size[0], layer.dilation[0], layer.output_padding[0]
                length = (length - 1) * stride - 2 * padding + dilation * (kernel - 1) + extra + 1
                length_formula.append({"input": before, "stride": stride, "padding": padding,
                                       "kernel": kernel, "dilation": dilation, "output_padding": extra,
                                       "output": length})
        assert length == raw_shape[-1]
    result = {
        "schema": "hepta.natural-audio-codec-independent-verification.v1", "status": "passed",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(), "script_sha256": digest(__file__),
        "attempts": attempts, "all_attempt_artifact_hashes_verified": True,
        "attempt_002_vs_003_artifacts_bitwise_equal": parity,
        "independent_metrics": {"mse": mse, "snr_db": snr, "signal_power": signal_power},
        "wav_headers_channels_width_rate_frames": wav_headers,
        "boundary_probe": {
            "input": "32000 literal zeros; no real audio or reference target used",
            "upstream_preprocessed_shape": upstream_preprocessed_shape,
            "upstream_forward_returned_audio_shape": raw_shape, "code_shape": code_shape,
            "transposed_convolution_length_formula_steps": length_formula,
            "original_attempt_001_output_length_recorded_in_001_receipt": False,
            "explanation": "This separate upstream forward probe measures the shape that the original length guard rejected; it does not edit the failed receipt.",
            "successful_adapter_right_zero_pad": 320, "successful_adapter_right_crop": 312,
            "successful_adapter_left_crop": 0, "target_dependent_alignment_or_gain_search": False,
            "compress_decompress_loudness_or_chunk_pipeline_used": False,
            "wall_seconds_including_load": time.perf_counter() - probe_started,
            "loading": loading, "warning_categories": sorted({row.category.__name__ for row in seen})},
        "scope": "loading/shape/artifact/metric verification only; no quality tuning or target-blind generation",
        "total_wall_seconds": time.perf_counter() - started,
    }
    args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "receipt": str(args.receipt),
                      "original_upstream_output_shape": raw_shape, "mse": mse, "snr_db": snr}))


if __name__ == "__main__":
    main()
