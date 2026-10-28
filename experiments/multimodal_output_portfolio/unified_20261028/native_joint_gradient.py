"""Bounded actual-trajectory LR training through the unchanged original owner.

Eight fixed updates and four original-development deployments prove a common
train/continuation/evaluation contract. They do not qualify a natural model.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..continuation_20261027.control.client import sha
from .natural_model import NaturalPortfolio, parameter_hash, score_bundle, SCORE_SPEC, cpu_seconds
from .native_joint_episode import episode, TARIFF
from .profile import NduProfile, CostEvent, digest, moment_cost, certainty_equivalent


INITIAL_SHA256 = "2c7068783532059479df475bb8c7b8d2c4721560a193a40513e8d0a50ef28617"
SCENARIOS = ((True, 7, 2), (False, 7, 2), (True, 6, 2), (True, 7, 1),
             (True, 6, 1), (True, 7, 2), (False, 6, 2), (False, 7, 1))
STEPS, REPLICATES, BASE_SEED, LEARNING_RATE = 8, 2, 28261001, 1e-5


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def components(model):
    result = {name: getattr(model, name) for name in
              ("encoder_video", "encoder_audio", "encoder_fusion", "initial_states", "shared_transition")}
    result.update({f"adapter_{name}": module for name, module in model.adapters.items()})
    result.update({f"emission_{name}": module for name, module in model.emissions.items()})
    return result


def gradients(model):
    result = {}
    for name, module in components(model).items():
        raw = [parameter.grad for parameter in module.parameters()]
        if any(value is None or not torch.isfinite(value).all() for value in raw):
            raise ValueError("An actual-reward component gradient is missing or nonfinite")
        flat = torch.cat([value.detach().flatten().double() for value in raw])
        h = hashlib.sha256()
        for parameter_name, parameter in module.named_parameters():
            h.update(parameter_name.encode())
            h.update(parameter.grad.detach().cpu().numpy().tobytes())
        result[name] = {"l2": float(flat.norm()), "max_abs": float(flat.abs().max()),
                        "nonzero_elements": int(torch.count_nonzero(flat)), "elements": flat.numel(),
                        "raw_gradient_sha256": h.hexdigest()}
    return result


def first_sources(events, split, count):
    selected, seen = [], set()
    for index, item in enumerate(events):
        if item["split"] == split and item["source_id"] not in seen:
            selected.append({"index": index, **{key: item[key] for key in ("event_id", "source_id", "split")}})
            seen.add(item["source_id"])
            if len(selected) == count:
                return selected
    raise ValueError("Insufficient original split sources for the fixed diagnostic")


def run(*, binary, checkpoint, assets, output):
    wall_started, total_cpu_started = time.perf_counter(), cpu_seconds()
    binary, checkpoint, assets, output = map(Path, (binary, checkpoint, assets, output))
    output.mkdir(parents=True, exist_ok=False)
    package = Path(__file__).resolve().parent
    owner = package.parent / "closure_v2_20261027/control/evidence/development-001"
    frozen = json.loads((owner / "FROZEN.json").read_text())
    if sha(binary) != frozen["binary_sha256"] or sha(checkpoint) != INITIAL_SHA256:
        raise ValueError("Original owner or preselected natural initialization changed")
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(BASE_SEED)
    parent = torch.load(checkpoint, weights_only=True, map_location="cpu")
    model = NaturalPortfolio(parent["vocabulary"]).eval().requires_grad_(True)
    model.load_state_dict(parent["model"])
    initial_components = {name: parameter_hash(module) for name, module in components(model).items()}
    events_doc = json.loads((assets / "EVENTS.json").read_text())
    if sha(assets / "EVENTS.npz") != events_doc["arrays_sha256"]:
        raise ValueError("Original source array hash changed")
    events = events_doc["events"]
    training, development = first_sources(events, "train", STEPS), first_sources(events, "development", 4)
    if {item["source_id"] for item in training} & {item["source_id"] for item in development}:
        raise ValueError("Original training/development source overlap")
    # Public arrays alone are made available to the model/owner closures.
    with np.load(assets / "EVENTS.npz") as archive:
        context_video, context_audio = archive["context_video"], archive["context_audio"]
    continuation = {"schema": "hepta.ndu.actual-natural-native-full-trajectory.v1",
        "binary_sha256": sha(binary), "readout_sha256": sha(owner / "MODEL.json"),
        "calibration_sha256": sha(owner / "ENCODER_DOMAIN_PROOF.json"),
        "implementation_sha256": {name: sha(package / name) for name in
            ("native_joint_gradient.py", "native_joint_episode.py", "control.py", "profile.py", "natural_model.py")},
        "actions": {"keep": "initial stochastic four-media neural emission", "swap": "fresh independent four-media emission from advanced episode RNG"},
        "native_decision": "unchanged original readout on arrived public transport-integrity scalar; original expiry and host media-budget checks",
        "native_authority": "DENY_ALL", "profile_binding_level": "host receipts only; original native scope objective unchanged",
        "calibration_scope": "original registered scalar encoder validity only, no claim of natural-semantic calibration",
        "control_mode": "fast without forecasts; mandatory actual cold replay; 17 original kernels per episode",
        "stop": "after actual native decision and optional admitted swap; maximum two emitted bundles",
        "public_feedback": "+1 physical four-file integrity/readback success; -1 actual codec or declared video transport failure",
        "fault": "when declared in public scenario, truncate only initial generated video.mkv to eight bytes",
        "private_score_phase": "only after owner closes, reopen final physical four files and apply frozen natural score",
        "failure_utility": 0., "tariff": asdict(TARIFF),
        "extra_cpu_charges": ["every-episode public input tensor preparation, public digest, current-checkpoint/parameter hashes and policy manifest assembly",
                              "current-snapshot load/hash/tensor/vocabulary verification", "post-stop identity check, final physical readback and private scoring"],
        "cpu_accounting": "all measured self+child CPU; inherited native_cpu_seconds field includes FFmpeg children as well as native owner",
        "cpu_gradient_model": "observed CPU realization conditionally exogenous; estimate stochastic-action LR only; no direct parameter derivative through runtime",
        "unbilled_setup_or_training": "one-time corpus/model load, optimizer/backward, checkpoint writes and diagnostic JSON serialization reported separately; not deployment return; all per-episode input/policy preparation is charged",
        "unexpected_computation_exception": "abort entire diagnostic, never silently omit an episode; sampled codec/transport failures retained with zero gross utility",
        "density": "Gaussian fixed normalizers restored in helper; every actually executed conditional sample density appears once",
        "parameter_update": "only after K complete trajectories; each next episode verifies current checkpoint tensors, vocabulary and parameter hash"}
    gross_score = {key: value for key, value in SCORE_SPEC.items() if key not in ("cost", "fixed_horizon")}
    objective = {"gross_score": gross_score, "actual_trajectory_tariff": asdict(TARIFF),
                 "failure_utility": 0., "cost_scope": continuation["extra_cpu_charges"],
                 "cpu_gradient_model": continuation["cpu_gradient_model"]}
    observer = {"frozen_natural_score_source_sha256": sha(package / "natural_model.py"),
                "physical_reopen_source_sha256": sha(package / "native_joint_episode.py")}
    profile = NduProfile(digest(objective), digest(observer), digest(continuation), gamma=2.,
                         aggregation="population", utility_bounds=(0., 1.),
                         required_modalities=("text", "audio", "image", "video"))
    protocol = {"schema": "hepta.ndu.native-joint-gradient-diagnostic.v1", "initial_checkpoint_sha256": sha(checkpoint),
        "initial_parent_profile_sha256": parent["profile_sha256"], "profile_sha256": profile.digest,
        "objective": objective, "observer": observer, "continuation": continuation,
        "source_events_sha256": sha(assets / "EVENTS.json"), "source_arrays_sha256": sha(assets / "EVENTS.npz"),
        "source_protocol_sha256": sha(assets / "SOURCE_PROTOCOL.json"), "train_sources": training, "development_sources": development,
        "source_selection": "first event from each of first distinct original split sources, before generating outcomes",
        "steps": STEPS, "independent_complete_episodes_per_update": REPLICATES, "seed": BASE_SEED,
        "scenarios": [{"fault": f, "expires": e, "budget": b} for f, e, b in SCENARIOS],
        "development_scenarios": "first four training scenario types; four original development sources; no selection",
        "optimizer": {"kind": "Adam", "learning_rate": LEARNING_RATE, "global_grad_clip_l2": 1.},
        "surrogate": "(mean_k moment_cost(complete_net_return_k,gamma)-previous_batch_baseline) * sum_k sum_actual_emissions log p_theta",
        "baseline": "zero on first batch, previous batch mean moment_cost thereafter; independent of current random draws",
        "joint_batch_reason": "retains cross scores if measured costs couple trajectories; mean already divides K, no additional division",
        "new_qualification": False, "efficacy_claim": False, "production_gates_passed": False,
        "finite_net_return_support": False, "tail_certificate_issued": False,
        "scope": "bounded mechanism proof of one new actual-trajectory profile, not a claim that prior profiles are identical or that original owner kernel parameters are trained"}
    save(output / "PROTOCOL.json", protocol)
    save(output / "PROFILE.json", profile.to_dict())
    save(output / "FROZEN.json", {"protocol_sha256": sha(output / "PROTOCOL.json"), "profile_sha256": profile.digest,
                                  "source_code_sha256": continuation["implementation_sha256"], "frozen_before_any_new_emission": True})
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    namespace = digest({"run_output": str(output.resolve())})[:16]
    snapshots, steps, all_episodes = [], [], []

    def snapshot(step):
        path = output / f"theta-{step:02d}.pt"
        theta = parameter_hash(model)
        torch.save({"model": model.state_dict(), "vocabulary": model.vocabulary, "profile_sha256": profile.digest,
                    "parameter_sha256": theta, "step": step, "initial_checkpoint_sha256": INITIAL_SHA256}, path)
        manifest = {"step": step, "path": str(path), "sha256": sha(path), "parameter_sha256": theta,
                    "profile_sha256": profile.digest}
        snapshots.append(manifest)
        return path

    def complete(item, scenario, phase, ordinal, replicate, current_checkpoint):
        preparation_started = cpu_seconds()
        index = item["index"]
        fault, expires, budget = scenario
        seed = BASE_SEED + 10000 * int(phase == "development") + ordinal * 100 + replicate
        case = f"{namespace}-{phase}-{ordinal:02d}-{replicate}"
        video = torch.from_numpy(context_video[index:index + 1].copy()).float().permute(0, 1, 4, 2, 3) / 255
        audio = torch.from_numpy(context_audio[index:index + 1].copy()).float()
        public = {key: item[key] for key in ("event_id", "source_id", "split")}
        public.update(emission_seed=seed, declared_transport_fault=fault,
            input_sha256=digest({"video": hashlib.sha256(context_video[index].tobytes()).hexdigest(),
                                "audio": hashlib.sha256(context_audio[index].tobytes()).hexdigest()}))

        def private_score(delivered):
            # This callback is invoked only after NativeController has closed.
            with np.load(assets / "EVENTS.npz") as archive:
                target = {name: archive["target_" + name][index] for name in ("video", "image", "audio")}
            target["video"] = target["video"].astype(np.float32) / 255
            target["image"] = target["image"].astype(np.float32) / 255
            return score_bundle(delivered, target, events[index]["caption"])

        policy = {"profile_sha256": profile.digest, "current_checkpoint_sha256": sha(current_checkpoint),
                  "current_parameter_sha256": parameter_hash(model), "vocabulary_sha256": digest(model.vocabulary),
                  "sampling": "stochastic joint four emission, fresh retry RNG", "implementation": continuation["implementation_sha256"]}
        policy_sha256 = digest(policy)
        preparation_cost = CostEvent(case + ":public-context-and-policy-preparation",
            .001 * (cpu_seconds() - preparation_started), profile.cost_unit, "per_episode_preparation_cpu")
        lp, value, receipt = episode(model=model, checkpoint=current_checkpoint, binary=binary,
            readout=owner / "MODEL.json", calibration=owner / "ENCODER_DOMAIN_PROOF.json",
            profile=profile, policy_sha256=policy_sha256, directory=output / "episodes" / case,
            case=case, public=public, video=video, audio=audio, seed=seed, fault=fault, expires=expires, budget=budget,
            private_score=private_score, implementation_paths=(__file__, package / "natural_model.py"), preparation_cost=preparation_cost)
        receipt.update(phase=phase, ordinal=ordinal, replicate=replicate, seed=seed, source_event=item,
                       scenario={"fault": fault, "expires": expires, "budget": budget}, policy=policy,
                       checkpoint_path=str(current_checkpoint), moment_cost=moment_cost(value, profile.gamma))
        save(output / "episodes" / case / "EPISODE.json", receipt)
        all_episodes.append(receipt)
        return lp, value, receipt

    baseline = 0.
    for step in range(STEPS):
        current = snapshot(step)
        before = {name: parameter_hash(module) for name, module in components(model).items()}
        optimizer.zero_grad(set_to_none=True)
        completed = [complete(training[step], SCENARIOS[step], "train", step, k, current) for k in range(REPLICATES)]
        mean_cost = sum(moment_cost(value, profile.gamma) for _, value, _ in completed) / REPLICATES
        scores = torch.stack([lp for lp, _, _ in completed]).sum()
        loss = (mean_cost - baseline) * scores
        loss.backward()
        audit = gradients(model)
        if any(row["l2"] <= 0 for row in audit.values()):
            raise ValueError("Actual complete-trajectory reward did not reach every trainable component")
        clip_norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), 1.))
        optimizer.step()
        changed = {name: parameter_hash(module) != before[name] for name, module in components(model).items()}
        row = {"step": step, "snapshot": snapshots[-1], "baseline_used": baseline, "mean_moment_cost": mean_cost,
               "actual_joint_score": float(scores.detach()), "surrogate_loss": float(loss.detach()),
               "preclip_gradients": audit, "global_gradient_norm_before_clip": clip_norm,
               "components_changed": changed, "actual_emissions": sum(r["actual_emission_scores"] for _, _, r in completed),
               "net_returns": [value for _, value, _ in completed], "parameter_update_after_all_owner_stops": True}
        save(output / f"UPDATE-{step:02d}.json", row)
        steps.append(row)
        baseline = mean_cost
        print(json.dumps({"step": step, "emissions": row["actual_emissions"], "all_component_gradients_nonzero": True}), flush=True)

    final_checkpoint = snapshot(STEPS)
    final_parameter = parameter_hash(model)
    reloaded = torch.load(final_checkpoint, weights_only=True, map_location="cpu")
    model = NaturalPortfolio(reloaded["vocabulary"]).eval().requires_grad_(True)
    model.load_state_dict(reloaded["model"])
    if parameter_hash(model) != final_parameter or reloaded["profile_sha256"] != profile.digest:
        raise ValueError("Final deployment reload changed the trained policy/profile")
    deployed = [complete(item, SCENARIOS[i], "development", i, 0, final_checkpoint) for i, item in enumerate(development)]
    actual = [row["native_execution"] for row in all_episodes]
    checks = {"all_episode_profile_hashes_match": all(row["profile_sha256"] == profile.digest for row in all_episodes),
        "all_current_checkpoints_match_native_host_binding": all(row["checkpoint_sha256"] == row["native_execution"]["binding"]["generator_checkpoint"] for row in all_episodes),
        "all_original_kernel_counts_17": all(row["kernel_executions"] == 17 for row in all_episodes),
        "all_cold_replayed_prefix_counts_10": all(row["measurements"]["cold_recovery_kernel_steps"] == 10 for row in actual),
        "every_actual_emission_scored_once": all(row["actual_emission_scores"] == row["native_execution"]["measurements"]["actual_generator_calls"] for row in all_episodes),
        "all_private_scoring_after_owner_closed": all(row["private_scoring_started_ns"] >= row["owner_closed_ns"] for row in all_episodes),
        "all_per_episode_input_and_policy_preparation_cpu_charged": all(sum(c["kind"] == "per_episode_preparation_cpu" for c in row["complete_costs"]) == 1 for row in all_episodes),
        "all_13_components_have_nonzero_actual_reward_gradient_each_update": all(all(g["l2"] > 0 for g in row["preclip_gradients"].values()) for row in steps),
        "all_13_components_changed": all(parameter_hash(module) != initial_components[name] for name, module in components(model).items()),
        "successful_actual_retry_observed": any(row["executed_action"] == "swap" and row["final"]["terminal_kind"] == "delivered" for row in actual),
        "expiry_denial_observed": any(row["permit"]["proposed"] and not row["permit"]["native_nonabstention"] for row in actual),
        "budget_denial_observed": any(row["permit"]["proposed"] and row["permit"]["native_nonabstention"] and row["permit"]["media_units_remaining"] == 0 for row in actual),
        "failed_episodes_retain_full_actual_cost": all(row["net_return"] < 0 and row["complete_costs"] for row in all_episodes if row["terminal_kind"] == "failed"),
        "no_qualification_sources_consumed": all(row["source_event"]["split"] in ("train", "development") for row in all_episodes),
        "native_authority_remains_DENY_ALL": all(row["permit"]["owner_authority"] == "DENY_ALL" for row in actual)}
    if not all(checks.values()):
        raise ValueError(f"Full-trajectory mechanism check failed: {checks}")
    measured_run_cpu = cpu_seconds() - total_cpu_started
    cpu_kinds = {"python_cpu_second", "native_cpu_second", "host_snapshot_binding_cpu",
                 "terminal_readback_private_scoring_cpu", "per_episode_preparation_cpu"}
    charged_cpu = sum(cost["amount"] / .001 for row in all_episodes for cost in row["complete_costs"]
                      if cost["kind"] in cpu_kinds)
    summary = {"schema": "hepta.ndu.native-joint-gradient-result.v1", "profile_sha256": profile.digest,
        "protocol_sha256": sha(output / "PROTOCOL.json"), "checks": checks, "train_updates": STEPS,
        "train_complete_episodes": STEPS * REPLICATES, "original_development_complete_episodes": len(deployed),
        "actual_generator_calls": sum(row["actual_emission_scores"] for row in all_episodes),
        "actual_native_kernel_executions": sum(row["kernel_executions"] for row in all_episodes),
        "actual_retries": sum(row["executed_action"] == "swap" for row in actual),
        "actual_denied_proposals": sum(row["continuation_kind"] == "refused" for row in actual),
        "failed_terminal_episodes": sum(row["terminal_kind"] == "failed" for row in all_episodes),
        "final_checkpoint": snapshots[-1], "snapshots": snapshots,
        "development_net_returns_descriptive_only": [value for _, value, _ in deployed],
        "development_population_ce_descriptive_only": certainty_equivalent([value for _, value, _ in deployed], profile.gamma),
        "total_measured_self_children_cpu_seconds": measured_run_cpu,
        "episode_charged_self_children_cpu_seconds": charged_cpu,
        "episode_preparation_cpu_seconds": sum(cost["amount"] / .001 for row in all_episodes for cost in row["complete_costs"]
                                                if cost["kind"] == "per_episode_preparation_cpu"),
        "outside_episode_setup_training_reporting_cpu_seconds": measured_run_cpu - charged_cpu,
        "total_episode_normalized_cost": sum(cost["amount"] for row in all_episodes for cost in row["complete_costs"]),
        "total_wall_seconds": time.perf_counter() - wall_started,
        "new_qualification": False, "efficacy_claim": False, "tail_certificate_issued": False, "production_gates_passed": False,
        "limitations": ["One new host profile only; no rewriting historical training objectives",
                        "Original native kernel/readout/calibration remain unchanged and advisory",
                        "CPU costs measured, direct parameter/runtime derivatives omitted under explicit conditional exogeneity model",
                        "Variable CPU has no finite future bound; no rigorous tail certificate",
                        "Eight training sources and four development sources provide mechanism evidence, not efficacy or generalization",
                        "Natural semantic observer adequacy and all previous failed capability gates remain unresolved"]}
    save(output / "SUMMARY.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for argument in ("binary", "checkpoint", "assets", "output"):
        parser.add_argument("--" + argument, required=True)
    run(**vars(parser.parse_args()))
