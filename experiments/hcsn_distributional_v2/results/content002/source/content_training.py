"""v2 optimizer loop with common 15/30/60 CPU selection opportunities.

This is an explicit adaptation of the frozen v1 training loop. Search-level
selection and heldout access still use v1.run_search; its factory/evaluator and
candidate function are bound only inside an isolated v2 worker.
"""

import hashlib
import json
from pathlib import Path
import time

import torch
from torch.nn import functional as F

from experiments.hcsn_free_boundary_v1 import training as base
from .model import build_model


def train_candidate(train, validation, model_name, seed, learning_rate, output_dir,
                    cpu_seconds=60.0, width=32, depth=1, batch_size=32, max_updates=65536):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    process_start, wall_start = time.process_time(), time.perf_counter()
    model = build_model(model_name, train["x"].shape[-1], int(train["y"].max())+1,
                        width=width, depth=depth, seed=seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    initial = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
    initial_hash = base.save_weights(output_dir / "initial.npz", model)
    setup_cpu = time.process_time()-process_start
    generator = torch.Generator().manual_seed(seed+200003)
    targets = sorted(set([t for t in (15.0, 30.0, 60.0) if t < cpu_seconds]+[cpu_seconds]))
    next_target, training_cpu, step, validation_cpu = 0, 0.0, 0, 0.0
    checkpoints, prefix, first128_prefix = [], hashlib.sha256(), None
    with (output_dir / "updates.jsonl").open("w") as log:
        while training_cpu < cpu_seconds and step < max_updates:
            update_start = time.process_time()
            model.train()
            indices = torch.randint(train["x"].shape[0], (batch_size,), generator=generator)
            prefix.update(indices.numpy().tobytes())
            x, dt, y = (train[key][indices] for key in ("x", "dt", "y"))
            optimizer.zero_grad(set_to_none=True)
            logits, aux = model(x, dt, return_sequence=True)
            loss = F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError(f"Nonfinite loss at update {step+1}")
            mass_error = None
            if "flow_mass" in aux:
                mass_error = max(float((layer["flow_mass"].detach()-1).abs().max())
                                 for layer in aux["layers"])
                if mass_error > 1e-4:
                    raise FloatingPointError("Training probability mass exceeded float32 gate")
            loss.backward()
            gradients = base._gradient_summary(model)
            if not all(row["finite"] for row in gradients.values()):
                raise FloatingPointError(f"Nonfinite gradient at update {step+1}")
            unclipped = float(torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0))
            optimizer.step()
            step += 1
            training_cpu += time.process_time()-update_start
            if step == 128:
                first128_prefix = prefix.hexdigest()
            row = dict(step=step, loss=float(loss.detach()), training_cpu_seconds=training_cpu,
                batch_sha256=hashlib.sha256(indices.numpy().tobytes()).hexdigest(),
                prefix_sha256=prefix.hexdigest(), gradients=gradients,
                preclip_gradient_l2=unclipped, max_probability_mass_error=mass_error)
            if "total_activity" in aux:
                row.update(modeled_activity=float(aux["total_activity"].detach()),
                           modeled_cost=float(aux["total_cost"].detach()))
            log.write(json.dumps(row, sort_keys=True, allow_nan=False)+"\n")
            crossed = []
            while next_target < len(targets) and training_cpu >= targets[next_target]:
                crossed.append(targets[next_target])
                next_target += 1
            stopping = training_cpu >= cpu_seconds or step >= max_updates
            if crossed or step == 128 or stopping:
                validation_start = time.process_time()
                metrics = base.evaluate(model, validation)
                validation_cpu += time.process_time()-validation_start
                filename = f"step_{step:06d}.npz"
                digest = base.save_weights(output_dir / filename, model)
                checkpoints.append(dict(step=step, weights=filename, sha256=digest,
                    training_cpu_seconds=training_cpu, crossed_cpu_targets=crossed,
                    fixed_step_128=(step == 128), validation=metrics,
                    primary_eligible=bool(crossed or stopping),
                    endpoint_overrun_seconds=max(0.0, training_cpu-cpu_seconds)))
                base._write_json(output_dir / "checkpoints.json", checkpoints)
    best = min((row for row in checkpoints if row["primary_eligible"]),
               key=lambda row: (row["validation"]["cross_entropy"],
                                row["training_cpu_seconds"], row["step"]))
    final_changes = base._parameter_changes(model, initial)
    base.load_weights(output_dir / best["weights"], model)
    result = dict(model=model_name, seed=seed, learning_rate=learning_rate,
        config=model.config, counts=model.counts(), requested_training_cpu_seconds=cpu_seconds,
        training_cpu_seconds=training_cpu, overrun_seconds=max(0.0, training_cpu-cpu_seconds),
        updates=step, stopping_reason="cpu_budget" if training_cpu>=cpu_seconds else "update_cap",
        setup_cpu_seconds=setup_cpu, validation_cpu_seconds=validation_cpu,
        total_cpu_seconds=time.process_time()-process_start,
        total_wall_seconds=time.perf_counter()-wall_start,
        process_peak_rss_bytes=base._peak_rss_bytes(), initial_sha256=initial_hash,
        batch_prefix_sha256=prefix.hexdigest(), first128_prefix_sha256=first128_prefix,
        checkpoints=checkpoints, best=best, final_parameter_changes=final_changes,
        selected_parameter_changes=base._parameter_changes(model, initial),
        primary_cpu_targets=targets,
        derivative_scope="first derivatives; upwind/remap/reset interpolation piecewise differentiable")
    base._write_json(output_dir / "candidate.json", result)
    return result
