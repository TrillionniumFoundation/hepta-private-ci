"""Pinned pretrained TAESD roundtrip on recorded media; no conditional generation.

The upstream source and weights are hash checked before import/load. Run with the
receipt from ingest.py. Binary weights, latents and reconstructions stay outside
git; the optional evidence JSON contains only measurements and provenance.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import resource
import subprocess
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version
import torch


COMMIT = "fdbae2df989db95761f482efb8977e1182fb68d2"
REPOSITORY = "https://github.com/madebyollin/taesd"
ASSETS = {
    "taesd.py": (10719, "5943493eb291f768e0a87dd9b54c60461d3be0a9141003db7f62bd6b8e9efa6f"),
    "LICENSE": (1073, "261497cf8e9ed613ed1fa5ddf48af32cdf50545b2ccd9edd7eacc91fb9255d6e"),
    "README.md": (8973, "3e4df28e304aaae5d87a25282a78ce6f662c6dfbd5605e667294f8cf24481e22"),
    "taesd_encoder.pth": (4912826, "15bc6128f0ac51c673d3427216082ebfa62402ffc89763af74edfe259b32d49d"),
    "taesd_decoder.pth": (4913399, "02873377c3f4659cd9f9adb2f718dcb434ba4c7bba3af3ee7bb95cbdabe2d3cf"),
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_assets(directory):
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, (size, expected) in ASSETS.items():
        path = directory / name
        url = f"https://raw.githubusercontent.com/madebyollin/taesd/{COMMIT}/{name}"
        if not path.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "HEPTA-natural-codec-smoke/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(size + 1)
            if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"upstream asset integrity failure: {name}")
            path.write_bytes(data)
        if path.stat().st_size != size or sha256(path) != expected:
            raise ValueError(f"local asset integrity failure: {name}")
        manifest[name] = {"url": url, "path": str(path), "bytes": size, "sha256": expected}
    return manifest


def tensor_stats(value):
    if not value.numel() or not torch.isfinite(value).all():
        raise ValueError("empty or nonfinite model tensor")
    return {"shape": list(value.shape), "dtype": str(value.dtype), "all_finite": True,
            "min": value.min().item(), "max": value.max().item(),
            "mean": value.mean().item(), "std": value.std(unbiased=False).item()}


def errors(reference, reconstructed):
    mse = ((reference.double() - reconstructed.double()) ** 2).mean().item()
    return {"mse": mse, "psnr_db_peak_1": 10 * math.log10(1 / mse) if mse else None,
            "mae": (reference.double() - reconstructed.double()).abs().mean().item()}


def rgb_image(value):
    array = value.detach().clamp(0, 1).mul(255).round().to(torch.uint8).permute(1, 2, 0).numpy()
    return Image.fromarray(array)


class ConvWork:
    """Counts every executed Conv2d; excludes elementwise/resize/memory operations."""

    def __init__(self, model):
        self.rows = []
        self.handles = [module.register_forward_hook(self.hook)
                        for module in model.modules() if isinstance(module, torch.nn.Conv2d)]

    def hook(self, module, arguments, output):
        products = module.in_channels // module.groups * math.prod(module.kernel_size)
        self.rows.append({"macs": output.numel() * products,
                          "bias_adds": output.numel() if module.bias is not None else 0})

    def since(self, start):
        selected = self.rows[start:]
        return {"conv2d_calls": len(selected), "conv2d_macs": sum(row["macs"] for row in selected),
                "conv2d_bias_adds": sum(row["bias_adds"] for row in selected)}


def measured_forward(function, value, work):
    start = len(work.rows)
    wall, cpu = time.perf_counter(), time.process_time()
    result = function(value)
    duration = {"wall_seconds": time.perf_counter() - wall,
                "process_cpu_seconds": time.process_time() - cpu}
    return result, {**duration, **work.since(start)}


def main(assets_directory, input_receipt, output_directory, receipt_path=None):
    wall, cpu = time.perf_counter(), time.process_time()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "codec-receipt.json"
    if any(output.iterdir()):
        raise FileExistsError("use an empty output directory to preserve earlier evidence")
    if receipt_path is not None and Path(receipt_path).exists():
        raise FileExistsError("evidence receipts are never overwritten")
    input_path = Path(input_receipt).resolve()
    ingestion = json.loads(input_path.read_text())
    if ingestion["status"] != "passed_input_ingestion_only":
        raise ValueError("expected a completed, independently recorded ingestion receipt")
    # Bind actual model inputs to the prior verified natural recording.
    for name in ("original.webm", "input-tensors.npz"):
        artifact = ingestion["artifacts"][name]
        path = Path(artifact["path"])
        if path.stat().st_size != artifact["bytes"] or sha256(path) != artifact["sha256"]:
            raise ValueError(f"input artifact differs from ingestion: {name}")
    with np.load(ingestion["artifacts"]["input-tensors.npz"]["path"], allow_pickle=False) as arrays:
        image = torch.from_numpy(arrays["image"].copy()).unsqueeze(0)
        video = torch.from_numpy(arrays["video"].copy())
    if image.shape != (1, 3, 144, 256) or video.shape != (4, 3, 72, 128):
        raise ValueError("unexpected dimensions for the fixed natural fixture")
    for value in (image, video):
        tensor_stats(value)
        if value.dtype != torch.float32 or value.min() < 0 or value.max() > 1:
            raise ValueError("TAESD requires finite float32 RGB in [0,1]")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    assets_directory = Path(assets_directory).resolve()
    manifest = prepare_assets(assets_directory)
    spec = importlib.util.spec_from_file_location("hepta_pinned_taesd", assets_directory / "taesd.py")
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    load_wall, load_cpu = time.perf_counter(), time.process_time()
    model = upstream.TAESD(encoder_path=None, decoder_path=None, latent_channels=4, image_channels=3)
    for side in ("encoder", "decoder"):
        state = torch.load(assets_directory / f"taesd_{side}.pth", map_location="cpu", weights_only=True)
        if not all(isinstance(value, torch.Tensor) and torch.isfinite(value).all() for value in state.values()):
            raise ValueError("nonfinite or non-tensor pretrained state")
        getattr(model, side).load_state_dict(state, strict=True)
    model.eval().requires_grad_(False)
    loading = {"wall_seconds": time.perf_counter() - load_wall,
               "process_cpu_seconds": time.process_time() - load_cpu, "weights_only": True,
               "strict_state_dict": True,
               "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
               "encoder_parameters": sum(p.numel() for p in model.encoder.parameters()),
               "decoder_parameters": sum(p.numel() for p in model.decoder.parameters())}
    work = ConvWork(model)
    rows, latents, reconstructions = [], [], []
    inputs = [("image", image)] + [(f"video_frame_{index}", video[index:index + 1]) for index in range(4)]
    with torch.inference_mode():
        for name, value in inputs:
            latent, encoder_work = measured_forward(model.encoder, value, work)
            result, decoder_work = measured_forward(model.decoder, latent, work)
            if result.shape != value.shape or latent.shape != (1, 4, value.shape[-2] // 8, value.shape[-1] // 8):
                raise ValueError("codec shape contract failed")
            rows.append({"name": name, "input": tensor_stats(value), "latent": tensor_stats(latent),
                         "output_raw": tensor_stats(result), "raw_error": errors(value, result),
                         "clipped_error": errors(value, result.clamp(0, 1)),
                         "out_of_range_fraction": ((result < 0) | (result > 1)).float().mean().item(),
                         "encoder_work": encoder_work, "decoder_work": decoder_work})
            latents.append(latent)
            reconstructions.append(result)
    for handle in work.handles:
        handle.remove()
    reconstructed_image = reconstructions[0]
    reconstructed_video = torch.cat(reconstructions[1:])
    rgb_image(reconstructed_image[0]).save(output / "image-reconstructed.png")
    comparison = Image.new("RGB", (512, 168), "white")
    comparison.paste(rgb_image(image[0]), (0, 24))
    comparison.paste(rgb_image(reconstructed_image[0]), (256, 24))
    ImageDraw.Draw(comparison).text((4, 5), "Recorded input                   TAESD reconstruction", fill="black")
    comparison.save(output / "image-comparison.png")
    sheet = Image.new("RGB", (512, 192), "white")
    for index in range(4):
        rgb_image(reconstructed_video[index]).save(output / f"video-reconstructed-{index:02d}.png")
        sheet.paste(rgb_image(video[index]), (index * 128, 24))
        sheet.paste(rgb_image(reconstructed_video[index]), (index * 128, 120))
    draw = ImageDraw.Draw(sheet)
    draw.text((4, 5), "Four recorded frames from source seconds 1-5", fill="black")
    draw.text((4, 101), "TAESD per-frame reconstruction; no temporal model", fill="black")
    sheet.save(output / "video-comparison.png")
    command = ["ffmpeg", "-v", "error", "-nostdin", "-framerate", "1", "-i",
               str(output / "video-reconstructed-%02d.png"), "-frames:v", "4", "-c:v", "libvpx-vp9",
               "-threads", "1", "-lossless", "1", str(output / "video-reconstructed.webm")]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    np.savez_compressed(output / "codec-tensors.npz", image_latent=latents[0].numpy(),
                        video_latent=torch.cat(latents[1:]).numpy(), image_reconstruction=reconstructed_image.numpy(),
                        video_reconstruction=reconstructed_video.numpy())
    (output / "TAESD-LICENSE.txt").write_bytes((assets_directory / "LICENSE").read_bytes())
    attribution = {"source_media": ingestion["source"], "derivative_media_license": "CC-BY-SA-4.0",
                   "codec_code_and_weights": {"repository": REPOSITORY, "commit": COMMIT, "license": "MIT"},
                   "changes": ["frozen learned TAESD image codec roundtrip without latent quantization",
                               "independent codec roundtrip of four actual recorded video frames",
                               "PNG display clips RGB to [0,1] and rounds to 8-bit; comparison labels added"],
                   "no_endorsement_implied": True}
    (output / "ATTRIBUTION.json").write_text(json.dumps(attribution, indent=2) + "\n")
    report = {
        "schema": "hepta.natural-pretrained-codec-smoke.v1", "status": "passed_codec_interfaces_only",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_code_sha256": sha256(Path(__file__)), "input_receipt": str(input_path),
        "input_receipt_sha256": sha256(input_path), "source_media_sha256": ingestion["source_sha256"],
        "model": {"repository": REPOSITORY, "commit": COMMIT, "license": "MIT", "assets": manifest, **loading},
        "runtime": {"python": platform.python_version(), "platform": platform.platform(), "torch": torch.__version__,
                    "numpy": np.__version__, "pillow": pillow_version, "device": "cpu", "dtype": "float32",
                    "torch_threads": 1, "interop_threads": 1, "batch_size": 1, "warmup_forwards": 0},
        "roundtrips": rows, "total_forward_work": work.since(0),
        "cost_scope": "Actual Conv2d hook MACs and bias adds; activations, resize, residual adds and memory operations excluded. CPU/wall measures include them.",
        "video_aggregate": {"raw_error": errors(video, reconstructed_video),
                            "clipped_error": errors(video, reconstructed_video.clamp(0, 1)),
                            "input_mean_absolute_temporal_difference": (video[1:] - video[:-1]).abs().mean().item(),
                            "reconstruction_mean_absolute_temporal_difference": (reconstructed_video[1:] - reconstructed_video[:-1]).abs().mean().item()},
        "video_export_command": command,
        "artifacts": {path.name: {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
                      for path in sorted(output.iterdir()) if path.is_file()},
        "total_wall_seconds": time.perf_counter() - wall, "total_process_cpu_seconds": time.process_time() - cpu,
        "timing_scope": "Main function after Python/Torch imports, including asset checks, model load, all five measured roundtrips and artifact export; no unreported warmup. Each forward has separate CPU/wall timing.",
        "child_cpu_seconds": resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
        "peak_process_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "scope": {"pretrained_codec_loaded": True, "actual_natural_image_video_roundtrip": True,
                  "audio_or_text_codec_executed": False, "conditional_generation_performed": False,
                  "temporal_video_model": False, "semantic_understanding_evaluated": False,
                  "training_performed": False, "ndu_benefit_evaluated": False,
                  "natural_foundation_model_blocker_closed": False, "formal_v3_experiment_changed": False},
    }
    payload = json.dumps(report, indent=2, allow_nan=False) + "\n"
    report_path.write_text(payload)
    if receipt_path is not None:
        receipt = Path(receipt_path)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        with receipt.open("x") as handle:
            handle.write(payload)
    print(json.dumps({"status": report["status"], "receipt": str(report_path), "model_commit": COMMIT,
                      "image": rows[0]["clipped_error"], "video": report["video_aggregate"]["clipped_error"],
                      "total_wall_seconds": report["total_wall_seconds"], "total_forward_work": report["total_forward_work"]}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-directory", required=True)
    parser.add_argument("--input-receipt", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--receipt")
    arguments = parser.parse_args()
    main(arguments.assets_directory, arguments.input_receipt, arguments.output_directory, arguments.receipt)
