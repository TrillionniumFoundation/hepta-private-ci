"""Verify exact optimization continuity by replaying a sealed training suffix.

This is recovery evidence, not another independent training seed or a new
evaluation outcome. The original corpus role, generation law, actual-media
reward and Adam update are unchanged; replay outputs are retained separately.
"""

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import time
import traceback

import torch

from ..v6.data import Observation, Target
from ..v6.neural import parameter_hash
from ..v6.observer import observe_tensors
from ..v7.data import make_batch
from ..v7.model import SlotPortfolio
from .emission import score_function_objective
from .media import RawMediaArchive
from .output_training import measured_phase, source_pins, training_seeds
from .runtime import initialize, transition, work_counts
from .warm_start import save_training_checkpoint, write_json


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_verified_checkpoint(path, expected_sha256):
    """Hash first, then weights-only load; allow only a known TorchVersion type."""
    require(file_sha(path) == expected_sha256, "Checkpoint SHA mismatch before deserialization")
    allowed = []
    try:
        record = torch.load(path, map_location="cpu", weights_only=True)
    except pickle.UnpicklingError:
        unsafe = torch.serialization.get_unsafe_globals_in_checkpoint(path)
        require(set(unsafe) == {"torch.torch_version.TorchVersion"},
                "Checkpoint requires an unrecognized deserialization global")
        from torch.torch_version import TorchVersion
        with torch.serialization.safe_globals([TorchVersion]):
            record = torch.load(path, map_location="cpu", weights_only=True)
        allowed = ["torch.torch_version.TorchVersion"]
    return record, allowed


def _exact(actual, expected, path, counts, tensor_counter):
    if isinstance(expected, torch.Tensor):
        require(isinstance(actual, torch.Tensor) and actual.dtype == expected.dtype
                and actual.shape == expected.shape and torch.equal(actual.detach().cpu(), expected.detach().cpu()),
                "Exact tensor mismatch: " + path)
        counts[tensor_counter] += 1
    elif isinstance(expected, dict):
        require(isinstance(actual, dict) and actual.keys() == expected.keys(), "Mapping keys differ: " + path)
        for key in expected:
            _exact(actual[key], expected[key], f"{path}/{key}", counts, tensor_counter)
    elif isinstance(expected, (tuple, list)):
        require(type(actual) is type(expected) and len(actual) == len(expected), "Sequence differs: " + path)
        for index, (value, reference) in enumerate(zip(actual, expected)):
            _exact(value, reference, f"{path}/{index}", counts, tensor_counter)
    else:
        require(type(actual) is type(expected) and actual == expected, "Scalar differs: " + path)


