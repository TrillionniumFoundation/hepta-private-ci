"""Independent evidence audit: no candidate model, training, or analysis imports.

This module recomputes metrics from serialized observations and raw predictions.
It never trains a model, selects a checkpoint, or repairs experimental records.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def read_npz(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: np.array(archive[key], copy=True) for key in archive.files}


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def serialized_metrics(path):
    """Stable cross entropy and exact correctness from saved raw logits."""
    data = read_npz(path)
    logits = np.asarray(data["logits"], dtype=np.float64)
    labels = np.asarray(data["labels"])
    if (logits.ndim != 2 or not len(logits) or labels.shape != (len(logits),)
            or not np.isfinite(logits).all()
            or not np.issubdtype(labels.dtype, np.integer)
            or np.any(labels < 0) or np.any(labels >= logits.shape[1])):
        raise ValueError("Malformed finite logits/class-label archive")
    shifted = logits - logits.max(axis=1, keepdims=True)
    logsum = np.log(np.exp(shifted).sum(axis=1))
    ce = logsum - shifted[np.arange(len(labels)), labels]
    correct = logits.argmax(axis=1) == labels
    if "correct" in data and not np.array_equal(correct, data["correct"]):
        raise ValueError("Stored correctness disagrees with logits")
    identifiers = data["sample_ids"].astype(str)
    groups = data["group_ids"].astype(str)
    exact = [bool(correct[identifiers == key].all()) for key in np.unique(identifiers)]
    group_scores = {key: dict(queries=int((groups == key).sum()),
        accuracy=float(correct[groups == key].mean()),
        cross_entropy=float(ce[groups == key].mean())) for key in np.unique(groups)}
    return dict(prediction_sha256=digest(path), observations=len(labels),
                classes=logits.shape[1], accuracy=float(correct.mean()),
                cross_entropy=float(ce.mean()), episodes=len(exact),
                episode_exact_recall=float(np.mean(exact)), independent_groups=len(group_scores),
                group_scores=group_scores if len(group_scores) <= 20 else None), data


def audit_process_receipt(path, expected_meter_sha=None, repository_root=None):
    """Reconcile whole-worker numbers without treating subtotals as additions."""
    receipt = read_json(path)
    errors = []
    if receipt.get("schema") == "hcsn-fourtrack-whole-process.v1":
        for name in ("wall_sec", "cpu_user_sec", "cpu_system_sec", "cpu_total_sec", "peak_rss_kib"):
            value = receipt.get(name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                errors.append("Invalid worker cost field: " + name)
        if not errors and not math.isclose(receipt["cpu_user_sec"] + receipt["cpu_system_sec"],
                receipt["cpu_total_sec"], rel_tol=1e-12, abs_tol=1e-9):
            errors.append("Worker CPU total differs from user+system")
        if receipt.get("exit_code") != 0 or not receipt.get("executed") or receipt.get("missing_outputs"):
            errors.append("Worker failed or a required output is absent")
        for stream in ("stdout", "stderr"):
            log = Path(path).parent / (stream + ".log")
            if not log.is_file() or digest(log) != receipt.get(stream + "_sha256"):
                errors.append("Worker log identity mismatch: " + stream)
        for output in receipt.get("outputs", []):
            recorded_root = Path(receipt["cwd"])
            target = recorded_root / output["path"]
            if repository_root is not None and target.is_relative_to(recorded_root):
                target = Path(repository_root).resolve() / target.relative_to(recorded_root)
            if (not target.is_file() or digest(target) != output["sha256"]
                    or target.stat().st_size != output["bytes"]):
                errors.append("Worker output identity mismatch: " + output["path"])
        return dict(receipt_sha256=digest(path), job_id=receipt["job_id"], errors=errors,
                    audit_ok=not errors, plan_sha256=receipt["plan_sha256"],
                    costs={key: receipt.get(key) for key in
                           ("wall_sec", "cpu_total_sec", "peak_rss_kib", "direct_energy_joules")})
    for name in ("wall_seconds", "child_user_seconds", "child_system_seconds",
                 "child_cpu_seconds", "supervisor_cpu_seconds", "child_peak_rss_bytes"):
        value = receipt.get(name)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            errors.append("Invalid worker cost field: " + name)
    if not errors and not math.isclose(receipt["child_user_seconds"] + receipt["child_system_seconds"],
                                       receipt["child_cpu_seconds"], abs_tol=1e-9, rel_tol=1e-12):
        errors.append("Worker CPU total differs from user+system")
    if receipt.get("returncode") != 0 or receipt.get("timed_out") or not receipt.get("child_reaped"):
        errors.append("Worker did not complete normally")
    if receipt.get("inner_training_clocks_are_subtotals") is not True:
        errors.append("Missing explicit nested-clock accounting contract")
    if expected_meter_sha and receipt.get("meter_source_sha256") != expected_meter_sha:
        errors.append("Meter source differs from registration")
    log = Path(receipt.get("log_path", ""))
    if not log.is_absolute():
        log = Path(receipt.get("cwd", ".")) / log
    if repository_root is not None and log.is_relative_to(Path(receipt.get("cwd", "."))):
        log = Path(repository_root).resolve() / log.relative_to(Path(receipt.get("cwd", ".")))
    if not log.is_file() or digest(log) != receipt.get("log_sha256"):
        errors.append("Worker stdout/stderr identity is absent or differs")
    return dict(receipt_sha256=digest(path), errors=errors, audit_ok=not errors,
                costs={name: receipt.get(name) for name in
                    ("wall_seconds", "child_cpu_seconds", "supervisor_cpu_seconds",
                     "child_peak_rss_bytes", "direct_energy_joules", "gpu_energy_joules",
                     "communication_energy_joules")},
                scope=receipt.get("cpu_scope"), exclusions=receipt.get("excluded"))


def audit_content_run(directory, *, allow_heldout=False):
    """Recompute a finished content worker from serialized records only."""
    directory = Path(directory)
    summary, job = read_json(directory / "summary.json"), read_json(directory / "job.json")
    selection = read_json(directory / "selection.json")
    trace, access = read_jsonl(directory / "trace.jsonl"), read_jsonl(directory / "access.jsonl")
    source = read_json(directory / "data_sources.json")
    errors, metrics = [], {}
    if summary.get("job") != job or summary.get("completed") is not True:
        errors.append("Incomplete worker or executed job mismatch")
    if summary.get("heldout_access") and not allow_heldout:
        raise PermissionError("Heldout prediction audit is not authorized yet")
    if [row["step"] for row in trace] != list(range(1, summary["final_step"] + 1)):
        errors.append("Training trace omits or repeats optimizer steps")
    for row in trace:
        if not all(math.isfinite(row[key]) for key in ("loss", "gradient_norm", "training_cpu")):
            errors.append("Nonfinite training trace")
        if any(index < 0 or index >= len(source["train_ids"]) for index in row["selected_indices"]):
            errors.append("Training minibatch index outside training split")
    if set(source["train_ids"]) & set(source["validation_ids"]):
        errors.append("Train/validation sample identity overlap")
    records = selection["validation_records"]
    if not records or any(not math.isfinite(row["ce"]) for row in records):
        raise ValueError("Missing or nonfinite validation selection trace")
    eligible = [row for row in records if row["step"] > 0 or selection.get("initial_allowed", True)]
    picked = min(eligible, key=lambda row: (row["ce"], row["step"]))
    if (picked["step"] != selection["selected_step"]
            or picked["step"] != summary["selected_step"]
            or not math.isclose(picked["ce"], selection["best_validation_ce"], abs_tol=1e-12)):
        errors.append("Selected checkpoint is not the first minimum validation CE")
    if records[0]["step"] != 0 or [r["step"] for r in records] != sorted({r["step"] for r in records}):
        errors.append("Invalid ordered validation-selection steps")
    for record in access:
        if record["split"] in ("test", "ood"):
            if not record.get("after_selection") or not record.get("allowed_heldout"):
                errors.append("Heldout open before selected checkpoint or without authorization")
            if not summary.get("heldout_access"):
                errors.append("Training-only worker accessed heldout data")
    selected_hash = digest(directory / "selected.pt")
    if selected_hash != selection["selected_checkpoint_sha256"] or selected_hash != summary["selected_checkpoint_sha256"]:
        errors.append("Selected checkpoint file identity mismatch")
    if digest(directory / "final.pt") != selection["final_checkpoint_sha256"]:
        errors.append("Final checkpoint file identity mismatch")
    import torch
    initial_path = directory / "initial_parameters.pt"
    if digest(initial_path) != summary.get("initial_parameters_sha256"):
        errors.append("Initial raw parameter identity mismatch")
    initial = torch.load(initial_path, map_location="cpu", weights_only=True)
    checkpoints = {name: torch.load(directory / (name + ".pt"), map_location="cpu", weights_only=True)
                   for name in ("selected", "final")}
    # Initial evidence serializes named parameters, whereas the model hash also
    # covers immutable buffers. Reconstruct only the declared fixed buffer,
    # require agreement at both later checkpoints, and bind it to the original
    # full initialization hash. This does not infer or change any model weight.
    buffers = {name: value for name, value in checkpoints["selected"]["model_state"].items()
               if name not in initial["parameters"]}
    expected_buffers = {"adapter.fixed_boundary"} if job["family"] == "analytic" else set()
    if set(buffers) != expected_buffers or any(not torch.equal(value,
            checkpoints["final"]["model_state"][name]) for name, value in buffers.items()):
        errors.append("Unexpected or changing nonparameter buffer in initialized model")
    buffer_contract = None
    if "adapter.fixed_boundary" in buffers:
        # Independently solve the scalar constructor's fixed-constant equation;
        # later checkpoint agreement alone is insufficient initialization proof.
        mu, sigma, rho, cost, reset, tau, slope = .1, .45, .45, .525, -.1, .75, -.0275
        discount = (1 + rho * tau / 2) ** -2
        constant = slope * mu / rho ** 2
        effective_cost = (cost + constant - discount * (slope * reset / rho + constant)) / (1 - slope / rho)
        kappa = 2 * rho / (math.sqrt(mu ** 2 + 2 * rho * sigma ** 2) + mu)
        low, high = effective_cost, effective_cost + 1 / kappa
        for _ in range(70):
            middle = (low + high) / 2
            residual = middle - effective_cost - (1 - discount * math.exp(kappa * (reset - middle))) / kappa
            if residual > 0:
                high = middle
            else:
                low = middle
        fixed_expected = (low + high) / 2
        fixed_error = float((buffers["adapter.fixed_boundary"].double() - fixed_expected).abs().max())
        if fixed_error > 5e-7:
            errors.append("Fixed buffer differs from the frozen constructor's constant boundary equation")
        defining_sources = ("experiments/hcsn_task_value_v1/model.py",
                            "experiments/hcsn_task_value_v1/operators.py",
                            "experiments/hcsn_free_boundary_v1/oracle_torch.py")
        buffer_contract = dict(name="adapter.fixed_boundary", archive_scope="initial_parameters.pt contains named_parameters only",
            source_contract="Constructor registers a nonparameter fixed boundary from constant physical inputs; value-mode training does not assign this buffer",
            defining_source_sha256={name: digest(REPOSITORY / name) for name in defining_sources},
            constant_inputs=dict(mu=mu, sigma=sigma, rho=rho, cost=cost, reset=reset, tau=tau, slope=slope, stages=2),
            independently_solved_boundary=fixed_expected, maximum_buffer_error=fixed_error,
            selected_and_final_equal=all(torch.equal(value, checkpoints["final"]["model_state"][name]) for name, value in buffers.items()),
            proof="Frozen constructor equation plus raw later buffer identity plus original full initialization digest; not later equality alone")
    initial_digest = hashlib.sha256()
    for name, value in sorted({**initial["parameters"], **buffers}.items()):
        value = value.detach().cpu().contiguous()
        initial_digest.update(name.encode())
        initial_digest.update(str((str(value.dtype), tuple(value.shape))).encode())
        initial_digest.update(value.numpy().tobytes())
    if initial_digest.hexdigest() != summary["initialization_model_sha256"]:
        errors.append("Initial raw tensors disagree with declared initialization hash")
    for field, names in (("total_parameters", list(initial["parameters"])),
            ("trainable_parameters", [n for n, flag in initial["requires_grad"].items() if flag]),
            ("shared_parameters", [n for n in initial["parameters"] if n.startswith("common.")])):
        if sum(initial["parameters"][name].numel() for name in names) != summary[field]:
            errors.append("Raw parameter count differs from summary: " + field)
    grouped_names = [name for names in initial["groups"].values() for name in names]
    if sorted(grouped_names) != sorted(initial["parameters"]):
        errors.append("Raw parameter groups do not partition the initialized parameters")
    changes = {}
    for which, checkpoint in checkpoints.items():
        if checkpoint["job"] != job or checkpoint["step"] != summary[which + "_step"]:
            errors.append("Checkpoint job or step mismatch: " + which)
        state = checkpoint["model_state"]
        computed = hashlib.sha256()
        for name, tensor in sorted(state.items()):
            value = tensor.detach().cpu().contiguous()
            if not bool(torch.isfinite(value).all()):
                errors.append("Nonfinite saved model parameter: " + name)
            computed.update(name.encode())
            computed.update(str((str(value.dtype), tuple(value.shape))).encode())
            computed.update(value.numpy().tobytes())
        if computed.hexdigest() != checkpoint["model_sha256"]:
            errors.append("Raw model tensors disagree with parameter hash: " + which)
        if any(not torch.equal(value, state["common." + name]) for name, value in checkpoint["common_state"].items()):
            errors.append("Checkpoint shared state disagrees with complete model: " + which)
        changes[which] = {}
        for group, names in initial["groups"].items():
            changed, maximum = 0, 0.0
            for name in names:
                before, after = initial["parameters"][name], state[name]
                unequal = not torch.equal(before, after)
                delta = float((after - before).abs().max())
                changed += int(unequal)
                maximum = max(maximum, delta)
                if not initial["requires_grad"][name] and unequal:
                    errors.append("Frozen raw parameter changed: " + which + ":" + name)
            reported = summary[which + "_group_changes"][group]
            if changed != reported["changed_tensors"] or not math.isclose(maximum, reported["max_abs_change"], abs_tol=1e-12):
                errors.append("Parameter-change summary differs from raw tensors: " + which + ":" + group)
            changes[which][group] = dict(changed_tensors=changed, max_abs_change=maximum)
    # Independently reconstruct the training-only minibatch RNG stream, including
    # the saved state at the selected update rather than merely the final update.
    random = np.random.default_rng(job["seed"] + 7109)
    selected_rng = random.bit_generator.state if summary["selected_step"] == 0 else None
    for row in trace:
        expected_indices = random.integers(0, len(source["train_ids"]), size=len(row["selected_indices"]))
        if expected_indices.tolist() != row["selected_indices"]:
            errors.append("Training minibatch stream differs from registered seed")
            break
        if row["step"] == summary["selected_step"]:
            selected_rng = random.bit_generator.state
    if selected_rng != checkpoints["selected"]["numpy_rng"] or random.bit_generator.state != checkpoints["final"]["numpy_rng"]:
        errors.append("Selected/final checkpoint RNG differs from recorded training prefix")
    source_identity = read_json(directory / "source_identity.json")
    for path, expected_hash in source_identity.items():
        if digest(REPOSITORY / path) != expected_hash:
            errors.append("Executed source differs from current audited source: " + path)
    if job.get("pretrained"):
        if digest(job["pretrained"]) != job["pretrained_sha256"]:
            errors.append("Shared pretrained checkpoint identity mismatch")
        if summary.get("pretrained_checkpoint_sha256") != job["pretrained_sha256"]:
            errors.append("Inherited shared checkpoint differs from registration")
        donor = torch.load(job["pretrained"], map_location="cpu", weights_only=True)
        if any(not torch.equal(value, initial["parameters"]["common." + name])
               for name, value in donor["common_state"].items()):
            errors.append("Raw initialized shared parameters differ from exact donor checkpoint")
        if (summary.get("shared_donor_selected_step") != donor["step"]
                or summary.get("shared_donor_trained") != (donor["step"] > 0)):
            errors.append("Declared donor trained/initial status differs from checkpoint")
    if job.get("content_mode") == "frozen_shared" and len({summary["shared_initial_sha256"],
            summary["shared_final_sha256"], summary["shared_selected_sha256"]}) != 1:
        errors.append("Frozen common encoder/attention/readout changed")
    expected_conditions = {f"val_length{job.get('length', 32)}_normal"}
    if summary.get("heldout_access"):
        audiovisual = job["task"] in ("async_av", "av_binding")
        lengths = [job.get("length", 32)] if audiovisual else job.get("eval_lengths", [32, 64, 128])
        expected_conditions.update(f"test_length{length}_normal" for length in lengths)
        if job["family"] != "shared":
            expected_conditions.add(f"test_length{job.get('length', 32)}_normal_adapter_disabled")
        if job.get("diagnostics", True):
            diagnostics = ["content_shuffle"]
            if audiovisual:
                diagnostics += ["missing_audio", "missing_video"]
            if job["task"] == "async_av":
                diagnostics.append("modality_mismatch")
            if job["task"] == "av_binding":
                diagnostics.append("metadata_only")
            if job["task"] == "mqar":
                diagnostics.append("query_permute")
            expected_conditions.update(f"test_length{lengths[0]}_{case}" for case in diagnostics)
    if set(summary["results"]) != expected_conditions:
        errors.append("Recorded prediction conditions differ from complete predeclared evaluation plan")
    prediction_files = {path.stem.removeprefix("predictions_") for path in directory.glob("predictions_*.npz")}
    if prediction_files != expected_conditions:
        errors.append("Raw prediction archive cohort differs from predeclared conditions")
    profile = read_json(directory / "inference_profile_validation.json")
    wall_times = np.asarray(profile["per_batch_wall_seconds"], dtype=np.float64)
    if (profile["selected_checkpoint_sha256"] != selected_hash
            or profile["input_array_sha256"] != source["validation"]["array_sha256"]
            or profile["request_ids"] != source["validation_ids"]
            or len(wall_times) != len(source["validation_ids"])
            or profile["batch_size"] != 1 or np.any(wall_times <= 0)):
        errors.append("Prepared single-request profile cohort or checkpoint differs")
    profile_wall = profile["prepared_input_batch_loop_wall_seconds"]
    if profile_wall + 1e-7 < float(wall_times.sum()) or any(n != 1 for n in profile["per_batch_samples"]):
        errors.append("Prepared request profile timing/batch-count accounting differs")
    for field, count in (("samples_per_second", len(source["validation_ids"])),
                          ("queries_per_second", sum(profile["per_batch_queries"]))):
        if not math.isclose(count / profile_wall, profile[field], rel_tol=1e-12, abs_tol=1e-9):
            errors.append("Prepared inference throughput differs from raw cohort and loop time")
    for field, probability in (("p50_wall_seconds", .5), ("p95_wall_seconds", .95)):
        if not math.isclose(float(np.quantile(wall_times, probability)), profile[field], abs_tol=1e-12):
            errors.append("Prepared request latency quantile differs from raw timings")
    for case, expected in summary["results"].items():
        if case.startswith(("test_", "ood_")) and not allow_heldout:
            raise PermissionError("Refuse to read heldout prediction archive")
        actual, raw = serialized_metrics(directory / ("predictions_" + case + ".npz"))
        if not math.isclose(actual["accuracy"], expected["accuracy"], abs_tol=1e-12):
            errors.append("Accuracy summary differs from saved logits: " + case)
        if not math.isclose(actual["cross_entropy"], expected["ce"], abs_tol=3e-6, rel_tol=3e-6):
            errors.append("Cross entropy summary differs from saved logits: " + case)
        if actual["observations"] != expected["queries"]:
            errors.append("Supervised-query count differs: " + case)
        if str(raw["checkpoint_sha256"].item()) != selected_hash:
            errors.append("Prediction checkpoint identity differs: " + case)
        if str(raw["model_sha256"].item()) != summary["model_parameter_sha256"]:
            errors.append("Prediction parameter identity differs: " + case)
        if str(raw["input_array_sha256"].item()) != expected["array_sha256"]:
            errors.append("Prediction input identity differs: " + case)
        sample_ids, positions = raw["sample_ids"].astype(str), raw["position"]
        if len(set(zip(sample_ids, positions, strict=True))) != len(sample_ids):
            errors.append("Duplicate prediction sample/query identity: " + case)
        if len(set(sample_ids)) != expected["samples"]:
            errors.append("Independent sample count differs: " + case)
        if (np.any(positions < 0) or not np.isfinite(raw["readout_time"]).all()
                or raw["readout_time"].shape != raw["labels"].shape):
            errors.append("Malformed prediction event time/position: " + case)
        shifted = raw["logits"].astype(np.float64)
        shifted -= shifted.max(axis=1, keepdims=True)
        probability = np.exp(shifted)
        probability /= probability.sum(axis=1, keepdims=True)
        if not np.allclose(probability, raw["probabilities"], atol=1e-7, rtol=1e-6):
            errors.append("Stored probabilities disagree with logits: " + case)
        if job["task"] == "async_av":
            split = "validation" if case.startswith("val_") else "test"
            original = read_npz(Path(job["av_directory"]) / (split + ".npz"))
            lookup = {str(identifier): (int(label), str(actor)) for identifier, label, actor in
                      zip(original["clip_ids"], original["labels"], original["actors"], strict=True)}
            if set(sample_ids) != set(lookup) or len(sample_ids) != len(lookup):
                errors.append("AV prediction cohort differs from original clips: " + case)
            for identifier, label, group in zip(sample_ids, raw["labels"], raw["group_ids"], strict=True):
                if lookup.get(identifier) != (int(label), str(group)):
                    errors.append("AV prediction label/group differs from original source: " + case)
            actual["independent_actor_units"] = len(set(raw["group_ids"].astype(str)))
        elif job["task"] == "av_binding":
            audio, video = raw["audio_source_ids"].astype(str), raw["video_source_ids"].astype(str)
            labels = raw["labels"]
            if not np.array_equal(labels, (audio == video).astype(np.int64)):
                errors.append("Binding target differs from source-identity relation: " + case)
            if (not np.array_equal(raw["group_ids"].astype(str), raw["donor_group_ids"].astype(str))
                    or not np.array_equal(raw["pair_group_ids"].astype(str), audio)):
                errors.append("Binding actor/pair group identity mismatch: " + case)
            split = "validation" if case.startswith("val_") else "test"
            original = read_npz(Path(job["av_directory"]) / (split + ".npz"))
            permitted = set(original["clip_ids"].astype(str))
            for modality in (audio, video):
                if set(modality) != permitted:
                    errors.append("Binding source cohort differs from original split: " + case)
                for identifier in permitted:
                    if sorted(labels[modality == identifier].tolist()) != [0, 1]:
                        errors.append("Binding has unbalanced single-source class marginals: " + case)
            retained = audio if case.endswith("missing_video") else video if case.endswith("missing_audio") else None
            if retained is not None:
                largest = 0.0
                for identifier in permitted:
                    paired = raw["logits"][retained == identifier]
                    largest = max(largest, float(np.max(np.abs(paired[0] - paired[1]))))
                if largest > 3e-6:
                    errors.append("Identical single-modality source predicts different binding labels: " + case)
                actual["maximum_single_modality_pair_logit_difference"] = largest
            actual["independent_actor_units"] = len(set(raw["group_ids"].astype(str)))
        actual["input_array_sha256"] = expected["array_sha256"]
        actual["sample_ids"] = sorted(set(sample_ids))
        metrics[case] = actual
    return dict(directory=str(directory), job=job, errors=errors, audit_ok=not errors,
                summary_sha256=digest(directory / "summary.json"),
                selection_sha256=digest(directory / "selection.json"),
                selected_checkpoint_sha256=selected_hash, metrics=metrics,
                final_step=summary["final_step"], selected_step=summary["selected_step"],
                heldout_access=summary["heldout_access"], source_data=source,
                initial_immutable_buffers_reconstructed=sorted(buffers),
                initial_buffer_source_contract=buffer_contract,
                independently_recomputed_parameter_changes=changes,
                shared_donor_trained=summary.get("shared_donor_trained"))


def audit_prepared_av():
    """Verify cached frontend identity and independently rebuild its features.

    This verifies the prepared arrays. It does not replace source-media decode
    receipts or establish that this previously inspected cohort is a blind test.
    """
    identity_path = PACKAGE / "DATA_IDENTITY.json"
    identity = read_json(identity_path)
    result = dict(identity_sha256=digest(identity_path), splits={}, errors=[],
                  old_heldout_previously_observed=identity.get("old_heldout_previously_observed"),
                  fresh_confirmation=identity.get("fresh_confirmation"),
                  scope="Prepared feature arrays; no independent raw-media decoding")
    errors = result["errors"]
    if identity.get("fresh_confirmation") is not False:
        errors.append("Previously observed AV cohort must not be described as fresh confirmation")
    data = {}
    for entry in identity["causal_prepared_features"]:
        path = REPOSITORY / entry["path"]
        split = path.stem
        if split not in ("train", "validation", "test") or split in data:
            raise ValueError("Duplicate or unknown AV split identity")
        if digest(path) != entry["sha256"] or path.stat().st_size != entry["bytes"]:
            errors.append("Prepared AV identity mismatch: " + split)
        data[split] = read_npz(path)
    if set(data) != {"train", "validation", "test"}:
        raise ValueError("Incomplete AV split identity")
    actors = {split: set(values["actors"].astype(str)) for split, values in data.items()}
    if any(actors[a] & actors[b] for a, b in
           (("train", "validation"), ("train", "test"), ("validation", "test"))):
        errors.append("Actor identity overlaps between splits")
    moments = {0: [], 1: []}
    unnormalized = {}
    labels_by_emotion = {"ANG": 0, "DIS": 1, "FEA": 2, "HAP": 3, "NEU": 4, "SAD": 5}
    for split, values in data.items():
        records = []
        clip_ids = values["clip_ids"].astype(str)
        if len(set(clip_ids)) != len(clip_ids):
            errors.append("Duplicate AV clip: " + split)
        if (len(values["offsets"]) != len(clip_ids) + 1
                or values["offsets"][0] != 0
                or values["offsets"][-1] != len(values["x"])
                or np.any(np.diff(values["offsets"]) <= 0)):
            raise ValueError("Invalid nonempty clip offsets: " + split)
        for index, clip in enumerate(clip_ids):
            begin, end = values["offsets"][index:index + 2]
            base = values["base"][begin:end].astype(np.float64)
            times = values["times"][begin:end]
            kinds = values["modality"][begin:end]
            width = base.shape[1]
            payload = np.zeros((len(base), width * 2), dtype=np.float64)
            previous = np.zeros((2, width), dtype=np.float64)
            seen = np.zeros(2, dtype=bool)
            last = np.zeros(2, dtype=np.float64)
            metadata = np.zeros((len(base), 8), dtype=np.float64)
            for row, (feature, stamp, kind) in enumerate(zip(base, times, kinds, strict=True)):
                kind = int(kind)
                delta = feature - previous[kind] if seen[kind] else np.zeros(width)
                payload[row] = np.r_[feature, delta]
                previous[kind], seen[kind], last[kind] = feature, True, stamp
                metadata[row, kind] = metadata[row, kind + 2] = 1
                metadata[row, 4:6] = np.where(seen, stamp - last, 0)
                metadata[row, 6:8] = seen
            if split == "train":
                for kind in (0, 1):
                    # The published moments were fit to the float32 frontend
                    # output before normalization, then accumulated in float64.
                    subset = payload[kinds == kind].astype(np.float32).astype(np.float64)
                    moments[kind].append((subset.mean(0), (subset ** 2).mean(0)))
            if (not np.isfinite(payload).all() or not np.isfinite(times).all()
                    or np.any(np.diff(times) < 0)
                    or not np.array_equal(np.lexsort((kinds, times)), np.arange(len(times)))):
                errors.append("Noncausal or nonfinite prepared chronology: " + clip)
            expected_dt = np.diff(np.r_[values["origins"][index], times]).astype(np.float32)
            if not np.array_equal(expected_dt, values["dt"][begin:end]):
                errors.append("Physical dt disagrees with timestamps: " + clip)
            actor, _, emotion, _ = clip.split("_")
            if str(values["actors"][index]) != actor or int(values["labels"][index]) != labels_by_emotion[emotion]:
                errors.append("Clip identity/actor/emotion label disagreement: " + clip)
            records.append((begin, end, payload, metadata, kinds))
        unnormalized[split] = records
        result["splits"][split] = dict(clips=len(clip_ids), actors=sorted(actors[split]),
            events=len(values["x"]), clip_ids=clip_ids.tolist())
    mean = np.asarray([np.mean([item[0] for item in moments[kind]], axis=0) for kind in (0, 1)])
    second = np.asarray([np.mean([item[1] for item in moments[kind]], axis=0) for kind in (0, 1)])
    scale = np.maximum(np.sqrt(np.maximum(second - mean ** 2, 0)), 0.01)
    max_error = 0.0
    for split, values in data.items():
        if (not np.allclose(mean, values["normalization_mean"], atol=1e-10, rtol=1e-10)
                or not np.allclose(scale, values["normalization_scale"], atol=1e-10, rtol=1e-10)):
            errors.append("Normalization disagrees with independent train-only recomputation: " + split)
        for begin, end, payload, metadata, kinds in unnormalized[split]:
            rebuilt = np.c_[(payload - mean[kinds]) / scale[kinds], metadata].astype(np.float32)
            error = float(np.max(np.abs(rebuilt - values["x"][begin:end])))
            max_error = max(max_error, error)
            if not np.allclose(rebuilt, values["x"][begin:end], atol=2e-5, rtol=2e-6):
                errors.append("Prepared feature reconstruction differs: " + split)
                break
    result["maximum_feature_reconstruction_error"] = max_error
    result["independent_actor_units_in_test"] = len(actors["test"])
    result["audit_ok"] = not errors
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--content-root", type=Path, action="append", default=[])
    parser.add_argument("--receipt-root", type=Path, action="append", default=[])
    parser.add_argument("--allow-heldout", action="store_true")
    parser.add_argument("--repository-root", type=Path,
                        help="Current checkout for receipt output hashes; original execution metadata is unchanged")
    args = parser.parse_args()
    result = dict(schema="hcsn-mechanism-content-independent-audit.v2",
                  audit_source_sha256=digest(__file__), prepared_av=audit_prepared_av(),
                  receipt_file_verification_root=str(args.repository_root.resolve()) if args.repository_root else None,
                  content_runs=[], process_receipts=[])
    for root in args.content_root:
        for summary in sorted(root.rglob("summary.json")):
            if read_json(summary).get("schema") == "hcsn-content-v2.summary":
                result["content_runs"].append(audit_content_run(summary.parent, allow_heldout=args.allow_heldout))
    for root in args.receipt_root:
        result["process_receipts"].extend(audit_process_receipt(path, repository_root=args.repository_root)
                                          for path in sorted(root.rglob("whole_process.json")))
    result["audit_ok"] = result["prepared_av"]["audit_ok"] and all(
        row["audit_ok"] for row in result["content_runs"] + result["process_receipts"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"audit_ok": result["audit_ok"], "content_runs": len(result["content_runs"]),
                      "process_receipts": len(result["process_receipts"])}))


if __name__ == "__main__":
    main()
