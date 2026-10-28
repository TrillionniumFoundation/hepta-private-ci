"""Independent density/gradient replay of the completed native trajectory study.

Reconstruct every sampled action from its immutable snapshot, public context and
recorded RNG seed. Require its original sampled-byte hash and raw preclip gradient
hash, then independently differentiate normalized Normal/Categorical densities.
This performs no native execution, scoring, update, selection or qualification.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from .natural_model import NaturalPortfolio, draw, parameter_hash
from .profile import NduProfile, digest


SIGMAS = {"image": 0.015, "video": 0.015, "audio": 0.0015}


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def components(model):
    result = {name: getattr(model, name) for name in
              ("encoder_video", "encoder_audio", "encoder_fusion", "initial_states", "shared_transition")}
    result.update({f"adapter_{name}": module for name, module in model.adapters.items()})
    result.update({f"emission_{name}": module for name, module in model.emissions.items()})
    return result


def sampled_sha(values):
    value = hashlib.sha256()
    for name, tensor in sorted(values.items()):
        value.update(name.encode())
        value.update(tensor.detach().cpu().numpy().tobytes())
    return value.hexdigest()


def gradient_records(model):
    result = {}
    for name, module in components(model).items():
        value = hashlib.sha256()
        gradients = []
        for parameter_name, parameter in module.named_parameters():
            if parameter.grad is None or not torch.isfinite(parameter.grad).all():
                raise ValueError(f"Missing or nonfinite replay gradient: {name}.{parameter_name}")
            value.update(parameter_name.encode())
            value.update(parameter.grad.detach().cpu().numpy().tobytes())
            gradients.append(parameter.grad.detach().flatten().double())
        flat = torch.cat(gradients)
        result[name] = {"raw_gradient_sha256": value.hexdigest(), "l2": float(flat.norm()),
                        "max_abs": float(flat.abs().max()), "nonzero_elements": int(torch.count_nonzero(flat)),
                        "elements": flat.numel()}
    return result


def verify_receipt(row, profile, checkpoint_sha, tariff, run):
    owner = row["native_execution"]
    if (row["profile_sha256"] != profile.digest or row["checkpoint_sha256"] != checkpoint_sha
            or owner["binding"]["profile_sha256"] != profile.digest
            or owner["binding"]["generator_checkpoint"] != checkpoint_sha
            or row["policy"]["current_checkpoint_sha256"] != checkpoint_sha
            or row["policy"]["current_parameter_sha256"] != row["parameter_sha256"]
            or owner["binding"]["policy_sha256"] != digest(row["policy"])):
        raise ValueError("Episode/current-snapshot/profile/policy binding differs")
    count = 1 + int(owner["executed_action"] == "swap")
    if (row["actual_emission_scores"] != count or len(row["emissions"]) != count
            or owner["measurements"]["actual_generator_calls"] != count):
        raise ValueError("An actual emission was omitted or an unexecuted retry was scored")
    emissions = row["emissions"]
    if any(emission["model_parameter_sha256"] != row["parameter_sha256"] for emission in emissions):
        raise ValueError("Parameter identity changed during an actual trajectory")
    if count == 2:
        if (emissions[0]["rng_after_sha256"] != emissions[1]["rng_before_sha256"]
                or emissions[0]["sampled_sha256"] == emissions[1]["sampled_sha256"]):
            raise ValueError("Retry was not a fresh draw from the advancing episode generator")
    if row["private_scoring_started_ns"] < row["owner_closed_ns"]:
        raise ValueError("Private scoring preceded the actual owner stop")
    if row["kernel_executions"] != 17 or owner["measurements"]["cold_recovery_kernel_steps"] != 10:
        raise ValueError("Unexpected native continuation/recovery work")
    costs = row["complete_costs"]
    if len({cost["event_id"] for cost in costs}) != len(costs):
        raise ValueError("Repeated event in the complete trajectory ledger")
    if any(cost["amount"] < 0 or not math.isfinite(cost["amount"])
           or cost["unit"] != profile.cost_unit for cost in costs):
        raise ValueError("Invalid trajectory cost")
    native_costs = {cost["event_id"]: cost for cost in owner["costs"]}
    measured = owner["measurements"]
    quantities = {"native_kernel": measured["actual_original_kernel_executions"],
                  "generator_call": measured["actual_generator_calls"],
                  "delivery": measured["actual_delivery_units"],
                  "refused_proposal": int(owner["permit"]["proposed"] and not owner["permit"]["execution_admitted"]),
                  "python_cpu_second": measured["python_cpu_seconds"],
                  "native_cpu_second": measured["native_cpu_seconds"], "wall_second": measured["wall_seconds"]}
    if (owner["binding"]["tariff"] != tariff or len(native_costs) != len(quantities)
            or {cost["kind"]: cost["amount"] for cost in native_costs.values()}
            != {kind: quantity * tariff[kind] for kind, quantity in quantities.items()}):
        raise ValueError("Physical native/dispatch counts and CPU measurements do not reproduce their charges")
    if any(cost not in costs for cost in native_costs.values()):
        raise ValueError("An actual native/dispatch/recovery charge was omitted")
    extras = [cost for cost in costs if cost["event_id"] not in native_costs]
    required = {"host_snapshot_binding_cpu", "terminal_readback_private_scoring_cpu", "per_episode_preparation_cpu"}
    if len(extras) != len(required) or {cost["kind"] for cost in extras} != required:
        raise ValueError("Every episode must charge preparation, binding and post-stop scoring exactly once")
    preparation = next(cost for cost in extras if cost["kind"] == "per_episode_preparation_cpu")
    if preparation["event_id"] != owner["case"] + ":public-context-and-policy-preparation":
        raise ValueError("Public input/policy preparation is not bound to its actual episode")
    utility = row["terminal_score"]["utility"]
    if row["terminal_kind"] == "failed" and utility != 0:
        raise ValueError("A failed physical terminal outcome changed the declared failure utility")
    value = utility - math.fsum(cost["amount"] for cost in costs)
    if not math.isclose(value, row["net_return"], rel_tol=0, abs_tol=2e-14):
        raise ValueError("Complete terminal utility and actual costs do not reproduce the return")
    # Files are read only to verify provenance; no reward observer is invoked.
    if Path(owner["case"]).name != owner["case"]:
        raise ValueError("Episode case cannot escape its archived run directory")
    original_scope = Path(owner["permit"]["scope"])
    actual_scope = run / "episodes" / owner["case"]
    copies = [owner["initial"]] + ([owner["final"]] if count == 2 else [])
    for copy in copies:
        for name, path in copy["artifact_refs"].items():
            relative = Path(path).relative_to(original_scope)
            if ".." in relative.parts or file_sha(actual_scope / relative) != copy["artifact_sha256"][name]:
                raise ValueError("Actual emitted file bytes changed or escaped their original episode scope")


def replay_update(step, run, protocol, profile, rows, contexts):
    update = json.loads((run / f"UPDATE-{step:02d}.json").read_text())
    checkpoint = run / f"theta-{step:02d}.pt"
    checkpoint_sha = file_sha(checkpoint)
    if checkpoint_sha != update["snapshot"]["sha256"]:
        raise ValueError("Current parameter snapshot changed")
    snapshot = torch.load(checkpoint, weights_only=True, map_location="cpu")
    model = NaturalPortfolio(snapshot["vocabulary"]).eval().requires_grad_(True)
    model.load_state_dict(snapshot["model"])
    if snapshot["profile_sha256"] != profile.digest or snapshot["parameter_sha256"] != parameter_hash(model):
        raise ValueError("Snapshot profile or parameter identity differs")
    selected = sorted((row for row in rows if row["phase"] == "train" and row["ordinal"] == step),
                      key=lambda row: row["replicate"])
    if [row["replicate"] for row in selected] != list(range(protocol["independent_complete_episodes_per_update"])):
        raise ValueError("A complete training trajectory is missing or repeated")
    previous = (json.loads((run / f"UPDATE-{step - 1:02d}.json").read_text())["mean_moment_cost"]
                if step else 0.0)
    if update["baseline_used"] != previous:
        raise ValueError("Baseline is not the declared previous-batch value")
    values, replayed_scores, held, log_errors = [], [], [], []
    for row in selected:
        if (row["source_event"] != protocol["train_sources"][step]
                or row["seed"] != protocol["seed"] + 100 * step + row["replicate"]
                or row["parameter_sha256"] != snapshot["parameter_sha256"]
                or row["policy"]["vocabulary_sha256"] != digest(snapshot["vocabulary"])):
            raise ValueError("Training input/seed differs from the predeclared source schedule")
        verify_receipt(row, profile, checkpoint_sha, protocol["continuation"]["tariff"], run)
        index = row["source_event"]["index"]
        video = torch.from_numpy(contexts["context_video"][index:index + 1].copy()).float().permute(0, 1, 4, 2, 3) / 255
        audio = torch.from_numpy(contexts["context_audio"][index:index + 1].copy()).float()
        rng = torch.Generator().manual_seed(row["seed"])
        scores = []
        for emission in row["emissions"]:
            if hashlib.sha256(rng.get_state().numpy().tobytes()).hexdigest() != emission["rng_before_sha256"]:
                raise ValueError("Sample RNG state differs before replay")
            samples, score = draw(model(video, audio), rng)
            normalizer = sum(samples[name][0].numel() * (math.log(sigma) + 0.5 * math.log(2 * math.pi))
                             for name, sigma in SIGMAS.items())
            score = (score - normalizer).sum()
            if (sampled_sha(samples) != emission["sampled_sha256"]
                    or hashlib.sha256(rng.get_state().numpy().tobytes()).hexdigest() != emission["rng_after_sha256"]):
                raise ValueError("Replayed action differs from the actual sampled trajectory")
            if float(score.detach()) != emission["log_probability"]:
                raise ValueError("Actual emitted log density does not reproduce exactly")
            held.append((video, audio, {name: value.detach() for name, value in samples.items()}))
            scores.append(score)
        total = torch.stack(scores).sum()
        log_errors.append(abs(float(total.detach()) - row["trajectory_log_probability"]))
        if log_errors[-1] != 0:
            raise ValueError("Complete-trajectory score differs from its actual emission census")
        replayed_scores.append(total)
        values.append(math.expm1(-profile.gamma * row["net_return"]) / profile.gamma)
    mean_cost = sum(values) / len(values)
    if mean_cost != update["mean_moment_cost"]:
        raise ValueError("Joint-batch loss differs from actual complete net returns")
    weight = mean_cost - update["baseline_used"]
    joint_score = torch.stack(replayed_scores).sum()
    if float(joint_score.detach()) != update["actual_joint_score"]:
        raise ValueError("Actual joint-batch score changed")
    loss = weight * joint_score
    loss.backward()
    actual = gradient_records(model)
    if actual != update["preclip_gradients"]:
        raise ValueError("Raw actual training gradients do not reproduce byte for byte")
    if len(actual) != 13 or any(value["l2"] <= 0 for value in actual.values()):
        raise ValueError("An actual trajectory gradient did not reach one of the 13 components")
    expected_gradients = {name: value.grad.detach().clone() for name, value in model.named_parameters()}
    model.zero_grad(set_to_none=True)
    independent = []
    for video, audio, samples in held:
        means = model(video, audio)
        terms = [torch.distributions.Normal(means[name], sigma).log_prob(samples[name]).flatten(1).sum(1)
                 for name, sigma in SIGMAS.items()]
        terms.append(torch.distributions.Categorical(logits=means["text"]).log_prob(samples["text"]).sum(1))
        independent.append(torch.stack(terms).sum())
    independent_joint_score = torch.stack(independent).sum()
    density_error = abs(float(independent_joint_score.detach()) - update["actual_joint_score"])
    if not math.isclose(float(independent_joint_score.detach()), update["actual_joint_score"], rel_tol=2e-6, abs_tol=0.05):
        raise ValueError("Independent normalized full-trajectory density disagrees")
    (weight * independent_joint_score).backward()
    errors, squared, reference_squared = {}, [], []
    for name, parameter in model.named_parameters():
        left, right = expected_gradients[name], parameter.grad
        if right is None or not torch.isfinite(right).all():
            raise ValueError("Independent normalized density lost a parameter gradient")
        difference = (left - right).double()
        if not torch.allclose(left, right, atol=0.0002, rtol=0.0002):
            raise ValueError(f"Independent full-density gradient disagrees: {name}")
        errors[name] = float(difference.abs().max())
        squared.append(float(difference.square().sum()))
        reference_squared.append(float(left.double().square().sum()))
    relative = math.sqrt(math.fsum(squared) / math.fsum(reference_squared))
    if relative > 2e-6:
        raise ValueError("Independent full-density gradient exceeds the float32 tolerance")
    return {"step": step, "snapshot_sha256": checkpoint_sha, "complete_episodes": len(selected),
            "actual_emissions": len(held), "maximum_trajectory_log_density_replay_error": max(log_errors),
            "all_13_raw_gradient_records_identical": len(actual) == 13,
            "all_13_component_gradients_nonzero": all(value["l2"] > 0 for value in actual.values()),
            "independent_normalized_joint_log_density_abs_error": density_error,
            "independent_density_gradient_relative_l2_error": relative,
            "independent_density_gradient_max_abs_error": max(errors.values()),
            "terminal_kinds": [row["terminal_kind"] for row in selected],
            "continuation_kinds": [row["native_execution"]["continuation_kind"] for row in selected]}


def run_review(*, run, assets, output):
    run, assets, output = map(Path, (run, assets, output))
    if output.exists():
        raise FileExistsError("Preserve previous independent review evidence")
    protocol = json.loads((run / "PROTOCOL.json").read_text())
    frozen = json.loads((run / "FROZEN.json").read_text())
    summary = json.loads((run / "SUMMARY.json").read_text())
    profile = NduProfile.from_dict(json.loads((run / "PROFILE.json").read_text()))
    if (frozen["protocol_sha256"] != file_sha(run / "PROTOCOL.json")
            or summary["protocol_sha256"] != frozen["protocol_sha256"]
            or frozen["profile_sha256"] != profile.digest or summary["profile_sha256"] != profile.digest
            or protocol["profile_sha256"] != profile.digest):
        raise ValueError("Frozen diagnostic protocol/profile chain differs")
    for name in ("objective", "observer", "continuation"):
        if digest(protocol[name]) != getattr(profile, name + "_sha256"):
            raise ValueError("Profile semantics differ from the frozen execution contract")
    package = Path(__file__).resolve().parent
    for name, expected in frozen["source_code_sha256"].items():
        if file_sha(package / name) != expected:
            raise ValueError(f"Executed source differs from the frozen study: {name}")
    arrays = assets / "EVENTS.npz"
    if file_sha(arrays) != protocol["source_arrays_sha256"]:
        raise ValueError("Public source arrays changed")
    with np.load(arrays) as archive:
        contexts = {name: archive[name] for name in ("context_video", "context_audio")}
    rows = [json.loads(path.read_text()) for path in sorted((run / "episodes").glob("*/EPISODE.json"))]
    expected_rows = protocol["steps"] * protocol["independent_complete_episodes_per_update"] + len(protocol["development_sources"])
    if len(rows) != expected_rows:
        raise ValueError("The completed diagnostic lost or repeated an episode")
    cost_ids = [cost["event_id"] for row in rows for cost in row["complete_costs"]]
    if len(cost_ids) != len(set(cost_ids)):
        raise ValueError("Different actual episodes reuse a cost event identity")
    development = sorted((row for row in rows if row["phase"] == "development"), key=lambda row: row["ordinal"])
    if [row["source_event"] for row in development] != protocol["development_sources"]:
        raise ValueError("Development deployment differs from its frozen source census")
    final_path = run / f"theta-{protocol['steps']:02d}.pt"
    final_sha = file_sha(final_path)
    final = torch.load(final_path, weights_only=True, map_location="cpu")
    if final_sha != summary["final_checkpoint"]["sha256"] or final["profile_sha256"] != profile.digest:
        raise ValueError("Deployment checkpoint/profile differs from the saved final model")
    final_model = NaturalPortfolio(final["vocabulary"]).eval()
    final_model.load_state_dict(final["model"])
    if parameter_hash(final_model) != final["parameter_sha256"]:
        raise ValueError("Deployment parameter identity does not match actual saved tensors")
    for row in development:
        verify_receipt(row, profile, final_sha, protocol["continuation"]["tariff"], run)
        if (row["parameter_sha256"] != final["parameter_sha256"] or row["replicate"] != 0
                or row["policy"]["vocabulary_sha256"] != digest(final["vocabulary"])
                or row["seed"] != protocol["seed"] + 10000 + 100 * row["ordinal"]):
            raise ValueError("Development deployment did not use the final parameters and declared seed")
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    updates = [replay_update(step, run, protocol, profile, rows, contexts) for step in range(protocol["steps"])]
    report = {"schema": "hepta.ndu.native-joint-independent-gradient-review.v2", "passed": True,
              "profile_sha256": profile.digest, "protocol_sha256": file_sha(run / "PROTOCOL.json"),
              "review_source_sha256": file_sha(__file__), "torch_version": torch.__version__,
              "updates": updates, "training_episodes_replayed": sum(row["complete_episodes"] for row in updates),
              "actual_emissions_replayed": sum(row["actual_emissions"] for row in updates),
              "development_deployment_receipts_verified": len(development),
              "all_episodes_charge_preparation_binding_execution_scoring_once": True,
              "additional_native_executions": 0, "optimizer_updates": 0, "private_score_calls": 0,
              "neural_forward_replays": 2 * sum(row["actual_emissions"] for row in updates),
              "new_media_deliveries": 0,
              "sampler_replay_purpose": "verify original latent hashes and raw gradients; not new random evidence",
              "independent_density": "normalized torch Normal/Categorical, held actual actions, all parameter gradients",
              "scope": "frozen diagnostic training trajectories only; no efficacy, generalization or tail certificate",
              "timing_assumption": protocol["continuation"]["cpu_gradient_model"],
              "cost_boundary": "charged every episode's public-input tensor/hash/policy preparation, checkpoint binding/verification, owner+dispatch+codec CPU, post-stop readback/scoring; only one-time load and training/checkpoint/report work excluded"}
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "assets", "output"):
        parser.add_argument("--" + name, required=True)
    report = run_review(**vars(parser.parse_args()))
    print(json.dumps({key: report[key] for key in ("passed", "training_episodes_replayed",
          "actual_emissions_replayed", "additional_native_executions")}))
