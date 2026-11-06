"""Linux CPU qualification of real tiny-sd training; never a confirmatory R2 fit.

The frozen base loader stays unchanged. This separate adapter trains only the
existing UNet output projection and reloads a delta against the exact base.
"""

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import math
from pathlib import Path
import re
import resource
import signal
import sys
import time

from .local_models import LocalModels
from .sd_checkpoint import (TRAINABLE, canonical, file_sha, freeze_for_training,
                            inventory, restore_candidate, save_candidate,
                            tensor_sha, write_json)


def validate_plan(plan):
    if (plan.get("schema") != "hepta.r2.sd-development-plan.v1"
            or plan.get("split") != "development"
            or plan.get("confirmatory_fit") is not False
            or plan.get("trainable") != list(TRAINABLE)):
        raise ValueError("only an explicit development output-projection plan is accepted")
    if not re.fullmatch(r"[0-9a-f]{40}", plan.get("source_sha", "")):
        raise ValueError("missing immutable source commit")
    actual_sources = {name: file_sha(Path(__file__).with_name(name)) for name in
                      ("sd_train.py", "sd_checkpoint.py", "local_models.py", "acquire_models.py")}
    if plan.get("source_files") != actual_sources:
        raise ValueError("executed source files differ from the frozen plan")
    for name, low, high in (("seed", 0, 2**31 - 1), ("steps", 1, 8), ("threads", 1, 2)):
        if type(plan.get(name)) is not int or not low <= plan[name] <= high:
            raise ValueError("invalid bounded " + name)
    if type(plan.get("learning_rate")) not in (float, int) or not 0 < plan["learning_rate"] <= 0.1:
        raise ValueError("invalid learning rate")
    if not isinstance(plan.get("prompt"), str) or not 0 < len(plan["prompt"].strip()) <= 1000:
        raise ValueError("missing development text target")
    for name in ("cpu_limit_seconds", "wall_limit_seconds"):
        if type(plan.get(name)) is not int or not 1 <= plan[name] <= 3600:
            raise ValueError("missing bounded process budget")
    if plan.get("resolution") != 256 or plan.get("momentum") != 0.9:
        raise ValueError("unsupported training definition")
    if file_sha(plan["image_path"]) != plan["image_sha256"]:
        raise ValueError("development image identity mismatch")
    return hashlib.sha256(canonical(plan)).hexdigest()


def load_pipeline(sd_dir, threads):
    import torch
    from diffusers import StableDiffusionPipeline
    from diffusers.models.model_loading_utils import load_state_dict
    from transformers.modeling_utils import load_state_dict as transformers_load

    verifier = LocalModels(sd_dir, sd_dir, threads=threads)
    verifier._verify("sd")
    if tuple(int(part) for part in torch.__version__.split(".")[:2]) < (2, 6):
        raise ValueError("pinned bin loading requires torch >= 2.6")
    if ('"weights_only": True' not in inspect.getsource(load_state_dict)
            or inspect.signature(transformers_load).parameters["weights_only"].default is not True):
        raise ValueError("installed loaders do not enforce weights_only")
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(True)
    pipe = StableDiffusionPipeline.from_pretrained(
        sd_dir, local_files_only=True, torch_dtype=torch.float32,
        use_safetensors=False, low_cpu_mem_usage=True)
    for module in (pipe.unet, pipe.vae, pipe.text_encoder):
        module.eval().requires_grad_(False)
    pipe.set_progress_bar_config(disable=True)
    pipe.enable_attention_slicing()
    pipe.enable_vae_slicing()
    return pipe, verifier.manifests["sd"]["manifest_sha256"]


