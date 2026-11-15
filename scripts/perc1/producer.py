"""Executed frozen MobileNet producer with retained, recomputable evidence.

Receipts are process observations, not independent attestation. The local producer
does not grant capture/admission authority or establish scientific qualification.
"""

import argparse
import base64
import copy
import io
import json
import os
import platform
import re
import time
from pathlib import Path

from .native import wire_bytes
from .projection import project
from .raster import export_native_raster
from .schema import digest, exact, integer, require, sha, string

CODE_SNAPSHOT = {
    name: sha(Path(__file__).with_name(name + ".py").read_bytes())
    for name in ("producer", "projection", "raster", "native", "schema")
}

PREPROCESS = {
    "decode": "Pillow.convert(RGB); EXIF orientation must be absent or 1",
    "resize": [224, 224],
    "interpolation": "Pillow.Resampling.BILINEAR",
    "scale": 255.0,
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
    "dtype": "float32",
    "layout": "NCHW",
    "pool": "mean spatial feature map",
}


def _read(path, limit):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    require(0 < len(raw) <= limit, "artifact byte limit exceeded")
    return raw


def _json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def invalid_constant(value):
        require(False, "nonfinite JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def _regions(regions, width, height, limit):
    require(type(regions) is list and 0 < len(regions) <= 64, "invalid region count")
    total, ids = 0, set()
    for region in regions:
        exact(region, "evidence_id x y width height")
        require(
            re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", string(region["evidence_id"]))
            and region["evidence_id"] not in ids,
            "invalid or duplicate region identity",
        )
        ids.add(region["evidence_id"])
        x, y = integer(region["x"]), integer(region["y"])
        rw, rh = integer(region["width"], 1), integer(region["height"], 1)
        require(x + rw <= width and y + rh <= height, "crop escapes original raster")
        total += rw * rh * 3
    require(total <= limit, "crop RGB byte limit exceeded")


class FrozenMobileNet:
    """Load a pinned state dict and execute a frozen MobileNetV3-small backbone."""

    def __init__(self, weights, expected_sha256, device="cpu"):
        started = time.perf_counter_ns()
        import numpy as np
        import PIL
        import torch
        import torchvision

        require(device in ("cpu", "cuda"), "unsupported worker device")
        require(
            device != "cuda" or torch.cuda.is_available(), "CUDA device unavailable"
        )
        raw = _read(weights, 64 * 1024 * 1024)
        require(sha(raw) == digest(expected_sha256), "weight file digest mismatch")
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        if device == "cuda":
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
        model = torchvision.models.mobilenet_v3_small(weights=None)
        model.load_state_dict(
            torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True),
            strict=True,
        )
        self.model = model.features.eval().requires_grad_(False).to(device)
        self.torch, self.np, self.device = torch, np, device
        self.weights_sha256, self.calls = expected_sha256, 0
        self.code = dict(CODE_SNAPSHOT)
        self.versions = {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "torchvision": torchvision.__version__,
            "pillow": PIL.__version__,
            "numpy": np.__version__,
        }
        self.device_name = (
            torch.cuda.get_device_name() if device == "cuda" else platform.machine()
        )
        self.cold_load_ns = time.perf_counter_ns() - started

    def features(self, raw_png_bytes, regions):
        """Decode one admitted capture and execute every requested crop in a batch."""
        from PIL import Image

        started = time.perf_counter_ns()
        require(
            all(
                sha(Path(__file__).with_name(name + ".py").read_bytes()) == pin
                for name, pin in self.code.items()
            ),
            "worker source changed; restart with frozen code",
        )
        require(
            type(raw_png_bytes) is bytes and 0 < len(raw_png_bytes) <= 4 * 1024 * 1024,
            "capture exceeds 4 MiB",
        )
        with Image.open(io.BytesIO(raw_png_bytes)) as encoded:
            require(
                encoded.format in ("PNG", "JPEG")
                and getattr(encoded, "n_frames", 1) == 1,
                "single-frame PNG/JPEG required",
            )
            require(
                encoded.getexif().get(274, 1) == 1,
                "EXIF rotation requires an explicit capture adapter",
            )
            width, height = encoded.size
            require(
                0 < width * height * 3 <= 64 * 1024 * 1024,
                "decoded raster exceeds 64 MiB",
            )
            image = encoded.convert("RGB")
        _regions(regions, width, height, 4 * 1024 * 1024)
        decode_ns = time.perf_counter_ns() - started
        tensors, receipts = [], []
        preprocess_start = time.perf_counter_ns()
        for region in regions:
            x, y, rw, rh = (region[key] for key in ("x", "y", "width", "height"))
            crop = image.crop((x, y, x + rw, y + rh))
            resized = crop.resize((224, 224), Image.Resampling.BILINEAR)
            value = self.np.asarray(resized, dtype=self.np.float32) / self.np.float32(
                255.0
            )
            value = (
                (
                    (value - self.np.asarray(PREPROCESS["mean"], dtype=self.np.float32))
                    / self.np.asarray(PREPROCESS["std"], dtype=self.np.float32)
                )
                .transpose(2, 0, 1)
                .copy()
            )
            tensors.append(self.torch.from_numpy(value))
            receipts.append(
                {
                    "region": dict(region),
                    "crop_rgb_sha256": sha(crop.tobytes()),
                    "crop_rgb_bytes": rw * rh * 3,
                    "tensor_f32le_sha256": sha(value.astype("<f4").tobytes()),
                }
            )
        batch = self.torch.stack(tensors).to(self.device)
        if self.device == "cuda":
            self.torch.cuda.synchronize()
        preprocessing_ns = time.perf_counter_ns() - preprocess_start
        inference_start = time.perf_counter_ns()
        with self.torch.inference_mode():
            features = self.model(batch).mean(dim=(2, 3)).cpu().numpy().copy()
        if self.device == "cuda":
            self.torch.cuda.synchronize()
        inference_ns = time.perf_counter_ns() - inference_start
        require(
            features.shape == (len(regions), 576) and self.np.isfinite(features).all(),
            "invalid backbone output",
        )
        self.calls += 1
        return (
            image,
            features,
            {
                "capture_sha256": sha(raw_png_bytes),
                "capture_bytes": len(raw_png_bytes),
                "raster_rgb_sha256": sha(image.tobytes()),
                "raster_shape": [height, width, 3],
                "preprocess": copy.deepcopy(PREPROCESS),
                "crops": receipts,
                "features_shape": list(features.shape),
                "features_f32le_sha256": sha(features.astype("<f4").tobytes()),
                "backbone_sha256": self.weights_sha256,
                "producer_code_sha256": sha(self.code),
                "decode_ns": decode_ns,
                "preprocessing_ns": preprocessing_ns,
                "inference_ns": inference_ns,
                "worker_call_index": self.calls,
                "device": self.device,
                "versions": dict(self.versions),
            },
        )


