"""Matched SFT/mean-output/exponential-moment continuations on actual media.

Every arm executes the deployment runtime and scores reopened PNG/UTF8 outputs.
The RL arms optimize a declared joint task/noise moment plus the registered
native supervised auxiliary term. Training rows are not held-out model results.
"""

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

import torch

from ..v6.data import Observation, Target, render_tokens
from ..v6.neural import parameter_hash
from ..v6.observer import METRIC_DIGEST, observe_tensors
from ..v7.data import make_batch
from ..v7.model import SlotPortfolio, observation_digest
from ..v7.snapshot import Snapshot
from .emission import score_function_objective
from .media import RawMediaArchive
from .runtime import HORIZON, PREFIX, initialize, transition, work_counts
from .warm_start import save_training_checkpoint, write_json


def training_seeds(seed, step):
    """Same input and emission stream seeds for every arm of a training seed."""
    return seed * 1_000_003 + 20_261_024 + step, seed * 1_000_033 + 20_261_025 + step


def source_pins():
    """Bind the actual training, runtime, serialization and scoring dependency set."""
    area = Path(__file__).resolve().parents[1]
    names = {"abc_recovery": ("output_training", "warm_start", "runtime", "emission", "media"),
             "v7": ("data", "model", "snapshot", "sources", "training"),
             "v6": ("data", "neural", "observer")}
    return {f"{directory}/{name}.py": hashlib.sha256(
        (area / directory / f"{name}.py").read_bytes()).hexdigest()
        for directory, modules in names.items() for name in modules}


@contextmanager
def measured_phase(costs, name):
    """Nested phase totals include partial failed work; they are not additive to total."""
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        yield
    finally:
        record = costs.setdefault(name, {"calls": 0, "wall_ns": 0, "cpu_ns": 0})
        record["calls"] += 1
        record["wall_ns"] += time.perf_counter_ns() - wall
        record["cpu_ns"] += time.process_time_ns() - cpu


def gradient_by_module(named_parameters, gradients):
    """Summed absolute gradients, including an explicit zero for unused modules."""
    result = Counter()
    for (name, _), gradient in zip(named_parameters, gradients):
        result[name.split(".")[0]] += 0. if gradient is None else float(gradient.detach().abs().sum())
    return dict(result)