def make_batch(pipe, plan):
    import numpy as np
    import torch
    from diffusers import DDPMScheduler
    from PIL import Image

    with Image.open(plan["image_path"]) as source:
        pixels = np.asarray(source.convert("RGB").resize((256, 256), Image.Resampling.BILINEAR)).copy()
    image = torch.from_numpy(pixels).permute(2, 0, 1).unsqueeze(0).float() / 127.5 - 1
    tokens = pipe.tokenizer(plan["prompt"], max_length=pipe.tokenizer.model_max_length,
                            truncation=True, padding="max_length", return_tensors="pt")
    with torch.no_grad():
        latent = pipe.vae.encode(image).latent_dist.mode() * pipe.vae.config.scaling_factor
        mask = {"attention_mask": tokens.attention_mask} if getattr(pipe.text_encoder.config, "use_attention_mask", False) else {}
        embeddings = pipe.text_encoder(tokens.input_ids, **mask)[0]
    scheduler = DDPMScheduler.from_config(pipe.scheduler.config)
    if scheduler.config.prediction_type != "epsilon":
        raise ValueError("only the fixed epsilon denoising objective is qualified")
    rng = torch.Generator(device="cpu").manual_seed(plan["seed"])
    noise = torch.randn(latent.shape, generator=rng, dtype=latent.dtype)
    timestep = torch.randint(0, scheduler.config.num_train_timesteps, (1,), generator=rng)
    noisy = scheduler.add_noise(latent, noise, timestep)
    batch = {"noisy": noisy, "timestep": timestep, "embeddings": embeddings, "target": noise}
    return batch, rng, {name: tensor_sha(value) for name, value in batch.items()}


def predict(unet, batch):
    import torch

    value = unet(batch["noisy"], batch["timestep"], encoder_hidden_states=batch["embeddings"]).sample
    if not torch.isfinite(value).all():
        raise ValueError("nonfinite real UNet prediction")
    return value


def fit(sd_dir, plan, output):
    import torch

    plan_sha = validate_plan(plan)
    pipe, base_sha = load_pipeline(sd_dir, plan["threads"])
    parameters = freeze_for_training(pipe.unet)
    before = inventory(pipe.unet)
    frozen_components = {name: inventory(getattr(pipe, name)) for name in ("vae", "text_encoder")}
    batch, rng, batch_identity = make_batch(pipe, plan)
    optimizer = torch.optim.SGD(parameters, lr=plan["learning_rate"], momentum=plan["momentum"])
    losses = []
    with torch.no_grad():
        before_prediction = tensor_sha(predict(pipe.unet, batch))
    for _ in range(plan["steps"]):
        optimizer.zero_grad(set_to_none=True)
        loss = torch.nn.functional.mse_loss(predict(pipe.unet, batch), batch["target"])
        if not torch.isfinite(loss):
            raise ValueError("nonfinite denoising loss")
        loss.backward()
        if any(p.grad is None or not torch.isfinite(p.grad).all() for p in parameters):
            raise ValueError("missing or nonfinite real parameter gradients")
        optimizer.step()
        losses.append(float(loss.detach()))
    with torch.no_grad():
        after_prediction = tensor_sha(predict(pipe.unet, batch))
    if before_prediction == after_prediction:
        raise ValueError("the actual UNet prediction did not change")
    if frozen_components != {name: inventory(getattr(pipe, name)) for name in frozen_components}:
        raise ValueError("a frozen text encoder or VAE tensor changed")
    metadata = {"base_manifest_sha256": base_sha, "plan": plan, "plan_sha256": plan_sha,
                "batch": batch_identity, "losses": losses, "prediction_before": before_prediction,
                "prediction_after": after_prediction, "frozen_components": frozen_components,
                "optimizer": {"kind": "SGD", "momentum": plan["momentum"],
                              "learning_rate": plan["learning_rate"], "completed_steps": plan["steps"]},
                "versions": {name: importlib.metadata.version(name) for name in
                             ("torch", "diffusers", "transformers", "safetensors")},
                "source_files": {name: file_sha(Path(__file__).with_name(name)) for name in
                                 ("sd_train.py", "sd_checkpoint.py", "local_models.py", "acquire_models.py")},
                "training_target": "one development image; deterministic VAE mean; epsilon MSE",
                "scope": "parameter-update-and-cold-reload-mechanism-only"}
    digest = save_candidate(output / "candidate", pipe.unet, optimizer, rng, before, metadata)
    return {"checkpoint_sha256": digest, "losses": losses, "batch": batch_identity,
            "prediction_before": before_prediction, "prediction_after": after_prediction,
            "changed": list(TRAINABLE), "frozen_components_unchanged": True,
            "semantic_quality_measured": False, "r2_fit_completed": False}


