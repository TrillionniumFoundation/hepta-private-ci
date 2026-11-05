"""Single-image denoising adapter wiring; no controller or efficacy evidence.

The verified frozen tiny-SD backbone runs on every update. A separate FP32
rank residual on conv_out preserves its output dtype, including at inference.
Full hashing, latent preparation, checkpoint reload and probes are charged.
Budgets are checked at boundaries, including after final report writes.
"""

import argparse
import gc
import hashlib
import json
import math
from pathlib import Path
import re
import resource
import sys
import time

import torch
from torch import nn
from torch.nn import functional as F

from .dual_runtime import digest_file, write_json
from .local_models import LocalModels
from .train_adapter import fingerprint, parameter_hashes


SCHEMA = "hepta.real-image-conv-adapter.v1"


def tensor_identity(value):
    value = value.detach().cpu().contiguous()
    return {"shape": list(value.shape), "dtype": str(value.dtype),
            "sha256": hashlib.sha256(memoryview(value.view(torch.uint8).reshape(-1).numpy())).hexdigest()}


class ImageOutputAdapter(nn.Module):
    """Low-rank spatial 1x1 residual; not an approximation of a full 3x3 LoRA."""

    def __init__(self, width, channels, rank=4, seed=17):
        super().__init__()
        if type(rank) is not int or not 1 <= rank <= 32:
            raise ValueError("Rank must be an integer in [1,32]")
        self.config = {"width": width, "channels": channels, "rank": rank, "seed": seed}
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.down = nn.Conv2d(width, rank, 1, bias=False, dtype=torch.float32)
            self.up = nn.Conv2d(rank, channels, 1, bias=False, dtype=torch.float32)
            nn.init.normal_(self.down.weight, std=0.02); nn.init.zeros_(self.up.weight)

    def forward(self, hidden):
        return self.up(self.down(hidden.detach().float())) / self.config["rank"]

    def attach(self, unet):
        if any(p.requires_grad or p.device.type != "cpu" for p in unet.parameters()):
            raise ValueError("The complete CPU UNet must be frozen")
        head = unet.conv_out
        if (not isinstance(head, nn.Conv2d) or head.in_channels != self.config["width"]
                or head.out_channels != self.config["channels"] or head.stride != (1, 1)
                or head.dilation != (1, 1) or any(2*p != k-1 for p, k in zip(head.padding, head.kernel_size))):
            raise ValueError("conv_out shape is incompatible with a same-grid residual")
        if any(getattr(h, "hepta_image_adapter", False) for h in head._forward_hooks.values()):
            raise ValueError("An image adapter is already attached")

        def hook(module, inputs, output):
            return output + self(inputs[0]).to(output.dtype)

        hook.hepta_image_adapter = True
        return head.register_forward_hook(hook)


def save_image_adapter(adapter, path, base_hash, metadata):
    from safetensors.torch import save_file
    config = {**metadata, "schema": SCHEMA, "base_parameter_sha256": base_hash, **adapter.config}
    save_file(adapter.state_dict(), str(path), metadata={"hepta": json.dumps(config, sort_keys=True)})
    return digest_file(path)


def load_image_adapter(unet, path, expected_sha256):
    """Hash-check the checkpoint and exact UNet; return a removable inference hook."""
    from safetensors import safe_open
    from safetensors.torch import load_file
    if digest_file(path) != expected_sha256:
        raise ValueError("Image adapter checkpoint digest mismatch")
    with safe_open(str(path), framework="pt", device="cpu") as reader:
        config = json.loads(reader.metadata()["hepta"])
    if config["schema"] != SCHEMA or config["base_parameter_sha256"] != fingerprint(parameter_hashes(unet)):
        raise ValueError("Image adapter belongs to a different UNet")
    adapter = ImageOutputAdapter(**{k: config[k] for k in ("width", "channels", "rank", "seed")})
    adapter.load_state_dict(load_file(str(path)), strict=True)
    if any(not bool(torch.isfinite(p).all()) for p in adapter.parameters()):
        raise ValueError("Nonfinite image adapter checkpoint")
    adapter.eval().requires_grad_(False)
    return adapter, adapter.attach(unet)