@torch.inference_mode(False)
@torch.enable_grad()
def verify_resume(directory, corpus_train, observer, output, *, start_step):
    """Replay updates after start_step through the original final checkpoint.

    Every original timing-only gradient probe is also executed, so even that
    observational operation is matched. No optimizer or RNG state is guessed.
    Per-step generators are restored/reseeded by the registered recipe; their
    final states and the global torch RNG are compared exactly.
    """
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    directory, output = Path(directory), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    costs, work, checks, matched_steps, allowances = {}, Counter(), Counter(), 0, {}
    phase, current_step = "sealed_inputs", start_step
    try:
        summary = json.loads((directory / "summary.json").read_text())
        require(summary["status"] == "completed" and not (directory / "failure.json").exists(), "Training arm is not sealed")
        required = ("registration.json", "training-outputs.jsonl.gz", "trajectory-ledger.jsonl.gz", "history.json", "model.pt")
        input_hashes = {name: summary["artifacts"][name]["sha256"] for name in required}
        input_hashes["summary.json"] = file_sha(directory / "summary.json")
        for name, expected in input_hashes.items():
            require(file_sha(directory / name) == expected, "Sealed artifact SHA mismatch: " + name)
        registration = json.loads((directory / "registration.json").read_text())
        training, seed, arm = registration["training"], registration["seed"], registration["arm"]
        end_step = training["fine_tuning_steps"]
        require(type(start_step) is int and 0 < start_step < end_step, "Invalid checkpoint suffix")
        require(set(corpus_train.splits) == {"train"} and registration["source_roles_read"] == ["train"]
                and registration["source_manifest_sha256"] == corpus_train.manifest["manifest_sha256"], "Training source role/manifest mismatch")
        require(not observer.training and not any(p.requires_grad for p in observer.parameters()), "Observer is not frozen")
        observer_sha = parameter_hash(observer)
        require(observer_sha == registration["primary_observer_parameter_sha256"], "Primary observer mismatch")
        require(str(torch.__version__) == registration["torch_version"], "Torch version differs from recorded training")
        require(source_pins() == registration["source_sha256"], "Original training dependencies changed")
        pins = {**registration["source_sha256"], "resume_verify.py": file_sha(__file__)}
        checkpoint_rows = {row["step"]: row for row in summary["optimizer_checkpoints"]}
        require(start_step in checkpoint_rows and end_step in checkpoint_rows, "Requested optimizer checkpoints were not recorded")
        for step in (start_step, end_step):
            input_hashes[f"checkpoints/step-{step:04d}.pt"] = checkpoint_rows[step]["sha256"]
        with measured_phase(costs, "verified_checkpoint_loading"):
            start, allowances["start"] = load_verified_checkpoint(directory / f"checkpoints/step-{start_step:04d}.pt", checkpoint_rows[start_step]["sha256"])
            final, allowances["final"] = load_verified_checkpoint(directory / f"checkpoints/step-{end_step:04d}.pt", checkpoint_rows[end_step]["sha256"])
            snapshot, allowances["snapshot"] = load_verified_checkpoint(directory / "model.pt", input_hashes["model.pt"])
        for step, record in ((start_step, start), (end_step, final)):
            require(record["schema"] == "hepta.ndu-abc.optimizer-checkpoint.v1" and record["step"] == step,
                    "Optimizer checkpoint schema/step mismatch")
            require(all(record["metadata"][key] == value for key, value in registration.items()), "Checkpoint registration mismatch")
            require(record["parameter_sha256"] == checkpoint_rows[step]["parameter_sha256"], "Checkpoint parameter identity mismatch")
        require((start["metadata"]["next_batch_seed"], start["metadata"]["next_generation_seed"]) == training_seeds(seed, start_step),
                "Checkpoint next-step RNG recipes disagree")
        verify_registration = {"schema": "hepta.abc.optimizer-resume-verification.v1", "seed": seed, "arm": arm,
            "source_directory": str(directory.resolve()), "source_sha256": pins, "input_file_sha256": input_hashes,
            "start_step": start_step, "end_step": end_step, "source_roles_read": ["train"],
            "primary_observer_parameter_sha256": observer_sha, "unsafe_pickle_enabled": False,
            "allowed_serialization_globals": allowances, "original_gradient_probes_preserved": True,
            "verification_is_additional_independent_experiment": False, "new_outcomes_used_for_tuning": False}
        write_json(output / "registration.json", verify_registration)
        torch.set_num_threads(registration["torch_threads"])
        torch.use_deterministic_algorithms(registration["torch_deterministic_algorithms"])
        conditions, scenarios = training["fine_tuning_conditions_per_step"], training["fine_tuning_scenarios_per_condition"]
        gamma, auxiliary = registration["risk_aversion"], registration["native_auxiliary_weight"]
        histories = json.loads((directory / "history.json").read_text())
        require(len(histories) == end_step, "History step census differs")
        original_rows_sha, replay_rows_sha, suffix_sha = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
        phase = "restore_and_replay"
        with torch.random.fork_rng(devices=[]):
            config = dict(start["model_config"])
            config.pop("architecture")
            model = SlotPortfolio(**config).train().requires_grad_(True)
            model.load_state_dict(start["state_dict"], strict=True)
            require(parameter_hash(model) == start["parameter_sha256"], "Restored model differs before continuation")
            optimizer = torch.optim.Adam(model.parameters(), lr=training["fine_tuning_learning_rate"])
            optimizer.load_state_dict(start["optimizer_state_dict"])
            _exact(optimizer.state_dict(), start["optimizer_state_dict"], "restored_adam", checks, "restored_adam_tensor_checks")
            torch.set_rng_state(start["torch_rng_state"])
            rng = torch.Generator()
            rng.set_state(start["generation_rng_state"])
            named_parameters = tuple(model.named_parameters())
            with (gzip.open(directory / "training-outputs.jsonl.gz", "rt", encoding="utf-8") as original,
                  gzip.open(directory / "trajectory-ledger.jsonl.gz", "rt", encoding="utf-8") as trajectories,
                  gzip.open(output / "replayed-outputs.jsonl.gz", "xt", encoding="utf-8") as replayed,
                  (output / "step-verification.jsonl").open("x", encoding="utf-8") as step_log,
                  RawMediaArchive(output / "replayed-raw-media.zip") as archive):
                for step in range(1, end_step + 1):
                    current_step = step
                    with measured_phase(costs, "original_evidence_read"):
                        lines = [original.readline() for _ in range(conditions * scenarios)]
                        require(all(lines), "Missing original output rows")
                        reference = [json.loads(line) for line in lines]
                        trajectory = json.loads(trajectories.readline())
                        require(trajectory["step"] == step, "Original trajectory census differs")
                        for index, row in enumerate(reference):
                            require((row["step"], row["condition"], row["scenario"]) == (step, index // scenarios, index % scenarios),
                                    "Original output census differs")
                        original_rows_sha.update("".join(lines).encode())
                    if step <= start_step:
                        replay_rows_sha.update("".join(lines).encode())
                        if step == start_step:
                            require(original_rows_sha.hexdigest() == start["metadata"]["training_rows_sha256"], "Checkpoint does not bind the original row prefix")
                        continue
                    with measured_phase(costs, "batch_and_actual_generation"):
                        batch_seed, generation_seed = training_seeds(seed, step - 1)
                        batch = make_batch(corpus_train, "train", conditions, batch_seed)
                        observation = Observation(*(value.repeat_interleave(scenarios, 0) for value in
                            (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
                        target = Target(*(value.repeat_interleave(scenarios, 0) for value in
                            (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
                        rng = torch.Generator().manual_seed(generation_seed)
                        run = initialize(model, observation, generator=rng)
                        for action in ("refine_image", "refine_text"):
                            run = transition(model, run, action, generator=rng)
                        work.update(work_counts(run))
                        require(json.loads(json.dumps(run.ledger)) == trajectory["events"], f"Actual runtime trajectory differs at step {step}")
                    with measured_phase(costs, "new_actual_media_write_reopen_and_primary_scoring"):
                        pixels, captions, records = archive.append(run.pixels, run.tokens)
                        observed = observe_tensors(observer, pixels, captions, target.pixels, target.labels)
                        utility = torch.tensor([float(row["utility"]) for row in observed], dtype=torch.float32)
                        actual_loss = -utility.reshape(conditions, scenarios)
                    with measured_phase(costs, "same_objective_backward_and_adam"):
                        estimate = score_function_objective(run.terminal_log_probability.reshape(conditions, scenarios), actual_loss, risk_aversion=gamma)
                        native = model.loss(model.decode(run.state, teacher_tokens=target.text_tokens), target)["joint"].mean()
                        objective = auxiliary * native
                        if arm != "sft_continuation":
                            objective = objective + estimate.surrogate
                        if arm != "sft_continuation" and (step % training["checkpoint_interval"] == 0 or step == end_step):
                            torch.autograd.grad(estimate.surrogate, tuple(p for _, p in named_parameters), retain_graph=True, allow_unused=True)
                            work["output_score_gradient_probe_backwards"] += 1
                        optimizer.zero_grad(set_to_none=True)
                        objective.backward()
                        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
                        optimizer.step()
                        work.update({"optimizer_updates": 1, "total_objective_backwards": 1,
                                     "primary_scored_output_pairs": len(records), "auxiliary_decoder_calls": 1})
                    with measured_phase(costs, "exact_rows_and_history_comparison"):
                        for index, (raw, metric, expected) in enumerate(zip(records, observed, reference)):
                            row = {"step": step, "condition": index // scenarios, "scenario": index % scenarios,
                                "source_ids": batch.source_ids[index // scenarios], "view": batch.views[index // scenarios],
                                "batch_seed": batch_seed, "generation_seed": generation_seed, "raw": raw,
                                "sampled_tokens": run.tokens[index].tolist(),
                                "terminal_log_probability": float(run.terminal_log_probability[index].detach()),
                                "actual_observed_loss": -float(metric["utility"]), "metric": metric}
                            line = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
                            require(line == lines[index], f"Actual media/token/logprob/loss row differs at step {step}, output {index}")
                            replayed.write(line)
                            replay_rows_sha.update(line.encode())
                            suffix_sha.update(line.encode())
                            checks.update({"exact_output_rows": 1, "actual_media_member_hashes": 2,
                                           "exact_terminal_logprob_checks": 1, "exact_actual_loss_checks": 1})
                        history = histories[step - 1]
                        for key, value in {"native_supervised_joint": float(native.detach()),
                            "actual_utility_mean": float(utility.mean()), "actual_loss_mean": float(actual_loss.mean()),
                            "score_surrogate_value_not_risk_value": float(estimate.surrogate.detach()),
                            "optimized_objective_value": float(objective.detach())}.items():
                            require(history[key] == value, f"Objective/history mismatch at step {step}: {key}")
                        matched_steps += 1
                        step_log.write(json.dumps({"step": step, "exact_output_rows": len(reference),
                            "raw_image_token_digest": run.ledger[-1]["output_sha256"],
                            "generation_rng_after_sha256": hashlib.sha256(rng.get_state().numpy().tobytes()).hexdigest(),
                            "native_supervised_joint": float(native.detach()), "actual_loss_mean": float(actual_loss.mean())}, sort_keys=True) + "\n")
                        if matched_steps == 1 or step % 25 == 0 or step == end_step:
                            print(json.dumps({"phase": "resume_verified_step", "seed": seed, "arm": arm,
                                              "step": step, "matched_suffix_steps": matched_steps}), flush=True)
                require(original.read(1) == "" and trajectories.read(1) == "", "Extra original census rows")
            phase = "exact_final_optimizer_and_snapshot"
            with measured_phase(costs, "final_state_verification_and_checkpoint"):
                require(model.config == final["model_config"] == snapshot["config"], "Final model configuration mismatch")
                _exact(model.state_dict(), final["state_dict"], "final_parameters", checks, "final_parameter_tensor_checks")
                _exact(optimizer.state_dict(), final["optimizer_state_dict"], "final_adam", checks, "final_adam_tensor_checks")
                _exact(model.state_dict(), snapshot["state_dict"], "final_snapshot", checks, "snapshot_parameter_tensor_checks")
                _exact(torch.get_rng_state(), final["torch_rng_state"], "global_rng", checks, "final_rng_tensor_checks")
                _exact(rng.get_state(), final["generation_rng_state"], "generation_rng", checks, "final_rng_tensor_checks")
                final_sha = parameter_hash(model)
                require(final_sha == final["parameter_sha256"] == snapshot["parameter_sha256"] == summary["final_parameter_sha256"],
                        "Final parameter identity mismatch")
                require(original_rows_sha.hexdigest() == replay_rows_sha.hexdigest() == summary["training_rows_sha256"] ==
                        final["metadata"]["training_rows_sha256"], "Full original/replayed row digest mismatch")
                checkpoint = save_training_checkpoint(output / f"resumed-step-{end_step:04d}.pt", model, optimizer, end_step, rng,
                                                       {**verify_registration, "recovery_evidence_only": True})
        require(parameter_hash(observer) == observer_sha and source_pins() == registration["source_sha256"]
                and file_sha(__file__) == pins["resume_verify.py"], "Frozen observer or code changed during replay")
        for name, expected in input_hashes.items():
            require(file_sha(directory / name) == expected, "Original input changed during verification: " + name)
        artifacts = {name: {"sha256": file_sha(output / name), "bytes": (output / name).stat().st_size}
                     for name in ("registration.json", "replayed-outputs.jsonl.gz", "replayed-raw-media.zip", "step-verification.jsonl")}
        report = {"schema": "hepta.abc.optimizer-resume-verification-result.v1", "status": "passed", "passed": True,
            "seed": seed, "arm": arm, "start_step": start_step, "end_step": end_step, "matched_suffix_steps": matched_steps,
            "checks": dict(checks), "work": dict(work), "final_parameter_sha256": final_sha,
            "original_and_replayed_full_row_sha256": replay_rows_sha.hexdigest(), "replayed_suffix_row_sha256": suffix_sha.hexdigest(),
            "artifacts": artifacts, "resumed_checkpoint": checkpoint, "allowed_serialization_globals": allowances,
            "original_gradient_probes_preserved": True, "exact_tensor_comparison_tolerance": 0,
            "observed_metric_comparison_tolerance": 0, "source_roles_read": ["train"],
            "verification_is_additional_independent_experiment": False, "new_outcomes_used_for_tuning": False,
            "nested_phases": costs, "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
            "timer_scope": "Entry through replay, new media/checkpoint writes and final identity verification; enclosing process measures final receipts."}
        write_json(output / "result.json", report)
        return report
    except Exception as error:
        report = {"schema": "hepta.abc.optimizer-resume-verification-result.v1", "status": "failed", "passed": False,
            "phase": phase, "step": current_step, "error": repr(error), "traceback": traceback.format_exc(),
            "matched_suffix_steps": matched_steps, "checks": dict(checks), "work": dict(work),
            "allowed_serialization_globals": allowances, "nested_phases": costs,
            "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu}
        write_json(output / "failure.json", report)
        return report
