"""Memory-bounded replay of the unchanged four-example warmstart objective.

One AdamW update follows four independently evaluated per-example losses. This
is the same mathematical batch objective; floating-point reduction order is not
claimed bit-identical to the retired dense-batch attempt. Every 64 updates stores
all model, optimizer and RNG state needed for an exact future execution resume.
"""
import argparse
import json
from pathlib import Path
import shutil
import time

import numpy as np
import torch

from .data_sources import digest, save
from .natural_model import LAW, NaturalGenerator, parameter_hash, proxy_loss
from .natural_train import WARMSTART, generator_rows, save_checkpoint
from .natural_proxy_data import LazyProxyDataset, context_cache
from .data_v3_contract import APPROVED_SOURCE_SHA
from .profile_contract import cpu_seconds


def full_checkpoint(path, *, model, optimizer, rng, step, protocol_sha, source_pins, log):
    record = {"schema": "hepta.closure.recoverable-warmstart.v1", "model": model.state_dict(),
              "optimizer": optimizer.state_dict(), "sampler_rng": rng.get_state(),
              "global_torch_rng": torch.get_rng_state(), "step": step,
              "ontology": model.ontology, "emission_law": LAW,
              "parameter_sha256": parameter_hash(model), "protocol_sha256": protocol_sha,
              "implementation_sha256": source_pins, "training_log": log}
    temporary = path.with_suffix(".pending")
    torch.save(record, temporary)
    temporary.replace(path)
    return {"path": path.name, "sha256": digest(path.read_bytes()), "step": step,
            "parameter_sha256": record["parameter_sha256"]}