def read_example(manifest, expected_sha256):
    path = Path(manifest)
    if digest_file(path) != expected_sha256:
        raise ValueError("Training manifest digest mismatch")
    data = json.loads(path.read_text())
    if (data.get("schema") != "hepta.real-image-adapter-training-data.v1"
            or data.get("role") != "training_only" or len(data.get("examples", [])) != 1):
        raise ValueError("Exactly one declared training-only image is required")
    row = data["examples"][0]
    if any(not isinstance(row[k], str) or not 1 <= len(row[k]) <= 4096
           for k in ("source_id", "prompt", "target_provenance")):
        raise ValueError("Source, prompt and target provenance must be explicit")
    image = (path.parent / row["image_path"]).resolve()
    if digest_file(image) != row["image_sha256"]:
        raise ValueError("Training image differs from its immutable manifest")
    return {**row, "image_path": str(image)}


def prepare_pair(pipeline, row, generator):
    from PIL import Image, ImageOps
    import numpy as np
    if digest_file(row["image_path"]) != row["image_sha256"]:
        raise ValueError("Training image changed after admission")
    limit = min(pipeline.tokenizer.model_max_length, pipeline.text_encoder.config.max_position_embeddings)
    ids = pipeline.tokenizer(row["prompt"], truncation=False)["input_ids"]
    if len(ids) > limit:
        raise ValueError("Prompt exceeds CLIP context; truncation is forbidden")
    tokens = pipeline.tokenizer(row["prompt"], padding="max_length", max_length=limit,
                                truncation=False, return_tensors="pt")
    with Image.open(row["image_path"]) as raw:
        if raw.width * raw.height > 16_000_000:
            raise ValueError("Training image exceeds the pixel bound")
        image = ImageOps.fit(raw.convert("RGB"), (256, 256), method=Image.Resampling.LANCZOS)
    pixels = torch.from_numpy(np.asarray(image, dtype=np.float32).copy()).permute(2, 0, 1)[None] / 127.5 - 1
    pixels = pixels.to(next(pipeline.vae.parameters()).dtype)
    with torch.no_grad():
        latents = pipeline.vae.encode(pixels).latent_dist.sample(generator=generator)
        latents = latents * pipeline.vae.config.scaling_factor
        mask = tokens["attention_mask"] if getattr(pipeline.text_encoder.config, "use_attention_mask", False) else None
        embeddings = pipeline.text_encoder(tokens["input_ids"], attention_mask=mask)[0]
    dtype = next(pipeline.unet.parameters()).dtype
    latents, embeddings = latents.to(dtype), embeddings.to(dtype)
    return latents, embeddings, {"pixels": tensor_identity(pixels), "latents": tensor_identity(latents),
                                "clip_embeddings": tensor_identity(embeddings), "prompt_tokens": len(ids),
                                "preprocessing": "RGB_center_fit_256_LANCZOS_then_minus1_to1",
                                "frozen_vae_clip_cache": "constructed_once_and_charged_this_run"}


def denoising_target(scheduler, latents, noise, timesteps):
    prediction = scheduler.config.prediction_type
    if prediction == "epsilon":
        return noise
    if prediction == "v_prediction":
        return scheduler.get_velocity(latents, noise, timesteps)
    if prediction == "sample":
        return latents
    raise ValueError(f"Unsupported prediction_type: {prediction}")


