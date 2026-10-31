"""Matched conditional-mean/moment regression, chosen only on fixed old sources."""

import argparse
from copy import deepcopy
import gc
import hashlib
import json
from pathlib import Path
import resource
import time

import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...v6.neural import parameter_hash
from .data import old_feature_table
from .model import FrozenPortfolio, SemanticAdapter, conditional_loss, pair_law, regression_matrix, select_action


PROFILES = ("mean", "entropic")
SEEDS = (17, 29, 43)


@torch.no_grad()
def measure(adapter, table, utility, strict, profile):
    probabilities = (table["raw_probabilities"] if adapter is None else
                     adapter(table["features"], table["raw_probabilities"], table["text_mask"]))
    q = pair_law(probabilities)
    actions, moments = select_action(q, utility, profile)
    values = utility[actions, table["target_codes"]]
    successes = strict[actions, table["target_codes"]]
    return {"CE": float(-torch.log(torch.exp(-2 * values).mean()) / 2),
            "mean_utility": float(values.mean()), "strict_success": float(successes.mean()),
            "actions": actions.tolist(), "utilities": values.tolist(),
            "strict_successes": successes.tolist(), "predicted_cost_selected": moments.gather(1, actions[:, None]).flatten().tolist(),
            "target_probability": q.gather(1, table["target_codes"][:, None]).flatten().tolist()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--endpoints", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    settings = json.loads(args.config.read_text())
    endpoint = json.loads(args.endpoints.read_text())
    if endpoint["status"] != "completed" or endpoint["actual_endpoint_count"] != 100:
        raise ValueError("A complete actual-codec return table is required")
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    source_pins = {str(p.resolve()): file_sha(p) for p in Path(__file__).parent.glob("*.py")}
    settings_pin, endpoint_pin = file_sha(args.config), file_sha(args.endpoints)
    write_json(args.output / "REGISTRATION.json", {"schema": "hepta.advance.conditional-cost-training.v1",
        "registered_unix_ns": time.time_ns(), "config_sha256": settings_pin, "endpoint_sha256": endpoint_pin,
        "source_pins": source_pins, "seeds": list(SEEDS), "profiles": list(PROFILES),
        "train_pairs": 512, "old_development_pairs": 128, "routes_per_pair": 4,
        "steps": 640, "batch": 64, "learning_rate": .001, "optimizer": "Adam",
        "adapter": "78->32 tanh->10 tanh bounded residual, all renderer/front-end weights frozen",
        "loss": "Normalized squared full conditional-cost-vector regression, plus .001 squared residual-to-reference posterior",
        "checkpoint_rule": "One final checkpoint per fixed seed/profile; no epoch search",
        "selection_rule": "Whole fixed three-seed profile mean CE on old development, then strict success, then mean on exact tie; reject learned profile if panel CE or strict success is below canonical baseline",
        "factorization": "Two conditional digit laws multiplied; approximate target law, not proven true joint conditional distribution",
        "new_confirmation_sources_opened": False,
        "arms": ["unchanged_full_reference", "canonical_no_training", "canonical_mean", "canonical_entropic"],
        "observer_scope": "Measured target-free actual-codec return table is a training target; no independent observer-family claim"})
    portfolio = FrozenPortfolio(settings["renderer_paths"])
    if portfolio.parameter_sha256 != endpoint["renderer_parameter_sha256"]:
        raise ValueError("Training renderer differs from actual measured endpoints")
    train, _ = old_feature_table(portfolio, settings, "train", 512, 240401, args.output / "fit-features")
    held, held_ids = old_feature_table(portfolio, settings, "development", 128, 240503, args.output / "old-development-features")
    utility = torch.tensor(endpoint["utility_action_by_target"], dtype=torch.float64)
    strict = torch.tensor(endpoint["strict_success_action_by_target"], dtype=torch.float64)
    reference = measure(None, held, utility, strict, "entropic")
    write_json(args.output / "CANONICAL_REFERENCE.json", reference)
    matrices = {name: regression_matrix(utility, name) for name in PROFILES}
    results = {}
    for seed in SEEDS:
        torch.manual_seed(seed)
        initial = SemanticAdapter()
        for profile in PROFILES:
            directory = args.output / f"seed-{seed}" / profile
            directory.mkdir(parents=True, exist_ok=False)
            adapter = deepcopy(initial)
            before = parameter_hash(adapter)
            optimizer = torch.optim.Adam(adapter.parameters(), lr=.001)
            rng = torch.Generator().manual_seed(seed * 240007)
            schedule, max_grad = hashlib.sha256(), 0.
            with (directory / "PROGRESS.jsonl").open("x") as log:
                for step in range(640):
                    indices = torch.randint(len(train["features"]), (64,), generator=rng)
                    probability = adapter(train["features"][indices], train["raw_probabilities"][indices], train["text_mask"][indices])
                    loss = conditional_loss(pair_law(probability), train["target_codes"][indices], matrices[profile][0])
                    anchor = (probability - train["raw_probabilities"][indices]).square().mean()
                    objective = loss + .001 * anchor
                    optimizer.zero_grad(set_to_none=True)
                    objective.backward()
                    grad = sum(float(p.grad.abs().sum()) for p in adapter.parameters() if p.grad is not None)
                    max_grad = max(max_grad, grad)
                    torch.nn.utils.clip_grad_norm_(adapter.parameters(), 5.)
                    optimizer.step()
                    schedule.update(indices.numpy().tobytes())
                    log.write(json.dumps({"step": step + 1, "loss": float(loss.detach()), "anchor": float(anchor.detach())}) + "\n")
            adapter.eval().requires_grad_(False)
            after = parameter_hash(adapter)
            if before == after or max_grad <= 0:
                raise ValueError("Claimed adapter received no actual learning update")
            checkpoint = directory / "adapter.pt"
            torch.save({"schema": "hepta.advance.semantic-adapter.v1", "state_dict": adapter.state_dict(),
                        "parameter_sha256": after, "seed": seed, "profile": profile,
                        "endpoint_sha256": endpoint_pin, "renderer_parameter_sha256": portfolio.parameter_sha256}, checkpoint)
            adapter.export_native(endpoint, directory / "NATIVE.json")
            metrics = measure(adapter, held, utility, strict, profile)
            row = {"seed": seed, "profile": profile, "initial_sha256": before, "final_sha256": after,
                   "schedule_sha256": schedule.hexdigest(), "maximum_gradient_abs_sum": max_grad,
                   "checkpoint": str(checkpoint), "checkpoint_sha256": file_sha(checkpoint),
                   "native_export": str(directory / "NATIVE.json"), "native_export_sha256": file_sha(directory / "NATIVE.json"),
                   "old_development": metrics, "regression": matrices[profile][1]}
            write_json(directory / "RESULT.json", row)
            results[f"{seed}/{profile}"] = row
            print(json.dumps({"seed": seed, "profile": profile, "CE": metrics["CE"], "strict": metrics["strict_success"]}), flush=True)
            del optimizer, adapter
            gc.collect()
        a, b = (results[f"{seed}/{profile}"] for profile in PROFILES)
        if a["initial_sha256"] != b["initial_sha256"] or a["schedule_sha256"] != b["schedule_sha256"]:
            raise ValueError("Profile initialization or training schedule was not paired")
    profile_metrics = {profile: {key: sum(results[f"{seed}/{profile}"]["old_development"][key] for seed in SEEDS) / len(SEEDS)
                                for key in ("CE", "strict_success", "mean_utility")} for profile in PROFILES}
    chosen = max(PROFILES, key=lambda name: (profile_metrics[name]["CE"], profile_metrics[name]["strict_success"], name == "mean"))
    qualifies = (profile_metrics[chosen]["CE"] >= reference["CE"]
                 and profile_metrics[chosen]["strict_success"] >= reference["strict_success"])
    selected_profile = chosen if qualifies else "canonical_no_training"
    # All three fixed training seeds remain in confirmation. A native single
    # checkpoint uses the predeclared first seed, never the best observed seed.
    selected_native = results[f"17/{chosen}"]["native_export"] if qualifies else None
    portfolio.assert_frozen()
    if any(file_sha(Path(p)) != h for p, h in source_pins.items()):
        raise ValueError("Training source changed during execution")
    write_json(args.output / "RESULTS.json", {"status": "completed", "arms": results,
        "profile_metrics": profile_metrics, "canonical_reference": {k: reference[k] for k in ("CE", "strict_success", "mean_utility")},
        "selected_profile": selected_profile, "learned_candidate_old_development_eligible": qualifies,
        "selected_native_export": selected_native, "native_seed_rule": "Fixed first seed17, never best-seed selection",
        "actual_updates_per_arm": 640, "new_confirmation_sources_opened": False,
        "only_adapter_updated": True, "all_frozen_components_unchanged": True,
        "profile_affine_equivalence": matrices["entropic"][1],
        "paired_parameter_equivalence": {str(seed): results[f"{seed}/mean"]["final_sha256"] == results[f"{seed}/entropic"]["final_sha256"] for seed in SEEDS},
        "registration_sha256": file_sha(args.output / "REGISTRATION.json"),
        "wall_ns_main": time.perf_counter_ns() - wall, "cpu_ns_main": time.process_time_ns() - cpu,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024})


if __name__ == "__main__":
    main()
