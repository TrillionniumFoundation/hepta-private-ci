"""Read-only trained-checkpoint feedback interventions on development sources.

This diagnostic does not update weights, select candidates, or consume any
confirmation source. The runtime's feedback_override applies to EVERY verify
transition, starting with the forced second transition. Actual timing remains
measured; a repeated low-feedback run detects selected-path/byte instability.
A separate fixed-logical-budget policy probe isolates the actor response from
physical timing. The policy probe is not an execution or cost equivalence test.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from experiments.multimodal_output_portfolio.joint_hepta_20261029.contract import JointGenerationProfile
from experiments.multimodal_output_portfolio.joint_hepta_20261029.deployment import load_candidate
from experiments.multimodal_output_portfolio.joint_hepta_20261029.mechanism_data import batch
from experiments.multimodal_output_portfolio.joint_hepta_20261029.media import read_bundle, utility
from experiments.multimodal_output_portfolio.joint_hepta_20261029.model import ACTIONS, tensor_digest
from experiments.multimodal_output_portfolio.joint_hepta_20261029.runtime import (
    HORIZON, INITIAL_BUDGET, TARIFF, cpu_seconds, execute, make_profile,
)
from experiments.multimodal_output_portfolio.joint_hepta_20261029.train import write


NAMESPACE = "controller-v2-development"
SOURCES = tuple(range(8))
BASE_SEED = 9_100_003
PREFIX = ("shared", "verify")


def public_feedback_interventions(public):
    """Zero versus 75% of the channel-wise feasible squared-error upper bound.

    These bounds use only observed values and masks. The high vector is a
    deliberately intervened feedback signal, not an assertion that any one
    generated bundle necessarily attains all three errors simultaneously.
    """
    upper = []
    for modality in ("image", "audio", "video"):
        observed, mask = public[modality], public[modality + "_mask"]
        squared = ((1 + observed.abs()).square() if modality == "audio" else
                   torch.maximum(observed.square(), (1 - observed).square()))
        upper.append((squared * mask).flatten(1).mean(1))
    high = torch.stack(upper, -1) * 0.75
    return {"low": torch.zeros_like(high), "high": high}


def policy_probe(model, public, interventions, seed):
    """Exact deterministic actor-law comparison at one matched public history."""
    state = model.encode(public)
    state, _ = model.advance(state, "shared", public)
    remaining = 1 - (TARIFF["encode"] + TARIFF["shared"] + TARIFF["verify"]) / INITIAL_BUDGET
    laws, choices = {}, {}
    for label, feedback in interventions.items():
        child, _ = model.advance(state, "verify", public, feedback_override=feedback)
        law, _ = model.policy(child, remaining, HORIZON)
        probability = law.exp()[0]
        rng = torch.Generator().manual_seed(seed)
        laws[label] = probability.tolist()
        choices[label] = {"sampled": ACTIONS[int(torch.multinomial(probability, 1, generator=rng))],
                          "greedy": ACTIONS[int(probability.argmax())]}
    tv = 0.5 * float((torch.tensor(laws["low"]) - torch.tensor(laws["high"])).abs().sum())
    return {"scope": "actor_law_only_at_identical_latents_and_fixed_logical_budget",
        "remaining_fraction": remaining, "probabilities": laws, "choices": choices,
        "total_variation": tv, "distribution_changed": tv > 0,
        "physical_timing_equivalence_claimed": False}


def intervention_triplet(model, public, target, directory, *, profile, source, seed, strategy):
    directory = Path(directory)
    interventions = public_feedback_interventions(public)
    before = tensor_digest(model.state_dict())
    probe = policy_probe(model, public, interventions, seed)
    records = {}
    # The second low run is a same-feedback execution control; no physical clock
    # is mocked and no small control differences are silently called exact.
    for label in ("low_first", "high", "low_repeat"):
        feedback = interventions["high" if label == "high" else "low"]
        episode = execute(model, public, lambda sample: utility(sample, target).item(),
            directory / label, seed=seed, context_id=f"diagnostic.{source}",
            source_id=f"synthetic.{NAMESPACE}.{source}", profile=profile,
            strategy=strategy, prefix=PREFIX, feedback_override=feedback)
        record = episode.record
        if [a["action"] for a in record["actions"][:2]] != list(PREFIX):
            raise ValueError("Diagnostic intervention did not follow the declared prefix")
        if record["failure"] is None:
            _, identities = read_bundle(directory / label / "outputs")
            if identities != dict(record["outcome"]["artifact_sha256"]):
                raise ValueError("Independent output readback differs from recorded file hashes")
        records[label] = {"actions_after_feedback": [a["action"] for a in record["actions"][2:]],
            "artifacts": dict(record["outcome"]["artifact_sha256"]),
            "terminal_state_sha256": tensor_digest(episode.terminal_state.tensors()),
            "feedback_override": feedback.tolist(), "utility": record["outcome"]["delivered_utility"],
            "net_return": episode.net_return, "net_with_audit_close": record["net_with_audit_close"],
            "actual_cost": record["actual_cost"], "failure": record["failure"],
            "first_post_feedback_remaining_budget": record["state_chain"][2]["remaining_budget"],
            "input_sha256": record["state_chain"][0]["input_sha256"],
            "policy_snapshot_sha256": record["policy_snapshot_sha256"],
            "parameter_snapshot_sha256": record["parameter_snapshot_sha256"]}
    if tensor_digest(model.state_dict()) != before:
        raise ValueError("Diagnostic changed learned parameters")
    low, high, repeat = (records[k] for k in ("low_first", "high", "low_repeat"))
    action_change = low["actions_after_feedback"] != high["actions_after_feedback"]
    content_change = low["artifacts"] != high["artifacts"]
    control_actions_same = low["actions_after_feedback"] == repeat["actions_after_feedback"]
    control_outputs_same = low["artifacts"] == repeat["artifacts"]
    failures = sum(r["failure"] is not None for r in records.values())
    return {"source": source, "source_namespace": NAMESPACE, "seed": seed, "strategy": strategy,
        "fixed_budget_policy_probe": probe, "actual_executions": records,
        "actions_changed": action_change, "output_hashes_changed": content_change,
        "actions_and_outputs_changed": action_change and content_change,
        "outputs_changed_without_action_change": content_change and not action_change,
        "same_feedback_control_actions_identical": control_actions_same,
        "same_feedback_control_outputs_identical": control_outputs_same,
        "intervention_result_robust_to_this_repeat_control": control_actions_same and control_outputs_same and failures == 0,
        "failures": failures, "parameters_unchanged": True,
        "physical_timing_exact_reproduction_claimed": False}


def run(development_results, output):
    development_results, output = Path(development_results), Path(output)
    study = json.loads(development_results.read_text())
    if study.get("stage") != "development" or study.get("confirmation_sources_consumed") != 0:
        raise ValueError("Only a controller-v2 development result is eligible for this diagnostic")
    if study.get("smoke") is not False:
        raise ValueError("Smoke checkpoints are not learned-model sensitivity evidence")
    protocol = json.loads((development_results.parent / "EXECUTED_PROTOCOL.json").read_text())
    if protocol.get("development_namespace") != NAMESPACE:
        raise ValueError("Diagnostic must not access a renamed or confirmation source namespace")
    if protocol.get("development_sources", 0) < len(SOURCES):
        raise ValueError("Fixed diagnostic sources exceed the declared development cohort")
    profile = JointGenerationProfile.from_dict(json.loads((development_results.parent / "PROFILE.json").read_text()))
    if profile.digest != study["profile_sha256"] or profile.digest != make_profile().digest:
        raise ValueError("Diagnostic runtime must match the frozen generation profile exactly")
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2); torch.use_deterministic_algorithms(True)
    begun, cpu = time.perf_counter(), cpu_seconds()
    result = {"schema": "hepta.joint-generation.controller-feedback-diagnostic.v1",
        "development_results_sha256": hashlib.sha256(development_results.read_bytes()).hexdigest(),
        "diagnostic_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "study_seed": study["seed"], "width": study["width"], "smoke": study["smoke"],
        "profile_sha256": profile.digest, "source_namespace": NAMESPACE,
        "source_ids": list(SOURCES), "draws_per_source": 1, "base_seed": BASE_SEED,
        "forced_prefix": list(PREFIX), "override_scope": "every_verify_starting_at_forced_second_transition",
        "parameters_updated": False, "used_for_candidate_selection": False,
        "confirmation_sources_consumed": 0, "research_effect_qualified": False,
        "semantic_qualification": False, "arms": {}}
    choices = [(name, development_results.parent / name / "MODEL.pt", entry["checkpoint"], "dynamic")
               for name, entry in study["arms"].items() if "dynamic" in name]
    choices.append(("distilled", development_results.parent / "distillation" / "STUDENT.pt",
                    study["distillation"]["checkpoint"], "greedy"))
    for arm, path, identity, strategy in choices:
        model, lineage = load_candidate(path, expected_arm=arm,
            expected_model_sha256=identity["model_sha256"])
        if lineage["old_metadata"].get("stage") != "development":
            raise ValueError("Checkpoint stage differs from the development-only diagnostic")
        rows = []
        with torch.no_grad():
            for source in SOURCES:
                public, target = batch([source], NAMESPACE)
                rows.append(intervention_triplet(model, public, target, output / arm / f"source-{source}",
                    profile=profile, source=source, seed=BASE_SEED + source * 7919, strategy=strategy))
        result["arms"][arm] = {"model_sha256": identity["model_sha256"], "checkpoint": lineage["manifest"],
            "strategy": strategy, "rows": rows,
            "distribution_changed_sources": sum(r["fixed_budget_policy_probe"]["distribution_changed"] for r in rows),
            "actions_changed_sources": sum(r["actions_changed"] for r in rows),
            "actions_and_outputs_changed_sources": sum(r["actions_and_outputs_changed"] for r in rows),
            "outputs_only_changed_sources": sum(r["outputs_changed_without_action_change"] for r in rows),
            "same_feedback_controls_identical_sources": sum(r["same_feedback_control_actions_identical"]
                and r["same_feedback_control_outputs_identical"] for r in rows),
            "actual_episodes": len(rows) * 3, "failures": sum(r["failures"] for r in rows)}
        write(output / "RESULTS.partial.json", result)
    result["cost"] = {"cpu_seconds": cpu_seconds() - cpu, "wall_seconds": time.perf_counter() - begun}
    write(output / "RESULTS.json", result)
    summary = {**result, "arms": {k: {f: v for f, v in a.items() if f != "rows"} for k, a in result["arms"].items()}}
    write(output / "SUMMARY.json", summary)
    print("DIAGNOSTIC_JSON=" + json.dumps(summary, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.development_results, args.output)