def run(root, output, verification, cache_from, resume=False):
    torch.set_num_threads(2)
    check = json.loads(verification.read_text())
    if not check.get("passed") or any(check["source_sha256"][name] != digest((Path(__file__).parent/name).read_bytes())
            for name in ("natural_recovery_check.py", "natural_train_microbatch.py", "natural_model.py", "natural_proxy_data.py")):
        raise ValueError("The low-memory execution amendment needs its current numerical/recovery check")
    plan, rows = generator_rows(root, "generator_train")
    if plan["protocol_sha256"] != APPROVED_SOURCE_SHA or len(rows) != 256:
        raise ValueError("Warmstart must bind the approved 256-source v3 training allocation")
    names = ("natural_train_microbatch.py", "natural_train.py", "natural_proxy_data.py", "data_v3_contract.py", "natural_model.py", "natural_media.py",
             "natural_port.py", "semantic_backbones.py", "semantic_tsm.py")
    pins = {name: digest((Path(__file__).parent / name).read_bytes()) for name in names}
    protocol = {**WARMSTART, "schema": "hepta.closure.natural-warmstart.v3",
                "source_protocol_sha256": plan["protocol_sha256"], "implementation_sha256": pins,
                "numerical_execution_check_sha256": digest(check),
                "microbatch": 1, "gradient_accumulation_count": 4, "adam_updates_unchanged": 2048,
                "reduction": "one fourth of each of four per-example proxy losses, then one AdamW update",
                "floating_point_scope": "mathematically equivalent batch gradient; reduction ordering may differ from dense-batch v2",
                "batch_independence": "model has no batch normalization, dropout or cross-example operation; the proxy loss returns one scalar per example",
                "checkpoint_frequency": 64, "cache_from": str(cache_from),
                "public_cache_receipt_sha256": digest((cache_from/"PUBLIC_CONTEXT_CACHE.json").read_bytes()),
                "public_feature_model_lifetime": "separate completed process before optimizer; warmstart verifies and loads only small pinned feature arrays",
                "training_source_amendment": plan["coverage_amendment"],
                "dataset_storage": "lazy NPZ one source at a time; only pinned frozen public features resident",
                "initialization_seed_reset_immediately_before_constructor": True,
                "prior_attempt": "v2 was OOM-terminated after checkpoint256 without optimizer state; no exact continuation is claimed",
                "training_sources": [row["source_id"] for _, row in rows]}
    if not resume:
        output.mkdir(parents=True, exist_ok=False)
        for name in ("PUBLIC_CONTEXT_CACHE.npz", "PUBLIC_CONTEXT_CACHE.json"):
            shutil.copyfile(cache_from/name,output/name)
        save(output / "WARMSTART_PROTOCOL.json", protocol)
        shutil.copyfile(verification, output / "EXECUTION_CHECK.json")
    elif json.loads((output / "WARMSTART_PROTOCOL.json").read_text()) != protocol:
        raise ValueError("Full resumed warmstart protocol/source identity changed")
    protocol_sha = digest(protocol)
    start, cpu_start = time.monotonic(), cpu_seconds()
    data = LazyProxyDataset(rows, plan["ontology"], context_cache(root, rows, output, require_existing=True))
    torch.manual_seed(WARMSTART["seed"])
    model = NaturalGenerator(plan["ontology"])
    initial_hashes = {key: parameter_hash(module) for key, module in model.components().items()}
    optimizer = torch.optim.AdamW(model.parameters(), lr=.0003, weight_decay=.0001)
    rng = torch.Generator().manual_seed(WARMSTART["seed"] + 1)
    log, start_step = [], 0
    if resume:
        state = torch.load(output / "RECOVERY.pt", map_location="cpu", weights_only=True)
        if state["protocol_sha256"] != protocol_sha or state["implementation_sha256"] != pins or state["emission_law"] != LAW:
            raise ValueError("Recovered optimizer/model/RNG identity changed")
        model.load_state_dict(state["model"], strict=True)
        optimizer.load_state_dict(state["optimizer"])
        rng.set_state(state["sampler_rng"])
        torch.set_rng_state(state["global_torch_rng"])
        if parameter_hash(model) != state["parameter_sha256"]:
            raise ValueError("Recovered model parameters changed")
        start_step, log = state["step"], state["training_log"]
        # A process may die after the recovery state is atomically installed
        # but before the public selection snapshot is serialized.
        if start_step in WARMSTART["checkpoints"] and not (output/f"warmstart-{start_step:04d}.pt").exists():
            save_checkpoint(output/f"warmstart-{start_step:04d}.pt",model,protocol_sha,start_step)
    else:
        save_checkpoint(output / "warmstart-0000.pt", model, protocol_sha, 0)
        full_checkpoint(output / "RECOVERY.pt", model=model, optimizer=optimizer, rng=rng,
                        step=0, protocol_sha=protocol_sha, source_pins=pins, log=log)
    for step in range(start_step + 1, WARMSTART["steps"] + 1):
        indices = torch.randint(len(rows), (4,), generator=rng)
        optimizer.zero_grad(set_to_none=True)
        losses = []
        for index in indices:
            batch, target = data[index]
            loss = proxy_loss(model(batch), target).mean()
            (loss / 4).backward()
            losses.append(float(loss.detach()))
        norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 2.)
        optimizer.step()
        if step % 64 == 0:
            item = {"step": step, "proxy_loss": float(np.mean(losses)), "raw_gradient_norm": float(norm),
                    "cpu_seconds_this_invocation": cpu_seconds() - cpu_start,
                    "wall_seconds_this_invocation": time.monotonic() - start,
                    "resumed_from_step": start_step}
            log.append(item)
            recovery = full_checkpoint(output / "RECOVERY.pt", model=model, optimizer=optimizer, rng=rng,
                                       step=step, protocol_sha=protocol_sha, source_pins=pins, log=log)
            save(output / f"recovery-{step:04d}.json", recovery)
            print(json.dumps(item), flush=True)
        if step in WARMSTART["checkpoints"]:
            save_checkpoint(output / f"warmstart-{step:04d}.pt", model, protocol_sha, step)
    if pins != {name: digest((Path(__file__).parent / name).read_bytes()) for name in pins}:
        raise ValueError("Warmstart source changed during execution")
    checkpoints = [{"file": f"warmstart-{step:04d}.pt", "sha256": digest((output / f"warmstart-{step:04d}.pt").read_bytes()), "step": step}
                   for step in WARMSTART["checkpoints"]]
    result = {"schema": "hepta.closure.natural-warmstart-result.v2", "protocol_sha256": protocol_sha,
              "source_protocol_sha256": plan["protocol_sha256"], "optimizer_steps": WARMSTART["steps"],
              "training_source_count": len(rows), "proxy_training_examples": WARMSTART["steps"] * 4,
              "trainable_parameters": sum(p.numel() for p in model.parameters()),
              "components_changed": {key: parameter_hash(module) != initial_hashes[key] for key, module in model.components().items()},
              "checkpoints": checkpoints, "training_log": log, "actual_ndu_updates": 0,
              "resumed_from_step": start_step, "new_development_metrics": 0,
              "new_calibration_metrics": 0, "new_qualification_metrics": 0,
              "scientific_scope": "supervised proxy common initialization only; full actual-output study remains separate"}
    save(output / "WARMSTART_RESULT.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "output", "verification", "cache-from"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run(args.assets, args.output, args.verification, args.cache_from, args.resume)