def produce(worker, request, projection):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    exact(
        request,
        "schema operation_id capture_path capture_sha256 source_id observed_at_micros regions representation scope_digest source_frontier exact_text",
    )
    require(
        request["schema"] == "perc1.producer-request.v1", "unknown producer request"
    )
    require(len(string(request["operation_id"])) <= 256, "operation identity too long")
    require(request["representation"] in ("global", "dense"), "invalid representation")
    require(
        re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", string(request["source_id"])),
        "invalid source identity",
    )
    integer(request["observed_at_micros"], 1)
    for name in ("capture_sha256", "scope_digest", "source_frontier"):
        require(digest(request[name]) != "0" * 64, "empty source/model binding")
    # Reject unbounded native crops before any model execution, including on failure.
    _regions(request["regions"], 2**32 - 1, 2**32 - 1, 8192)
    capture_start = time.perf_counter_ns()
    raw = _read(request["capture_path"], 4 * 1024 * 1024)
    require(sha(raw) == digest(request["capture_sha256"]), "capture digest mismatch")
    capture_ns = time.perf_counter_ns() - capture_start
    text = None
    if request["exact_text"] is not None:
        item = exact(request["exact_text"], "kind path sha256 capture_sha256 engine")
        require(
            item["kind"] in ("source_text", "dom", "ocr"), "unknown exact text kind"
        )
        require(
            item["capture_sha256"] == request["capture_sha256"],
            "text/capture binding mismatch",
        )
        string(item["engine"])
        text_raw = _read(item["path"], 8192)
        require(
            len(text_raw) <= 8192 and sha(text_raw) == digest(item["sha256"]),
            "exact text digest mismatch",
        )
        text = {
            **item,
            "text": text_raw.decode("utf-8", errors="strict"),
            "raw_base64": base64.b64encode(text_raw).decode(),
            "fidelity": "ocr_transcription_unverified"
            if item["kind"] == "ocr"
            else "source_bytes_preserved",
            "origin_authenticated": False,
        }
    image, features, transform = worker.features(raw, request["regions"])
    projection_start = time.perf_counter_ns()
    projected = project(
        features.mean(axis=0, keepdims=True)
        if request["representation"] == "global"
        else features,
        projection,
        worker.weights_sha256,
    )
    projection_ns = time.perf_counter_ns() - projection_start
    code = {
        name: sha(Path(__file__).with_name(name + ".py").read_bytes())
        for name in worker.code
    }
    require(code == worker.code, "worker source changed during inference")
    model = {
        "architecture": "torchvision.mobilenet_v3_small.features",
        "backbone_sha256": worker.weights_sha256,
        "projection_sha256": sha(projection),
        "producer_code_sha256": sha(code),
    }
    encoder = {
        "model": model,
        "preprocess": copy.deepcopy(PREPROCESS),
        "representation": request["representation"],
        "dimension": projection["dimension"],
        "global_pool": "mean crop features before projection",
    }
    observation = export_native_raster(
        image.tobytes(),
        width=image.width,
        height=image.height,
        source_id=request["source_id"],
        origin_sha256=request["capture_sha256"],
        raster_sha256=transform["raster_rgb_sha256"],
        observed_at_micros=request["observed_at_micros"],
        regions=request["regions"],
        tokens=projected.tolist(),
        representation=request["representation"],
        scope_digest=request["scope_digest"],
        source_frontier=request["source_frontier"],
        encoder_digest=sha(encoder),
        latent_model_digest=sha(model),
    )
    result = {
        "schema": "perc1.producer-receipt.v1",
        "status": "executed",
        "scientific_status": "HOLD",
        "trust": "local worker execution and recomputable bytes; not independent attestation",
        "operation_id": request["operation_id"],
        "request_sha256": sha(request),
        "observation": observation,
        "observation_sha256": sha(wire_bytes(observation)),
        "exact_text": text,
        "transform": transform,
        "model": model,
        "encoder": encoder,
        "worker": {
            "pid": os.getpid(),
            "device": worker.device,
            "device_name": worker.device_name,
            "versions": dict(worker.versions),
            "code": code,
            "cold_load_ns": worker.cold_load_ns,
        },
        "measurements": {
            "capture_read_ns": capture_ns,
            "projection_ns": projection_ns,
            "wall_ns": time.perf_counter_ns() - started,
            "cpu_ns": time.process_time_ns() - cpu,
            "energy_joules": None,
            "provider_billing": None,
        },
    }
    result["receipt_sha256"] = sha(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "request",
        "weights",
        "weights-sha256",
        "projection",
        "projection-sha256",
        "output",
    ):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    require(
        not Path(args.output).exists(), "output already exists; retain original receipt"
    )
    request_raw = _read(args.request, 65536)
    projection_raw = _read(args.projection, 8 * 1024 * 1024)
    require(
        sha(projection_raw) == digest(args.projection_sha256),
        "projection file digest mismatch",
    )
    request, projection = _json(request_raw), _json(projection_raw)
    worker = FrozenMobileNet(args.weights, args.weights_sha256, args.device)
    result = produce(worker, request, projection)
    with Path(args.output).open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")


if __name__ == "__main__":
    main()
