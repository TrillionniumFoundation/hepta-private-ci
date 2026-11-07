"""Bounded actual-generator smoke for an explicitly declared device/dtype pair.

Run under decision_audit.meter with a finite outer wall timeout. This executes
one short VLM description and a two-step tiny-SD image, not model training or a
semantic benchmark. Only an observed successful CUDA run can verify this profile.
"""

import argparse
import json
from pathlib import Path
import time
import uuid

from .dual_runtime import digest_file, write_json
from .local_models import LocalModels


def execute(models, image, output, source_sha, *, device="cpu", dtype="bfloat16", threads=2):
    import torch
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start = time.process_time(), time.perf_counter()
    backend = LocalModels(Path(models) / "vlm", Path(models) / "sd", threads, device=device, dtype=dtype)
    report = {"attempt_id": uuid.uuid4().hex, "source_sha": source_sha,
              "requested_device": device, "requested_dtype": dtype,
              "status": "started", "gpu_execution_verified": False,
              "semantic_acceptance": "not_evaluated", "training_performed": False,
              "stages": [], "unknown_costs": ["energy", "accelerator_charge", "acquisition", "outer_process_and_final_write"]}
    write_json(output / "DEVICE_SMOKE.json", report)
    try:
        report["input_image_sha256"] = digest_file(image)
        begin = time.process_time(), time.perf_counter()
        text = backend.describe(image, "Briefly identify visible objects in this picture.", max_tokens=8)
        backend.synchronize()
        text_path = output / "text.txt"; text_path.write_text(text + "\n")
        anchor = next(backend.model.parameters())
        if str(anchor.device) != backend.device or str(anchor.dtype).removeprefix("torch.") != dtype:
            raise ValueError("Actual VLM parameters differ from the declared placement")
        report["stages"].append({"name": "actual_vlm_forward", "status": "completed",
            "device": str(anchor.device), "dtype": str(anchor.dtype), "output_sha256": digest_file(text_path),
            "cpu_seconds": time.process_time() - begin[0], "wall_seconds": time.perf_counter() - begin[1]})
        begin = time.process_time(), time.perf_counter()
        image_result = backend.draw("A simple illustration of an object on a plain background.", output / "image.png", 17, steps=2)
        backend.synchronize()
        placements = {name: str(next(module.parameters()).device) for name, module in
                      (("unet", backend.pipeline.unet), ("vae", backend.pipeline.vae), ("text_encoder", backend.pipeline.text_encoder))}
        if (set(placements.values()) != {backend.device} or image_result["generator_device"] != backend.device
                or not 1 <= image_result["actual_steps"] <= 4):
            raise ValueError("Diffusion placement or observed denoising step count differs")
        report["stages"].append({"name": "actual_diffusion_forward", "status": "completed",
            "module_devices": placements, "generator_device": image_result["generator_device"], "result": image_result,
            "cpu_seconds": time.process_time() - begin[0], "wall_seconds": time.perf_counter() - begin[1]})
        report.update(status="completed", gpu_execution_verified=backend.device.startswith("cuda"))
    except (Exception, KeyboardInterrupt) as error:
        report.update(status="cancelled" if isinstance(error, KeyboardInterrupt) else "failed",
                      error={"type": type(error).__name__, "message": str(error)})
    finally:
        report.update(cpu_seconds=time.process_time() - start[0], wall_seconds=time.perf_counter() - start[1])
        try:
            report["backend"] = backend.identity()
            if backend.device.startswith("cuda") and torch.cuda.is_available():
                report["cuda_peak_allocated_bytes"] = torch.cuda.max_memory_allocated(backend.device)
                report["cuda_peak_reserved_bytes"] = torch.cuda.max_memory_reserved(backend.device)
        except Exception as error:
            report["final_identity_error"] = {"type": type(error).__name__, "message": str(error)}
            report.update(status="failed", gpu_execution_verified=False)
        write_json(output / "DEVICE_SMOKE.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("models", "image", "output", "source-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--dtype", default="bfloat16", choices=("bfloat16", "float16", "float32"))
    args = parser.parse_args()
    result = execute(args.models, args.image, args.output, args.source_sha, device=args.device, dtype=args.dtype)
    print(json.dumps({k: result[k] for k in ("status", "gpu_execution_verified", "attempt_id")}, allow_nan=False))
    raise SystemExit(0 if result["status"] == "completed" else 1)
