"""The published v7 supervised recipe, without training an unused N profile.

Checkpoint callbacks are owner-side recording hooks, not changes to the batch,
action, loss or optimizer schedule. They add measured I/O cost to this run.
"""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

import torch

from ..v6.data import Observation, Target
from ..v6.neural import ACTIONS, parameter_hash
from ..v7.data import make_batch
from ..v7.model import SlotPortfolio
from ..v7.snapshot import Snapshot
from ..v7.training import TrainConfig


def write_json(path, value):
    """Create one immutable JSON record; never replace an earlier attempt."""
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def save_training_checkpoint(path, model, optimizer, step, rng, metadata):
    """Preserve actual parameters, Adam state and completed-step RNG identities."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    record = {"schema": "hepta.ndu-abc.optimizer-checkpoint.v1", "step": step,
              "model_config": deepcopy(model.config), "state_dict": model.state_dict(),
              "optimizer_state_dict": optimizer.state_dict(), "torch_rng_state": torch.get_rng_state(),
              "generation_rng_state": rng.get_state(), "metadata": deepcopy(metadata),
              "parameter_sha256": parameter_hash(model)}
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("xb") as stream:
        torch.save(record, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size, "step": step,
            "parameter_sha256": record["parameter_sha256"]}


@torch.inference_mode(False)
@torch.enable_grad()
def train_supervised(corpus, config=None, progress=None, checkpoint=None, checkpoint_interval=100):
    """Return the same S parameters/history as v7.train_profiles for this recipe."""
    config = config or TrainConfig()
    if (config.steps < 1 or config.batch_size < 1 or config.scenarios < 2
            or config.horizon != 4 or config.threads not in {1, 2}
            or config.risk_aversion <= 0 or config.learning_rate <= 0 or checkpoint_interval < 1):
        raise ValueError("Invalid registered supervised warm-start configuration")
    torch.set_num_threads(config.threads)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.seed)
        original = SlotPortfolio(noise_scale=config.noise_scale)
    initial_sha = parameter_hash(original)
    model = deepcopy(original).train()
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    rng = torch.Generator().manual_seed(config.seed + 104729)
    schedule, gradients, histories = hashlib.sha256(), {}, []
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    if checkpoint:
        checkpoint(model, optimizer, 0, rng, schedule.hexdigest())
    for step in range(config.steps):
        batch_seed = config.seed * 1000003 + step
        batch = make_batch(corpus, "train", config.batch_size, batch_seed)
        observation = Observation(*(value.repeat_interleave(config.scenarios, 0)
                                   for value in (batch.observation.pixels, batch.observation.mask,
                                                 batch.observation.text_tokens)))
        target = Target(*(value.repeat_interleave(config.scenarios, 0)
                          for value in (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
        noise = torch.randn((config.batch_size * config.scenarios, 96), generator=rng)
        state = model.encode(observation, noise)
        actions = torch.randint(4, (step % (config.horizon + 1),), generator=rng).tolist()
        for action in actions:
            state = model.step(state, ACTIONS[action])
        terms = model.loss(model.decode(state, teacher_tokens=target.text_tokens), target)
        objective = terms["joint"].reshape(config.batch_size, config.scenarios).mean()
        if not torch.isfinite(objective):
            raise FloatingPointError(f"Nonfinite objective at supervised:{step}")
        optimizer.zero_grad(set_to_none=True)
        objective.backward()
        for name, parameter in model.named_parameters():
            if parameter.grad is not None:
                module = name.split(".")[0]
                gradients[module] = max(gradients.get(module, 0), float(parameter.grad.abs().sum()))
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
        optimizer.step()
        schedule.update(f"{batch_seed}:{actions}\n".encode())
        row = {"step": step + 1, "objective": float(objective.detach()), "horizon": len(actions),
               **{key: float(value.detach().mean()) for key, value in terms.items()}}
        histories.append(row)
        if checkpoint and ((step + 1) % checkpoint_interval == 0 or step + 1 == config.steps):
            checkpoint(model, optimizer, step + 1, rng, schedule.hexdigest())
        if progress and (step == 0 or (step + 1) % 100 == 0):
            progress("supervised", row)
    metadata = {"profile": "supervised", "training_config": asdict(config),
                "source_manifest_sha256": corpus.manifest["manifest_sha256"],
                "initial_parameter_sha256": initial_sha}
    snapshot = Snapshot(model, metadata)
    report = {**metadata, "final_snapshot_sha256": snapshot.fingerprint,
              "final_parameter_sha256": parameter_hash(model), "history": histories,
              "optimizer_updates": config.steps, "gradient_abs_sum_max": gradients,
              "schedule_sha256": schedule.hexdigest(),
              "wall_ns": time.perf_counter_ns() - start_wall,
              "cpu_ns": time.process_time_ns() - start_cpu,
              "parameter_count": sum(p.numel() for p in model.parameters()),
              "reward": "-(pixel_bce + 0.5*teacher_forced_text_ce + 0.3*semantic_digit_ce)",
              "actual_emitted_output_ndu_objective": False,
              "role": "supervised_or_conditional_latent_noise_surrogate_pretraining"}
    return snapshot, report


def fit_supervised(corpus, output, seed, protocol, progress=None):
    """Record a fresh S-only warm-start invocation with resumable checkpoints."""
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    training = protocol["training"]
    if seed not in protocol["training_seeds"]:
        raise ValueError("Unregistered training seed")
    config = TrainConfig(seed=seed, steps=training["warm_start_steps"],
                         batch_size=training["warm_start_batch_size"],
                         scenarios=training["warm_start_scenarios"],
                         learning_rate=training["warm_start_learning_rate"], threads=protocol["threads"])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    canonical_protocol = json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()
    registration = {"schema": "hepta.ndu-abc.supervised-warm-start.v1", "config": asdict(config),
                    "source_manifest_sha256": corpus.manifest["manifest_sha256"],
                    "protocol_canonical_sha256": hashlib.sha256(canonical_protocol).hexdigest(),
                    "optimizer_resume_checkpoints": True, "unused_ndu_profile_trained": False,
                    "warm_start_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    checkpoints = []
    try:
        write_json(output / "registration.json", registration)
        def checkpoint(model, optimizer, step, rng, schedule):
            metadata = {**registration, "schedule_sha256": schedule, "next_step": step,
                        "next_batch_seed": seed * 1000003 + step}
            checkpoints.append(save_training_checkpoint(output / "checkpoints" / f"step-{step:04d}.pt",
                                                        model, optimizer, step, rng, metadata))
        snapshot, report = train_supervised(corpus, config, progress, checkpoint,
                                             training["checkpoint_interval"])
        report["checkpoint_file_sha256"] = snapshot.save(output / "supervised.pt")
        report["optimizer_checkpoints"] = checkpoints
        report["invocation_wall_ns"] = time.perf_counter_ns() - started_wall
        report["invocation_cpu_ns"] = time.process_time_ns() - started_cpu
        report["cost_scope"] = "Entry through final snapshot save; external wrapper includes final receipt writes."
        write_json(output / "training.json", report)
        return snapshot, report
    except BaseException as error:
        write_json(output / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                   "wall_ns": time.perf_counter_ns() - started_wall,
                   "cpu_ns": time.process_time_ns() - started_cpu, "checkpoints": checkpoints})
        raise