def replay(sd_dir, checkpoint, digest, output, render, fit_result_sha256):
    import torch

    fit_result = checkpoint.parent / "RESULT.json"
    if file_sha(fit_result) != fit_result_sha256:
        raise ValueError("fit terminal receipt identity mismatch")
    receipt = json.loads(fit_result.read_text())
    if (receipt.get("status") != "completed" or receipt.get("mode") != "fit"
            or receipt.get("result", {}).get("checkpoint_sha256") != digest):
        raise ValueError("checkpoint has no completed bound fit receipt")
    # Read only after checking the caller's independently retained identity.
    if file_sha(checkpoint / "CHECKPOINT.json") != digest:
        raise ValueError("checkpoint identity mismatch")
    header = json.loads((checkpoint / "CHECKPOINT.json").read_text())
    plan = header["metadata"]["plan"]
    if validate_plan(plan) != header["metadata"]["plan_sha256"]:
        raise ValueError("training plan differs from its frozen digest")
    current_versions = {name: importlib.metadata.version(name) for name in
                        ("torch", "diffusers", "transformers", "safetensors")}
    if (header["metadata"]["versions"] != current_versions
            or header["metadata"]["source_files"] != plan["source_files"]):
        raise ValueError("replay source or numerical environment differs from the fit")
    pipe, base_sha = load_pipeline(sd_dir, plan["threads"])
    manifest, _, _ = restore_candidate(checkpoint, pipe.unet, base_sha, digest)
    batch, _, batch_identity = make_batch(pipe, plan)
    with torch.no_grad():
        prediction = tensor_sha(predict(pipe.unet, batch))
    if batch_identity != manifest["metadata"]["batch"] or prediction != manifest["metadata"]["prediction_after"]:
        raise ValueError("cold process numerical replay mismatch")
    result = {"checkpoint_sha256": digest, "prediction_sha256": prediction,
              "batch": batch_identity, "cold_replay_matches": True}
    if render:
        with torch.inference_mode():
            generated = pipe(plan["prompt"], height=256, width=256, num_inference_steps=12,
                             generator=torch.Generator(device="cpu").manual_seed(plan["seed"]),
                             guidance_scale=7.5)
        generated.images[0].save(output / "candidate.png")
        result["output"] = {"sha256": file_sha(output / "candidate.png"),
                            "bytes": (output / "candidate.png").stat().st_size,
                            "nsfw_content_detected": generated.nsfw_content_detected,
                            "quality_evaluated": False}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fit", "replay"))
    parser.add_argument("--sd", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--fit-result-sha256")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("this process-budget and resource qualification requires Linux")
    args.output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    report = {"status": "running", "mode": args.mode, "confirmatory_fit": False,
              "production_promotion_permitted": False}
    write_json(args.output / "STARTED.json", report)
    exit_code = 1
    try:
        if args.mode == "fit":
            plan = json.loads(args.plan.read_text())
        else:
            if file_sha(args.checkpoint / "CHECKPOINT.json") != args.sha256:
                raise ValueError("checkpoint identity mismatch")
            plan = json.loads((args.checkpoint / "CHECKPOINT.json").read_text())["metadata"]["plan"]
        validate_plan(plan)
        def interrupted(signum, _frame):
            raise TimeoutError("process interrupted by signal " + str(signum))
        for name in (signal.SIGTERM, signal.SIGXCPU, signal.SIGALRM):
            signal.signal(name, interrupted)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        cpu_soft = math.ceil(usage.ru_utime + usage.ru_stime) + plan["cpu_limit_seconds"]
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_soft, cpu_soft + 5))
        signal.alarm(plan["wall_limit_seconds"])
        report["result"] = (fit(args.sd, plan, args.output) if args.mode == "fit" else
                            replay(args.sd, args.checkpoint, args.sha256, args.output, args.render,
                                   args.fit_result_sha256))
        report["status"] = "completed"
        exit_code = 0
    except BaseException as error:
        report.update(status="failed", error=type(error).__name__ + ": " + str(error))
    finally:
        signal.alarm(0)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        report["cost"] = {"process_cpu_seconds": usage.ru_utime + usage.ru_stime,
                          "wall_seconds_through_report_preparation": time.perf_counter() - start,
                          "peak_rss_bytes": usage.ru_maxrss * 1024,
                          "disk_bytes_before_terminal_report": sum(p.stat().st_size for p in args.output.rglob("*") if p.is_file()),
                          "energy_joules": None, "energy_reason": "no meter attached",
                          "network_bytes": None, "network_reason": "not instrumented; local-files-only loading",
                          "final_report_write_and_process_exit_cost": None,
                          "cost_scope": "inclusive process envelope; do not add nested stages"}
        write_json(args.output / "RESULT.json", report)
        print(json.dumps(report, sort_keys=True, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