@torch.inference_mode(False)
@torch.enable_grad()
def fit_arm(warm_snapshot, corpus, observer, output, seed, arm, protocol):
    """Return (Snapshot, report) from one fresh, registered fine-tuning arm.

    All RNG seeds, source groups, per-output scores, path likelihoods, physical
    media and optimizer checkpoints are retained. The designated primary
    observer's actual parameter identity is bound here; its qualification and
    source-role certification belong to the enclosing frozen registration.

    ``terminal_log_probability`` is valid because the four actions are fixed and
    the optimized reward depends only on retained terminal outputs. Actual I/O
    cost is measured separately, not inserted as a discarded-draw-dependent
    reward. The root process wrapper must include final receipt serialization.
    """
    whole_wall, whole_cpu = time.perf_counter_ns(), time.process_time_ns()
    training = deepcopy(protocol["training"])
    if (seed not in protocol["training_seeds"] or arm not in training["arms"]
            or arm not in {"sft_continuation", "output_mean", "output_ndu"}
            or tuple(protocol["initial_prefix"]) != PREFIX
            or protocol["fixed_policy"] != ["refine_image", "refine_text"]
            or protocol["continuation_budget"] != HORIZON
            or protocol["roles"]["generator_training"] != "train"):
        raise ValueError("Unsupported or unregistered training program")
    steps, conditions = training["fine_tuning_steps"], training["fine_tuning_conditions_per_step"]
    scenarios, interval = training["fine_tuning_scenarios_per_condition"], training["checkpoint_interval"]
    rate = training["fine_tuning_learning_rate"]
    gamma = protocol["utility"]["risk_aversion"] if arm == "output_ndu" else 0.
    auxiliary_weight = (training["sft_continuation_supervised_weight"] if arm == "sft_continuation"
                        else training["output_RL_auxiliary_supervised_weight"])
    if (not isinstance(warm_snapshot, Snapshot) or steps < 1 or conditions < 1 or scenarios < 2
            or interval < 1 or not math.isfinite(rate) or rate <= 0
            or not math.isfinite(auxiliary_weight) or auxiliary_weight < 0
            or not math.isfinite(gamma) or gamma < 0):
        raise ValueError("Invalid fine-tuning configuration")
    if observer.training or any(p.requires_grad for p in observer.parameters()):
        raise ValueError("Only a frozen evaluation-mode primary observer is permitted")
    manifest = corpus.manifest["manifest_sha256"]
    if warm_snapshot.metadata.get("source_manifest_sha256") != manifest:
        raise ValueError("Warm start and training corpus source identities differ")
    warm_identity = warm_snapshot.verify_integrity()
    observer_identity = parameter_hash(observer)
    expected_observer = protocol.get("primary_observer_parameter_sha256", observer_identity)
    if observer_identity != expected_observer:
        raise ValueError("Primary observer differs from its registered identity")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    costs, completed, histories, checkpoints = {}, 0, [], []
    work = Counter()
    schedule, raw_rows_sha = hashlib.sha256(), hashlib.sha256()
    total_gradient_max, output_gradient_max, probe_rows = {}, {}, []
    pins = source_pins()
    protocol_sha = hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    registration = {"schema": "hepta.ndu-abc.actual-output-training-registration.v1",
                    "seed": seed, "arm": arm, "training": training,
                    "protocol_canonical_sha256": protocol_sha, "source_sha256": pins,
                    "warm_snapshot_sha256": warm_identity, "warm_parameter_sha256": warm_snapshot.parameter_sha256,
                    "primary_observer_parameter_sha256": observer_identity, "metric_sha256": METRIC_DIGEST,
                    "source_manifest_sha256": manifest, "source_roles_read": ["train"],
                    "torch_version": str(torch.__version__), "torch_threads": protocol["threads"],
                    "torch_deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                    "batch_seed_recipe": "seed*1000003 + 20261024 + zero_based_step",
                    "generation_seed_recipe": "seed*1000033 + 20261025 + zero_based_step",
                    "same_seed_does_not_imply_same_post_EOS_rng_consumption_across_models": True,
                    "risk_aversion": gamma, "observed_loss_argument": "minus_actual_utility",
                    "native_auxiliary_weight": auxiliary_weight,
                    "actual_output_score_used_in_optimizer": arm != "sft_continuation",
                    "pure_NDU_objective": arm == "output_ndu" and auxiliary_weight == 0,
                    "output_gradient_probe_steps": "1 and every checkpoint interval, including the last step",
                    "additional_gradient_probes_are_counted": True}
    try:
        write_json(output / "registration.json", registration)
        torch.set_num_threads(protocol["threads"])
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            configuration = dict(warm_snapshot.config)
            configuration.pop("architecture")
            model = SlotPortfolio(**configuration)
        model.load_state_dict(warm_snapshot.to_record()["state_dict"], strict=True)
        model.train().requires_grad_(True)
        optimizer = torch.optim.Adam(model.parameters(), lr=rate)
        named_parameters = tuple(model.named_parameters())
        rng = torch.Generator().manual_seed(training_seeds(seed, 0)[1])
        def checkpoint(step):
            batch_seed, generation_seed = training_seeds(seed, step)
            metadata = {**registration, "schedule_sha256": schedule.hexdigest(),
                        "training_rows_sha256": raw_rows_sha.hexdigest(), "completed_step": step,
                        "next_batch_seed": batch_seed, "next_generation_seed": generation_seed}
            checkpoints.append(save_training_checkpoint(output / "checkpoints" / f"step-{step:04d}.pt",
                                                        model, optimizer, step, rng, metadata))
        with measured_phase(costs, "checkpoint_and_ledger"):
            checkpoint(0)
        with (RawMediaArchive(output / "raw-media.zip") as archive,
              gzip.open(output / "training-outputs.jsonl.gz", "xt", encoding="utf-8") as rows,
              gzip.open(output / "trajectory-ledger.jsonl.gz", "xt", encoding="utf-8") as trajectories):
            for step in range(steps):
                batch_seed, generation_seed = training_seeds(seed, step)
                with measured_phase(costs, "batch_construction"):
                    batch = make_batch(corpus, "train", conditions, batch_seed)
                    observation = Observation(*(value.repeat_interleave(scenarios, 0)
                        for value in (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
                    target = Target(*(value.repeat_interleave(scenarios, 0)
                        for value in (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
                    rng = torch.Generator().manual_seed(generation_seed)
                with measured_phase(costs, "actual_generation"):
                    run = initialize(model, observation, generator=rng)
                    for action in protocol["fixed_policy"]:
                        run = transition(model, run, action, generator=rng)
                    work.update(work_counts(run))
                with measured_phase(costs, "physical_media_write_fsync_reopen"):
                    pixels, captions, records = archive.append(run.pixels, run.tokens)
                    if (len(records) != conditions * scenarios or not torch.equal(pixels, run.pixels.cpu())
                            or captions != [render_tokens(tokens) for tokens in run.tokens]):
                        raise ValueError("Actual training media did not round-trip faithfully")
                    # Empty captions are valid stochastic emissions. Keep them
                    # in the census and score their failure without resampling.
                with measured_phase(costs, "frozen_primary_scoring"):
                    observed = observe_tensors(observer, pixels, captions, target.pixels, target.labels)
                    # Scoring uses inference_mode internally. Python numbers are
                    # reconstructed here as ordinary tensors, outside that mode.
                    utility = torch.tensor([float(row["utility"]) for row in observed], dtype=torch.float32)
                    actual_loss = -utility.reshape(conditions, scenarios)
                    if torch.is_inference(actual_loss):
                        raise RuntimeError("Inference tensor escaped the scoring boundary")
                    work["primary_scored_output_pairs"] += len(observed)
                    work["primary_observer_panel_examples"] += 2 * len(observed)
                with measured_phase(costs, "objectives_and_auxiliary_decode"):
                    estimate = score_function_objective(run.terminal_log_probability.reshape(conditions, scenarios),
                                                        actual_loss, risk_aversion=gamma)
                    terms = model.loss(model.decode(run.state, teacher_tokens=target.text_tokens), target)
                    native = terms["joint"].mean()
                    objective = auxiliary_weight * native
                    if arm != "sft_continuation":
                        objective = objective + estimate.surrogate
                    if not torch.isfinite(objective):
                        raise FloatingPointError("Nonfinite generator objective")
                    work.update({"auxiliary_decoder_calls": 1, "auxiliary_pixel_panel_examples": 2 * len(utility),
                                 "auxiliary_teacher_forced_token_positions": 7 * len(utility)})
                with measured_phase(costs, "backward_and_optimizer"):
                    probe = arm != "sft_continuation" and (step == 0 or (step + 1) % interval == 0 or step + 1 == steps)
                    if probe:
                        gradients = torch.autograd.grad(estimate.surrogate, tuple(p for _, p in named_parameters),
                                                        retain_graph=True, allow_unused=True)
                        measured = gradient_by_module(named_parameters, gradients)
                        probe_rows.append({"step": step + 1, "output_score_only": measured})
                        for name, value in measured.items():
                            output_gradient_max[name] = max(output_gradient_max.get(name, 0.), value)
                        work["output_score_gradient_probe_backwards"] += 1
                    optimizer.zero_grad(set_to_none=True)
                    objective.backward()
                    gradients = gradient_by_module(named_parameters, tuple(p.grad for _, p in named_parameters))
                    for name, value in gradients.items():
                        total_gradient_max[name] = max(total_gradient_max.get(name, 0.), value)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
                    optimizer.step()
                    work["optimizer_updates"] += 1
                    work["total_objective_backwards"] += 1
                completed = step + 1
                with measured_phase(costs, "checkpoint_and_ledger"):
                    schedule_row = {"step": completed, "batch_seed": batch_seed, "generation_seed": generation_seed,
                                    "observation_sha256": observation_digest(batch.observation),
                                    "source_ids": batch.source_ids, "views": batch.views}
                    schedule.update(json.dumps(schedule_row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
                    token_rows = run.tokens.tolist()
                    logps = run.terminal_log_probability.detach().tolist()
                    for index, (raw, metric) in enumerate(zip(records, observed)):
                        row = {"step": completed, "condition": index // scenarios, "scenario": index % scenarios,
                               "source_ids": batch.source_ids[index // scenarios], "view": batch.views[index // scenarios],
                               "batch_seed": batch_seed, "generation_seed": generation_seed, "raw": raw,
                               "sampled_tokens": token_rows[index], "terminal_log_probability": logps[index],
                               "actual_observed_loss": -float(metric["utility"]), "metric": metric}
                        line = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
                        rows.write(line)
                        raw_rows_sha.update(line.encode())
                    trajectories.write(json.dumps({"step": completed, "events": run.ledger}, sort_keys=True) + "\n")
                    rows.flush()
                    trajectories.flush()
                    history = {"step": completed, "native_supervised_joint": float(native.detach()),
                               "actual_utility_mean": float(utility.mean()),
                               "actual_joint_loss_mean": sum(row["joint_loss"] for row in observed) / len(observed),
                               "actual_loss_mean": float(actual_loss.mean()),
                               "score_surrogate_value_not_risk_value": float(estimate.surrogate.detach()),
                               "empirical_transformed_moment": estimate.empirical_transformed_moment,
                               "empirical_joint_loss_ce": estimate.empirical_joint_loss_ce,
                               "empirical_mean_conditional_loss_ce": estimate.empirical_mean_conditional_loss_ce,
                               "empirical_exponential_moment": estimate.empirical_exponential_moment,
                               "optimized_objective_value": float(objective.detach()),
                               "actual_output_score_used_in_optimizer": arm != "sft_continuation"}
                    histories.append(history)
                    if completed % interval == 0 or completed == steps:
                        checkpoint(completed)
                    if completed == 1 or completed % interval == 0 or completed == steps:
                        print(json.dumps({"seed": seed, "arm": arm, **history}, sort_keys=True), flush=True)
        if (source_pins() != pins or warm_snapshot.verify_integrity() != warm_identity
                or parameter_hash(observer) != observer_identity):
            raise RuntimeError("Frozen training source, warm start or primary observer changed")
        metadata = {"profile": arm, "seed": seed, "source_manifest_sha256": manifest,
                    "protocol_canonical_sha256": protocol_sha, "warm_snapshot_sha256": warm_identity,
                    "actual_output_score_used_in_optimizer": arm != "sft_continuation",
                    "risk_aversion": gamma, "native_auxiliary_weight": auxiliary_weight}
        with measured_phase(costs, "final_snapshot_and_reports"):
            snapshot = Snapshot(model, metadata)
            checkpoint_sha = snapshot.save(output / "model.pt")
            write_json(output / "history.json", histories)
            write_json(output / "gradient-probes.json", probe_rows)
            artifacts = {name: {"bytes": (output / name).stat().st_size,
                                "sha256": hashlib.sha256((output / name).read_bytes()).hexdigest()}
                         for name in ("raw-media.zip", "training-outputs.jsonl.gz", "trajectory-ledger.jsonl.gz",
                                      "history.json", "gradient-probes.json", "model.pt", "registration.json")}
        report = {"schema": "hepta.ndu-abc.actual-output-training-result.v1", "status": "completed",
                  **metadata, "completed_steps": completed, "terminal_output_rows": completed * conditions * scenarios,
                  "source_sha256": pins, "schedule_sha256": schedule.hexdigest(),
                  "training_rows_sha256": raw_rows_sha.hexdigest(), "artifacts": artifacts,
                  "final_parameter_sha256": snapshot.parameter_sha256, "final_snapshot_sha256": snapshot.fingerprint,
                  "checkpoint_file_sha256": checkpoint_sha, "optimizer_checkpoints": checkpoints,
                  "total_gradient_abs_sum_max": total_gradient_max,
                  "output_score_gradient_abs_sum_max": output_gradient_max,
                  "work": dict(work), "nested_phases": costs,
                  "invocation_wall_ns": time.perf_counter_ns() - whole_wall,
                  "invocation_cpu_ns": time.process_time_ns() - whole_cpu,
                  "cost_scope": "Entry through sealed media, all training/checkpoint I/O and artifact hashes; final summary write belongs to external process receipt.",
                  "new_held_out_task_outcomes_opened": False,
                  "training_outputs_are_model_admission_evidence": False}
        write_json(output / "summary.json", report)
        return snapshot, report
    except BaseException as error:
        write_json(output / "failure.json", {"status": "failed", "error": repr(error),
                   "traceback": traceback.format_exc(), "completed_steps": completed,
                   "known_completed_work": dict(work), "partial_step_work_may_be_unmeasured": True,
                   "nested_phases": costs, "checkpoints": checkpoints,
                   "wall_ns": time.perf_counter_ns() - whole_wall, "cpu_ns": time.process_time_ns() - whole_cpu})
        raise