def train(models, manifest, output, source_sha, manifest_sha256, *, seed=17, rank=4,
          steps=2, learning_rate=0.001, threads=2, cpu_budget=600.0, wall_budget=600.0):
    started = previous = (time.process_time(), time.perf_counter())
    out = Path(output); out.mkdir(parents=True, exist_ok=False)
    events, updates, before, after, adapter_before, initial_adapter_parameters = [], [], {}, {}, {}, {}
    backend = adapter = handle = row = checkpoint = scheduler = None
    status, error, probe, prepared, initial_hash = "failed", None, {}, {}, None
    forward_attempts = forward_completed = 0
    requested = {"seed": seed, "rank": rank, "steps": steps, "threads": threads,
                 "learning_rate": learning_rate, "cpu_budget": cpu_budget, "wall_budget": wall_budget}
    requested = {key: repr(value) if isinstance(value, float) and not math.isfinite(value) else value
                 for key, value in requested.items()}

    def record(kind, detail=None):
        nonlocal previous
        now = time.process_time(), time.perf_counter()
        event = {"id": len(events), "kind": kind, "cpu_seconds": now[0]-previous[0],
                 "wall_seconds": now[1]-previous[1], "detail": detail}
        events.append(event); previous = now
        with (out / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(event, allow_nan=False) + "\n")

    def budget():
        if time.process_time()-started[0] > cpu_budget or time.perf_counter()-started[1] > wall_budget:
            raise TimeoutError("Image training allowance exceeded at an operation boundary")

    def fail(stage, exc):
        nonlocal status, error
        status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "timeout" if isinstance(exc, TimeoutError) else "failed"
        error = {"type": type(exc).__name__, "message": str(exc)}; record(stage, error)

    def base_hashes():
        return {f"{key}.{name}": sha for key in ("unet", "vae", "text_encoder")
                for name, sha in parameter_hashes(getattr(backend.pipeline, key)).items()}

    def forward(noisy, timestep, embeddings):
        nonlocal forward_attempts, forward_completed
        forward_attempts += 1
        result = backend.pipeline.unet(noisy, timestep, encoder_hidden_states=embeddings).sample
        forward_completed += 1
        return result

    try:
        if (not re.fullmatch(r"[0-9a-f]{40}", source_sha) or type(seed) is not int or not 0 <= seed < 2**63
                or type(steps) is not int or not 1 <= steps <= 64
                or any(not math.isfinite(x) or x <= 0 for x in (learning_rate, cpu_budget, wall_budget))):
            raise ValueError("Invalid immutable source, seed, bounded steps or allowance")
        row = read_example(manifest, manifest_sha256); record("data_admission", row); budget()
        backend = LocalModels(Path(models)/"vlm", Path(models)/"sd", threads)
        backend._activate("sd"); record("load_frozen_sd", backend.identity()); budget()
        before = base_hashes(); record("full_base_parameter_hash_before"); budget()
        pipe = backend.pipeline
        from diffusers import DDPMScheduler
        scheduler = DDPMScheduler.from_config(pipe.scheduler.config)
        generator = torch.Generator(device="cpu").manual_seed(seed)
        latents, embeddings, prepared = prepare_pair(pipe, row, generator)
        record("prepare_real_vae_and_clip", prepared); budget()
        adapter = ImageOutputAdapter(pipe.unet.conv_out.in_channels, pipe.unet.conv_out.out_channels, rank, seed)
        adapter_before = {n: p.detach().clone() for n, p in adapter.named_parameters()}
        initial_adapter_parameters = parameter_hashes(adapter); initial_hash = fingerprint(initial_adapter_parameters)
        handle = adapter.attach(pipe.unet)
        optimizer = torch.optim.Adam(adapter.parameters(), lr=learning_rate)
        for index in range(steps):
            budget(); record("update_started", {"index": index, "source_id": row["source_id"]})
            noise = torch.randn(latents.shape, dtype=latents.dtype, generator=generator)
            timestep = torch.randint(scheduler.config.num_train_timesteps, (1,), generator=generator)
            noisy = scheduler.add_noise(latents, noise, timestep)
            target = denoising_target(scheduler, latents, noise, timestep)
            prediction = forward(noisy, timestep, embeddings)
            if prediction.shape != target.shape:
                raise ValueError("UNet prediction shape differs from the denoising target")
            loss = F.mse_loss(prediction.float(), target.float())
            if not bool(torch.isfinite(loss)):
                raise ValueError("Nonfinite denoising loss")
            optimizer.zero_grad(set_to_none=True); loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(adapter.parameters(), 1.0, error_if_nonfinite=True)
            finite_grad = all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in adapter.parameters())
            if not finite_grad or float(norm) <= 0:
                raise ValueError("Adapter gradient must be finite and nonzero")
            optimizer.step()
            if any(not bool(torch.isfinite(p).all()) for p in adapter.parameters()):
                raise ValueError("Nonfinite updated adapter parameter")
            updates.append({"index": index, "source_id": row["source_id"], "loss": float(loss.detach()),
                            "finite_gradient": finite_grad, "gradient_norm_before_clipping": float(norm),
                            "timestep": int(timestep.item()), "noise": tensor_identity(noise)})
            record("update_completed", updates[-1]); del prediction, loss
            budget()
        status = "updates_complete"
    except (Exception, KeyboardInterrupt) as exc:
        fail("training_failure", exc)
    try:
        if status == "updates_complete":
            if not any(bool((p.detach() != adapter_before[n]).any()) for n, p in adapter.named_parameters()):
                raise ValueError("No neural adapter parameter changed")
            budget()
            with torch.no_grad():
                trained = forward(noisy, timestep, embeddings).detach().clone()
            handle.remove(); handle = None
            with torch.no_grad():
                base = forward(noisy, timestep, embeddings).detach()
            unet_hash = fingerprint({k.removeprefix("unet."): v for k, v in before.items() if k.startswith("unet.")})
            path = out / "image_adapter.safetensors"
            sha = save_image_adapter(adapter, path, unet_hash,
                    {"source_sha": source_sha, "manifest_sha256": manifest_sha256,
                     "prediction_type": scheduler.config.prediction_type, "steps": len(updates)})
            checkpoint = {"path": path.name, "sha256": sha, "reload_verified": False}
            record("save_image_adapter", checkpoint.copy()); budget()
            restored, handle = load_image_adapter(pipe.unet, path, sha)
            with torch.no_grad():
                reloaded = forward(noisy, timestep, embeddings).detach()
            probe = {"noisy_latents": tensor_identity(noisy), "timestep": int(timestep.item()),
                     "trained": tensor_identity(trained), "reloaded": tensor_identity(reloaded),
                     "equal": torch.equal(trained, reloaded), "dtype_preserved": trained.dtype == base.dtype == reloaded.dtype,
                     "max_reload_abs_difference": float((trained.float()-reloaded.float()).abs().max()),
                     "base_vs_trained_changed_values": int((base != trained).sum())}
            if not probe["equal"] or not probe["dtype_preserved"] or parameter_hashes(restored) != parameter_hashes(adapter):
                raise ValueError("Saved image adapter failed same-input reload equivalence")
            checkpoint["reload_verified"] = True; record("real_reload_forward_equivalence", probe); budget()
            status = "completed"
    except (Exception, KeyboardInterrupt) as exc:
        fail("checkpoint_or_probe_failure", exc)
    finally:
        if handle is not None:
            handle.remove()
    try:
        if before:
            after = base_hashes(); record("full_base_parameter_hash_after")
            if before != after or any(p.requires_grad or p.grad is not None for key in ("unet", "vae", "text_encoder")
                                      for p in getattr(backend.pipeline, key).parameters()):
                raise ValueError("Frozen generator backbone changed or accumulated gradients")
        if status == "completed":
            budget()
    except (Exception, KeyboardInterrupt) as exc:
        fail("final_audit_failure", exc)
    report = {"schema": SCHEMA, "status": status, "error": error, "checkpoint": checkpoint,
              "source_sha": source_sha, "manifest_sha256": manifest_sha256, "training_source": row,
              "seed": requested["seed"], "rank": requested["rank"], "planned_updates": requested["steps"],
              "request_configuration": requested, "completed_updates": len(updates), "updates": updates,
              "declared_source_count": int(row is not None), "observed_training_source_count": int(bool(updates)),
              "base_parameter_hashes_before": before, "base_parameter_hashes_after": after,
              "base_changed_parameter_tensors": sum(before.get(k) != after.get(k) for k in set(before)|set(after)) if before and after else None,
              "adapter_sha256_before": initial_hash, "adapter_sha256_after": None,
              "adapter_parameter_hashes_before": initial_adapter_parameters, "adapter_parameter_hashes_after": None,
              "adapter_changed_parameter_values": None, "adapter_changed_parameter_tensors": None,
              "adapter_parameter_count": None, "finalization_complete": False,
              "prepared_inputs": prepared, "reload_probe": probe, "actual_unet_forward_attempts": forward_attempts,
              "actual_unet_forward_completed": forward_completed, "learning_rate": requested["learning_rate"], "gradient_clip_norm": 1.0,
              "scheduler": dict(scheduler.config) if scheduler is not None else None,
              "budgets": {"cpu_seconds": requested["cpu_budget"], "wall_seconds": requested["wall_budget"], "preemptive": False},
              "scope": "single_image_generator_adapter_wiring_only", "four_arm_efficacy_established": False,
              "visual_conditioning_verified": False, "controller_updated": False,
              "repeated_steps_are_independent_sources": False, "cost_receipt": "cost_receipt.json"}
    try:
        report.update(runtime_source_sha256=digest_file(__file__),
                      runtime_sources={n: digest_file(Path(__file__).with_name(n)) for n in
                                       ("train_adapter.py", "local_models.py", "acquire_models.py")},
                      model_identity=backend.identity() if backend else None)
        if adapter is not None:
            final_adapter_parameters = parameter_hashes(adapter)
            report.update(adapter_sha256_after=fingerprint(final_adapter_parameters), adapter_parameter_hashes_after=final_adapter_parameters,
                          adapter_changed_parameter_values=sum(int((p.detach() != adapter_before[n]).sum()) for n, p in adapter.named_parameters()) if adapter_before else None,
                          adapter_changed_parameter_tensors=sum(bool((p.detach() != adapter_before[n]).any()) for n, p in adapter.named_parameters()) if adapter_before else None,
                          adapter_parameter_count=sum(p.numel() for p in adapter.parameters()))
        report["finalization_complete"] = True
    except (Exception, KeyboardInterrupt) as exc:
        fail("report_construction_failure", exc)
    backend = adapter = pipe = optimizer = restored = latents = embeddings = noisy = None
    try:
        gc.collect()
    except (Exception, KeyboardInterrupt) as exc:
        fail("resource_release_failure", exc)
    record("report_construction")

    def write_reports():
        report.update(status=status, error=error, checkpoint_qualified=(status == "completed" and report["finalization_complete"]))
        write_json(out / "report.json", report); record("report_write")
        write_json(out / "cost_receipt.json", {"events": events,
                   "cpu_seconds": math.fsum(e["cpu_seconds"] for e in events),
                   "wall_seconds": math.fsum(e["wall_seconds"] for e in events),
                   "cumulative_process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
                   "scope": "exclusive_intervals_through_report_write_including_hashes_reload_and_validation",
                   "unknown_outer_costs": ["last_meter_journal_and_cost_receipt_write", "external_process_startup"],
                   "training_cost_is_not_inference_cost": True})

    try:
        write_reports()
        if status == "completed":
            budget()
    except (Exception, KeyboardInterrupt) as exc:
        fail("final_report_or_budget_failure", exc); write_reports()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("models", "manifest", "output", "source-sha", "manifest-sha256"):
        parser.add_argument("--" + name, required=True)
    for name, default in (("seed", 17), ("rank", 4), ("steps", 2), ("threads", 2)):
        parser.add_argument("--" + name, type=int, default=default)
    for name, default in (("learning-rate", .001), ("cpu-budget", 600.), ("wall-budget", 600.)):
        parser.add_argument("--" + name, type=float, default=default)
    result = train(**vars(parser.parse_args()))
    print(json.dumps({k: result[k] for k in ("status", "checkpoint", "completed_updates", "adapter_changed_parameter_values")}, indent=2))
    if result["status"] != "completed":
        raise SystemExit(1)
